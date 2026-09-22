import katex from 'katex';
import hljs from 'highlight.js/lib/common';
import { $nodeSchema, $remark, $view } from '@milkdown/kit/utils';
import { codeBlockSchema,imageSchema,blockquoteSchema } from '@milkdown/kit/preset/commonmark';
import type { EditorView } from '@milkdown/kit/prose/view';
import type { Node } from '@milkdown/kit/prose/model';
import remarkMath from 'remark-math';
import {protectionPlugin,rawHtml} from './markdown';
import {context,send} from './bridge';
import {renderIssues,track,safeHtml,resolveImages,displayImage,diagramSvg,isDiagramDark,subscribeDiagramTheme,escapeHtml} from './rendering';
export {renderPending,renderIssues,initializeMermaid,renderStaticDiagram,track,safeHtml,resolveImages,escapeHtml} from './rendering';

export const modeListeners=new Set<()=>void>();
let editing=false;
export function setViewMode(value:boolean){if(editing===value)return;editing=value;modeListeners.forEach(fn=>fn());}

/** Source dialogs update atomic nodes without exposing the whole document as code. */
export function editSource(title:string,value:string,onSave:(value:string)=>void,options:{multiline?:boolean;label?:string}={}) {
  const documentId=context.documentId,revision=context.revision;
  const dialog=document.createElement('dialog');dialog.className='source-dialog';
  const form=document.createElement('form');form.method='dialog';
  const h=document.createElement('h2');h.textContent=title;
  const label=document.createElement('label');label.textContent=options.label??'Notation';
  const input=options.multiline===false?document.createElement('input'):document.createElement('textarea');
  input.value=value;input.spellcheck=false;label.append(input);
  const actions=document.createElement('div');actions.className='dialog-actions';
  const cancel=document.createElement('button');cancel.textContent='Cancel';cancel.type='button';cancel.onclick=()=>dialog.close();
  const save=document.createElement('button');save.className='primary';save.textContent='Apply';save.type='submit';
  actions.append(cancel,save);form.append(h,label,actions);dialog.append(form);document.body.append(dialog);
  form.onsubmit=e=>{e.preventDefault();if(editing&&context.documentId===documentId&&context.revision===revision)onSave(input.value);dialog.close();};dialog.onclose=()=>dialog.remove();dialog.showModal();input.focus();
}

function rawNode(inline:boolean) {return $nodeSchema(inline?'reader_inline':'reader_block',()=>({
  group:inline?'inline':'block',inline,atom:true,selectable:true,isolating:true,
  attrs:{raw:{default:''},kind:{default:''},notation:{default:''},label:{default:''},target:{default:''}},
  parseDOM:[{tag:inline?'span[data-reader-protected]':'div[data-reader-protected]',getAttrs:dom=>({raw:(dom as HTMLElement).dataset.raw??'',kind:(dom as HTMLElement).dataset.kind??''})}],
  toDOM:node=>[inline?'span':'div',{'data-reader-protected':'true','data-raw':node.attrs.raw,'data-kind':node.attrs.kind},node.attrs.raw],
  parseMarkdown:{match:node=>node.type===(inline?'readerInline':'readerBlock'),runner:(state,node,type)=>state.addNode(type,{raw:node.value,kind:node.kind,notation:node.notation,label:node.label,target:node.target})},
  toMarkdown:{match:node=>node.type.name===(inline?'reader_inline':'reader_block'),runner:(state,node)=>{state.addNode(inline?'readerInline':'readerBlock',undefined,node.attrs.raw);}},
}));}
export const protectedBlock=rawNode(false),protectedInline=rawNode(true);
export const protectRemark=$remark('reader-protection',()=>protectionPlugin);
export const mathRemark=$remark('reader-math',()=>remarkMath);

