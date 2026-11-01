import React from 'react';
import source from '../../../docs/API.md?raw';
import Icon from '../components/Icon.jsx';
import Markdown, { parseMarkdown, slug } from '../components/Markdown.jsx';
import { CopyButton } from '../components/kit.jsx';
import { useT } from '../i18n.jsx';

// The page renders docs/API.md (bundled at build time) so the in-app docs and
// the repo docs never drift; example hosts become the address in use.
export default function ApiDocs() {
  const t = useT();
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
          <h1>{t('docs.title')}</h1>
          <p className="muted">{t('docs.subtitle')}</p>
        </div>
        <div className="row">
          <a className="btn" href="#/settings"><Icon name="key" /> {t('docs.createToken')}</a>
          <a className="btn" href="/api/docs" target="_blank" rel="noreferrer"><Icon name="external" /> {t('docs.swagger')}</a>
        </div>
      </div>

      <div className="card row between" style={{ gap: 12 }}>
        <div className="grow" style={{ minWidth: 220 }}>
          <div className="opt-label" style={{ marginBottom: 4 }}>{t('docs.baseUrl')}</div>
          <code className="mono" style={{ fontSize: 14, wordBreak: 'break-all' }}>{base}</code>
        </div>
        <CopyButton text={base} label={t('action.copy')} />
      </div>

      <div className="docs">
        <nav className="docs-toc">
          <div className="opt-label">{t('docs.toc')}</div>
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
