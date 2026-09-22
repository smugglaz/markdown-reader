import type {Mark,Node as ProseNode} from '@milkdown/kit/prose/model';

type Attributes=Readonly<Record<string,unknown>>;

function attributeKeys(type:string,attrs:Attributes):string[] {
  const protectedNode=type==='reader_block'||type==='reader_inline';
  return Object.keys(attrs).filter(key=>{
    if(key==='id'||key==='spread'||key==='colwidth')return false;
    if(type==='list_item'&&(key==='label'||key==='listType'))return false;
    if(protectedNode&&key!=='raw'&&key!=='kind')return false;
    const value=attrs[key];return value!==null&&value!==undefined&&value!=='';
  }).sort();
}

function normalizedAttributes(type:string,attrs:Attributes):Record<string,unknown> {
  const normalized:Record<string,unknown>={};
  for(const key of attributeKeys(type,attrs))normalized[key]=attrs[key];
  return normalized;
}

function equivalentAttributes(type:string,a:Attributes,b:Attributes):boolean {
  if(a===b)return true;
  const left=attributeKeys(type,a),right=attributeKeys(type,b);
  // Such values are unusual in document attributes, but local JSON comparison
  // retains the exact canonical model behavior (omission, toJSON and NaN).
  const unusual=(keys:string[],attrs:Attributes)=>keys.some(key=>{
    const value=attrs[key];return typeof value==='function'||typeof value==='symbol'||typeof value==='number'&&!Number.isFinite(value);
  });
  if(unusual(left,a)||unusual(right,b))return JSON.stringify(normalizedAttributes(type,a))===JSON.stringify(normalizedAttributes(type,b))&&Boolean(left.length)===Boolean(right.length);
  if(left.length!==right.length)return false;
  for(let index=0;index<left.length;index++){
    const key=left[index];if(key!==right[index])return false;
    const first=a[key],second=b[key];
    if(first===second)continue;
    if(typeof first!=='object'&&typeof second!=='object')return false;
    if(JSON.stringify(first)!==JSON.stringify(second))return false;
  }
  return true;
}

function markSignature(mark:Mark):string {
  const attrs=normalizedAttributes(mark.type.name,mark.attrs);
  return JSON.stringify(Object.keys(attrs).length?{type:mark.type.name,attrs}:{type:mark.type.name});
}

function equivalentMarks(a:readonly Mark[],b:readonly Mark[]):boolean {
  if(a===b)return true;
  if(a.length!==b.length)return false;
  if(a.every((mark,index)=>mark===b[index]||(mark.type.name===b[index].type.name&&equivalentAttributes(mark.type.name,mark.attrs,b[index].attrs))))return true;
  const compare=(left:string,right:string)=>left.localeCompare(right);
  const left=a.map(markSignature).sort(compare),right=b.map(markSignature).sort(compare);
  return left.every((mark,index)=>mark===right[index]);
}

function emptyParagraph(node:ProseNode):boolean {
  return node.type.name==='paragraph'&&node.childCount===0;
}

/**
 * Compare the same meaning as canonicalEditorModel without serializing a whole
 * document. ProseMirror nodes are immutable: unchanged nodes and fragments can
 * be skipped, so ordinary edits visit only the changed branches. No model or
 * document strings are retained between comparisons.
 */
export function equivalentEditorDocuments(a:ProseNode,b:ProseNode):boolean {
  if(a===b)return true;
  if(a.type.name!==b.type.name||a.text!==b.text)return false;
  if(!equivalentAttributes(a.type.name,a.attrs,b.attrs)||!equivalentMarks(a.marks,b.marks))return false;
  if(a.content===b.content)return true;
  let left=0,right=0;
  while(true){
    while(left<a.childCount&&emptyParagraph(a.child(left)))left++;
    while(right<b.childCount&&emptyParagraph(b.child(right)))right++;
    if(left===a.childCount||right===b.childCount)return left===a.childCount&&right===b.childCount;
    if(!equivalentEditorDocuments(a.child(left++),b.child(right++)))return false;
  }
}
