import type {EditorView} from '@milkdown/kit/prose/view';
import {setBlockType} from '@milkdown/kit/prose/commands';
import {liftListItem} from '@milkdown/kit/prose/schema-list';
import {undo, redo} from '@milkdown/kit/prose/history';
import {deleteColumn, deleteRow} from '@milkdown/kit/prose/tables';
import {toggleStrongCommand, toggleEmphasisCommand, toggleInlineCodeCommand, toggleLinkCommand, createCodeBlockCommand, wrapInBulletListCommand, wrapInOrderedListCommand, wrapInBlockquoteCommand, insertHrCommand, insertImageCommand} from '@milkdown/kit/preset/commonmark';
import {toggleStrikethroughCommand, insertTableCommand, addRowAfterCommand, addColAfterCommand} from '@milkdown/kit/preset/gfm';
import {editSource} from './views';
import {chooseImage,context} from './bridge';

// Local SVGs share a single optical size and stroke. No icon font or network dependency.
const paths: Record<string,string> = {
  bold:'<path d="M6 3h6a4 4 0 0 1 0 8H6m0 0h7a4 4 0 0 1 0 8H6V3"/>',
  italic:'<path d="M10 3h8M4 19h8M14 3 8 19"/>',
  strike:'<path d="M16 5c-1-2-7-3-9 0-1 2 0 4 3 5m4 3c4 3 1 7-3 6-2 0-4-1-5-2M3 11h16"/>',
  code:'<path d="m7 6-5 5 5 5m8-10 5 5-5 5m-3-13-2 16"/>',
  link:'<path d="m9 14 5-5m-7 3-2 2a4 4 0 0 0 6 6l3-3a4 4 0 0 0 0-6m1-1 2-2a4 4 0 0 0-6-6L8 5a4 4 0 0 0 0 6" transform="translate(0 -1)"/>',
  bullet:'<path d="M8 5h12M8 11h12M8 17h12"/><circle cx="3" cy="5" r="1" fill="currentColor"/><circle cx="3" cy="11" r="1" fill="currentColor"/><circle cx="3" cy="17" r="1" fill="currentColor"/>',
  ordered:'<path d="M9 5h11M9 11h11M9 17h11M2 3h2v5M2 8h4M2 13c3-2 5 1 2 3l-2 3h4"/>',
  task:'<rect x="2" y="4" width="7" height="7" rx="1.5"/><path d="m4 7 1.5 1.5L8 6m5 1h7M13 16h7"/><rect x="2" y="13" width="7" height="7" rx="1.5"/>',
  undo:'<path d="M7 5 2 10l5 5M3 10h10a6 6 0 0 1 6 6"/>',
  redo:'<path d="m15 5 5 5-5 5m4-5H9a6 6 0 0 0-6 6"/>',
  clear:'<path d="M4 4h13M10 4 7 17m6-4 7 7m0-7-7 7"/>',
  chevron:'<path d="m7 9 4 4 4-4"/>',
  plus:'<path d="M11 4v14M4 11h14"/>',
  table:'<rect x="3" y="3" width="16" height="16" rx="2"/><path d="M3 8h16M3 13h16M9 3v16"/>',
};
const svg=(name:string)=>`<svg viewBox="0 0 22 22" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name]}</svg>`;

