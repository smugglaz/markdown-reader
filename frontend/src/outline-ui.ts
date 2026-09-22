const CLOSE_LABEL = 'Close contents';

export function syncOutlineLayout(): void {
  const size = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--reader-font-size')) || 17;
  // Preserve a useful reading column when Contents is open at larger text sizes.
  document.body.classList.toggle('compact-outline', innerWidth < 215 + Math.max(560, size * 34));
}

export function updateOutlineCurrent(root: HTMLElement): void {
  if (!root.isConnected || !document.body.classList.contains('show-outline')) return;
  const headings = root.querySelectorAll<HTMLElement>('#editor h1[id],#editor h2[id],#editor h3[id],#editor h4[id],#editor h5[id],#editor h6[id]');
  let active = headings[0]?.id;
  for (const heading of headings) {
    if (heading.getBoundingClientRect().top <= 150) active = heading.id;
    else break;
  }
  for (const link of root.querySelectorAll<HTMLAnchorElement>('#outline-items a')) {
    let linkId = link.getAttribute('href')?.slice(1) ?? '';
    try { linkId = decodeURIComponent(linkId); } catch { /* Keep a malformed literal fragment usable. */ }
    if (linkId === active) link.setAttribute('aria-current', 'location');
    else link.removeAttribute('aria-current');
  }
}

export function closeCompactOutline(root: HTMLElement): void {
  if (root.isConnected && document.body.classList.contains('compact-outline'))
    document.body.classList.remove('show-outline');
}

export function toggleOutline(root: HTMLElement): void {
  syncOutlineLayout();
  document.body.classList.toggle('show-outline');
  updateOutlineCurrent(root);
}

export function setupOutline(root: HTMLElement): void {
  const nav = root.querySelector<HTMLElement>('#outline')!;
  const close = document.createElement('button');
  close.type = 'button'; close.className = 'outline-close';
  close.textContent = 'Close'; close.setAttribute('aria-label', CLOSE_LABEL);
  close.onclick = () => document.body.classList.remove('show-outline');
  nav.insertBefore(close, nav.querySelector('#outline-items'));
  const backdrop = document.createElement('button');
  backdrop.type = 'button'; backdrop.className = 'outline-backdrop';
  backdrop.setAttribute('aria-label', CLOSE_LABEL);
  backdrop.onclick = close.onclick;
  root.append(backdrop);
  nav.addEventListener('click', event => {
    if ((event.target as Element).closest('a[href]')) closeCompactOutline(root);
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && root.isConnected && document.body.classList.contains('show-outline')) {
      document.body.classList.remove('show-outline');
      event.preventDefault();
    }
  });
  let pending = false;
  window.addEventListener('scroll', () => {
    if (pending || !root.isConnected || !document.body.classList.contains('show-outline')) return;
    pending = true;
    requestAnimationFrame(() => { pending = false; updateOutlineCurrent(root); });
  }, {passive: true});
  window.addEventListener('resize', syncOutlineLayout);
}
