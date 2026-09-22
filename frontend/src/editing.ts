import {CrepeBuilder} from '@milkdown/crepe/builder';
import {table} from '@milkdown/crepe/feature/table';
import {listView,refreshListViewMode} from './list-view';
import type {Node as ProseNode} from '@milkdown/kit/prose/model';
import {editorViewCtx,editorStateCtx,parserCtx,serializerCtx,schemaCtx,remarkCtx} from '@milkdown/kit/core';
import {callCommand,$prose,$remark} from '@milkdown/kit/utils';
import {EditorState,Plugin,TextSelection} from '@milkdown/kit/prose/state';
import {Decoration,DecorationSet} from '@milkdown/kit/prose/view';
import {codeBlockSchema,remarkInlineLinkPlugin,remarkPreserveEmptyLinePlugin} from '@milkdown/kit/preset/commonmark';
import {listener} from '@milkdown/kit/plugin/listener';
import {equivalentEditorDocuments} from './model-equality';
import {anchorViews,updateDocumentAnchors,headingAnchor,paragraphAnchor} from './anchors';
import {createCachedSerializer} from './serialization';
import {createFormattingToolbar} from './toolbar';
import {splitFrontmatter,assertRoundtrip,canonical,primeCanonical,rawHtml,rebaseMarkdown} from './markdown';
import {context,send,assetResolved,imageChosen,type LoadPayload,type ScrollState} from './bridge';
import {protectedBlock,protectedInline,protectRemark,mathRemark,protectedBlockView,protectedInlineView,imageView,codeView,quoteView,setViewMode,initializeMermaid,renderPending,renderIssues,safeHtml,resolveImages,track,renderStaticDiagram} from './views';
import hljs from 'highlight.js/lib/common';
import katex from 'katex';

export const editingRoot=document.createElement('div');
const app=editingRoot;
app.innerHTML='<nav id="outline" aria-label="Document outline"><div class="outline-title">CONTENTS</div><div id="outline-items"></div></nav><main id="main"><div id="toolbar" role="toolbar" aria-label="Formatting" hidden></div><div id="notice" role="status" hidden></div><div id="page"><details id="metadata" hidden><summary>Document metadata</summary><pre></pre></details><div id="editor"></div></div></main>';
const toolbar=app.querySelector<HTMLDivElement>('#toolbar')!,notice=app.querySelector<HTMLDivElement>('#notice')!,host=app.querySelector<HTMLDivElement>('#editor')!,metadata=app.querySelector<HTMLDetailsElement>('#metadata')!;
let editor:CrepeBuilder|null=null,original='',savedMarkdown='',prefix='',editable=false,mode:'read'|'edit'='read',suppressed=true,generation=0,dirty=false,loaded=false,changeTimer=0,outlineTimer=0,debug=false;
let currentTheme:'light'|'dark'='light';
const timings:Record<string,number>={};
function measure(name:string,start:number){if(debug)timings[name]=Math.round(performance.now()-start);}

function status(message:string){notice.textContent=message;notice.hidden=!message;send({type:'status',message});}
function command(key:any,payload?:any){if(!editor||mode!=='edit')return;editor.editor.action(callCommand(key,payload));editor.editor.action(ctx=>ctx.get(editorViewCtx).focus());}
function viewAction(action:(view:any)=>void){editor?.editor.action(ctx=>{const view=ctx.get(editorViewCtx);action(view);view.focus();});}
const formatting=createFormattingToolbar(toolbar,()=>{
  if(!editor||!loaded||!editingRoot.isConnected)return null;
  return editor.editor.action(ctx=>ctx.get(editorViewCtx));
},command);
const formattingState=$prose(()=>new Plugin({
  view(view){formatting.sync(view);return {update(next,previous){if(mode==='edit')formatting.sync(next);if(!suppressed&&next.state.doc!==previous.doc){clearTimeout(changeTimer);changeTimer=window.setTimeout(updateDirty,200);}}};},
  props:{handleKeyDown(_view,event){
    if(mode==='edit'&&(event.ctrlKey||event.metaKey)&&event.altKey&&event.code==='Digit0'){
      event.preventDefault();formatting.normalText();return true;
    }return false;
  }},
}));