export function createFormattingToolbar(root:HTMLElement, getView:()=>EditorView|null, command:(key:any,payload?:any)=>void) {
  let opened:HTMLElement|null=null;
  const toggles=new Map<string,HTMLButtonElement>();
  const action=(fn:(view:EditorView)=>void)=>{const view=getView();if(!view||!view.editable)return;fn(view);view.focus();sync();};
  const closeMenus=()=>{if(!opened)return;opened.hidden=true;opened.previousElementSibling?.setAttribute('aria-expanded','false');opened=null;};
  const group=(label:string)=>{const g=document.createElement('div');g.className='toolbar-group';g.setAttribute('role','group');g.setAttribute('aria-label',label);root.append(g);return g;};
  function button(parent:HTMLElement,label:string,icon:string,run:()=>void,key?:string){
    const b=document.createElement('button');b.type='button';b.title=label;b.setAttribute('aria-label',label);b.innerHTML=svg(icon);
    b.onmousedown=e=>e.preventDefault();b.onclick=()=>{closeMenus();run();};parent.append(b);
    if(key){toggles.set(key,b);b.setAttribute('aria-pressed','false');}return b;
  }
  function menu(parent:HTMLElement,label:string,icon?:string){
    const wrap=document.createElement('div');wrap.className='toolbar-menu';parent.append(wrap);
    const trigger=document.createElement('button');trigger.type='button';trigger.className='menu-trigger';trigger.setAttribute('aria-label',label);trigger.setAttribute('aria-haspopup','menu');trigger.setAttribute('aria-expanded','false');
    trigger.innerHTML=(icon?svg(icon):'')+`<span>${label}</span>`+svg('chevron');wrap.append(trigger);
    const panel=document.createElement('div');panel.className='format-menu';panel.setAttribute('role','menu');panel.setAttribute('aria-label',label);panel.hidden=true;wrap.append(panel);
    trigger.onmousedown=e=>e.preventDefault();
    trigger.onclick=()=>{const wasOpen=opened===panel;closeMenus();if(!wasOpen){panel.hidden=false;opened=panel;trigger.setAttribute('aria-expanded','true');(panel.querySelector<HTMLButtonElement>('button[aria-checked=true]')??panel.querySelector<HTMLButtonElement>('button'))?.focus();}};
    trigger.onkeydown=e=>{if(e.key==='ArrowDown'){e.preventDefault();if(panel.hidden)trigger.click();}};
    panel.onkeydown=e=>{const items=[...panel.querySelectorAll<HTMLButtonElement>('button:not(:disabled)')];const i=items.indexOf(document.activeElement as HTMLButtonElement);
      if(['ArrowDown','ArrowUp','Home','End'].includes(e.key)){e.preventDefault();items[e.key==='Home'?0:e.key==='End'?items.length-1:(i+(e.key==='ArrowDown'?1:-1)+items.length)%items.length]?.focus();}
      if(e.key==='Escape'){e.preventDefault();e.stopPropagation();closeMenus();trigger.focus();}if(e.key==='Tab')closeMenus();};
    return {wrap,trigger,panel};
  }
  function item(panel:HTMLElement,label:string,run:()=>void,detail?:string){
    const b=document.createElement('button');b.type='button';b.setAttribute('role','menuitem');b.setAttribute('aria-label',label);b.textContent=label;
    if(detail){const hint=document.createElement('span');hint.className='menu-hint';hint.textContent=detail;b.append(hint);}
    b.onmousedown=e=>e.preventDefault();b.onclick=()=>{closeMenus();run();};panel.append(b);return b;
  }
  // Lifting uses the editor's list transform, preserving siblings and nested content.
  function leaveList(view:EditorView){for(let i=0;i<20;i++){if(!liftListItem(view.state.schema.nodes.list_item)(view.state,view.dispatch))break;}}
  function style(level:number){action(view=>{leaveList(view);setBlockType(view.state.schema.nodes[level?'heading':'paragraph'],level?{level}:undefined)(view.state,view.dispatch);});}
  const textGroup=group('Text style');
  const styles=menu(textGroup,'Text style');styles.trigger.id='text-style';
  for(let level=0;level<7;level++){
    const b=item(styles.panel,level?`Heading ${level}`:'Normal text',()=>style(level),level?'': 'Ctrl+Alt+0');
    b.dataset.style=String(level);b.className=level?`style-preview heading-${level}`:'style-preview normal';b.setAttribute('role','menuitemradio');b.setAttribute('aria-checked','false');
  }
  const marks=group('Text formatting');
  button(marks,'Bold (Ctrl+B)','bold',()=>command(toggleStrongCommand.key),'strong');
  button(marks,'Italic (Ctrl+I)','italic',()=>command(toggleEmphasisCommand.key),'emphasis');
  button(marks,'Strikethrough','strike',()=>command(toggleStrikethroughCommand.key),'strike_through');
  button(marks,'Inline code','code',()=>command(toggleInlineCodeCommand.key),'inlineCode');
  button(marks,'Insert link','link',()=>editSource('Insert link','https://',href=>command(toggleLinkCommand.key,{href}),{multiline:false,label:'URL or relative file path'}),'link');
  button(marks,'Clear formatting','clear',()=>action(view=>{const {from,to,empty,$from}=view.state.selection;if(empty&&!$from.parent.isTextblock)return;const tr=view.state.tr.removeMark(empty?$from.start():from,empty?$from.end():to).setStoredMarks([]);view.dispatch(tr); }));
  const lists=group('Lists');
  function list(kind:'bullet'|'ordered'|'task') {action(view=>{
    const {$from}=view.state.selection;let current='';
    for(let d=$from.depth;d>0;d--){const node=$from.node(d);if(node.type.name==='list_item'){current=node.attrs.checked!=null?'task':$from.node(d-1).type.name==='ordered_list'?'ordered':'bullet';break;}}
    leaveList(view);if(current===kind)return;
    command(kind==='ordered'?wrapInOrderedListCommand.key:wrapInBulletListCommand.key);
    if(kind==='task'){const tr=view.state.tr,{from,to}=view.state.selection;view.state.doc.nodesBetween(from,to,(node,pos)=>{if(node.type.name==='list_item')tr.setNodeMarkup(pos,undefined,{...node.attrs,checked:false});});view.dispatch(tr);}
  });}
  button(lists,'Bullet list','bullet',()=>list('bullet'),'bullet');button(lists,'Numbered list','ordered',()=>list('ordered'),'ordered');button(lists,'Task list','task',()=>list('task'),'task');
  const insertGroup=group('Insert');const insert=menu(insertGroup,'Insert','plus');
  item(insert.panel,'Table',()=>command(insertTableCommand.key,{row:3,col:3}));
  item(insert.panel,'Image from file…',async()=>{const docView=getView(),documentId=context.documentId,revision=context.revision;const src=await chooseImage();if(src&&getView()===docView&&documentId===context.documentId&&revision===context.revision)command(insertImageCommand.key,{src,alt:''});});
  item(insert.panel,'Image from URL…',()=>editSource('Insert image','https://',src=>command(insertImageCommand.key,{src,alt:''}),{multiline:false,label:'Image URL'}));
  item(insert.panel,'Blockquote',()=>command(wrapInBlockquoteCommand.key));
  item(insert.panel,'Horizontal rule',()=>command(insertHrCommand.key));
  item(insert.panel,'Code block',()=>command(createCodeBlockCommand.key,''));
  item(insert.panel,'Equation…',()=>editSource('Insert equation','E = mc^2',notation=>action(view=>view.dispatch(view.state.tr.replaceSelectionWith(view.state.schema.nodes.reader_block.create({kind:'math',notation,raw:`$$\n${notation}\n$$`})) ))));
  item(insert.panel,'Mermaid diagram…',()=>editSource('Insert Mermaid diagram','flowchart LR\n  Idea --> Document\n  Document --> Insight',value=>action(view=>view.dispatch(view.state.tr.replaceSelectionWith(view.state.schema.nodes.code_block.create({language:'mermaid',meta:''},view.state.schema.text(value)))))));
  const tableGroup=group('Table tools');const table=menu(tableGroup,'Table','table');
  item(table.panel,'Add row',()=>command(addRowAfterCommand.key));item(table.panel,'Add column',()=>command(addColAfterCommand.key));
  item(table.panel,'Delete row',()=>action(view=>{deleteRow(view.state,view.dispatch);}));item(table.panel,'Delete column',()=>action(view=>{deleteColumn(view.state,view.dispatch);}));
  tableGroup.hidden=true;
  const history=group('History');history.classList.add('toolbar-history');
  const undoButton=button(history,'Undo (Ctrl+Z)','undo',()=>action(view=>{undo(view.state,view.dispatch);}));
  const redoButton=button(history,'Redo (Ctrl+Shift+Z)','redo',()=>action(view=>{redo(view.state,view.dispatch);}));
  function sync(view=getView()) {
    if(!view)return;const {state}=view,{$from,from,to,empty}=state.selection;
    const block=$from.parent;const level=block.type.name==='heading'?String(block.attrs.level):'0';
    const textBlocks=new Set<string>();state.doc.nodesBetween(from,to,node=>{if(node.isTextblock)textBlocks.add(node.type.name==='heading'?`Heading ${node.attrs.level}`:node.type.name==='code_block'?'Code block':'Normal text');});
    const label=textBlocks.size>1?'Mixed styles':block.type.name==='heading'?`Heading ${level}`:block.type.name==='code_block'?'Code block':block.isTextblock?'Normal text':'Text style';
    styles.trigger.querySelector('span')!.textContent=label;styles.trigger.dataset.value=textBlocks.size>1?'mixed':level;
    for(const option of styles.panel.querySelectorAll<HTMLElement>('[data-style]'))option.setAttribute('aria-checked',String(textBlocks.size<=1&&block.type.name!=='code_block'&&option.dataset.style===level));
    for(const [name,b] of toggles){const mark=state.schema.marks[name];if(mark)b.setAttribute('aria-pressed',String(empty?!!mark.isInSet(state.storedMarks??$from.marks()):state.doc.rangeHasMark(from,to,mark)));}
    let currentList='',insideTable=false;for(let d=$from.depth;d>0;d--){const n=$from.node(d);if(n.type.name==='table')insideTable=true;if(!currentList&&n.type.name==='list_item')currentList=n.attrs.checked!=null?'task':$from.node(d-1).type.name==='ordered_list'?'ordered':'bullet';}
    for(const name of ['bullet','ordered','task'])toggles.get(name)!.setAttribute('aria-pressed',String(currentList===name));
    tableGroup.hidden=!insideTable;undoButton.disabled=!undo(state);redoButton.disabled=!redo(state);
  }
  document.addEventListener('mousedown',e=>{if(!root.contains(e.target as Node))closeMenus();});
  document.addEventListener('keydown',e=>{if(e.key==='Escape')closeMenus();});
  root.addEventListener('focusout',()=>queueMicrotask(()=>{if(!root.contains(document.activeElement))closeMenus();}));
  return {sync,close:closeMenus,normalText:()=>style(0)};
}
