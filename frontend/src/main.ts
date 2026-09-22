import {context,send,assetResolved,imageChosen,type LoadPayload,type ScrollState} from './bridge';
import {splitFrontmatter,canonical,rebaseMarkdown} from './markdown';
import {headingAnchor,paragraphAnchor,updateDocumentAnchors} from './document-anchors';
import {renderReading,refreshReadingTheme} from './reading';
import {setupOutline,syncOutlineLayout,toggleOutline,updateOutlineCurrent} from './outline-ui';
import {initializeMermaid,renderPending,renderIssues,resolveImages,track} from './rendering';
import '@milkdown/crepe/theme/common/style.css';
import 'katex/dist/katex.min.css';
import './style.css';
import './reading.css';

// Reading has no editor dependency. A single editor module/model is retained
// after first use, with its DOM detached while the reading view is displayed.
const app=document.querySelector<HTMLDivElement>('#app')!;
const readingRoot=document.createElement('div');
readingRoot.innerHTML='<nav id="outline" aria-label="Document outline"><div class="outline-title">CONTENTS</div><div id="outline-items"></div></nav><main id="main"><div id="notice" role="status" hidden></div><div id="page"><details id="metadata" hidden><summary>Document metadata</summary><pre></pre></details><div id="editor"></div></div></main>';
const host=readingRoot.querySelector<HTMLDivElement>('#editor')!,notice=readingRoot.querySelector<HTMLDivElement>('#notice')!,metadata=readingRoot.querySelector<HTMLDetailsElement>('#metadata')!;
app.replaceChildren(readingRoot);
setupOutline(readingRoot);
let payload:LoadPayload|null=null,generation=0,loaded=false,busy=false,dirty=false,editable=false;
let mode:'read'|'edit'='read',desiredMode:'read'|'edit'='read';
let renderedSource:string|null=null,editorGeneration=-1,modeToken=0;
let editing:typeof import('./editing')|null=null;
let importing:Promise<typeof import('./editing')>|null=null;
let preparing:Promise<void>|null=null;
let preparingGeneration=-1;
let timings:Record<string,number>={};
const activeEditor=()=>mode==='edit'&&editing?.editingRoot.isConnected;
const statePayload=()=>({type:'mode',mode,busy,editable});
function reportMode(reason=''){send({...statePayload(),reason});}
function pruneIssues(){for(const element of renderIssues.keys())if(!readingRoot.contains(element)&&!editing?.editingRoot.contains(element))renderIssues.delete(element);}
function currentMarkdown(){if(editorGeneration===generation&&editing){const state=editing.editingReader.inspect();return state.dirty?state.markdown:(payload?.savedMarkdown??payload?.markdown??'');}return payload?.markdown??'';}
function synchronizeBuffer(){if(editorGeneration!==generation||!editing||!payload)return;editing.editingReader.flush();const state=editing.editingReader.inspect();dirty=state.dirty;payload.markdown=dirty?state.markdown:(payload.savedMarkdown??payload.markdown);}
function headings(){const root=activeEditor()?editing!.editingRoot:readingRoot;return Array.from(root.querySelectorAll<HTMLElement>('#editor h1,#editor h2,#editor h3,#editor h4,#editor h5,#editor h6')).map(h=>({level:Number(h.tagName.slice(1)),text:h.textContent??'',id:h.id}));}
function buildOutline(){
  const targets=Array.from(host.querySelectorAll<HTMLElement>('h1,h2,h3,h4,h5,h6,.reading-document>p'),element=>({element,base:element.tagName==='P'?paragraphAnchor(element.textContent??''):headingAnchor(element.textContent??'')}));
  updateDocumentAnchors(targets,host.querySelectorAll<HTMLElement>('[id]'));
  const fragment=document.createDocumentFragment();
  for(const h of host.querySelectorAll<HTMLElement>('h1,h2,h3,h4,h5,h6')){const link=document.createElement('a');link.href='#'+h.id;link.textContent=h.textContent;link.style.paddingLeft=`${12+(Number(h.tagName.slice(1))-1)*12}px`;fragment.append(link);}
  if(!fragment.childElementCount){const empty=document.createElement('p');empty.textContent='Headings appear here.';fragment.append(empty);}
  readingRoot.querySelector('#outline-items')!.replaceChildren(fragment);
  updateOutlineCurrent(readingRoot);
}
function getState():ScrollState {
  if(activeEditor()){
    const state=editing!.editingReader.getState();
    if(state.scrollY<=1)return {scrollY:0};
    const toolbar=editing!.editingRoot.querySelector<HTMLElement>('#toolbar');
    return {...state,offset:state.offset===undefined?undefined:state.offset-(toolbar?.getBoundingClientRect().height??0)};
  }
  let anchor:HTMLElement|undefined;
  for(const element of host.querySelectorAll<HTMLElement>('[data-reader-anchor]')){if(element.getBoundingClientRect().top<=100)anchor=element;else break;}
  return {scrollY:window.scrollY,anchor:anchor?.id,offset:anchor?.getBoundingClientRect().top};
}
function restoreState(state:ScrollState){const revision=generation;requestAnimationFrame(()=>{if(revision!==generation)return;const target=state.anchor?document.getElementById(state.anchor):null;window.scrollTo({top:target?window.scrollY+target.getBoundingClientRect().top-(state.offset??0):state.scrollY??0});});}
function setTheme(theme:'light'|'dark'){
  if(payload)payload.theme=theme;document.documentElement.dataset.theme=theme;initializeMermaid(theme==='dark');
  if(editing)editing.editingReader.setTheme(theme);
  refreshReadingTheme(host);
}
function setZoom(zoom:number){if(payload)payload.zoom=zoom;const ratio=zoom>4?zoom/100:zoom;document.documentElement.style.setProperty('--reader-font-size',`${17*Math.min(2.5,Math.max(.6,ratio||1))}px`);syncOutlineLayout();}
function setWidth(width:'comfortable'|'wide'){
  const next=width==='wide'?'wide':'comfortable';
  const position=loaded?(activeEditor()?editing!.editingReader.getState():getState()):null;
  if(payload)payload.width=next;
  document.documentElement.dataset.width=next;
  syncOutlineLayout();
  if(position){if(activeEditor())editing!.editingReader.restoreState(position);else restoreState(position);}
}
async function renderCurrent(){
  if(!payload)return;
  const source=payload.markdown;
  if(renderedSource!==source){
    const {prefix,body}=splitFrontmatter(source);metadata.hidden=!prefix;metadata.querySelector('pre')!.textContent=prefix;
    await renderReading(host,body);renderedSource=source;buildOutline();
  }else refreshReadingTheme(host);
  pruneIssues();
}
async function load(next:LoadPayload){
  const started=performance.now(),previous=getState(),mine=++generation;++modeToken;
  document.querySelectorAll<HTMLDialogElement>('dialog.reader-focus-dialog[open]').forEach(dialog=>dialog.close());
  editing?.editingReader.invalidate();editorGeneration=-1;
  document.querySelectorAll<HTMLDialogElement>('.source-dialog[open]').forEach(dialog=>dialog.close());
  payload={...next};context.documentId=next.documentId;context.revision=next.revision;
  loaded=false;busy=false;mode=desiredMode='read';editable=next.editable;
  dirty=next.markdown!==(next.savedMarkdown??next.markdown)&&canonical(next.markdown)!==canonical(next.savedMarkdown??next.markdown);
  timings={};notice.hidden=true;document.body.classList.remove('editing');app.replaceChildren(readingRoot);
  setTheme(next.theme);setZoom(next.zoom);setWidth(next.width??'comfortable');host.setAttribute('aria-busy','true');
  try{await renderCurrent();}catch(error){host.replaceChildren();const pre=document.createElement('pre');pre.textContent=next.markdown;host.append(pre);editable=false;notice.textContent=`This document could not be rendered: ${(error as Error).message}`;notice.hidden=false;}
  if(mine!==generation)return;
  loaded=true;host.removeAttribute('aria-busy');timings['read render']=Math.round(performance.now()-started);timings['load total']=timings['read render'];
  if(!next.editable&&notice.hidden){notice.textContent='This document is read-only. Its encoding or permissions prevent safe editing.';notice.hidden=false;}
  restoreState(next.scrollState??next.state??previous);
  send({type:'loaded',editable,dirty,reason:notice.hidden?'':notice.textContent,headings:headings(),issues:[...renderIssues.entries()].filter(([e])=>host.contains(e)).map(([,v])=>v)});
  if(dirty)send({type:'dirty',dirty:true,markdown:next.markdown});
}
async function ensureEditor(){
  if(!payload)throw new Error('No document is loaded.');
  if(editorGeneration===generation&&editing)return;
  // Serialize construction across superseding document revisions. Invalidation
  // prevents an obsolete load from publishing a dirty buffer for a newer file.
  if(preparing){
    const requested=generation,previousGeneration=preparingGeneration;
    try{await preparing;}catch(error){if(previousGeneration===requested)throw error;}
    if(requested!==generation)throw new Error('The document changed while preparing the editor.');
    if(editorGeneration===generation)return;
  }
  const mine=generation,source={...payload,scrollState:getState()};
  const operation=(async()=>{
    editing=await(importing??=import('./editing'));
    if(mine!==generation)throw new Error('The document changed while preparing the editor.');
    await editing.editingReader.load(source);
    if(mine!==generation)throw new Error('The document changed while preparing the editor.');
    const result=editing.editingReader.inspect();
    if(!result.loaded||!result.editable){editable=false;throw new Error(result.reason||'This document cannot be edited safely.');}
    // Enable editing while detached. The browser lays out only the final view
    // when it is attached, rather than a read-only editor and then an editable one.
    editing.editingReader.setMode('edit');editorGeneration=mine;
  })();
  preparing=operation;preparingGeneration=mine;
  try{await operation;}finally{if(preparing===operation)preparing=null;}
}
async function setMode(next:'read'|'edit'){
  if(!loaded||!payload)return false;
  document.querySelectorAll<HTMLDialogElement>('dialog.reader-focus-dialog[open]').forEach(dialog=>dialog.close());
  desiredMode=next;const token=++modeToken,mine=generation,position=getState(),started=performance.now();
  if(next==='read'){
    if(activeEditor())synchronizeBuffer();
    mode='read';busy=false;document.body.classList.remove('editing');app.replaceChildren(readingRoot);editing?.editingReader.suspend();
    await renderCurrent();if(mine!==generation||token!==modeToken)return false;
    restoreState(position);reportMode();return true;
  }
  if(!editable){reportMode(notice.textContent||'This document can only be read.');return false;}
  if(activeEditor()&&!busy){reportMode();return true;}
  busy=true;reportMode('Preparing editor…');
  try{
    await ensureEditor();
    if(mine!==generation||token!==modeToken||desiredMode!=='edit'){if(mine===generation&&desiredMode==='read')editing?.editingReader.suspend();return false;}
    app.replaceChildren(editing!.editingRoot);mode='edit';busy=false;
    const toolbarHeight=editing!.editingRoot.querySelector<HTMLElement>('#toolbar')?.getBoundingClientRect().height??0;
    const editPosition=position.scrollY<=1?{scrollY:0}:{...position,offset:position.offset===undefined?undefined:position.offset+toolbarHeight};
    editing!.editingReader.resume(editPosition);timings['first or resumed Edit']=Math.round(performance.now()-started);reportMode();return true;
  }catch(error){
    if(mine!==generation||token!==modeToken)return false;
    mode='read';desiredMode='read';busy=false;document.body.classList.remove('editing');app.replaceChildren(readingRoot);
    notice.textContent=(error as Error).message;notice.hidden=false;reportMode(notice.textContent);return false;
  }
}
async function withSerializableEditor(action:()=>void,requestId:string,type:'serialized'|'rebased'){
  const mine=generation;
  try{await ensureEditor();if(mine!==generation)throw new Error('The document changed. Please retry.');action();}
  catch(error){if(mine===generation)send({type,requestId,ok:false,dirty,error:(error as Error).message});}
}
async function prepareExport(requestId:string){
  if(activeEditor())return editing!.editingReader.prepareExport(requestId);
  const identity={documentId:context.documentId,revision:context.revision};
  document.body.classList.add('preparing-export');await document.fonts.ready;
  const deadline=Date.now()+12000;
  while(renderPending.size&&Date.now()<deadline)await Promise.race([Promise.allSettled([...renderPending]),new Promise(resolve=>setTimeout(resolve,400))]);
  const images=Array.from(host.querySelectorAll<HTMLImageElement>('img[src]'));
  await Promise.all(images.map(img=>Promise.race([img.decode().catch(()=>{}),new Promise(resolve=>setTimeout(resolve,5000))])));
  await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
  const issues=[...renderIssues.entries()].filter(([element])=>host.contains(element)).map(([,issue])=>issue);
  if(renderPending.size)issues.push('Some diagrams or images did not finish rendering before export.');
  for(const img of images)if(!img.complete||!img.naturalWidth)issues.push(`Image unavailable: ${img.alt||'image'}`);
  send({...identity,type:'exportReady',requestId,issues:[...new Set(issues)],html:readingRoot.querySelector('#page')!.outerHTML,title:headings()[0]?.text??'Markdown document',bodyClass:''});
}
function scrollToHeading(fragment:string){let id=fragment.replace(/^#/,'');try{id=decodeURIComponent(id);}catch{}document.getElementById(id)?.scrollIntoView({block:'start'});}

document.addEventListener('click',event=>{
  if(!readingRoot.isConnected)return;
  const link=(event.target as HTMLElement).closest<HTMLAnchorElement>('a[href]');if(!link)return;
  event.preventDefault();const href=link.getAttribute('href')??'';
  if(href.startsWith('#'))scrollToHeading(href);else send({type:'openLink',href});
});
document.addEventListener('keydown',event=>{if(!readingRoot.isConnected)return;if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='s'){event.preventDefault();send({type:event.shiftKey?'saveAs':'save'});}});
let scrollTimer=0;window.addEventListener('scroll',()=>{if(!readingRoot.isConnected)return;clearTimeout(scrollTimer);scrollTimer=window.setTimeout(()=>send({type:'scroll',state:getState()}),180);},{passive:true});
window.addEventListener('error',event=>send({type:'status',message:`Renderer error: ${event.message}`}));
window.reader={
  load,setMode,setTheme,setZoom,setWidth,assetResolved,imageChosen,getState,restoreState,prepareExport,scrollToHeading,
  exportFinished(){document.body.classList.remove('preparing-export');if(activeEditor())editing!.editingReader.exportFinished();},
  serialize(requestId:string){
    if(editorGeneration===generation&&editing)return editing.editingReader.serialize(requestId);
    if(!dirty)return send({type:'serialized',requestId,ok:true,dirty:false,markdown:payload?.savedMarkdown??payload?.markdown??''});
    return withSerializableEditor(()=>editing!.editingReader.serialize(requestId),requestId,'serialized');
  },
  markSaved(markdown:string,revision?:number){
    if(!payload)return;
    if(editorGeneration===generation&&editing){editing.editingReader.markSaved(markdown,revision);const state=editing.editingReader.inspect();dirty=state.dirty;payload.markdown=dirty?state.markdown:markdown;}
    else {payload.markdown=markdown;dirty=false;}
    payload.savedMarkdown=markdown;if(revision!==undefined){payload.revision=revision;context.revision=revision;}
  },
  rebase(requestId:string,oldBase:string,newBase:string){
    if(editorGeneration===generation&&editing)return editing.editingReader.rebase(requestId,oldBase,newBase);
    if(dirty)return withSerializableEditor(()=>editing!.editingReader.rebase(requestId,oldBase,newBase),requestId,'rebased');
    try{send({type:'rebased',requestId,ok:true,markdown:rebaseMarkdown(currentMarkdown(),oldBase,newBase)});}catch(error){send({type:'rebased',requestId,ok:false,error:(error as Error).message});}
  },
  refreshAssets(){renderedSource=null;if(editorGeneration===generation)editing?.editingReader.refreshAssets();if(!activeEditor())void renderCurrent();},
  testInsertText(text:string,flush=true){if(!activeEditor()||busy)throw new Error('Enter Edit mode first.');return editing!.editingReader.testInsertText(text,flush);},
  testSelectText(text:string){if(!activeEditor()||busy)throw new Error('Enter Edit mode first.');return editing!.editingReader.testSelectText(text);},
  testSelectRange(from:number,to=from){if(!activeEditor()||busy)throw new Error('Enter Edit mode first.');return editing!.editingReader.testSelectRange(from,to);},
  toggleOutline(){toggleOutline(activeEditor()?editing!.editingRoot:readingRoot);},find(text:string){return window.find?.(text,false,false,true,false,false,false);},
  requestState(requestId:string){send({type:'state',requestId,state:getState()});},
  performanceReport(){return {...(editorGeneration===generation?editing?.editingReader.performanceReport():{}),...timings};},
  inspect(){const current=editorGeneration===generation?editing?.editingReader.inspect():null;return {documentId:context.documentId,revision:context.revision,loaded,editable,mode,busy,editorCreated:!!editing,editorReady:editorGeneration===generation,dirty:current?.dirty??dirty,markdown:current?.markdown??payload?.markdown??'',headings:headings(),issues:[...renderIssues.entries()].filter(([e])=>e.isConnected).map(([,v])=>v),text:(activeEditor()?editing!.editingRoot:host).textContent,theme:payload?.theme};},
};
send({type:'ready'});
