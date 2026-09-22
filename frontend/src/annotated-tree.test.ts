import {describe,expect,it} from 'vitest';
import {parseAnnotatedTree} from './annotated-tree';

describe('annotated file tree detection',()=>{
  const source=[
    'nsedata/             collector package (Python 3.11+)',
    '  config.py           paths, hosts, politeness limits, retry policy',
    '  eras.py             EVERY known format era, cutover date, header fingerprint, API',
    '  data/',
    '    raw/<source>/...  collector-retained files; historical transformations',
    '    ingest.sqlite     state + attempt log',
    '.venv/               duckdb, polars, pyarrow',
  ].join('\n');

  it('separates paths and full descriptions without changing their source',()=>{
    const entries=parseAnnotatedTree(source,'');
    expect(entries).not.toBeNull();
    expect(entries?.map(row=>row.depth)).toEqual([0,1,1,1,2,2,0]);
    expect(entries?.[2]).toEqual({path:'eras.py',description:'EVERY known format era, cutover date, header fingerprint, API',depth:1});
    expect(entries?.[3].description).toBe('');
    expect(source).toContain('  config.py           paths');
  });

  it('leaves programs and ambiguous text in their exact code view',()=>{
    expect(parseAnnotatedTree(source,'python')).toBeNull();
    expect(parseAnnotatedTree('foo.py  note\nbar.py  note\ntext', '')).toBeNull();
    expect(parseAnnotatedTree('root/  note\n  value.py  note\n  other.py  note\n  more.py  note','')).not.toBeNull();
  });
});
