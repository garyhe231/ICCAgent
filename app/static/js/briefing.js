/* ICC AI Agent — Briefing page: render markdown */

document.addEventListener('DOMContentLoaded', () => {
  const el = document.getElementById('briefing-content');
  if (!el) return;
  const raw = el.textContent;
  el.innerHTML = renderMarkdown(raw);
});

/**
 * Lightweight markdown renderer sufficient for the briefing format.
 * Handles: headings, bold, italic, tables, code, blockquotes, hr, ul/ol, paragraphs.
 */
function renderMarkdown(md) {
  let html = md;

  // Escape HTML entities first (except we need to allow our own tags)
  html = html.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

  // Code blocks (``` ... ```)
  html = html.replace(/```[\w]*\n?([\s\S]*?)```/g, (_, code) =>
    `<pre><code>${code.trim()}</code></pre>`
  );

  // Inline code
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

  // HR
  html = html.replace(/^---+$/gm, '<hr>');

  // Headings
  html = html.replace(/^#### (.+)$/gm, '<h4>$1</h4>');
  html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
  html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');

  // Blockquotes
  html = html.replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>');

  // Bold + italic
  html = html.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>');
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');

  // Tables
  html = renderTables(html);

  // Unordered lists
  html = html.replace(/((?:^[-*] .+\n?)+)/gm, (block) => {
    const items = block.trim().split('\n').map(l => `<li>${l.replace(/^[-*] /, '')}</li>`).join('');
    return `<ul>${items}</ul>`;
  });

  // Ordered lists
  html = html.replace(/((?:^\d+\. .+\n?)+)/gm, (block) => {
    const items = block.trim().split('\n').map(l => `<li>${l.replace(/^\d+\. /, '')}</li>`).join('');
    return `<ol>${items}</ol>`;
  });

  // Paragraphs: wrap lines not already in block tags
  html = html.split(/\n\n+/).map(chunk => {
    chunk = chunk.trim();
    if (!chunk) return '';
    if (/^<(h[1-6]|ul|ol|pre|blockquote|table|hr)/.test(chunk)) return chunk;
    return `<p>${chunk.replace(/\n/g, '<br>')}</p>`;
  }).join('\n');

  return html;
}

function renderTables(html) {
  // Match pipe-delimited table blocks
  const tableRegex = /((?:^\|.+\|\n?){2,})/gm;
  return html.replace(tableRegex, (block) => {
    const rows = block.trim().split('\n').filter(r => r.trim());
    if (rows.length < 2) return block;

    let out = '<table>';
    rows.forEach((row, i) => {
      // Skip separator row (|---|---|)
      if (/^\|[-| :]+\|$/.test(row.trim())) return;
      const cells = row.split('|').slice(1, -1).map(c => c.trim());
      const tag = i === 0 ? 'th' : 'td';
      out += '<tr>' + cells.map(c => `<${tag}>${c}</${tag}>`).join('') + '</tr>';
    });
    out += '</table>';
    return out;
  });
}
