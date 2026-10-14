import React from 'react';
import { CopyButton } from './kit.jsx';

// Small Markdown renderer for our own docs (headings, paragraphs, lists, tables,
// fenced code, blockquotes, rules; inline code, bold, links). Builds React
// elements — no HTML injection.

const INLINE = /(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\([^)\s]+\))/g;

export function slug(text) {
  return text.toLowerCase().replace(/[`*]/g, '').replace(/[^\p{L}\p{N}]+/gu, '-').replace(/^-|-$/g, '');
}

function inline(text, key = 'i') {
  return text.split(INLINE).filter(Boolean).map((part, i) => {
    const k = `${key}-${i}`;
    if (part.startsWith('`') && part.endsWith('`')) return <code key={k}>{part.slice(1, -1)}</code>;
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={k}>{part.slice(2, -2)}</strong>;
    const link = part.match(/^\[([^\]]+)\]\(([^)\s]+)\)$/);
    if (link) {
      const external = /^https?:/.test(link[2]);
      return <a key={k} href={link[2]} {...(external ? { target: '_blank', rel: 'noreferrer' } : {})}>{link[1]}</a>;
    }
    return part;
  });
}

const splitRow = (line) => line.trim().replace(/^\||\|$/g, '').split(/(?<!\\)\|/).map((c) => c.trim().replace(/\\\|/g, '|'));

export function parseMarkdown(src) {
  const lines = src.replace(/\r\n/g, '\n').split('\n');
  const blocks = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i += 1; continue; }
    const fence = line.match(/^```(\w*)/);
    if (fence) {
      const body = [];
      i += 1;
      while (i < lines.length && !lines[i].startsWith('```')) body.push(lines[i++]);
      blocks.push({ type: 'code', lang: fence[1], text: body.join('\n') });
      i += 1;
      continue;
    }
    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) { blocks.push({ type: 'h', level: heading[1].length, text: heading[2] }); i += 1; continue; }
    if (/^---+\s*$/.test(line)) { blocks.push({ type: 'hr' }); i += 1; continue; }
    if (line.trim().startsWith('|') && /^\s*\|?\s*:?-{3,}/.test(lines[i + 1] || '')) {
      const head = splitRow(line);
      const rows = [];
      i += 2;
      while (i < lines.length && lines[i].trim().startsWith('|')) rows.push(splitRow(lines[i++]));
      blocks.push({ type: 'table', head, rows });
      continue;
    }
    if (line.startsWith('>')) {
      const body = [];
      while (i < lines.length && lines[i].startsWith('>')) body.push(lines[i++].replace(/^>\s?/, ''));
      blocks.push({ type: 'quote', text: body.join(' ') });
      continue;
    }
    const item = line.match(/^(\s*)(-|\d+\.)\s+(.*)$/);
    if (item) {
      const ordered = /\d/.test(item[2]);
      const items = [];
      while (i < lines.length) {
        const m = lines[i].match(/^(\s*)(-|\d+\.)\s+(.*)$/);
        if (m) { items.push(m[3]); i += 1; continue; }
        if (lines[i].startsWith('  ') && lines[i].trim() && items.length) { items[items.length - 1] += ` ${lines[i].trim()}`; i += 1; continue; }
        break;
      }
      blocks.push({ type: ordered ? 'ol' : 'ul', items });
      continue;
    }
    const para = [];
    while (i < lines.length && lines[i].trim() && !/^(```|#{1,4}\s|>|\s*(-|\d+\.)\s|\||---)/.test(lines[i])) para.push(lines[i++].trim());
    if (!para.length) { para.push(line.trim()); i += 1; }
    blocks.push({ type: 'p', text: para.join(' ') });
  }
  return blocks;
}

export default function Markdown({ source }) {
  const blocks = React.useMemo(() => parseMarkdown(source), [source]);
  return (
    <div className="md">
      {blocks.map((b, n) => {
        const key = `b${n}`;
        switch (b.type) {
          case 'h': {
            const Tag = `h${Math.min(4, Math.max(2, b.level))}`;  // the page itself owns the h1
            return <Tag key={key} id={slug(b.text)}>{inline(b.text, key)}</Tag>;
          }
          case 'code':
            return (
              <div key={key} className="md-code">
                <div className="md-code-bar"><span className="faint small mono">{b.lang || 'text'}</span><CopyButton text={b.text} className="ghost sm" /></div>
                <pre><code>{b.text}</code></pre>
              </div>
            );
          case 'table':
            return (
              <div key={key} className="table-wrap md-table">
                <table className="table">
                  <thead><tr>{b.head.map((c, j) => <th key={j}>{inline(c, `${key}h${j}`)}</th>)}</tr></thead>
                  <tbody>{b.rows.map((r, j) => <tr key={j}>{r.map((c, k) => <td key={k}>{inline(c, `${key}r${j}${k}`)}</td>)}</tr>)}</tbody>
                </table>
              </div>
            );
          case 'quote':
            return <div key={key} className="alert info md-quote"><div>{inline(b.text, key)}</div></div>;
          case 'ul':
          case 'ol': {
            const Tag = b.type;
            return <Tag key={key}>{b.items.map((t, j) => <li key={j}>{inline(t, `${key}-${j}`)}</li>)}</Tag>;
          }
          case 'hr':
            return <hr key={key} />;
          default:
            return <p key={key}>{inline(b.text, key)}</p>;
        }
      })}
    </div>
  );
}
