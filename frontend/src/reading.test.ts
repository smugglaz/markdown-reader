import {describe,expect,it,vi} from 'vitest';
// The pure source helpers do not need WebKit or the renderer's browser globals.
vi.mock('./rendering',()=>({safeHtml:()=>'',resolveImages:async()=>{},renderStaticDiagram:()=>{},renderIssues:new Map(),track:(promise:Promise<unknown>)=>promise}));
vi.mock('./bridge',()=>({send:()=>{}}));
import {rawHtml} from './markdown';
import {preserveReadingTasks,readingCallout} from './reading';

describe('static reading source helpers',()=>{
  it('retains checked state as immutable accessible task indicators',()=>{
    const html=preserveReadingTasks(rawHtml('- [x] Complete\n- [ ] Pending\n\n`<input type="checkbox" checked disabled>`'));
    expect(html).toContain('aria-checked="true" aria-readonly="true" aria-disabled="true">☑');
    expect(html).toContain('aria-checked="false" aria-readonly="true" aria-disabled="true">☐');
    expect(html).not.toContain('<input');
    expect(html).toContain('&#x3C;input type="checkbox" checked disabled>');
  });
  it('recognizes callout titles and folds while preserving the body boundary',()=>{
    expect(readingCallout('[!NOTE]\nKeep this paragraph.')).toEqual({length:8,kind:'note',title:'Note',fold:''});
    const folded='[!WARNING]- ध्यान\nA body';
    expect(readingCallout(folded)).toEqual({length:folded.indexOf('\n')+1,kind:'warning',title:'ध्यान',fold:'-'});
    expect(readingCallout('[!tip]+ Open')).toEqual({length:12,kind:'tip',title:'Open',fold:'+'});
    expect(readingCallout('Ordinary quotation')).toBeNull();
  });
  it('keeps LaTeX fences distinct from equations, and keeps footnote destinations',()=>{
    const source='```latex title="example"\nx^2\n```\n\n$x^2$ and A[^note].\n\n$$\nx+y\n$$\n\n[^note]: Footnote text.';
    const html=rawHtml(source);
    expect(html).toContain('class="language-latex"');
    expect(html).toContain('math-inline');expect(html).toContain('math-display');
    expect(html).toContain('href="#user-content-fn-note"');
    expect(source).toContain('latex title="example"');
  });
});
