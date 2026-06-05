// src/tokens.jsx — Design tokens, icônes SVG, Logo, MarkdownContent
// Exporté vers window : { T, Ic, Logo, MarkdownContent }

// ── Design tokens ──────────────────────────────────────────────
const T = {
  // Surfaces
  white:        '#ffffff',
  panel:        '#f6f6f3',
  panel2:       '#f0efeb',
  railBg:       '#fbfbf9',
  // Bordures
  border:       '#eceae5',
  borderStrong: '#e1ded7',
  // Texte
  ink:          '#1c1b18',
  sub:          '#6b6963',
  muted:        '#9c9990',
  // Accent azur
  azure:        '#2f6df0',
  azureHover:   '#2257d4',
  azureSoft:    '#ecf2fe',
  azureBorder:  '#d2e0fc',
  azureInk:     '#2257d4',
  // États
  danger:       '#dc2626',
  success:      '#16a34a',
  // Typographie
  font:         '"Hanken Grotesk", -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif',
  mono:         '"Cascadia Code", "Consolas", ui-monospace, monospace',
  // Arrondis
  radiusSm:     '8px',
  radiusMd:     '14px',
  radiusLg:     '20px',
  radiusPill:   '999px',
};

// ── Icônes SVG (traits fins 1.7px) ────────────────────────────
const S = (p = {}) => ({ fill: 'none', stroke: 'currentColor', strokeWidth: 1.7, strokeLinecap: 'round', strokeLinejoin: 'round', ...p });
const Ic = {
  Plus:      ({ s = 18 }) => <svg width={s} height={s} viewBox="0 0 18 18" {...S()}><path d="M9 3.5v11M3.5 9h11"/></svg>,
  Up:        ({ s = 18 }) => <svg width={s} height={s} viewBox="0 0 18 18" {...S({ strokeWidth: 2 })}><path d="M9 14.5V4M4 8.5 9 3.5l5 5"/></svg>,
  Mic:       ({ s = 18 }) => <svg width={s} height={s} viewBox="0 0 18 18" {...S()}><rect x="6.5" y="2.5" width="5" height="8.5" rx="2.5"/><path d="M3.8 8.2a5.2 5.2 0 0 0 10.4 0M9 13.5v2"/></svg>,
  Paperclip: ({ s = 18 }) => <svg width={s} height={s} viewBox="0 0 18 18" {...S()}><path d="M13.5 6.5 7.9 12a2.3 2.3 0 0 1-3.3-3.2l5.8-5.8a3.4 3.4 0 0 1 4.8 4.8l-5.7 5.7"/></svg>,
  Bookmark:  ({ s = 16, filled = false }) => <svg width={s} height={s} viewBox="0 0 18 18" {...S({ fill: filled ? 'currentColor' : 'none' })}><path d="M4.5 3.2h9v11.6L9 11.2l-4.5 3.6z"/></svg>,
  Copy:      ({ s = 16 }) => <svg width={s} height={s} viewBox="0 0 18 18" {...S()}><rect x="6.2" y="6.2" width="8" height="8" rx="2"/><path d="M11.5 6.2V4.6a2 2 0 0 0-2-2H4.6a2 2 0 0 0-2 2v4.9a2 2 0 0 0 2 2h1.6"/></svg>,
  Doc:       ({ s = 14 }) => <svg width={s} height={s} viewBox="0 0 18 18" {...S()}><path d="M5 2.5h5l3.5 3.5v9.5H5z"/><path d="M10 2.6V6h3.4"/></svg>,
  Close:     ({ s = 14 }) => <svg width={s} height={s} viewBox="0 0 18 18" {...S()}><path d="M4 4l10 10M14 4 4 14"/></svg>,
  Check:     ({ s = 14 }) => <svg width={s} height={s} viewBox="0 0 18 18" {...S({ strokeWidth: 2 })}><path d="M3 9.5l4.5 4.5 7.5-8"/></svg>,
  Refresh:   ({ s = 15 }) => <svg width={s} height={s} viewBox="0 0 18 18" {...S()}><path d="M3.5 9A5.5 5.5 0 1 1 9 14.5H5.5M5.5 14.5v-3M5.5 14.5H2.5"/></svg>,
  Lightning: ({ s = 14 }) => <svg width={s} height={s} viewBox="0 0 18 18" {...S({ fill: 'currentColor', stroke: 'none' })}><path d="M10.5 2 4 10h5.5L7.5 16l6.5-8H8.5z"/></svg>,
  Search:    ({ s = 14 }) => <svg width={s} height={s} viewBox="0 0 18 18" {...S()}><circle cx="8" cy="8" r="4.5"/><path d="M11.5 11.5 15 15"/></svg>,
  Microscope:({ s = 14 }) => <svg width={s} height={s} viewBox="0 0 18 18" {...S()}><rect x="6" y="2" width="6" height="8" rx="3"/><path d="M9 10v3M5 16h8M12.5 13A3.5 3.5 0 0 1 5.5 13"/></svg>,
  Inject:    ({ s = 14 }) => <svg width={s} height={s} viewBox="0 0 18 18" {...S()}><path d="M9 13V4M5 8l4-4 4 4"/><path d="M3 15h12"/></svg>,
  Upload:    ({ s = 15 }) => <svg width={s} height={s} viewBox="0 0 18 18" {...S()}><path d="M3 13v2a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1v-2M9 3v9M6 6l3-3 3 3"/></svg>,
};