const parseCache=$remark('reader-parse-cache',()=>function(this:any){
  const parse=this.parser;
  this.parser=(source:string,file:any)=>{const tree=parse(source,file);primeCanonical(prefix+String(source),tree);return tree;};
});
const guard=$prose(()=>new Plugin({props:{handlePaste(_view,event){if(Array.from(event.clipboardData?.items??[]).some(item=>item.kind==='file')){status('Use Insert → Image from file to add an existing image. Image paste is not supported.');return true;}return false;},handleDrop(_view,event){if(event.dataTransfer?.files.length){status('Use Insert → Image from file to add an existing image.');return true;}return false;}}}));
const calloutMarkers=$prose(()=>{
  let lastDoc:ProseNode|null=null,lastSet=DecorationSet.empty;
  return new Plugin({props:{decorations(state){
    if(lastDoc===state.doc)return lastSet;
    const decorations:Decoration[]=[];state.doc.descendants((node,pos)=>{if(node.type.name==='blockquote'&&node.firstChild){const marker=node.firstChild.textContent.match(/^\[![^\]]+\][+-]?[^\n]*(?:\n|$)/);if(marker)decorations.push(Decoration.inline(pos+2,pos+2+marker[0].length,{class:'callout-source-marker'}));}});
    lastDoc=state.doc;lastSet=DecorationSet.create(state.doc,decorations);return lastSet;
  }}});
});

async function fallback(body:string){
  try{await editor?.destroy();}catch{}editor=null;
  host.innerHTML=`<article class="fallback-document">${safeHtml(rawHtml(body))}</article>`;track(resolveImages(host));
  for(const math of host.querySelectorAll<HTMLElement>('.math-inline,.math-display')){try{const isDisplay=math.classList.contains('math-display');const target=isDisplay&&math.parentElement?.tagName==='PRE'?math.parentElement:math;katex.render(math.textContent??'',target,{displayMode:isDisplay,throwOnError:false,trust:false})}catch{}}
  for(const code of host.querySelectorAll<HTMLElement>('pre>code')){const language=Array.from(code.classList).find(c=>c.startsWith('language-'))?.slice(9);if(language==='mermaid'){const diagram=document.createElement('div');diagram.className='diagram-preview';const source=code.textContent??'';code.parentElement!.replaceWith(diagram);renderStaticDiagram(diagram,source);}else if(language&&hljs.getLanguage(language))code.innerHTML=hljs.highlight(code.textContent??'',{language,ignoreIllegals:true}).value;}
}

let savedDoc:ProseNode|null=null;
let markdownCache=new Map<ProseNode,string>();
let serializedSnapshot:{markdown:string;doc:ProseNode}|null=null;
function currentDoc(){return editor!.editor.action(ctx=>ctx.get(editorViewCtx).state.doc);}
function getMarkdown(){
  if(!editor)return original;
  const doc=currentDoc();let markdown=markdownCache.get(doc);
  if(markdown===undefined){const start=performance.now();markdown=prefix+editor.getMarkdown();measure('serialize',start);markdownCache.set(doc,markdown);if(markdownCache.size>2)markdownCache.delete(markdownCache.keys().next().value!);}
  return markdown;
}
function isDirty(){if(!editor)return dirty;const doc=currentDoc();return prefix!==splitFrontmatter(savedMarkdown).prefix||!savedDoc||(!doc.eq(savedDoc)&&!equivalentEditorDocuments(doc,savedDoc));}
function serializeChecked(){
  if(!dirty)return savedMarkdown;
  if(!editable||!editor)throw new Error('Visual editing is unavailable for this document.');
  const markdown=getMarkdown();
  editor.editor.action(ctx=>{const parse=ctx.get(parserCtx),serialize=ctx.get(serializerCtx);const roundtrip=parse(markdown.slice(prefix.length));if(!roundtrip)throw new Error('The edited document could not be validated.');if(!equivalentEditorDocuments(ctx.get(editorViewCtx).state.doc,roundtrip))throw new Error('Some edited formatting cannot be saved as Markdown without changing its content. Undo the last formatting change or copy the affected text before saving.');assertRoundtrip(markdown,prefix+serialize(roundtrip));});
  serializedSnapshot={markdown,doc:currentDoc()};return markdown;
}

