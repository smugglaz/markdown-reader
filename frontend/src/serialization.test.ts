import {describe,expect,it,vi} from 'vitest';
import {Schema,type Node,type NodeSpec,type MarkSpec} from '@milkdown/kit/prose/model';
import {SerializerState,type RemarkParser} from '@milkdown/kit/transformer';
import {unified} from 'unified';
import remarkParse from 'remark-parse';
import remarkStringify from 'remark-stringify';
import remarkGfm from 'remark-gfm';
import {protectionPlugin} from './markdown';
import {createCachedSerializer} from './serialization';

function fixture(){
  const visits=vi.fn();
  function node(name:string,spec:NodeSpec,runner:(state:SerializerState,node:Node)=>void):NodeSpec {
    return {...spec,toMarkdown:{match:(node:Node)=>node.type.name===name,runner}};
  }
  function container(name:string,markdown:string,content:string):NodeSpec {
    return node(name,{content,group:'block'},(state,node)=>{state.openNode(markdown).next(node.content).closeNode();});
  }
  function mark(name:string,markdown:string):MarkSpec {
    return {toMarkdown:{match:(mark:any)=>mark.type.name===name,runner:(state:SerializerState,mark:any)=>state.withMark(mark,markdown)}};
  }
  const schema=new Schema({nodes:{
    doc:node('doc',{content:'block+',marks:'_'},(state,node)=>{state.openNode('root').next(node.content);}),
    paragraph:node('paragraph',{content:'inline*',group:'block'},(state,node)=>{visits(node);state.openNode('paragraph').next(node.content).closeNode();}),
    heading:node('heading',{content:'inline*',group:'block',attrs:{level:{default:1}}},(state,node)=>{state.openNode('heading',undefined,{depth:node.attrs.level}).next(node.content).closeNode();}),
    blockquote:container('blockquote','blockquote','block+'),
    bullet_list:node('bullet_list',{content:'list_item+',group:'block'},(state,node)=>{state.openNode('list',undefined,{ordered:false}).next(node.content).closeNode();}),
    ordered_list:node('ordered_list',{content:'list_item+',group:'block',attrs:{order:{default:1}}},(state,node)=>{state.openNode('list',undefined,{ordered:true,start:node.attrs.order}).next(node.content).closeNode();}),
    list_item:node('list_item',{content:'block+',attrs:{checked:{default:null}}},(state,node)=>{state.openNode('listItem',undefined,{checked:node.attrs.checked}).next(node.content).closeNode();}),
    code_block:node('code_block',{content:'text*',group:'block',marks:'',attrs:{language:{default:''},meta:{default:''}}},(state,node)=>{state.addNode('code',undefined,node.textContent,{lang:node.attrs.language,meta:node.attrs.meta});}),
    hr:node('hr',{group:'block'},state=>{state.addNode('thematicBreak');}),
    table:node('table',{group:'block',content:'table_row+'},(state,node)=>{state.openNode('table',undefined,{align:['left','right']}).next(node.content).closeNode();}),
    table_row:node('table_row',{content:'table_cell+'},(state,node)=>{state.openNode('tableRow').next(node.content).closeNode();}),
    table_cell:node('table_cell',{content:'inline*'},(state,node)=>{state.openNode('tableCell').next(node.content).closeNode();}),
    reader_block:node('reader_block',{group:'block',atom:true,attrs:{raw:{default:''}}},(state,node)=>{state.addNode('readerBlock',undefined,node.attrs.raw);}),
    reader_inline:node('reader_inline',{group:'inline',inline:true,atom:true,attrs:{raw:{default:''}}},(state,node)=>{state.addNode('readerInline',undefined,node.attrs.raw);}),
    text:node('text',{group:'inline'},(state,node)=>{state.addNode('text',undefined,node.text);}),
    hardbreak:node('hardbreak',{group:'inline',inline:true},state=>{state.addNode('break');}),
    extension:node('extension',{group:'block',atom:true},state=>{state.addNode('html',undefined,'<!-- preserved extension -->');}),
  },marks:{strong:mark('strong','strong'),emphasis:mark('emphasis','emphasis'),strike_through:mark('strike_through','delete'),link:{attrs:{href:{}},toMarkdown:{match:(mark:any)=>mark.type.name==='link',runner:(state:SerializerState,mark:any)=>state.withMark(mark,'link',undefined,{url:mark.attrs.href})}},inline_code:{toMarkdown:{match:(mark:any)=>mark.type.name==='inline_code',runner:(state:SerializerState,mark:any,node:Node)=>{state.withMark(mark,'inlineCode',node.textContent);return true;}}}}});
  const remark=unified().use(remarkParse).use(remarkStringify).use(remarkGfm).use(protectionPlugin) as unknown as RemarkParser;
  const paragraph=(text:string)=>schema.node('paragraph',null,text?schema.text(text):[]);
  const standard=SerializerState.create(schema,remark);
  return {schema,remark,paragraph,standard,visits};
}

