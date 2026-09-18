import { unified } from 'unified';
import remarkParse from 'remark-parse';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import remarkRehype from 'remark-rehype';
import rehypeStringify from 'rehype-stringify';
import {decodeString} from 'micromark-util-decode-string';

export type Ast = {type: string; children?: Ast[]; position?: {start:{offset?:number};end:{offset?:number}}; [key:string]: unknown};
export const parser = unified().use(remarkParse).use(remarkGfm).use(remarkMath);
const htmlProcessor = unified().use(remarkParse).use(remarkGfm).use(remarkMath).use(remarkRehype, {allowDangerousHtml:true}).use(rehypeStringify,{allowDangerousHtml:true});

export function splitFrontmatter(source:string): {prefix:string;body:string} {
  const match = source.match(/^(?:\uFEFF)?---\r?\n(?:[\s\S]*?\r?\n)?(?:---|\.\.\.)(?:\r?\n|$)/);
  return match ? {prefix:match[0],body:source.slice(match[0].length)} : {prefix:'',body:source};
}

export function rawHtml(source:string):string {
  return String(htmlProcessor.processSync(source));
}

/** Compare meaning, allowing changes in Markdown delimiters and list spacing. */
export function canonical(source:string):string {
  const {prefix,body} = splitFrontmatter(source.replace(/\r\n/g,'\n'));
  const tree=parser.parse(body) as Ast;
  const definitions=new Map<string,Ast>();
  function scan(node:Ast) { if(node.type==='definition'&&!definitions.has(String(node.identifier))) definitions.set(String(node.identifier),node); node.children?.forEach(scan); }
  scan(tree);
  function normalize(node:Ast): unknown {
    let n={...node};
    if(n.type==='linkReference'||n.type==='imageReference') {
      const def=definitions.get(String(n.identifier));
      if(def) n={...n,type:n.type==='linkReference'?'link':'image',url:def.url,title:def.title,identifier:undefined,label:undefined,referenceType:undefined};
    }
    const out:Record<string,unknown>={};
    for(const k of Object.keys(n).sort()) {
      const value=n[k];
      if(['position','data','spread'].includes(k)||value===null||value===undefined) continue;
      if(k==='children') out[k]=(value as Ast[]).map(normalize);
      else out[k]=value;
    }
    return out;
  }
  return JSON.stringify({prefix,tree:normalize(tree)});
}

export function assertRoundtrip(before:string,after:string):void {
  if(canonical(before)!==canonical(after)) throw new Error('This document uses formatting the visual editor cannot yet preserve. Reading and PDF export remain available.');
  if(/!\[[^\]]*\]\((?:blob:|reader:)/i.test(after)) throw new Error('A temporary image URL cannot be saved. Use Insert Image to choose an existing file.');
}

/** Compare the editor model itself, not only two outputs of the serializer. */
export function canonicalEditorModel(input:any):string {
  function normalize(node:any):any {
    const result:any={type:node.type};
    if(node.text!==undefined)result.text=node.text;
    if(node.marks?.length)result.marks=node.marks.map(normalize).sort((a:any,b:any)=>JSON.stringify(a).localeCompare(JSON.stringify(b)));
    const attrs:Record<string,unknown>={};
    for(const key of Object.keys(node.attrs??{}).sort()){
      if(key==='id'||key==='spread'||key==='colwidth'||(node.type==='list_item'&&['label','listType'].includes(key)))continue;
      if(['reader_block','reader_inline'].includes(node.type)&&!['raw','kind'].includes(key))continue;
      const value=node.attrs[key];if(value===null||value===undefined||value==='')continue;attrs[key]=value;
    }
    if(Object.keys(attrs).length)result.attrs=attrs;
    const children=(node.content??[]).filter((child:any)=>!(child.type==='paragraph'&&!child.content?.length)).map(normalize);
    if(children.length)result.content=children;
    return result;
  }
  return JSON.stringify(normalize(input));
}