function updateDirty(){
  if(suppressed||!editor)return;
  const start=performance.now();dirty=isDirty();measure('dirty model',start);const markdown=dirty?getMarkdown():savedMarkdown;
  send({type:'dirty',dirty,markdown:dirty?markdown:savedMarkdown});measure('dirty total',start);scheduleOutline();
}
function scheduleOutline(){clearTimeout(outlineTimer);outlineTimer=window.setTimeout(()=>{const start=performance.now();buildOutline();measure('outline update',start);},200);}

let pendingLoad:LoadPayload|null=null,loadRunning=false;
async function load(payload:LoadPayload){pendingLoad=payload;if(loadRunning)return;loadRunning=true;try{while(pendingLoad){const current=pendingLoad;pendingLoad=null;await performLoad(current);}}finally{loadRunning=false;}}
async function performLoad(payload:LoadPayload){
  const start=performance.now();document.querySelectorAll<HTMLDialogElement>('.source-dialog[open]').forEach(dialog=>dialog.close());const myGeneration=++generation,previous=getState();suppressed=true;loaded=false;clearTimeout(changeTimer);context.documentId=payload.documentId;context.revision=payload.revision;
  original=payload.markdown;savedMarkdown=payload.savedMarkdown??original;debug=payload.debug??false;({prefix}=splitFrontmatter(original));const {body}=splitFrontmatter(original);editable=payload.editable;dirty=original!==savedMarkdown&&canonical(original)!==canonical(savedMarkdown);mode='read';formatting.close();toolbar.hidden=true;setTheme(payload.theme);setZoom(payload.zoom);setViewMode(false);
  measure('load setup',start);host.classList.add('loading');host.setAttribute('aria-busy','true');notice.hidden=true;
  savedDoc=null;markdownCache=new Map();
  if(myGeneration!==generation)return;
  if(!editor)host.replaceChildren();metadata.hidden=!prefix;metadata.querySelector('pre')!.textContent=prefix;
  measure('destroy',start);let reason='';
  try {
    const createStart=performance.now();let instance=editor;
    if(instance){
      instance.setReadonly(true);
      instance.editor.action(ctx=>{const view=ctx.get(editorViewCtx),doc=ctx.get(parserCtx)(body);if(!doc)throw new Error('The document could not be parsed.');const state=EditorState.create({schema:view.state.schema,doc,plugins:view.state.plugins});ctx.set(editorStateCtx,state);view.updateState(state);});
    }else{
    instance=new CrepeBuilder({root:host,defaultValue:body});editor=instance;
    // Start in reading mode without laying out an editable document first.
    instance.setReadonly(true);
    await instance.editor.remove([...remarkInlineLinkPlugin,...remarkPreserveEmptyLinePlugin,listener]);
    instance.addFeature(table);
    instance.editor.config(ctx=>{
      ctx.update(codeBlockSchema.key,prev=>inner=>{
        const schema=prev(inner);return {...schema,attrs:{...schema.attrs,meta:{default:''}},parseMarkdown:{match:node=>node.type==='code',runner:(state,node,type)=>{state.openNode(type,{language:node.lang??'',meta:node.meta??''});if(node.value)state.addText(String(node.value));state.closeNode();}},toMarkdown:{match:node=>node.type.name==='code_block',runner:(state,node)=>{state.addNode('code',undefined,node.textContent,{lang:node.attrs.language||null,meta:node.attrs.meta||null});}}};
      });
    }).use(mathRemark).use(parseCache).use(protectRemark).use(protectedBlock).use(protectedInline).use(protectedBlockView).use(protectedInlineView).use(imageView).use(codeView).use(quoteView).use(guard).use(calloutMarkers).use(formattingState).use(listView).use(anchorViews);
    await instance.create();
    instance.editor.action(ctx=>ctx.set(serializerCtx,createCachedSerializer(ctx.get(schemaCtx),ctx.get(remarkCtx),ctx.get(serializerCtx))));
    }
    measure('create',createStart);instance.setReadonly(true);refreshListViewMode();const validationStart=performance.now();
    const serialized=getMarkdown();
    savedDoc=dirty?instance.editor.action(ctx=>ctx.get(parserCtx)(splitFrontmatter(savedMarkdown).body)):currentDoc();serializedSnapshot=null;
    try{assertRoundtrip(original,serialized);}catch(error){editable=false;reason=String((error as Error).message);await fallback(body);}
    measure('validation',validationStart);if(!payload.editable&&!reason)reason='This document is read-only. Its original encoding or file permissions prevent safe visual editing.';
  } catch(error){
    editable=false;reason=`Visual editor unavailable: ${(error as Error).message}. This is a read-only preview.`;
    await fallback(body);
  }
  if(myGeneration!==generation)return;

  suppressed=false;loaded=true;formatting.sync();host.classList.remove('loading');host.removeAttribute('aria-busy');if(reason){notice.textContent=reason;notice.hidden=false;}
  const outlineStart=performance.now();buildOutline();measure('outline',outlineStart);measure('load total',start);restoreState(payload.scrollState??payload.state??previous);if(dirty)send({type:'dirty',dirty,markdown:original});
}

