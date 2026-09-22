import {afterEach,describe,expect,it,vi} from 'vitest';
import {Schema,type Node as ProseNode} from '@milkdown/kit/prose/model';
import {canonicalEditorModel} from './markdown';
import {equivalentEditorDocuments} from './model-equality';

const schema=new Schema({
  nodes:{
    doc:{content:'block*'},
    paragraph:{group:'block',content:'inline*',attrs:{id:{default:''},annotation:{default:null},data:{default:null}}},
    heading:{group:'block',content:'inline*',attrs:{level:{default:1},id:{default:''}}},
    blockquote:{group:'block',content:'block*'},
    list_item:{group:'block',content:'block*',attrs:{label:{default:'•'},listType:{default:'bullet'},spread:{default:false},checked:{default:null}}},
    table_cell:{group:'block',content:'block*',attrs:{colwidth:{default:null},align:{default:null}}},
    code_block:{group:'block',content:'text*',marks:'',attrs:{language:{default:''},meta:{default:''}}},
    reader_block:{group:'block',atom:true,attrs:{raw:{default:''},kind:{default:''},notation:{default:''},label:{default:''},target:{default:''}}},
    reader_inline:{group:'inline',inline:true,atom:true,attrs:{raw:{default:''},kind:{default:''},notation:{default:''},label:{default:''},target:{default:''}}},
    text:{group:'inline'},
  },
  marks:{strong:{attrs:{id:{default:null}}},emphasis:{},link:{attrs:{href:{default:''},title:{default:null}}}},
});

const text=(value:string)=>schema.text(value);
const paragraph=(value='Keep every word',attrs?:Record<string,unknown>)=>schema.node('paragraph',attrs,value?[text(value)]:[]);
const document=(...children:ProseNode[])=>schema.node('doc',null,children);
const canonicalEqual=(a:ProseNode,b:ProseNode)=>canonicalEditorModel(a.toJSON())===canonicalEditorModel(b.toJSON());
function agrees(a:ProseNode,b:ProseNode,expected:boolean){
  expect(canonicalEqual(a,b)).toBe(expected);
  expect(equivalentEditorDocuments(a,b)).toBe(expected);
  expect(equivalentEditorDocuments(b,a)).toBe(expected);
}

afterEach(()=>vi.restoreAllMocks());

