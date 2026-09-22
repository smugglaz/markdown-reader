import {rawHtml} from './markdown';
import {send} from './bridge';
import {safeHtml,resolveImages,renderStaticDiagram,renderIssues,track} from './rendering';
import './reading.css';

const diagramSources=new WeakMap<HTMLElement,string>();

/** Refresh cached reading DOM after its theme changed while detached. */
export function refreshReadingTheme(host:HTMLElement):void {
  for(const element of host.querySelectorAll<HTMLElement>('[data-reader-static-diagram]')){
    const source=diagramSources.get(element);if(source!==undefined)renderStaticDiagram(element,source);
  }
}

/** GFM emits these disabled inputs; retain their state through HTML sanitizing. */
export function preserveReadingTasks(html:string):string {
  return html.replace(/<input type="checkbox"( checked)? disabled>/g,(_input,checked:string|undefined)=>
    `<span class="reading-task-marker" role="checkbox" aria-checked="${!!checked}" aria-readonly="true" aria-disabled="true">${checked?'☑':'☐'}</span>`);
}

export function readingCallout(text:string):{length:number;kind:string;title:string;fold:'+'|'-'|''}|null {
  const match=text.match(/^\[!([^\]\n]+)\]([+-]?)(?:[ \t]+([^\n]*))?(?:\n|$)/);
  if(!match)return null;
  const kind=match[1].toLowerCase();
  return {length:match[0].length,kind,title:match[3]?.trim()||kind.charAt(0).toUpperCase()+kind.slice(1),fold:match[2] as '+'|'-'|''};
}

function renderCallouts(article:HTMLElement):void {
  for(const quote of article.querySelectorAll<HTMLElement>('blockquote')){
    const first=quote.firstElementChild;
    if(!first||first.tagName!=='P')continue;
    // A hard line break also ends the marker/title line. Ordinary Markdown
    // soft breaks remain newline text in the generated paragraph.
    const text=Array.from(first.childNodes).map(node=>node.nodeName==='BR'?'\n':node.textContent??'').join('');
    const callout=readingCallout(text);if(!callout)continue;
    let remaining=callout.length;
    function removePrefix(parent:Node):void {
      for(const child of Array.from(parent.childNodes)){
        if(!remaining)break;
        if(child.nodeType===Node.TEXT_NODE){
          const count=Math.min(remaining,child.textContent?.length??0);
          child.textContent=(child.textContent??'').slice(count);remaining-=count;
          if(!child.textContent)child.remove();
        }else if(child.nodeName==='BR'){child.remove();remaining--;}
        else {removePrefix(child);if(!child.textContent&&!child.childNodes.length)child.remove();}
      }
    }
    removePrefix(first);if(!first.textContent?.trim()&&!first.querySelector('img,svg,br'))first.remove();
    const content=document.createElement('div');content.className='reading-callout-content';
    content.append(...Array.from(quote.childNodes));
    const label=document.createElement(callout.fold?'button':'div');label.className='callout-label';
    let folded=callout.fold==='-';
    const update=()=>{
      label.textContent=`${callout.fold?(folded?'▸ ':'▾ '):''}${callout.title}`;
      content.hidden=folded;
      if(callout.fold)label.setAttribute('aria-expanded',String(!folded));
    };
    if(label instanceof HTMLButtonElement){label.type='button';label.onclick=()=>{folded=!folded;update();};}
    quote.classList.add('callout','reading-callout');quote.dataset.callout=callout.kind;
    quote.append(label,content);update();
  }
}

function renderImages(article:HTMLElement):void {
  for(const image of article.querySelectorAll<HTMLImageElement>('img')){
    const source=image.getAttribute('src')??'';
    const wrapper=document.createElement('span');wrapper.className='document-image';
    image.replaceWith(wrapper);wrapper.append(image);
    const refresh=()=>{
      image.onerror=null;image.classList.remove('unavailable');renderIssues.delete(image);
      image.setAttribute('src',source);track(resolveImages(wrapper));
    };
    wrapper.addEventListener('reader-refresh-assets',refresh);refresh();
  }
}