function setMode(next:'read'|'edit'){
  if(next==='edit'&&!editable){send({type:'status',message:notice.textContent||'This document can only be read.'});return false;}
  if(!loaded)return false;if(mode===next)return true;const start=performance.now();formatting.close();mode=next;
  // Apply layout changes together before ProseMirror reads selection geometry.
  // Otherwise showing the toolbar invalidates the layout a second time at focus.
  toolbar.hidden=next!=='edit';setViewMode(next==='edit');measure('mode views',start);
  editor?.setReadonly(next==='read');measure('mode readonly',start);refreshListViewMode();formatting.sync();measure('mode toolbar',start);if(next==='edit')editor?.editor.action(ctx=>ctx.get(editorViewCtx).focus());measure('mode',start);return true;
}
function setTheme(theme:'light'|'dark'){currentTheme=theme;document.documentElement.dataset.theme=theme;initializeMermaid(theme==='dark');if(loaded)setViewMode(mode==='edit');}
function setZoom(zoom:number){const ratio=zoom>4?zoom/100:zoom;document.documentElement.style.setProperty('--reader-font-size',`${17*Math.min(2.5,Math.max(.6,ratio||1))}px`);}
function headings(){return Array.from(host.querySelectorAll<HTMLElement>('h1,h2,h3,h4,h5,h6')).map(h=>({level:Number(h.tagName.slice(1)),text:h.textContent??'',id:h.id}));}
function buildOutline(){
  const items=app.querySelector('#outline-items')!,fragment=document.createDocumentFragment();
  // Lightweight paragraph/heading views own these two DOM attributes, so
  // assigning anchors does not make ProseMirror reparse document content.
  const anchors=Array.from(host.querySelectorAll<HTMLElement>('h1,h2,h3,h4,h5,h6,.ProseMirror>p,.fallback-document>p'),element=>({element,base:element.tagName==='P'?paragraphAnchor(element.textContent??''):headingAnchor(element.textContent??'')}));
  updateDocumentAnchors(anchors,host.querySelectorAll<HTMLElement>('[id]'));
  for(const heading of host.querySelectorAll<HTMLElement>('h1,h2,h3,h4,h5,h6')){
    const link=document.createElement('a');link.href=`#${heading.id}`;link.textContent=heading.textContent;
    link.style.paddingLeft=`${12+(Number(heading.tagName.slice(1))-1)*12}px`;fragment.append(link);
  }
  if(!fragment.childElementCount){const empty=document.createElement('p');empty.textContent='Headings appear here.';fragment.append(empty);}
  items.replaceChildren(fragment);
}
function getState():ScrollState{let anchor:HTMLElement|undefined;for(const h of host.querySelectorAll<HTMLElement>('[data-reader-anchor]')){if(h.getBoundingClientRect().top<=100)anchor=h;else break;}return {scrollY:window.scrollY,anchor:anchor?.id,offset:anchor?anchor.getBoundingClientRect().top:undefined};}
function restoreState(state:ScrollState){if(!editingRoot.isConnected)return;requestAnimationFrame(()=>{const target=state.anchor?document.getElementById(state.anchor):null;if(target)window.scrollTo({top:window.scrollY+target.getBoundingClientRect().top-(state.offset??0)});else window.scrollTo({top:state.scrollY??0});});}