describe('immutable editor document equivalence',()=>{
  it('accepts exact node identity without reading its descendants or JSON',()=>{
    const doc=document(paragraph());
    const children=vi.spyOn(doc,'child'),json=vi.spyOn(doc,'toJSON');
    expect(equivalentEditorDocuments(doc,doc)).toBe(true);
    expect(children).not.toHaveBeenCalled();expect(json).not.toHaveBeenCalled();
  });

  it('matches independently rebuilt models and detects changed or lost text',()=>{
    agrees(document(paragraph()),document(paragraph()),true);
    agrees(document(paragraph()),document(paragraph('Keep one word')),false);
    agrees(document(paragraph(),paragraph('Second paragraph')),document(paragraph()),false);
    agrees(document(paragraph('café हिन्दी')),document(paragraph('cafe हिन्दी')),false);
  });

  it('ignores generated IDs, list labels/spread/type and table column widths',()=>{
    const first=document(
      schema.node('heading',{level:2,id:'first'},[text('Heading')]),
      schema.node('list_item',{label:'1.',listType:'ordered',spread:true},[paragraph()]),
      schema.node('table_cell',{colwidth:[120]},[paragraph('Cell')]),
    );
    const second=document(
      schema.node('heading',{level:2,id:'second'},[text('Heading')]),
      schema.node('list_item',{label:'•',listType:'bullet',spread:false},[paragraph()]),
      schema.node('table_cell',{colwidth:[240]},[paragraph('Cell')]),
    );
    agrees(first,second,true);
  });

  it('retains meaningful heading, checkbox, table, code language and metadata differences',()=>{
    for(const [type,attrs,changed,content] of [
      ['heading',{level:1},{level:2},[text('Heading')]],
      ['list_item',{checked:false},{checked:true},[paragraph()]],
      ['table_cell',{align:'left'},{align:'right'},[paragraph()]],
      ['code_block',{language:'latex',meta:'title="same"'},{language:'math',meta:'title="same"'},[text('x^2')]],
      ['code_block',{language:'js',meta:'title="before"'},{language:'js',meta:'title="after"'},[text('keep()')]],
    ] as const)agrees(document(schema.node(type,attrs,content)),document(schema.node(type,changed,content)),false);
  });

  it('drops null, undefined and empty attributes but preserves zero and false',()=>{
    for(const absent of [null,undefined,''])agrees(document(paragraph('Text',{annotation:absent})),document(paragraph('Text')),true);
    for(const value of [false,0])agrees(document(paragraph('Text',{annotation:value})),document(paragraph('Text')),false);
    agrees(document(paragraph('Text',{annotation:false})),document(paragraph('Text',{annotation:0})),false);
  });

  it('compares structured attributes with the same JSON semantics as the canonical model',()=>{
    agrees(document(paragraph('Text',{data:{a:[1,null,'x'],b:true}})),document(paragraph('Text',{data:{a:[1,null,'x'],b:true}})),true);
    agrees(document(paragraph('Text',{data:{a:1,b:2}})),document(paragraph('Text',{data:{b:2,a:1}})),false);
    agrees(document(paragraph('Text',{data:{a:undefined}})),document(paragraph('Text',{data:{}})),true);
    agrees(document(paragraph('Text',{annotation:NaN})),document(paragraph('Text',{annotation:Infinity})),true);
    agrees(document(paragraph('Text',{annotation:NaN})),document(paragraph('Text',{annotation:null})),false);
  });

  it('skips empty paragraphs at every content depth, including attributed empty paragraphs',()=>{
    const nested=(extra:boolean)=>schema.node('blockquote',null,[
      ...(extra?[paragraph('',{annotation:'ignored empty paragraph'})]:[]),
      schema.node('list_item',null,[...(extra?[paragraph('')]:[]),paragraph('Nested text'),...(extra?[paragraph('')]:[])]),
      ...(extra?[paragraph('')]:[]),
    ]);
    agrees(document(paragraph(''),nested(true),paragraph('')),document(nested(false)),true);
    agrees(document(paragraph('')),document(),true);
    agrees(document(paragraph(' ')),document(),false);
  });

  it('compares protected block and inline math only by raw source and kind',()=>{
    for(const type of ['reader_block','reader_inline']){
      const node=(attrs:Record<string,unknown>)=>schema.node(type,attrs);
      const wrap=(n:ProseNode)=>document(type==='reader_inline'?schema.node('paragraph',null,[text('Math: '),n]):n);
      const first={raw:'$x^2$',kind:'inlineMath',notation:'x^2',label:'one',target:'first'};
      agrees(wrap(node(first)),wrap(node({...first,notation:'different display cache',label:'two',target:'second'})),true);
      agrees(wrap(node(first)),wrap(node({...first,raw:'$x^3$'})),false);
      agrees(wrap(node(first)),wrap(node({...first,kind:'html'})),false);
    }
  });

  it('normalizes mark order and ignored mark attributes but preserves mark content',()=>{
    const strong=schema.mark('strong',{id:'generated'}),otherStrong=schema.mark('strong',{id:'changed'}),em=schema.mark('emphasis');
    const marked=(marks:readonly ReturnType<typeof schema.mark>[])=>document(schema.node('paragraph',null,[text('Marked text').mark(marks)]));
    agrees(marked([strong,em]),marked([em,otherStrong]),true);
    agrees(marked([strong,em]),marked([strong]),false);
    agrees(marked([schema.mark('link',{href:'../one.md'})]),marked([schema.mark('link',{href:'../two.md'})]),false);
    // localeCompare can consider differently encoded Unicode equal. The
    // canonical model uses a stable sort, so retain that exact ordering rule.
    const first=schema.mark('link',{href:'é'}),second=schema.mark('link',{href:'e\u0301'});
    expect(equivalentEditorDocuments(marked([first,second]),marked([second,first])))
      .toBe(canonicalEqual(marked([first,second]),marked([second,first])));
  });

  it('does not traverse unchanged shared subtrees when another branch changes',()=>{
    const shared=schema.node('blockquote',null,[paragraph('Shared paragraph'),schema.node('list_item',null,[paragraph('Shared nested list')])]);
    const before=document(shared,paragraph('Current branch',{id:'old'}));
    const after=document(shared,paragraph('Current branch',{id:'new'}));
    expect(canonicalEqual(before,after)).toBe(true);
    const children=vi.spyOn(shared,'child'),json=vi.spyOn(shared,'toJSON');
    expect(equivalentEditorDocuments(before,after)).toBe(true);
    expect(children).not.toHaveBeenCalled();expect(json).not.toHaveBeenCalled();
    expect(equivalentEditorDocuments(before,document(shared,paragraph('Changed words')))).toBe(false);
    expect(children).not.toHaveBeenCalled();expect(json).not.toHaveBeenCalled();
  });
});
