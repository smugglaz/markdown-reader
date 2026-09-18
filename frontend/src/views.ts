import DOMPurify from 'dompurify';
import katex from 'katex';
import mermaid from 'mermaid';
import hljs from 'highlight.js/lib/common';
import { $nodeSchema, $remark, $view } from '@milkdown/kit/utils';
import { codeBlockSchema,imageSchema,blockquoteSchema } from '@milkdown/kit/preset/commonmark';
import type { EditorView } from '@milkdown/kit/prose/view';
import type { Node } from '@milkdown/kit/prose/model';
import remarkMath from 'remark-math';
import {protectionPlugin,rawHtml} from './markdown';
import {resolveAsset,send} from './bridge';

export const renderPending=new Set<Promise<unknown>>();
export const renderIssues=new Map<HTMLElement,string>();
export const modeListeners=new Set<()=>void>();
let editing=false,diagramCounter=0;
export function setViewMode(value:boolean){editing=value;modeListeners.forEach(fn=>fn());}
export function initializeMermaid(dark:boolean){mermaid.initialize({startOnLoad:false,securityLevel:'strict',theme:dark?'dark':'default',suppressErrorRendering:true,fontFamily:'system-ui, sans-serif',htmlLabels:false,flowchart:{htmlLabels:false},maxTextSize:150000});}
export function renderStaticDiagram(element:HTMLElement,source:string){return track(mermaid.render(`reader-diagram-${++diagramCounter}`,source).then(({svg})=>{element.innerHTML=DOMPurify.sanitize(svg,{USE_PROFILES:{svg:true,svgFilters:true},FORBID_TAGS:['script','foreignObject'],FORBID_ATTR:['onclick','onload']});}).catch(error=>{element.textContent=source;renderIssues.set(element,`Diagram could not be rendered: ${String(error).split('\n')[0]}`);}));}
export function track<T>(promise:Promise<T>):Promise<T>{renderPending.add(promise);promise.finally(()=>renderPending.delete(promise));return promise;}
export function safeHtml(raw:string):string{return DOMPurify.sanitize(raw,{USE_PROFILES:{html:true,svg:true,svgFilters:true,mathMl:true},FORBID_TAGS:['style','script','iframe','object','embed','form','input','textarea','button','video','audio','link','meta'],FORBID_ATTR:['style','srcdoc','srcset'],ALLOW_DATA_ATTR:false});}

export async function resolveImages(root:HTMLElement){
  await Promise.all(Array.from(root.querySelectorAll('img')).map(async img=>{
    const original=img.getAttribute('src')??'';img.removeAttribute('src');
    await displayImage(img,original);
  }));
}

async function displayImage(img:HTMLImageElement,src:string){
  img.referrerPolicy='no-referrer';img.alt=img.alt||'Image';
  const url=await resolveAsset(src);
  if(url){img.src=url;img.onerror=()=>{img.classList.add('unavailable');renderIssues.set(img,`Image unavailable: ${src}`);img.title=`Image unavailable: ${src}`;};}
  else {img.classList.add('unavailable');img.title=`Image unavailable: ${src}`;renderIssues.set(img,`Image unavailable: ${src}`);}
}