async function prepareExport(requestId:string){
  const identity={documentId:context.documentId,revision:context.revision};
  // Printing uses the current in-memory document, including unsaved edits.
  setViewMode(false);document.body.classList.add('preparing-export');
  await document.fonts.ready;
  const deadline=Date.now()+12000;
  while(renderPending.size&&Date.now()<deadline)await Promise.race([Promise.allSettled([...renderPending]),new Promise(resolve=>setTimeout(resolve,400))]);
  const documentImages=Array.from(host.querySelectorAll<HTMLImageElement>('img[src]')).filter(img=>!!img.getAttribute('src'));
  await Promise.all(documentImages.map(img=>new Promise<void>(resolve=>{if(img.complete)return resolve();const timer=setTimeout(resolve,5000);img.addEventListener('load',()=>{clearTimeout(timer);resolve();},{once:true});img.addEventListener('error',()=>{clearTimeout(timer);resolve();},{once:true});})));
  await Promise.all(documentImages.map(img=>Promise.race([img.decode().catch(()=>{}),new Promise(resolve=>setTimeout(resolve,5000))])));
  await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
  const issues=[...renderIssues.entries()].filter(([element])=>element.isConnected).map(([,value])=>value);
  if(renderPending.size)issues.push('Some diagrams or images did not finish rendering before export.');
  for(const img of documentImages)if(!img.complete||!img.naturalWidth)issues.push(`Image unavailable: ${img.alt||img.title||'image'}`);
  send({...identity,type:'exportReady',requestId,issues:[...new Set(issues)],html:app.querySelector('#page')!.outerHTML,title:headings()[0]?.text??'Markdown document',bodyClass:''});
}

document.addEventListener('click',event=>{if(!editingRoot.isConnected)return;const target=(event.target as HTMLElement).closest<HTMLAnchorElement>('a[href]');if(!target)return;const href=target.getAttribute('href')??'';if(mode==='edit'&&host.contains(target)&&!(event.ctrlKey||event.metaKey)&&!target.closest('.protected-inline')){event.preventDefault();return;}event.preventDefault();if(href.startsWith('#')){let id=href.slice(1);try{id=decodeURIComponent(id)}catch{}document.getElementById(id)?.scrollIntoView({behavior:'smooth',block:'start'});}else send({type:'openLink',href});});
document.addEventListener('keydown',event=>{if(!editingRoot.isConnected)return;if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='s'){event.preventDefault();send({type:event.shiftKey?'saveAs':'save'});}if(event.key==='Escape'){document.querySelector<HTMLDialogElement>('dialog[open]')?.close();}});
// Crepe's generic upload plugin runs before later ProseMirror handlers. Stop
// binary transfers during capture so it cannot create a temporary blob node.
document.addEventListener('paste',event=>{if(host.contains(event.target as Node)&&Array.from(event.clipboardData?.items??[]).some(item=>item.kind==='file')){event.preventDefault();event.stopImmediatePropagation();status('Use Insert → Image from file to add an existing image. Image paste is not supported.');}},true);
document.addEventListener('drop',event=>{if(host.contains(event.target as Node)&&event.dataTransfer?.files.length){event.preventDefault();event.stopImmediatePropagation();status('Use Insert → Image from file to add an existing image.');}},true);

