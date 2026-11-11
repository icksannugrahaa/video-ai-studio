import React from 'react';
import { api } from '../../api.js';
import Icon from '../Icon.jsx';
import { Button, timeAgo, useDialog, useToast } from '../kit.jsx';
import { useI18n, useT } from '../../i18n.jsx';

function fmtSize(bytes) {
  if (!bytes) return '0 MB';
  return bytes >= 1e9 ? `${(bytes / 1e9).toFixed(1)} GB` : `${Math.max(0.1, bytes / 1e6).toFixed(1)} MB`;
}

/** Snapshots of the project's result: back up now, restore one (replaces the
 *  current scenes), or delete it. ``version`` changes whenever the project
 *  reloads, so a backup made by Rebuild shows up without a manual refresh. */
export default function BackupsCard({ projectId, hasScenes, busy, version, onRestored }) {
  const t = useT();
  const { lang } = useI18n();
  const toast = useToast();
  const dialog = useDialog();
  const [items, setItems] = React.useState(null);
  const [working, setWorking] = React.useState('');
  const [open, setOpen] = React.useState(false);

  const load = React.useCallback(async () => {
    try {
      setItems(await api.get(`/projects/${projectId}/backups`));
    } catch {
      setItems([]);
    }
  }, [projectId]);
  React.useEffect(() => { load(); }, [load, version]);

  async function act(key, fn, ok) {
    setWorking(key);
    try {
      const result = await fn();
      if (ok) toast(ok, 'ok');
      await load();
      return result;
    } catch (err) {
      toast(err.message, 'bad');
      return null;
    } finally {
      setWorking('');
    }
  }

  async function backupNow() {
    const label = await dialog.prompt({ title: t('backup.newTitle'), body: t('backup.newBody'),
      placeholder: t('backup.labelPlaceholder'), confirmLabel: t('backup.save') });
    if (label === null) return;
    await act('new', () => api.post(`/projects/${projectId}/backups`, { label: label.trim() }), t('backup.saved'));
    setOpen(true);
  }

  async function restore(b) {
    if (!(await dialog.confirm({ title: t('backup.restoreTitle'), body: t('backup.restoreBody', { when: timeAgo(b.created_at, t, lang) }),
      confirmLabel: t('backup.restore'), danger: true }))) return;
    const project = await act(b.id, () => api.post(`/projects/${projectId}/backups/${b.id}/restore`), t('backup.restored'));
    if (project) onRestored(project);
  }

  async function remove(b) {
    if (!(await dialog.confirm({ title: t('backup.deleteTitle'), body: t('backup.deleteBody'),
      confirmLabel: t('action.delete'), danger: true }))) return;
    await act(b.id, () => api.del(`/projects/${projectId}/backups/${b.id}`), t('backup.deleted'));
  }

  const list = items || [];
  return (
    <div className="card">
      <div className="row between">
        <h3 className="row" style={{ gap: 8, cursor: list.length ? 'pointer' : 'default' }} onClick={() => list.length && setOpen(!open)}>
          <Icon name="layers" /> {t('backup.title')}
          {list.length > 0 && <span className="faint small">({list.length})</span>}
          {list.length > 0 && <Icon name="chevron" className={`chev${open ? ' open' : ''}`} />}
        </h3>
        <Button className="sm" icon="download" loading={working === 'new'} disabled={busy || !hasScenes || !!working}
          title={!hasScenes ? t('backup.nothing') : t('backup.newTitle')} onClick={backupNow}>{t('backup.now')}</Button>
      </div>
      {!list.length && <div className="faint small" style={{ marginTop: 6 }}>{t('backup.empty')}</div>}
      {open && list.length > 0 && (
        <div className="stack tight" style={{ marginTop: 10 }}>
          {list.map((b) => (
            <div key={b.id} className="row between" style={{ gap: 8, padding: '8px 0', borderTop: '1px solid var(--line)' }}>
              <div className="grow stack tight" style={{ minWidth: 0 }}>
                <strong className="ellipsis">{b.label || t('backup.untitled')}</strong>
                <span className="faint small">
                  {timeAgo(b.created_at, t, lang)} · {t('backup.scenes', { n: b.scenes, clips: b.clips })}
                  {b.has_final ? ` · ${t('backup.final')}` : ''} · {fmtSize(b.bytes)}
                </span>
              </div>
              <Button className="sm" icon="refresh" loading={working === b.id} disabled={busy || !!working}
                onClick={() => restore(b)}>{t('backup.restore')}</Button>
              <Button className="sm ghost" icon="trash" disabled={busy || !!working} onClick={() => remove(b)}
                title={t('action.delete')} aria-label={t('action.delete')} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
