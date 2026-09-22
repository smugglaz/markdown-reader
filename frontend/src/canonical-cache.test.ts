import {afterEach,describe,expect,it,vi} from 'vitest';
import {assertRoundtrip,canonical,parser,primeCanonical,type Ast} from './markdown';

afterEach(()=>vi.restoreAllMocks());

describe('canonical reuse',()=>{
  it('reuses the editor pre-transform tree without retaining its mutable AST',()=>{
    const source='---\ntitle: Shared parser\n---\n# Primed source\n\n- Keep **both** words.\n';
    const tree=parser.parse('# Primed source\n\n- Keep **both** words.\n');
    const expected=canonical(source);
    primeCanonical(source,tree as Ast);
    tree.children=[];
    const parse=vi.spyOn(parser,'parse');
    expect(canonical(source)).toBe(expected);
    expect(parse).not.toHaveBeenCalled();
    expect(()=>assertRoundtrip(source,'# Primed source\n')).toThrow();
  });

  it('keeps normalized raw HTML validation for CRLF source',()=>{
    const source='<div>CRLF priming\r\nbody</div>\r\n';
    primeCanonical(source,parser.parse(source) as Ast);
    const parse=vi.spyOn(parser,'parse');
    expect(canonical(source)).toBe(canonical(source.replace(/\r\n/g,'\n')));
    expect(parse).toHaveBeenCalledTimes(1);
  });

  it('parses an unchanged source only once across load and roundtrip checks',()=>{
    const parse=vi.spyOn(parser,'parse');
    const source='# Reused document\n\nKeep **every** word and café.\n';
    const first=canonical(source);
    expect(canonical(source)).toBe(first);
    expect(()=>assertRoundtrip(source,source)).not.toThrow();
    expect(parse).toHaveBeenCalledTimes(1);
  });

  it('reuses equivalent newline styles while preserving the original comparison rules',()=>{
    const parse=vi.spyOn(parser,'parse');
    const source='---\ntitle: Newline cache\n---\n# Text\n';
    expect(canonical(source.replace(/\n/g,'\r\n'))).toBe(canonical(source));
    expect(parse).toHaveBeenCalledTimes(1);
  });

  it('does not mistake equal-length content or changed code metadata for a cache hit',()=>{
    const source='```js title="cache-a"\nkeep()\n```';
    canonical(source);
    expect(()=>assertRoundtrip(source,source.replace('cache-a','cache-b'))).toThrow();
    expect(()=>assertRoundtrip('Cache original text','Cache replaced text')).toThrow();
  });

  it('still rejects internal image URLs on cache hits and identical roundtrips',()=>{
    for(const source of ['![cache blob](blob:cached)','![cache reader](reader://asset/cached)']){
      canonical(source);
      expect(()=>assertRoundtrip(source,source)).toThrow('temporary image URL');
    }
  });

  it('bounds retained source text across multiple large revisions',()=>{
    const parse=vi.spyOn(parser,'parse').mockReturnValue({type:'root',children:[]});
    const revisions=['A','B','C'].map(letter=>`Source budget ${letter}\n${letter.repeat(800_000)}`);
    for(const source of revisions)canonical(source);
    expect(parse).toHaveBeenCalledTimes(3);
    canonical(revisions[0]);
    expect(parse).toHaveBeenCalledTimes(4);
  });

  it('does not retain a source larger than the complete source budget',()=>{
    const parse=vi.spyOn(parser,'parse').mockReturnValue({type:'root',children:[]});
    const source='Oversized source\n'+'.'.repeat(3*1024*1024);
    canonical(source);canonical(source);
    expect(parse).toHaveBeenCalledTimes(2);
  });

  it('also bounds canonical output expansion and tiny document counts',()=>{
    const parse=vi.spyOn(parser,'parse').mockReturnValue({type:'root',children:[{type:'text',value:'x'.repeat(9*1024*1024)}]});
    canonical('Expanded cache source');canonical('Expanded cache source');
    expect(parse).toHaveBeenCalledTimes(2);
    parse.mockReturnValue({type:'root',children:[]}).mockClear();
    for(let index=0;index<100;index++)canonical(`Tiny bounded document ${index}`);
    canonical('Tiny bounded document 0');
    expect(parse).toHaveBeenCalledTimes(101);
  });

  it('does not cache a failed parse',()=>{
    const parse=vi.spyOn(parser,'parse').mockImplementationOnce(()=>{throw new Error('Parse failed');});
    expect(()=>canonical('Retry after failed cache parse')).toThrow('Parse failed');
    expect(()=>canonical('Retry after failed cache parse')).not.toThrow();
    expect(parse).toHaveBeenCalledTimes(2);
  });
});
