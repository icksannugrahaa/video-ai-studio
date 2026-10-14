import React from 'react';
import { api, fileUrl } from '../api.js';
import { go } from '../App.jsx';
import Icon from '../components/Icon.jsx';
import { Button, Empty, RatioIcon, StatusBadge, fmtDuration, timeAgo, useToast } from '../components/kit.jsx';
import { useT, useI18n } from '../i18n.jsx';

const EXAMPLES = ['projects.ex1', 'projects.ex2', 'projects.ex3', 'projects.ex4'];
const DURATIONS = [[15, 'projects.d15'], [30, 'projects.d30'], [60, 'projects.d60'], [180, 'projects.d180']];
const FILTERS = [['all', 'projects.filter.all'], ['active', 'projects.filter.active'], ['done', 'projects.filter.done'], ['draft', 'projects.filter.draft']];

function Composer({ presets, profiles }) {
  const t = useT();
  const { lang } = useI18n();
  const toast = useToast();
  const [form, setForm] = React.useState({ prompt: '', preset: 'tiktok', target_seconds: 30, profile_id: '' });
  const [custom, setCustom] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const area = React.useRef(null);
  React.useEffect(() => {
    if (profiles[0]) setForm((f) => ({ ...f, profile_id: f.profile_id || profiles[0].id }));
  }, [profiles]);
  React.useEffect(() => {
    if (window.location.hash.includes('?new')) area.current?.focus();
  }, []);

  const preset = presets.find((p) => p.id === form.preset);
  const tooLong = preset && Number(form.target_seconds) > preset.max_seconds;

  async function create(e) {
    e?.preventDefault();
    if (!form.prompt.trim()) { area.current?.focus(); return; }
    setBusy(true);
    try {
      const project = await api.post('/projects', {
        ...form, target_seconds: Number(form.target_seconds), profile_id: form.profile_id ? Number(form.profile_id) : null,
      });
      go(`/projects/${project.id}`);
    } catch (err) {
      toast(err.message, 'bad');
      setBusy(false);
    }
  }

  return (
    <form className="card composer" onSubmit={create}>
      <div className="composer-body">
        <div>
          <h2 style={{ display: 'flex', alignItems: 'center', gap: 8 }}><Icon name="sparkles" /> {t('projects.composerTitle')}</h2>
          <p className="muted small" style={{ margin: '4px 0 0' }}>{t('projects.composerHint')}</p>
        </div>
        <textarea ref={area} value={form.prompt} placeholder={t('projects.promptPlaceholder')}
          onChange={(e) => setForm({ ...form, prompt: e.target.value })}
          onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') create(); }} />
        {!form.prompt && (
          <div className="examples">
            {EXAMPLES.map((ex) => <button type="button" key={ex} className="example" onClick={() => setForm({ ...form, prompt: t(ex) })}>{t(ex)}</button>)}
          </div>
        )}
        <div>
          <div className="opt-label">{t('projects.platform')}</div>
          <div className="chips">
            {presets.map((p) => (
              <button type="button" key={p.id} className={`chip${form.preset === p.id ? ' active' : ''}`}
                onClick={() => setForm({ ...form, preset: p.id })}>
                <RatioIcon aspect={p.aspect} /> {p.label} <span className="faint small">{p.aspect}</span>
              </button>
            ))}
          </div>
        </div>
        <div>
          <div className="opt-label">{t('projects.duration')}</div>
          <div className="chips">
            {DURATIONS.map(([s, label]) => (
              <button type="button" key={s} className={`chip${!custom && Number(form.target_seconds) === s ? ' active' : ''}`}
                onClick={() => { setCustom(false); setForm({ ...form, target_seconds: s }); }}>{t(label)}</button>
            ))}
            <span className={`chip${custom ? ' active' : ''}`} onClick={() => setCustom(true)}>
              {t('projects.custom')}
              {custom && <input type="number" min={5} max={3600} autoFocus value={form.target_seconds}
                onChange={(e) => setForm({ ...form, target_seconds: e.target.value })} />}
              {custom && <span className="faint small">{t('time.seconds')}</span>}
            </span>
          </div>
          {tooLong && <p className="small" style={{ color: 'var(--warn)', margin: '8px 0 0' }}>
            {t('projects.tooLong', { label: preset.label, max: fmtDuration(preset.max_seconds, t) })}</p>}
          {Number(form.target_seconds) >= 120 && !tooLong && <p className="faint small" style={{ margin: '8px 0 0' }}>
            {t('projects.longVideo')}</p>}
        </div>
      </div>
      <div className="composer-foot">
        <label className="row small muted">
          <Icon name="server" /> {t('projects.profile')}
          <select value={form.profile_id} onChange={(e) => setForm({ ...form, profile_id: e.target.value })}>
            <option value="">{t('common.selectedProfile')}</option>
            {profiles.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </label>
        <div className="row">
          <span className="kbd">⌘/Ctrl + Enter</span>
          <Button className="primary" icon="sparkles" loading={busy} type="submit" disabled={!form.prompt.trim()}>{t('projects.create')}</Button>
        </div>
      </div>
    </form>
  );
}

function Thumb({ project }) {
  const t = useT();
  const ref = React.useRef(null);
  const src = project.files?.includes('final.mp4') ? fileUrl(project.id, 'final.mp4', project.updated_at)
    : project.files?.includes('preview.mp4') ? fileUrl(project.id, 'preview.mp4', project.updated_at)
      : project.thumb_clip ? fileUrl(project.id, project.thumb_clip) : null;
  const job = project.active_job;
  const progress = job ? job.progress : project.scene_count ? project.clips_ready / project.scene_count : 0;
  return (
    <div className="pthumb"
      onMouseEnter={() => ref.current?.play().catch(() => {})}
      onMouseLeave={() => { if (ref.current) { ref.current.pause(); ref.current.currentTime = 1; } }}>
      {src
        ? <video ref={ref} src={`${src}#t=1`} muted loop playsInline preload="metadata" />
        : <div className="placeholder"><Icon name="film" size={26} strokeWidth={1.5} />{project.scene_count ? t('projects.sceneCount', { n: project.scene_count }) : t('projects.noVideo')}</div>}
      <div className="overlay">
        <StatusBadge status={job ? job.status : project.status} label={job ? `${Math.round(job.progress * 100)}%` : undefined} />
      </div>
      {project.total_seconds > 0 && <span className="dur">{fmtDuration(project.total_seconds, t)}</span>}
      {(job || (project.status !== 'done' && progress > 0)) && <div className="bar"><div style={{ width: `${progress * 100}%` }} /></div>}
    </div>
  );
}

export default function Projects() {
  const t = useT();
  const { lang } = useI18n();
  const toast = useToast();
  const [projects, setProjects] = React.useState(null);
  const [profiles, setProfiles] = React.useState([]);
  const [presets, setPresets] = React.useState([]);
  const [query, setQuery] = React.useState('');
  const [filter, setFilter] = React.useState('all');

  const loadProjects = React.useCallback(() => api.get('/projects').then(setProjects).catch((e) => toast(e.message, 'bad')), [toast]);
  React.useEffect(() => {
    loadProjects();
    api.get('/profiles').then(setProfiles).catch(() => {});
    api.get('/presets').then(setPresets).catch(() => {});
  }, [loadProjects]);

  const anyActive = projects?.some((p) => p.active_job);
  React.useEffect(() => {
    if (!anyActive) return undefined;
    const t = setInterval(() => { if (!document.hidden) loadProjects(); }, 5000);
    return () => clearInterval(t);
  }, [anyActive, loadProjects]);

  const presetById = Object.fromEntries(presets.map((p) => [p.id, p]));
  const q = query.trim().toLowerCase();
  const shown = (projects || []).filter((p) => {
    if (q && !`${p.title} ${p.prompt}`.toLowerCase().includes(q)) return false;
    if (filter === 'active') return Boolean(p.active_job);
    if (filter === 'done') return p.status === 'done';
    if (filter === 'draft') return !p.active_job && p.status !== 'done';
    return true;
  });

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{t('projects.title')}</h1>
          <p className="muted">{t('projects.subtitle')}</p>
        </div>
      </div>

      {!profiles.length && projects && (
        <div className="alert warn" style={{ marginBottom: 16 }}>
          <Icon name="alert" />
          <div>{t('projects.noProfile')} <a href="#/settings">{t('projects.addEndpoint')}</a> {t('projects.noProfileAfter')}</div>
        </div>
      )}

      <Composer presets={presets} profiles={profiles} />

      <div className="toolbar">
        <div className="row">
          <h2>{t('projects.mine')}</h2>
          {projects && <span className="badge">{projects.length}</span>}
        </div>
        <div className="row">
          <div className="chips">
            {FILTERS.map(([id, label]) => (
              <button key={id} className={`chip${filter === id ? ' active' : ''}`} onClick={() => setFilter(id)}>{t(label)}</button>
            ))}
          </div>
          <div className="input-icon">
            <Icon name="search" />
            <input placeholder={t('projects.search')} value={query} onChange={(e) => setQuery(e.target.value)} />
          </div>
        </div>
      </div>

      {!projects && <Empty icon="loader" title={t('projects.loading')} />}
      {projects && !projects.length && <div className="card"><Empty title={t('projects.empty')}>{t('projects.emptyHint')}</Empty></div>}
      {projects && projects.length > 0 && !shown.length && <div className="card"><Empty icon="search" title={t('projects.noMatch')}>{t('projects.noMatchHint')}</Empty></div>}

      <div className="pgrid">
        {shown.map((p) => (
          <a key={p.id} className="pcard" href={`#/projects/${p.id}`}>
            <Thumb project={p} />
            <div className="pcard-body">
              <div className="pcard-title">{p.title || p.prompt || `Project #${p.id}`}</div>
              {p.active_job && <div className="small muted ellipsis">{p.active_job.message || t('projects.processing')}</div>}
              <div className="pcard-meta">
                <span className="row" style={{ gap: 5 }}><RatioIcon aspect={presetById[p.preset]?.aspect} size={11} />{presetById[p.preset]?.label || p.preset}</span>
                {p.scene_count > 0 && <span>{t('projects.clipProgress', { ready: p.clips_ready, total: p.scene_count })}</span>}
                <span>{timeAgo(p.updated_at, t, lang === 'en' ? 'en-US' : 'id-ID')}</span>
              </div>
            </div>
          </a>
        ))}
      </div>
    </>
  );
}