function renderMath(article:HTMLElement):void {
  const equations=Array.from(article.querySelectorAll<HTMLElement>('.math-inline,.math-display')).map(source=>{
    const display=source.classList.contains('math-display'),notation=source.textContent??'';
    const target=document.createElement(display?'div':'span');target.className=display?'protected-block reading-math':'protected-inline reading-math';
    target.dataset.kind=display?'math':'inlineMath';target.textContent=notation;
    (display&&source.parentElement?.tagName==='PRE'?source.parentElement:source).replaceWith(target);
    return {target,notation,display};
  });
  if(!equations.length)return;
  track(import('katex').then(({default:katex})=>{
    for(const {target,notation,display} of equations){
      if(!article.contains(target))continue;
      try{katex.render(notation,target,{displayMode:display,throwOnError:true,trust:false,strict:'warn'});}
      catch(error){target.classList.add('render-error');target.textContent=notation;renderIssues.set(target,`Equation could not be rendered: ${String(error)}`);}
    }
  }).catch(error=>{
    for(const {target} of equations){target.classList.add('render-error');renderIssues.set(target,`Equation renderer unavailable: ${String(error)}`);}
  }));
}

function renderCode(article:HTMLElement):void {
  const highlights:{code:HTMLElement;language:string;source:string}[]=[];
  for(const code of article.querySelectorAll<HTMLElement>('pre>code')){
    const pre=code.parentElement!,source=code.textContent??'';
    const language=Array.from(code.classList).find(value=>value.startsWith('language-'))?.slice(9)??'';
    const block=document.createElement('div');block.className='code-block';
    const bar=document.createElement('div');bar.className='code-bar';
    const label=document.createElement('span');label.textContent=language||'Code';
    const copy=document.createElement('button');copy.type='button';copy.textContent='Copy';copy.title='Copy code';
    copy.onclick=async()=>{
      try{await navigator.clipboard.writeText(source);}catch{send({type:'copyText',text:source});}
      copy.textContent='Copied';setTimeout(()=>{copy.textContent='Copy';},1300);
    };
    bar.append(label,copy);pre.replaceWith(block);block.append(bar);
    if(language.toLowerCase()==='mermaid'){
      const preview=document.createElement('div');preview.className='diagram-preview';preview.textContent='Rendering diagram…';
      block.append(preview);diagramSources.set(preview,source);renderStaticDiagram(preview,source);
    }else {
      block.append(pre);if(language)highlights.push({code,language,source});
    }
  }
  if(highlights.length)track(import('highlight.js/lib/common').then(({default:hljs})=>{
    for(const {code,language,source} of highlights)if(article.contains(code)&&hljs.getLanguage(language)){
      try{code.innerHTML=hljs.highlight(source,{language,ignoreIllegals:true}).value;}catch{/* Plain code remains readable. */}
    }
  }).catch(()=>{/* Plain code remains readable if highlighting is unavailable. */}));
}

/** Render the body (metadata already separated by the shell), without editing. */
export async function renderReading(host:HTMLElement,markdown:string):Promise<void> {
  for(const element of renderIssues.keys())if(host.contains(element))renderIssues.delete(element);
  const article=document.createElement('article');article.className='fallback-document reading-document';
  article.innerHTML=safeHtml(preserveReadingTasks(rawHtml(markdown)));
  renderCallouts(article);renderMath(article);renderCode(article);renderImages(article);
  for(const table of article.querySelectorAll('table')){
    const scroll=document.createElement('div');scroll.className='reading-table';scroll.setAttribute('role','region');scroll.setAttribute('aria-label','Table');scroll.tabIndex=0;
    table.replaceWith(scroll);scroll.append(table);
  }
  host.replaceChildren(article);
  // Images, equations, syntax highlighting and diagrams are tracked separately.
  // Their completion is required for export, not for showing readable content.
}