// ── Logo NotebookLM Azure ──────────────────────────────────────
const Logo = ({ s = 28, r = 9 }) => (
  <div style={{
    width: s, height: s, borderRadius: r, background: T.azure,
    display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
  }}>
    <div style={{
      width: s * 0.36, height: s * 0.36, background: '#fff',
      transform: 'rotate(45deg)', borderRadius: s * 0.06,
    }} />
  </div>
);

// ── MarkdownContent ────────────────────────────────────────────
// Rend : Markdown (GFM) + diagrammes Mermaid + badges citation [N]
// Sanitisation : DOMPurify.sanitize() avant tout rendu innerHTML (SEC-002)
const MarkdownContent = ({ text, hasCitations = false, onCitationClick }) => {
  const ref = React.useRef(null);

  const html = React.useMemo(() => {
    if (!text) return '';
    let src = text;
    if (hasCitations) {
      src = src.replace(/\[(\d+)\]/g,
        '<span class="nlaz-cite">$1</span>'
      );
    }
    const rawHtml = marked.parse(src);
    // Sanitisation DOMPurify : bloque les balises/attributs dangereux (onerror, onclick, script…)
    return typeof DOMPurify !== 'undefined'
      ? DOMPurify.sanitize(rawHtml, {
          ADD_TAGS: ['span'],
          ADD_ATTR: ['class'],
          FORBID_TAGS: ['script', 'style', 'iframe', 'object', 'embed'],
          FORBID_ATTR: ['onerror', 'onload', 'onclick', 'onmouseover', 'onfocus'],
        })
      : rawHtml;
  }, [text, hasCitations]);

  React.useEffect(() => {
    if (!ref.current) return;
    const blocks = ref.current.querySelectorAll('code.language-mermaid');
    blocks.forEach(async (codeEl, i) => {
      const pre = codeEl.closest('pre');
      if (!pre) return;
      try {
        const id = `nlaz-mmd-${Date.now()}-${i}`;
        const { svg } = await mermaid.render(id, codeEl.textContent.trim());
        const wrapper = document.createElement('div');
        wrapper.className = 'nlaz-mermaid';
        // Sanitise le SVG Mermaid avant injection (securityLevel:'strict' désactive HTML dans labels)
        wrapper.innerHTML = typeof DOMPurify !== 'undefined'
          ? DOMPurify.sanitize(svg, { USE_PROFILES: { svg: true, svgFilters: true } })
          : svg;
        pre.replaceWith(wrapper);
      } catch {
        pre.classList.add('nlaz-mermaid-error');
      }
    });
  }, [html]);

  const handleClick = React.useCallback((e) => {
    if (!onCitationClick) return;
    const badge = e.target.closest('.nlaz-cite');
    if (badge) onCitationClick(Number(badge.textContent));
  }, [onCitationClick]);

  return (
    <div
      ref={ref}
      className="nlaz-md"
      dangerouslySetInnerHTML={{ __html: html }}
      onClick={handleClick}
    />
  );
};

Object.assign(window, { T, Ic, Logo, MarkdownContent });