describe('cached Markdown serialization',()=>{
  it('matches the whole serializer for marks, nested lists, Unicode, fences and protected source',()=>{
    const {schema,remark,paragraph,standard}=fixture(),strong=schema.mark('strong'),emphasis=schema.mark('emphasis'),code=schema.mark('inline_code');
    const text=(value:string,marks:any[]=[])=>schema.text(value,marks);
    const doc=schema.node('doc',null,[
      schema.node('heading',{level:2},text('A heading',[strong])),
      schema.node('paragraph',null,[text('Before '),text('bold ',[strong]),text('and italic',[strong,emphasis]),text(' after. हिन्दी 日本語 '),text('x`y',[code]),schema.node('hardbreak'),schema.node('reader_inline',{raw:'$x^2$'}),text('Link',[schema.mark('link',{href:'../a%20b.md#section'})])]),
      schema.node('blockquote',null,[paragraph('[!NOTE]+ A title'),paragraph('A body')]),
      schema.node('bullet_list',null,[schema.node('list_item',{checked:true},paragraph('Done')),schema.node('list_item',null,[paragraph('Nested'),schema.node('ordered_list',{order:3},schema.node('list_item',null,paragraph('Third')))])]),
      schema.node('bullet_list',null,schema.node('list_item',null,paragraph('A separate adjacent list'))),
      schema.node('code_block',{language:'latex',meta:'title="keep"'},text('x^2')),
      schema.node('table',null,[schema.node('table_row',null,[schema.node('table_cell',null,text('Name')),schema.node('table_cell',null,text('Value'))]),schema.node('table_row',null,[schema.node('table_cell',null,text('a|b',[code])),schema.node('table_cell',null,text('42'))])]),
      schema.node('reader_block',{raw:'$$\nx+y\n$$'}),schema.node('reader_block',{raw:'<div>Exact HTML</div>'}),schema.node('reader_block',{raw:'[^key]: Protected **footnote**.'}),schema.node('hr'),paragraph(''),
    ]);
    const cached=createCachedSerializer(schema,remark);
    expect(cached(doc)).toBe(standard(doc));
    expect(cached(doc)).toBe(standard(doc));
  });
  it('serializes only a changed top-level block while retaining shared blocks',()=>{
    const {schema,remark,paragraph,standard,visits}=fixture(),keep=paragraph('Keep this block'),before=paragraph('Before'),after=paragraph('After');
    const cached=createCachedSerializer(schema,remark),initial=schema.node('doc',null,[keep,before]),edited=schema.node('doc',null,[keep,after]);
    cached(initial);expect(visits).toHaveBeenCalledTimes(2);
    const output=cached(edited);expect(visits).toHaveBeenCalledTimes(3);expect(output).toBe(standard(edited));
  });
  it('drops departed blocks even when undo history still holds their nodes',()=>{
    const {schema,remark,paragraph,standard,visits}=fixture(),keep=paragraph('Shared'),before=paragraph('Before'),after=paragraph('After');
    const initial=schema.node('doc',null,[keep,before]),edited=schema.node('doc',null,[keep,after]),cached=createCachedSerializer(schema,remark);
    cached(initial);cached(edited);visits.mockClear();
    const undone=cached(initial);
    expect(visits).toHaveBeenCalledTimes(1);expect(visits).toHaveBeenCalledWith(before);
    expect(undone).toBe(standard(initial));
    visits.mockClear();cached(initial);expect(visits).not.toHaveBeenCalled();
  });
  it('releases the current block cache when using the full fallback',()=>{
    const {schema,remark,paragraph,visits}=fixture(),block=paragraph('Shared'),doc=schema.node('doc',null,block),cached=createCachedSerializer(schema,remark);
    cached(doc);cached(schema.node('doc',null,schema.node('extension')));visits.mockClear();
    cached(doc);expect(visits).toHaveBeenCalledExactlyOnceWith(block);
  });
  it('uses the full serializer for marked or unsupported top-level blocks',()=>{
    const {schema,remark,paragraph,standard}=fixture(),fallback=vi.fn(standard),cached=createCachedSerializer(schema,remark,fallback);
    const marked=schema.node('doc',null,[paragraph('First').mark([schema.mark('strong')]),paragraph('Second').mark([schema.mark('strong')])]);
    expect(cached(marked)).toBe(standard(marked));expect(fallback).toHaveBeenCalledTimes(1);
    const extension=schema.node('doc',null,schema.node('extension'));
    expect(cached(extension)).toBe(standard(extension));expect(fallback).toHaveBeenCalledTimes(2);
  });
  it('falls back without poisoning cached source if an extension mutates its input',()=>{
    const {schema,remark,standard}=fixture();
    remark.use(function(this:any){
      const data=this.data(),extensions=data.toMarkdownExtensions||(data.toMarkdownExtensions=[]);
      extensions.push({handlers:{readerBlock(node:any){node.value+='!';return node.value;}}});
    });
    const fallback=vi.fn(standard),cached=createCachedSerializer(schema,remark,fallback),block=schema.node('reader_block',{raw:'Original'}),doc=schema.node('doc',null,block);
    expect(cached(doc)).toBe('Original!\n');expect(fallback).toHaveBeenCalledTimes(1);
    expect(cached(doc)).toBe('Original!\n');expect(fallback).toHaveBeenCalledTimes(2);
    expect(block.attrs.raw).toBe('Original');
  });
});
