import React from 'react';
import source from '../../../docs/API.md?raw';
import Icon from '../components/Icon.jsx';
import Markdown, { parseMarkdown, slug } from '../components/Markdown.jsx';
import { CopyButton } from '../components/kit.jsx';

// The page renders docs/API.md (bundled at build time) so the in-app docs and
// the repo docs never drift; example hosts become the address in use.
export default function ApiDocs() {
  const origin = window.location.origin;
  const base = `${origin}/api`;
  const doc = React.useMemo(() => source
    .replace(/^# .*\n/, '')
    .replaceAll('https://<host-kamu>', origin)
    .replaceAll('https://video.example.com', origin), [origin]);
  const toc = React.useMemo(() => parseMarkdown(doc).filter((b) => b.type === 'h' && b.level === 2), [doc]);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Dokumentasi API</h1>
          <p className="muted">Buat video dari aplikasi lain (bot WA, script, backend) dengan token API.</p>
        </div>
        <div className="row">
          <a className="btn" href="#/settings"><Icon name="key" /> Buat token</a>
          <a className="btn" href="/api/docs" target="_blank" rel="noreferrer"><Icon name="external" /> Swagger</a>
        </div>
      </div>

      <div className="card row between" style={{ gap: 12 }}>
        <div className="grow" style={{ minWidth: 220 }}>
          <div className="opt-label" style={{ marginBottom: 4 }}>Base URL server ini</div>
          <code className="mono" style={{ fontSize: 14, wordBreak: 'break-all' }}>{base}</code>
        </div>
        <CopyButton text={base} label="Salin" />
      </div>

      <div className="docs">
        <nav className="docs-toc">
          <div className="opt-label">Isi</div>
          {toc.map((h) => (
            <a key={h.text} href={`#${slug(h.text)}`} onClick={(e) => {
              e.preventDefault();
              const el = document.getElementById(slug(h.text));
              if (el) window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - 16, behavior: 'smooth' });
            }}>{h.text.replace(/`/g, '')}</a>
          ))}
        </nav>
        <div className="card docs-body"><Markdown source={doc} /></div>
      </div>
    </>
  );
}
