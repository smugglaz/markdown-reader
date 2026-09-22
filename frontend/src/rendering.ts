import DOMPurify from 'dompurify';
import {resolveAsset} from './bridge';

// Shared rendering services have no editor dependency, so reading can load first.
export const renderPending=new Set<Promise<unknown>>();
export const renderIssues=new Map<HTMLElement,string>();
let diagramCounter=0,diagramDark=false;
let mermaidModule:Promise<typeof import('mermaid')['default']>|undefined,configuredDiagramDark:boolean|undefined;
const diagramListeners=new Set<()=>void>();
const staticDiagrams=new WeakMap<HTMLElement,{source:string;dark:boolean;generation:number;pending:Promise<unknown>}>();

export function isDiagramDark(){return diagramDark;}
export function subscribeDiagramTheme(listener:()=>void):()=>void {
  diagramListeners.add(listener);
  return ()=>{diagramListeners.delete(listener);};
}
export function initializeMermaid(dark:boolean){
  if(diagramDark===dark)return;
  diagramDark=dark;diagramListeners.forEach(fn=>fn());
  for(const element of document.querySelectorAll<HTMLElement>('[data-reader-static-diagram]')){
    const previous=staticDiagrams.get(element);if(previous)renderStaticDiagram(element,previous.source);
  }
}
export async function diagramSvg(source:string){
  // Most documents have no diagrams. Load the renderer only when one needs it.
  const mermaid=await(mermaidModule??=import('mermaid').then(module=>module.default));
  if(configuredDiagramDark!==diagramDark){
    mermaid.initialize({startOnLoad:false,securityLevel:'strict',theme:diagramDark?'dark':'default',suppressErrorRendering:true,fontFamily:'system-ui, sans-serif',htmlLabels:false,flowchart:{htmlLabels:false},maxTextSize:150000});
    configuredDiagramDark=diagramDark;
  }
  const {svg}=await mermaid.render(`reader-diagram-${++diagramCounter}`,source);
  return DOMPurify.sanitize(svg,{USE_PROFILES:{svg:true,svgFilters:true},FORBID_TAGS:['script','foreignObject'],FORBID_ATTR:['onclick','onload']});
}
export function renderStaticDiagram(element:HTMLElement,source:string){
  const previous=staticDiagrams.get(element);
  if(previous?.source===source&&previous.dark===diagramDark)return previous.pending;
  const generation=(previous?.generation??0)+1;renderIssues.delete(element);element.dataset.readerStaticDiagram='true';
  const pending=track(diagramSvg(source).then(svg=>{if(staticDiagrams.get(element)?.generation===generation)element.innerHTML=svg;}).catch(error=>{
    if(staticDiagrams.get(element)?.generation!==generation)return;
    element.textContent=source;renderIssues.set(element,`Diagram could not be rendered: ${String(error).split('\n')[0]}`);
  }));
  staticDiagrams.set(element,{source,dark:diagramDark,generation,pending});return pending;
}
export function track<T>(promise:Promise<T>):Promise<T>{renderPending.add(promise);void promise.then(()=>renderPending.delete(promise),()=>renderPending.delete(promise));return promise;}
export function safeHtml(raw:string):string{return DOMPurify.sanitize(raw,{USE_PROFILES:{html:true,svg:true,svgFilters:true,mathMl:true},FORBID_TAGS:['style','script','iframe','object','embed','form','input','textarea','button','video','audio','link','meta'],FORBID_ATTR:['style','srcdoc','srcset'],ALLOW_DATA_ATTR:false});}

export async function resolveImages(root:HTMLElement){
  await Promise.all(Array.from(root.querySelectorAll('img')).map(async img=>{
    const original=img.getAttribute('src')??'';img.removeAttribute('src');
    await displayImage(img,original);
  }));
}

export async function displayImage(img:HTMLImageElement,src:string){
  img.referrerPolicy='no-referrer';img.alt=img.alt||'Image';
  const url=await resolveAsset(src);
  if(url){img.src=url;img.onerror=()=>{img.classList.add('unavailable');renderIssues.set(img,`Image unavailable: ${src}`);img.title=`Image unavailable: ${src}`;};}
  else {img.classList.add('unavailable');img.title=`Image unavailable: ${src}`;renderIssues.set(img,`Image unavailable: ${src}`);}
}

export function escapeHtml(text:string){const span=document.createElement('span');span.textContent=text;return span.innerHTML;}
