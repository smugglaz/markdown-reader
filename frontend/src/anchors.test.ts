import {describe,expect,it,vi} from 'vitest';
import {createAnchorAllocator,headingAnchor,paragraphAnchor,updateDocumentAnchors} from './anchors';

describe('document anchor names',()=>{
  it('keeps Unicode heading slugs and paragraph hashes compatible',()=>{
    expect(headingAnchor('  Hello, WORLD!  ')).toBe('hello-world');
    expect(headingAnchor('日本語 — हिन्दी 42')).toBe('日本語-हनद-42');
    expect(headingAnchor('!!!')).toBe('heading');
    expect(paragraphAnchor('Hello')).toBe('reader-paragraph-4116459851');
    expect(paragraphAnchor('x'.repeat(140)+'one')).toBe(paragraphAnchor('x'.repeat(140)+'two'));
  });
  it('keeps text-based anchors stable when unrelated text follows the reading anchor',()=>{
    const start='A stable paragraph with Unicode 日本語 and inline text. '.repeat(3);
    expect(paragraphAnchor(start+'Before')).toBe(paragraphAnchor(start+'After'));
    expect(headingAnchor('Nested heading')).toBe('nested-heading');
    expect(paragraphAnchor('Before')).not.toBe(paragraphAnchor('After'));
  });
  it('preserves existing IDs and skips collisions across literal and numbered names',()=>{
    const original=['topic','topic-1','topic-3','topic-1-1'],used=new Set(original),allocate=createAnchorAllocator(used);
    expect([allocate('topic'),allocate('topic'),allocate('topic-1'),allocate('topic-2'),allocate('topic')])
      .toEqual(['topic-2','topic-4','topic-1-2','topic-2-1','topic-5']);
    for(const id of original)expect(used.has(id)).toBe(true);
  });
  it('allocates repeated heading names with a bounded number of collision checks',()=>{
    const used=new Set<string>(),has=vi.spyOn(used,'has'),allocate=createAnchorAllocator(used);
    const names=Array.from({length:500},()=>allocate('a-useful-section'));
    expect(names[0]).toBe('a-useful-section');expect(names.at(-1)).toBe('a-useful-section-499');
    expect(new Set(names).size).toBe(500);expect(has.mock.calls.length).toBeLessThanOrEqual(1000);
  });
  it('renumbers reused duplicate headings after insertion, deletion and reordering',()=>{
    const heading=()=>({element:{id:'',dataset:{} as {readerAnchor?:string}},base:headingAnchor('Same')});
    const first=heading(),second=heading(),inserted=heading();
    const update=(targets:ReturnType<typeof heading>[])=>updateDocumentAnchors(targets,targets.map(({element})=>element));
    update([first,second]);
    expect([first.element.id,second.element.id]).toEqual(['same','same-1']);
    update([inserted,first,second]);
    expect([inserted.element.id,first.element.id,second.element.id]).toEqual(['same','same-1','same-2']);
    update([first,second]);
    expect([first.element.id,second.element.id]).toEqual(['same','same-1']);
    update([second,first]);
    expect([second.element.id,first.element.id]).toEqual(['same','same-1']);
  });
  it('preserves explicit protected HTML IDs while reallocating generated anchors',()=>{
    const generated={element:{id:'',dataset:{} as {readerAnchor?:string}},base:'same'};
    const explicit={element:{id:'same',dataset:{} as {readerAnchor?:string}},base:'different-heading-text'};
    const outsideOutline={id:'same-1',dataset:{}};
    updateDocumentAnchors([generated,explicit],[generated.element,explicit.element,outsideOutline]);
    expect(generated.element).toEqual({id:'same-2',dataset:{readerAnchor:'generated'}});
    expect(explicit.element).toEqual({id:'same',dataset:{readerAnchor:'fixed'}});
    generated.base='renamed';
    updateDocumentAnchors([explicit,generated],[explicit.element,generated.element,outsideOutline]);
    expect(generated.element.id).toBe('renamed');
    expect(explicit.element.id).toBe('same');expect(outsideOutline.id).toBe('same-1');
  });
  it('does not rewrite unchanged ID or ownership attributes on repeated updates',()=>{
    const element={id:'',dataset:{} as {readerAnchor?:string}},target={element,base:'stable'};
    updateDocumentAnchors([target],[element]);
    let id=element.id,marker=element.dataset.readerAnchor;
    const setId=vi.fn((value:string)=>{id=value;}),setMarker=vi.fn((value:string)=>{marker=value;});
    Object.defineProperty(element,'id',{get:()=>id,set:setId});
    Object.defineProperty(element.dataset,'readerAnchor',{get:()=>marker,set:setMarker});
    updateDocumentAnchors([target],[element]);
    expect(setId).not.toHaveBeenCalled();expect(setMarker).not.toHaveBeenCalled();
  });
});