let scrollTimer=0;window.addEventListener('scroll',()=>{if(!editingRoot.isConnected)return;clearTimeout(scrollTimer);scrollTimer=window.setTimeout(()=>send({type:'scroll',state:getState()}),180);},{passive:true});
export const editingReader={
  load,setMode,setTheme,setZoom,assetResolved,imageChosen,prepareExport,
  invalidate(){generation++;suppressed=true;loaded=false;clearTimeout(changeTimer);clearTimeout(outlineTimer);document.querySelectorAll<HTMLDialogElement>('.source-dialog[open]').forEach(dialog=>dialog.close());},
  flush(){clearTimeout(changeTimer);if(!suppressed)updateDirty();},
  suspend(){mode='read';formatting.close();setViewMode(false);document.querySelectorAll<HTMLDialogElement>('.source-dialog[open]').forEach(dialog=>dialog.close());},
  resume(state:ScrollState){mode='edit';document.body.classList.add('editing');setViewMode(true);formatting.sync();editor?.editor.action(ctx=>ctx.get(editorViewCtx).focus());restoreState(state);},
  exportFinished(){document.body.classList.remove('preparing-export');setViewMode(mode==='edit');},
  serialize(requestId:string){clearTimeout(changeTimer);if(!suppressed)updateDirty();try{send({type:'serialized',requestId,dirty,markdown:serializeChecked(),ok:true});}catch(error){send({type:'serialized',requestId,dirty,ok:false,error:(error as Error).message});}},
  markSaved(markdown:string,revision?:number){original=markdown;savedMarkdown=markdown;if(editor){savedDoc=serializedSnapshot?.markdown===markdown?serializedSnapshot.doc:getMarkdown()===markdown?currentDoc():editor.editor.action(ctx=>ctx.get(parserCtx)(splitFrontmatter(markdown).body));}if(revision!==undefined)context.revision=revision;updateDirty();},
  rebase(requestId:string,oldBase:string,newBase:string){clearTimeout(changeTimer);if(!suppressed)updateDirty();try{send({type:'rebased',requestId,ok:true,markdown:rebaseMarkdown(serializeChecked(),oldBase,newBase)});}catch(error){send({type:'rebased',requestId,ok:false,error:(error as Error).message});}},
  refreshAssets(){for(const image of host.querySelectorAll('.document-image'))image.dispatchEvent(new Event('reader-refresh-assets'));},
  scrollToHeading(fragment:string){let id=fragment.replace(/^#/,'');try{id=decodeURIComponent(id)}catch{}document.getElementById(id)?.scrollIntoView({block:'start'});},
  testInsertText(text:string,flush=true){if(!debug)throw new Error('Test operations are disabled.');if(mode!=='edit')throw new Error('Enter Edit mode first.');viewAction(view=>view.dispatch(view.state.tr.insertText(text,Math.max(1,view.state.doc.content.size-1))));if(flush)updateDirty();},
  testSelectText(text:string){if(!debug)throw new Error('Test operations are disabled.');let found=false;viewAction(view=>{view.state.doc.descendants((node:any,pos:number)=>{if(found||!node.isText)return;const index=node.text.indexOf(text);if(index>=0){view.dispatch(view.state.tr.setSelection(TextSelection.create(view.state.doc,pos+index,pos+index+text.length)));found=true;}})});if(!found)throw new Error(`Text not found: ${text}`);return true;},
  testSelectRange(from:number,to:number=from){if(!debug)throw new Error('Test operations are disabled.');viewAction(view=>view.dispatch(view.state.tr.setSelection(TextSelection.create(view.state.doc,from,to))));},
  toggleOutline(){document.body.classList.toggle('show-outline');},
  find(text:string){return window.find?.(text,false,false,true,false,false,false);},
  performanceReport(){return {...timings};},getState,restoreState,requestState(requestId:string){send({type:'state',requestId,state:getState()});},
  // A read-only diagnostic surface helps native integration checks inspect actual WebKit state.
  inspect(){return {documentId:context.documentId,revision:context.revision,loaded,editable,mode,dirty,reason:notice.hidden?'':notice.textContent,markdown:getMarkdown(),headings:headings(),issues:[...renderIssues.values()],text:host.textContent,theme:currentTheme};},
};