/** Source dialogs update atomic nodes without exposing the whole document as code. */
export function editSource(title:string,value:string,onSave:(value:string)=>void,options:{multiline?:boolean;label?:string}={}) {
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
  form.onsubmit=e=>{e.preventDefault();onSave(input.value);dialog.close();};dialog.onclose=()=>dialog.remove();dialog.showModal();input.focus();
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
  const render=()=>{
    dom.replaceChildren();renderIssues.delete(dom);dom.dataset.kind=current.attrs.kind;
    const kind=String(current.attrs.kind),raw=String(current.attrs.raw);
    if(kind==='math'||kind==='inlineMath'){
      try {katex.render(String(current.attrs.notation),dom,{displayMode:kind==='math',throwOnError:true,trust:false,strict:'warn'});}
      catch(error){dom.textContent=raw;dom.classList.add('render-error');renderIssues.set(dom,`Equation could not be rendered: ${String(error)}`);}
      if(editing){dom.title='Double-click to edit equation';dom.classList.add('editable-atom');}
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
    dom.classList.toggle('protected-editing',editing);
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
  render();modeListeners.add(render);
  return {dom,update(next:Node){if(next.type!==current.type)return false;current=next;render();return true},ignoreMutation:()=>true,stopEvent:()=>true,destroy(){modeListeners.delete(render);renderIssues.delete(dom)}};
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
    label.textContent=language||'Code';edit.hidden=!editing||!isDiagram;pre.hidden=!editing||isDiagram;preview.hidden=editing&&!isDiagram;renderIssues.delete(dom);
    if(isDiagram){
      const key=++generation;preview.className='code-preview diagram-preview';preview.textContent='Rendering diagram…';
      const promise=mermaid.render(`reader-diagram-${++diagramCounter}`,current.textContent).then(({svg})=>{if(key===generation){preview.innerHTML=DOMPurify.sanitize(svg,{USE_PROFILES:{svg:true,svgFilters:true},FORBID_TAGS:['script','foreignObject'],FORBID_ATTR:['onclick','onload']});}}).catch(error=>{if(key===generation){preview.textContent=current.textContent;preview.classList.add('render-error');renderIssues.set(dom,`Diagram could not be rendered: ${String(error).split('\n')[0]}`);}});track(promise);
    }else if(!editing){preview.className='code-preview';const output=document.createElement('pre');const highlighted=document.createElement('code');try{highlighted.innerHTML=language&&hljs.getLanguage(language)?hljs.highlight(current.textContent,{language,ignoreIllegals:true}).value:escapeHtml(current.textContent);}catch{highlighted.textContent=current.textContent;}output.append(highlighted);preview.replaceChildren(output);}
  };
  render();modeListeners.add(render);
  return {dom,contentDOM:code,update(next){if(next.type!==current.type)return false;const changed=!next.eq(current);current=next;if(changed)render();return true},ignoreMutation:mutation=>!code.contains(mutation.target),stopEvent:event=>bar.contains(event.target as globalThis.Node)||preview.contains(event.target as globalThis.Node),destroy(){modeListeners.delete(render);renderIssues.delete(dom);generation++;}};
});

export const quoteView=$view(blockquoteSchema.node,()=> (node)=>{
  let current=node;const dom=document.createElement('blockquote');const label=document.createElement('button');label.type='button';label.className='callout-label';label.contentEditable='false';const content=document.createElement('div');dom.append(label,content);let folded=false;
  const render=()=>{const match=current.firstChild?.textContent.match(/^\[!([^\]]+)\]([+-]?)(?:[ \t]+([^\n]+))?/);dom.classList.toggle('callout',!!match);label.hidden=!match;dom.classList.toggle('callout-reading',!editing);if(match){dom.dataset.callout=match[1].toLowerCase();label.textContent=`${match[2]?(folded?'▸ ':'▾ '):''}${match[3]||match[1].charAt(0).toUpperCase()+match[1].slice(1).toLowerCase()}`;label.disabled=!match[2];content.hidden=!editing&&folded;}else content.hidden=false;};
  const initial=current.firstChild?.textContent.match(/^\[![^\]]+\](-)/);folded=!!initial;label.onclick=()=>{folded=!folded;render();};render();modeListeners.add(render);
  return {dom,contentDOM:content,update(next){if(next.type!==current.type)return false;current=next;render();return true},ignoreMutation:mutation=>!content.contains(mutation.target),stopEvent:event=>label.contains(event.target as globalThis.Node),destroy(){modeListeners.delete(render)}};
});

export function escapeHtml(text:string){const span=document.createElement('span');span.textContent=text;return span.innerHTML;}