function protectedView(inline:boolean){return (node:Node,view:EditorView,getPos:()=>number|undefined)=>{
  let current=node;const dom=document.createElement(inline?'span':'div');dom.className=inline?'protected-inline':'protected-block';dom.contentEditable='false';
  const syncMode=()=>{
    const kind=String(current.attrs.kind),isMath=kind==='math'||kind==='inlineMath';
    dom.classList.toggle('protected-editing',editing);dom.classList.toggle('editable-atom',editing&&isMath);
    if(isMath)dom.title=editing?'Double-click to edit equation':'';
    if(kind==='definition')dom.textContent=editing?'Reference definition · source preserved':'';
  };
  const render=()=>{
    for(const image of dom.querySelectorAll('img'))renderIssues.delete(image);
    dom.replaceChildren();renderIssues.delete(dom);dom.dataset.kind=current.attrs.kind;
    dom.classList.remove('render-error','source-preserved','footnote-definition','reference-definition');dom.removeAttribute('title');dom.removeAttribute('id');
    const kind=String(current.attrs.kind),raw=String(current.attrs.raw);
    if(kind==='math'||kind==='inlineMath'){
      try {katex.render(String(current.attrs.notation),dom,{displayMode:kind==='math',throwOnError:true,trust:false,strict:'warn'});}
      catch(error){dom.textContent=raw;dom.classList.add('render-error');renderIssues.set(dom,`Equation could not be rendered: ${String(error)}`);}
    }else if(kind==='htmlFragment'){
      dom.innerHTML=safeHtml(rawHtml(raw)).replace(/^<p>/,'').replace(/<\/p>\n?$/,'');track(resolveImages(dom));dom.title='Embedded HTML source is preserved unchanged';
    }else if(kind==='html') {
      dom.innerHTML=safeHtml(raw);track(resolveImages(dom));
      if(!dom.textContent?.trim()&&!dom.querySelector('img,svg,br,hr')){dom.textContent='Embedded HTML · source preserved';dom.classList.add('source-preserved');}
      dom.title='HTML source is preserved unchanged';
    }else if(kind==='footnoteReference'){
      const link=document.createElement('a');link.href=`#${encodeURIComponent('fn-'+current.attrs.target)}`;link.className='footnote-link';link.textContent=String(current.attrs.label);dom.append(link);
    }else if(kind==='footnoteDefinition'){
      dom.id=`fn-${current.attrs.target}`;dom.classList.add('footnote-definition');
      const text=raw.replace(/^\[\^[^\]]+\]:\s*/,'');dom.innerHTML=`<span class="footnote-number"></span><div class="footnote-body">${safeHtml(rawHtml(text))}</div>`;
      dom.querySelector('.footnote-number')!.textContent=String(current.attrs.label);track(resolveImages(dom));
      dom.title='Footnote source is protected; double-click to edit';
    }else if(kind==='definition'){
      dom.classList.add('reference-definition');dom.textContent=editing?'Reference definition · source preserved':'';
    }else {dom.innerHTML=safeHtml(rawHtml(raw));track(resolveImages(dom));dom.title='Protected source';}
    syncMode();
  };
  dom.ondblclick=()=>{
    if(!editing||!['math','inlineMath','footnoteDefinition'].includes(current.attrs.kind))return;
    const isMath=['math','inlineMath'].includes(current.attrs.kind);
    editSource(isMath?'Edit equation':'Edit footnote',isMath?current.attrs.notation:current.attrs.raw,value=>{
      const pos=getPos();if(pos===undefined)return;
      const raw=isMath?(current.attrs.kind==='math'?`$$\n${value}\n$$`:`$${value}$`):value;
      view.dispatch(view.state.tr.setNodeMarkup(pos,undefined,{...current.attrs,raw,notation:isMath?value:current.attrs.notation}));
    });
  };
  render();modeListeners.add(syncMode);
  return {dom,update(next:Node){if(next.type!==current.type)return false;if(next.eq(current))return true;current=next;render();return true},ignoreMutation:()=>true,stopEvent:()=>true,destroy(){modeListeners.delete(syncMode);renderIssues.delete(dom);for(const image of dom.querySelectorAll('img'))renderIssues.delete(image)}};
};}
export const protectedBlockView=$view(protectedBlock.node,()=>protectedView(false));
export const protectedInlineView=$view(protectedInline.node,()=>protectedView(true));

export const imageView=$view(imageSchema.node,()=> (node,view,getPos)=>{
  const dom=document.createElement('span');dom.className='document-image';dom.contentEditable='false';
  let current=node;
  const render=()=>{dom.replaceChildren();const img=document.createElement('img');img.alt=String(current.attrs.alt??'');img.title=String(current.attrs.title??'');dom.append(img);track(displayImage(img,String(current.attrs.src)));};
  dom.ondblclick=()=>{if(!editing)return;editSource('Image address',current.attrs.src,src=>{const pos=getPos();if(pos!==undefined)view.dispatch(view.state.tr.setNodeMarkup(pos,undefined,{...current.attrs,src}))},{multiline:false,label:'File path or image URL'});};
  render();dom.addEventListener('reader-refresh-assets',render);return {dom,update(next){if(next.type!==current.type)return false;if(next.eq(current))return true;current=next;render();return true},ignoreMutation:()=>true,stopEvent:()=>true,destroy(){for(const image of dom.querySelectorAll('img'))renderIssues.delete(image);dom.removeEventListener('reader-refresh-assets',render)}};
});

