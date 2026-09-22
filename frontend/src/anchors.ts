import {DOMSerializer,type Node} from '@milkdown/kit/prose/model';
import type {NodeView} from '@milkdown/kit/prose/view';
import {headingSchema,paragraphSchema} from '@milkdown/kit/preset/commonmark';
import {$view} from '@milkdown/kit/utils';

export {headingAnchor,paragraphAnchor,createAnchorAllocator,updateDocumentAnchors} from './document-anchors';

/** Own only outline attributes; all document content remains managed by PM. */
function anchorView(initial:Node):NodeView {
  let current=initial;
  const render=initial.type.spec.toDOM;
  if(!render)throw new Error('The document block has no DOM renderer.');
  const {dom,contentDOM}=DOMSerializer.renderSpec(document,render(initial));
  if(!(dom instanceof HTMLElement)||!contentDOM)throw new Error('The document block has no editable content region.');
  const clearAnchor=()=>{dom.removeAttribute('id');dom.removeAttribute('data-reader-anchor');};
  // The outline assigns IDs in document order, including duplicate suffixes.
  clearAnchor();
  return {
    dom,contentDOM,
    update(next){
      if(next===current)return true;
      // Recreate when the schema changes its tag or attributes (e.g. H2 -> H3).
      if(!next.sameMarkup(current))return false;
      if(next.textContent!==current.textContent)clearAnchor();
      current=next;return true;
    },
    ignoreMutation(mutation){
      return mutation.type==='attributes'&&mutation.target===dom&&
        (mutation.attributeName==='id'||mutation.attributeName==='data-reader-anchor');
    },
  };
}

// Node views avoid both observer reparses from unmanaged IDs and the quadratic
// DecorationSet.forChild cost of decorating every root block in long documents.
export const anchorViews=[
  $view(headingSchema.node,()=>anchorView),
  $view(paragraphSchema.node,()=>anchorView),
];
