import type {Node,Schema} from '@milkdown/kit/prose/model';
import {SerializerState,type MarkdownNode,type RemarkParser,type Root,type Serializer} from '@milkdown/kit/transformer';

// These Reader block runners emit independent root children. Unknown extensions
// may inspect sibling state or span marks across blocks, so retain the full path.
const independentBlocks=new Set(['paragraph','heading','blockquote','bullet_list','ordered_list','code_block','hr','table','html','reader_block','footnote_definition']);

function freezeTree(value:unknown):void {
  if(!value||typeof value!=='object'||Object.isFrozen(value))return;
  for(const child of Object.values(value))freezeTree(child);
  Object.freeze(value);
}

/** Create one serializer per editor/schema; callers retain the full save checks. */
export function createCachedSerializer(schema:Schema,remark:RemarkParser,fallback:Serializer=SerializerState.create(schema,remark)):Serializer {
  // Undo history retains old PM nodes. Keep ASTs only for the current document,
  // not every historical version of a large list or code block.
  let blocks=new Map<Node,MarkdownNode[]>();
  let usable=true;
  function serializeWhole(doc:Node){blocks.clear();return fallback(doc);}
  return (doc:Node)=>{
    if(!usable||doc.type.schema!==schema||doc.type.name!=='doc'||doc.marks.length)return serializeWhole(doc);
    let supported=true;
    doc.forEach(block=>{if(block.marks.length||!independentBlocks.has(block.type.name))supported=false;});
    if(!supported)return serializeWhole(doc);
    try {
      const children:MarkdownNode[]=[],nextBlocks=new Map<Node,MarkdownNode[]>();
      doc.forEach(block=>{
        // Milkdown can treat an empty paragraph differently at the end of the
        // editor. Do not retain its AST when it moves to another position.
        const cacheable=block.type.name!=='paragraph'||block.content.size>0;
        let output=cacheable?(nextBlocks.get(block)??blocks.get(block)):undefined;
        if(!output){
          const root=new SerializerState(schema).openNode('root').next(block).build();
          if(root.type!=='root'||root.children?.some(child=>child.isMark))throw new Error('Block requires document-wide serialization.');
          output=root.children??[];
          // Standard stringify does not mutate the tree. Freeze it so a future
          // extension cannot silently corrupt a cached block for the next save.
          freezeTree(output);
        }
        if(cacheable)nextBlocks.set(block,output);
        for(const child of output)children.push(child);
      });
      // Stringify the assembled document once. Separately stringifying blocks
      // would change list separators, references, and Markdown escaping.
      const markdown=remark.stringify({type:'root',children} as Root);
      blocks=nextBlocks;return markdown;
    }catch{
      usable=false;
      return serializeWhole(doc);
    }
  };
}