export const codeView=$view(codeBlockSchema.node,()=> (node,view,getPos)=>{
  let current=node,generation=0;
  let previewSource:string|undefined,previewLanguage='',previewDark=false;
  const dom=document.createElement('div');dom.className='code-block';
  const bar=document.createElement('div');bar.className='code-bar';bar.contentEditable='false';
  const label=document.createElement('span');const buttons=document.createElement('span');
  const edit=document.createElement('button');edit.type='button';edit.textContent='Edit diagram';edit.onclick=()=>editSource('Edit Mermaid diagram',current.textContent,value=>{const pos=getPos();if(pos===undefined)return;view.dispatch(view.state.tr.replaceWith(pos+1,pos+1+current.content.size,value?view.state.schema.text(value):[]));});
  const copy=document.createElement('button');copy.type='button';copy.textContent='Copy';copy.title='Copy code';copy.onclick=async()=>{try{await navigator.clipboard.writeText(current.textContent);copy.textContent='Copied';setTimeout(()=>copy.textContent='Copy',1300);}catch{send({type:'copyText',text:current.textContent});copy.textContent='Copied';setTimeout(()=>copy.textContent='Copy',1300);}};
  buttons.append(edit,copy);bar.append(label,buttons);
  const pre=document.createElement('pre');const code=document.createElement('code');pre.append(code);
  const preview=document.createElement('div');preview.className='code-preview';preview.contentEditable='false';dom.append(bar,pre,preview);
  const render=()=>{
    const language=String(current.attrs.language??''),isDiagram=language.toLowerCase()==='mermaid';
    label.textContent=language||'Code';edit.hidden=!editing||!isDiagram;pre.hidden=!editing||isDiagram;preview.hidden=editing&&!isDiagram;
    if(!isDiagram&&editing){
      if(previewLanguage.toLowerCase()==='mermaid'){generation++;previewSource=undefined;previewLanguage=language;renderIssues.delete(dom);}
      return;
    }
    const source=current.textContent;
    if(previewSource===source&&previewLanguage===language&&(!isDiagram||previewDark===isDiagramDark()))return;
    previewSource=source;previewLanguage=language;previewDark=isDiagramDark();renderIssues.delete(dom);
    const key=++generation;
    if(isDiagram){
      preview.className='code-preview diagram-preview';preview.textContent='Rendering diagram…';
      const promise=diagramSvg(source).then(svg=>{if(key===generation)preview.innerHTML=svg;}).catch(error=>{if(key===generation){preview.textContent=source;preview.classList.add('render-error');renderIssues.set(dom,`Diagram could not be rendered: ${String(error).split('\n')[0]}`);}});track(promise);
    }else {preview.className='code-preview';const output=document.createElement('pre');const highlighted=document.createElement('code');try{highlighted.innerHTML=language&&hljs.getLanguage(language)?hljs.highlight(source,{language,ignoreIllegals:true}).value:escapeHtml(source);}catch{highlighted.textContent=source;}output.append(highlighted);preview.replaceChildren(output);}
  };
  const refreshDiagram=()=>{if(String(current.attrs.language??'').toLowerCase()==='mermaid')render();};
  render();modeListeners.add(render);const unsubscribeDiagramTheme=subscribeDiagramTheme(refreshDiagram);
  return {dom,contentDOM:code,update(next){if(next.type!==current.type)return false;const changed=!next.eq(current);current=next;if(changed)render();return true},ignoreMutation:mutation=>!code.contains(mutation.target),stopEvent:event=>bar.contains(event.target as globalThis.Node)||preview.contains(event.target as globalThis.Node),destroy(){modeListeners.delete(render);unsubscribeDiagramTheme();renderIssues.delete(dom);generation++;}};
});

export const quoteView=$view(blockquoteSchema.node,()=> (node)=>{
  let current=node;const dom=document.createElement('blockquote');const label=document.createElement('button');label.type='button';label.className='callout-label';label.contentEditable='false';const content=document.createElement('div');dom.append(label,content);let folded=false,foldingMarker='';
  const render=()=>{
    const match=current.firstChild?.textContent.match(/^\[!([^\]]+)\]([+-]?)(?:[ \t]+([^\n]+))?/),nextMarker=match?.[2]??'';
    // Preserve a reader's fold choice while the marker is unchanged, but adopt
    // a changed marker's default when an agent replaces this reused NodeView.
    if(nextMarker!==foldingMarker){foldingMarker=nextMarker;folded=nextMarker==='-';}
    dom.classList.toggle('callout',!!match);label.hidden=!match;dom.classList.toggle('callout-reading',!editing);
    if(match){
      const type=match[1].charAt(0).toUpperCase()+match[1].slice(1).toLowerCase().replace(/-/g,' ');
      const title=match[3]?.trim(),visible=title&&title.toLowerCase()!==type.toLowerCase()?`${type} · ${title}`:type;
      dom.dataset.callout=match[1].toLowerCase();label.textContent=`${match[2]?(folded?'▸ ':'▾ '):''}${visible}`;
      label.disabled=!match[2];content.hidden=!editing&&!!foldingMarker&&folded;
    }else content.hidden=false;
  };
  label.onclick=()=>{folded=!folded;render();};render();modeListeners.add(render);
  return {dom,contentDOM:content,update(next){if(next.type!==current.type)return false;if(next.eq(current))return true;current=next;render();return true},ignoreMutation:mutation=>(mutation.type==='attributes'&&mutation.target===content&&mutation.attributeName==='hidden')||!content.contains(mutation.target),stopEvent:event=>label.contains(event.target as globalThis.Node),destroy(){modeListeners.delete(render)}};
});
