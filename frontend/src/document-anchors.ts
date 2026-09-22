export function headingAnchor(text:string):string {
  return text.toLowerCase().trim().replace(/[^\p{L}\p{N}\s_-]/gu,'').replace(/\s+/g,'-')||'heading';
}

export function paragraphAnchor(text:string):string {
  let hash=2166136261;
  for(const character of text.slice(0,140))hash=Math.imul(hash^character.charCodeAt(0),16777619);
  return `reader-paragraph-${hash>>>0}`;
}

/** Reserve unique IDs without rescanning earlier suffixes for each duplicate. */
export function createAnchorAllocator(used:Set<string>):(base:string)=>string {
  const nextSuffix=new Map<string,number>();
  return base=>{
    let suffix=nextSuffix.get(base)??0,id=suffix?`${base}-${suffix}`:base;
    while(used.has(id)){suffix++;id=`${base}-${suffix}`;}
    used.add(id);nextSuffix.set(base,suffix+1);return id;
  };
}

type AnchorElement={id:string;dataset:{readerAnchor?:string}};
type AnchorTarget={element:AnchorElement;base:string};

/** Reassign owned IDs in document order; explicit HTML IDs always stay fixed. */
export function updateDocumentAnchors(targets:readonly AnchorTarget[],identifiedElements:Iterable<AnchorElement>):void {
  const generated=new Set(targets.filter(({element})=>!element.id||element.dataset.readerAnchor==='generated').map(({element})=>element));
  const reserved=new Set<string>();
  // Reserve explicit IDs throughout the document, including protected HTML
  // outside the outline. Old generated IDs must not reserve their old numbers.
  for(const element of identifiedElements)if(element.id&&!generated.has(element))reserved.add(element.id);
  const allocate=createAnchorAllocator(reserved);
  for(const {element,base} of targets){
    const owned=generated.has(element),id=owned?allocate(base):element.id,marker=owned?'generated':'fixed';
    if(element.id!==id)element.id=id;
    if(element.dataset.readerAnchor!==marker)element.dataset.readerAnchor=marker;
  }
}
