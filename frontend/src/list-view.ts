/** Lightweight list markers: one DOM view, no framework or mount transactions. */
import { listItemSchema } from '@milkdown/kit/preset/commonmark';
import { $view } from '@milkdown/kit/utils';

// Same marker geometry as Milkdown/Crepe (MIT). Clip paths are unnecessary for
// these shapes, and omitting them avoids duplicate SVG IDs in long lists.
const bullet = '<circle cx="12" cy="12" r="3" />';
const checked = '<path d="M19 3H5C3.9 3 3 3.9 3 5V19C3 20.1 3.9 21 5 21H19C20.1 21 21 20.1 21 19V5C21 3.9 20.1 3 19 3ZM10.71 16.29C10.32 16.68 9.69 16.68 9.3 16.29L5.71 12.7C5.32 12.31 5.32 11.68 5.71 11.29C6.1 10.9 6.73 10.9 7.12 11.29L10 14.17L16.88 7.29C17.27 6.9 17.9 6.9 18.29 7.29C18.68 7.68 18.68 8.31 18.29 8.7L10.71 16.29Z" />';
const unchecked = '<path d="M18 19H6C5.45 19 5 18.55 5 18V6C5 5.45 5.45 5 6 5H18C18.55 5 19 5.45 19 6V18C19 18.55 18.55 19 18 19ZM19 3H5C3.9 3 3 3.9 3 5V19C3 20.1 3.9 21 5 21H19C20.1 21 21 20.1 21 19V5C21 3.9 20.1 3 19 3Z" />';
const svg = (shape: string) => `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" aria-hidden="true">${shape}</svg>`;
const taskModeUpdates = new Set<() => void>();

/** Call after changing editor readonly state; only task controls need updating. */
export function refreshListViewMode() {
  for (const update of taskModeUpdates) update();
}

export const listView = $view(listItemSchema.node, () => (initialNode, view, getPos) => {
  let current = initialNode;
  const dom = document.createElement('div');
  dom.className = 'milkdown-list-item-block';
  const item = document.createElement('li');
  item.className = 'list-item';
  const wrapper = document.createElement('div');
  wrapper.className = 'label-wrapper';
  wrapper.contentEditable = 'false';
  const label = document.createElement('span');
  label.className = 'milkdown-icon label';
  wrapper.append(label);
  const children = document.createElement('div');
  children.className = 'children';
  const contentDOM = document.createElement('div');
  contentDOM.className = 'content-dom';
  contentDOM.dataset.contentDom = 'true';
  children.append(contentDOM);
  item.append(wrapper, children);
  dom.append(item);

  const syncMode = () => {
    const task = current.attrs.checked != null;
    label.classList.toggle('readonly', task && !view.editable);
    if (task) {
      wrapper.tabIndex = view.editable ? 0 : -1;
      wrapper.setAttribute('aria-readonly', String(!view.editable));
    }
  };
  const renderMarker = () => {
    const attrs = current.attrs;
    const task = attrs.checked != null;
    const kind = task ? (attrs.checked ? 'checked' : 'unchecked') : attrs.listType === 'bullet' ? 'bullet' : 'ordered';
    label.className = 'milkdown-icon label ' + kind;
    if (task || attrs.listType === 'bullet') {
      label.innerHTML = svg(task ? (attrs.checked ? checked : unchecked) : bullet);
    } else {
      // Labels are document data, never HTML.
      label.textContent = String(attrs.label ?? '1.');
    }
    if (task) {
      wrapper.setAttribute('role', 'checkbox');
      wrapper.setAttribute('aria-label', 'Task completed');
      wrapper.setAttribute('aria-checked', String(Boolean(attrs.checked)));
      taskModeUpdates.add(syncMode);
    } else {
      wrapper.removeAttribute('role');
      wrapper.removeAttribute('aria-label');
      wrapper.removeAttribute('aria-checked');
      wrapper.removeAttribute('aria-readonly');
      wrapper.removeAttribute('tabindex');
      taskModeUpdates.delete(syncMode);
    }
    syncMode();
  };
  const toggle = () => {
    if (!view.editable || view.isDestroyed || current.attrs.checked == null) return;
    const pos = getPos();
    if (pos == null) return;
    const liveNode = view.state.doc.nodeAt(pos);
    if (!liveNode || liveNode.type !== current.type || liveNode.attrs.checked == null) return;
    if (!view.hasFocus()) view.focus();
    view.dispatch(view.state.tr.setNodeAttribute(pos, 'checked', !liveNode.attrs.checked));
  };
  const pointerDown = (event: PointerEvent) => {
    // Keep the current text selection when clicking a task marker.
    event.preventDefault();
    event.stopPropagation();
  };
  const click = (event: MouseEvent) => {
    event.preventDefault();
    event.stopPropagation();
    toggle();
  };
  const keyDown = (event: KeyboardEvent) => {
    if (event.key !== ' ' && event.key !== 'Enter') return;
    event.preventDefault();
    event.stopPropagation();
    toggle();
  };
  wrapper.addEventListener('pointerdown', pointerDown);
  wrapper.addEventListener('click', click);
  wrapper.addEventListener('keydown', keyDown);
  renderMarker();

  return {
    dom,
    contentDOM,
    update(next) {
      if (next.type !== current.type) return false;
      const previous = current.attrs;
      current = next;
      if (previous.checked !== next.attrs.checked || previous.label !== next.attrs.label || previous.listType !== next.attrs.listType) renderMarker();
      return true;
    },
    ignoreMutation(mutation) {
      if (mutation.type === 'selection') return false;
      if (mutation.target === contentDOM && mutation.type === 'attributes') return true;
      return !contentDOM.contains(mutation.target);
    },
    stopEvent(event) {
      return wrapper.contains(event.target as globalThis.Node);
    },
    selectNode() {
      dom.classList.add('selected');
      item.classList.add('ProseMirror-selectednode');
    },
    deselectNode() {
      dom.classList.remove('selected');
      item.classList.remove('ProseMirror-selectednode');
    },
    destroy() {
      taskModeUpdates.delete(syncMode);
      wrapper.removeEventListener('pointerdown', pointerDown);
      wrapper.removeEventListener('click', click);
      wrapper.removeEventListener('keydown', keyDown);
    },
  };
});