export function rebaseMarkdown(source:string,oldBase:string,newBase:string):string {
  const {prefix,body}=splitFrontmatter(source);
  const tree=parser.parse(body) as Ast;
  const edits:{start:number;end:number;text:string}[]=[];
  function relative(url:string):string {
    if(!url||url.startsWith('#')||url.startsWith('/')||/^[a-z][a-z0-9+.-]*:/i.test(url))return url;
    const target=new URL(url,`file://${oldBase.split('/').map(encodeURIComponent).join('/')}/`);
    const oldParts=decodeURIComponent(target.pathname).split('/').filter(Boolean),newParts=newBase.split('/').filter(Boolean);
    while(oldParts.length&&newParts.length&&oldParts[0]===newParts[0]){oldParts.shift();newParts.shift();}
    return [...newParts.map(()=>'..'),...oldParts.map(encodeURIComponent)].join('/')+target.search+target.hash;
  }
  function walk(node:Ast){
    const start=node.position?.start.offset,end=node.position?.end.offset;
    if(start!==undefined&&end!==undefined){
      const raw=body.slice(start,end);
      if(typeof node.url==='string'&&relative(node.url)!==node.url){
        let destinationStart=-1;
        if(node.type==='definition')destinationStart=raw.match(/^\s*\[[^\]]+\]:\s*/)?.[0].length??-1;
        else {const index=raw.lastIndexOf('](');if(index>=0)destinationStart=index+2+(raw.slice(index+2).match(/^\s*/)?.[0].length??0);}
        if(destinationStart>=0){
          const angled=raw[destinationStart]==='<';if(angled)destinationStart++;
          let destinationEnd=destinationStart,depth=0;
          for(;destinationEnd<raw.length;destinationEnd++){
            const char=raw[destinationEnd];if(char==='\\'){destinationEnd++;continue;}
            if(angled&&char==='>')break;
            if(!angled){if(char==='(')depth++;if(char===')'){if(!depth)break;depth--;}if(/\s/.test(char)&&!depth)break;}
          }
          edits.push({start:start+destinationStart,end:start+destinationEnd,text:relative(node.url)});
        }
      }
      if(node.type==='html'){
        // Limit attribute replacement to opening tags; do not rewrite displayed
        // text that merely looks like src="...". Preserve all surrounding HTML.
        let cursor=0;
        while(cursor<raw.length){
          const tagStart=raw.indexOf('<',cursor);if(tagStart<0)break;
          if(raw.startsWith('<!--',tagStart)){const endComment=raw.indexOf('-->',tagStart+4);cursor=endComment<0?raw.length:endComment+3;continue;}
          const opening=raw.slice(tagStart).match(/^<([a-z][\w:.-]*)\b/i);if(!opening){cursor=tagStart+1;continue;}
          let at=tagStart+opening[0].length;
          while(at<raw.length&&raw[at]!=='>'){
            while(/\s/.test(raw[at]??'')&&at<raw.length)at++;
            if(raw[at]==='>'||raw[at]==='/'){at++;break;}
            const nameStart=at;while(at<raw.length&&!/[\s=/>]/.test(raw[at]))at++;
            const name=raw.slice(nameStart,at).toLowerCase();if(!name){at++;continue;}
            while(/\s/.test(raw[at]??'')&&at<raw.length)at++;
            if(raw[at]!=='=')continue;at++;while(/\s/.test(raw[at]??'')&&at<raw.length)at++;
            const quote=raw[at]==='"'||raw[at]==="'"?raw[at++]:null,valueStart=at;
            while(at<raw.length&&(quote?raw[at]!==quote:!/[\s>]/.test(raw[at])))at++;
            const value=raw.slice(valueStart,at);if(quote&&raw[at]===quote)at++;
            if(name==='src'||name==='href'){
              const decoded=decodeString(value),rebased=relative(decoded);
              if(rebased!==decoded)edits.push({start:start+valueStart,end:start+valueStart+value.length,text:rebased.replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/'/g,'&#39;')});
            }
          }
          cursor=Math.max(at+1,tagStart+1);
          if(/^(script|style|textarea|title)$/i.test(opening[1])){const close=raw.toLowerCase().indexOf(`</${opening[1].toLowerCase()}`,cursor);cursor=close<0?raw.length:close;}
        }
      }
    }
    node.children?.forEach(walk);
  }
  walk(tree);let result=body;for(const edit of edits.sort((a,b)=>b.start-a.start))result=result.slice(0,edit.start)+edit.text+result.slice(edit.end);return prefix+result;
}

/** Keep unsupported syntax in atom nodes with its original bytes. */
export function protectionPlugin(this:any) {
  const data=this.data();
  const extensions=data.toMarkdownExtensions||(data.toMarkdownExtensions=[]);
  extensions.push({handlers:{readerBlock:(node:Ast)=>String(node.value??''),readerInline:(node:Ast)=>String(node.value??'')}});
  return (input:any,file:{value?:unknown})=> {
    const tree=input as Ast;
    const source=String(file.value??'');
    const definitions=new Map<string,Ast>();
    function scan(node:Ast) {if(node.type==='definition'&&!definitions.has(String(node.identifier)))definitions.set(String(node.identifier),node);node.children?.forEach(scan);}
    scan(tree);
    function walk(node:Ast,parent?:Ast) {
      if(!node.children)return;
      node.children=node.children.map(child=> {
        // Inline HTML must be sanitized as a complete paragraph: independently
        // rendering opening and closing tag atoms changes its visible meaning.
        function hasHtml(n:Ast):boolean{return n.type==='html'||!!n.children?.some(hasHtml);}
        const start=child.position?.start.offset,end=child.position?.end.offset;
        const exact=start!==undefined&&end!==undefined?source.slice(start,end):String(child.value??'');
        if(['heading','tableCell'].includes(child.type)&&hasHtml(child)&&child.children?.length){
          const first=child.children[0].position?.start.offset,last=child.children.at(-1)?.position?.end.offset;
          if(first!==undefined&&last!==undefined)return {...child,children:[{type:'readerInline',value:source.slice(first,last),kind:'htmlFragment'}]};
        }
        if(child.type==='paragraph'&&hasHtml(child))return {type:'readerBlock',value:exact,kind:'htmlParagraph',position:child.position};
        if(child.type==='paragraph'&&/(?:!?\[\[[^\]]+\]\]|^:::)/m.test(exact))return {type:'readerBlock',value:exact,kind:'extension',position:child.position};
        if(child.type==='linkReference'||child.type==='imageReference') {
          const def=definitions.get(String(child.identifier));
          if(def) child={...child,type:child.type==='linkReference'?'link':'image',url:def.url,title:def.title};
        }
        const kind=child.type;
        if(['html','math','inlineMath','footnoteDefinition','footnoteReference','definition'].includes(kind)) {
          const raw=exact;
          const inline=kind==='inlineMath'||kind==='footnoteReference'||(kind==='html'&&['paragraph','heading','tableCell','emphasis','strong','delete','link'].includes(node.type));
          return {type:inline?'readerInline':'readerBlock',value:raw,kind,notation:child.value??'',label:child.label??child.identifier??'',target:child.identifier??'',position:child.position};
        }
        walk(child,node);return child;
      });
    }
    walk(tree);
  };
}
