import React from 'react';
import { fileUrl } from '../../api.js';
import Icon from '../Icon.jsx';
import { api } from '../../api.js';
import { Button, Empty, StatusBadge, Switch, fmtClock, fmtDuration } from '../kit.jsx';
import { SCENE_LABEL, sceneState, totalSeconds } from './shared.js';
import { useT } from '../../i18n.jsx';

const STATE_TONE = { done: 'done', stale: 'stale', running: 'running', failed: 'failed', pending: 'pending' };
const LEGEND = [['var(--ok)', 'sb.stateDone'], ['var(--info)', 'sb.stateRunning'], ['var(--bad)', 'sb.stateFailed'], ['var(--warn)', 'sb.stateStale'], ['var(--surface-3)', 'sb.statePending']];

function Timeline({ scenes, selected, onSelect }) {
  const t = useT();
  return (
    <>
      <div className="timeline" role="tablist" aria-label={t('sb.timelineAria')}>
        {scenes.map((s, i) => {
          const state = sceneState(s);
          return (
            <button key={s.id || `new-${i}`} role="tab" aria-selected={selected === i}
              className={`tl-block ${STATE_TONE[state]}${selected === i ? ' selected' : ''}${s.continues && i > 0 ? ' cont' : ''}`}
              style={{ flex: `${Math.max(1, Number(s.duration) || 1)} 1 0` }}
              title={`${t('sb.sceneN', { n: i + 1 })} · ${t('sb.secs', { n: s.duration })} · ${t(SCENE_LABEL[state])}${s.continues && i > 0 ? ` · ${t('sb.contPrev')}` : ''}`}
              onClick={() => onSelect(i)}>{i + 1}</button>
          );
        })}
      </div>
      <div className="legend">
        {LEGEND.map(([color, label]) => <span key={label}><i style={{ background: color }} />{t(label)}</span>)}
      </div>
    </>
  );
}

const BIBLE_FIELDS = [
  ['bible_character', 'sb.character', 'sb.characterHint', 4],
  ['bible_world', 'sb.world', 'sb.worldHint', 3],
  ['bible_style', 'sb.style', 'sb.styleHint', 2],
];

function BibleCard({ project, busy, run }) {
  const t = useT();
  const o = project.options;
  const saved = Object.fromEntries(BIBLE_FIELDS.map(([k]) => [k, o[k] || '']));
  const [form, setForm] = React.useState(saved);
  const [open, setOpen] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const savedKey = JSON.stringify(saved);
  React.useEffect(() => { setForm(JSON.parse(savedKey)); }, [savedKey]);
  const changed = BIBLE_FIELDS.some(([k]) => form[k] !== saved[k]);
  const empty = BIBLE_FIELDS.every(([k]) => !saved[k]);

  async function save() {
    setSaving(true);
    await run(() => api.patch(`/projects/${project.id}`, { options: form }), t('sb.bibleSaved'));
    setSaving(false);
  }

  return (
    <div className="card flat" style={{ marginBottom: 14, padding: 14 }}>
      <div className="row between" style={{ cursor: 'pointer' }} onClick={() => setOpen(!open)}>
        <div className="row" style={{ gap: 10 }}>
          <Icon name="chevron" className={`chev${open ? ' open' : ''}`} />
          <div>
            <b>{t('sb.bibleTitle')}</b>
            <div className="faint small">
              {empty ? t('sb.bibleEmpty') : t('sb.bibleFilled')}
            </div>
          </div>
        </div>
        {!open && !empty && <span className="badge ok"><span className="dot" />{t('sb.active')}</span>}
      </div>
      {open && (
        <div className="stack" style={{ marginTop: 14 }}>
          {BIBLE_FIELDS.map(([key, label, hint, rows]) => (
            <label key={key} className="field"><span>{t(label)} <span className="hint">— {t(hint)}</span></span>
              <textarea rows={rows} value={form[key]} onChange={(e) => setForm({ ...form, [key]: e.target.value })} />
            </label>
          ))}
          <div className="row">
            <Button className="primary sm" icon="check" loading={saving} disabled={!changed} onClick={save}>{t('action.save')}</Button>
            {changed && <button className="btn ghost sm" onClick={() => setForm(saved)}>{t('action.discard')}</button>}
            <span className="faint small">{t('sb.bibleNote')}{busy ? t('sb.bibleNoteBusy') : ''}.</span>
          </div>
        </div>
      )}
    </div>
  );
}

function SceneCard({ scene, index, count, start, project, open, selected, busy, dirty, onToggle, onChange, onMove, onRemove, onRegenerate }) {
  const t = useT();
  const ref = React.useRef(null);
  const state = sceneState(scene);
  React.useEffect(() => {
    if (selected) ref.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [selected]);
  const clip = scene.clip_file && (state === 'done' || state === 'stale') ? fileUrl(project.id, scene.clip_file, scene.clip_version) : null;

  return (
    <div ref={ref} className={`scene${selected ? ' selected' : ''}${state === 'failed' ? ' failed' : ''}`}>
      <div className="scene-head" onClick={onToggle}>
        <Icon name="chevron" className={`chev${open ? ' open' : ''}`} />
        <span className="scene-num">{index + 1}</span>
        <div className="scene-thumb">
          {clip ? <video src={`${clip}#t=0.5`} muted preload="metadata" /> : <Icon name={state === 'running' ? 'loader' : 'film'} className={state === 'running' ? 'spin' : ''} />}
        </div>
        <div className="scene-summary">
          <div className="v ellipsis">{scene.visual_prompt || <span className="faint">{t('sb.emptyVisual')}</span>}</div>
          <div className="n ellipsis">{scene.narration || <span className="faint">{t('sb.noNarration')}</span>}</div>
        </div>
        {scene.continues && index > 0 && <span className="badge info" title={t('sb.contPrev')}><Icon name="link" size={11} /></span>}
        {state === 'done' && scene.clip_gen_seconds != null && (
          <span className="gen-time mono" title={t('sb.clipMadeIn', { dur: fmtDuration(scene.clip_gen_seconds, t) }) + (scene.clip_attempts > 1 ? ' · ' + t('sb.attempts', { n: scene.clip_attempts }) : '')}>
            <Icon name="clock" size={11} />{fmtClock(scene.clip_gen_seconds)}{scene.clip_attempts > 1 && <span style={{ color: 'var(--warn)' }}>×{scene.clip_attempts}</span>}
          </span>
        )}
        <span className="faint small mono" style={{ flex: 'none' }}>{fmtClock(start)} · {t('sb.secsShort', { n: scene.duration })}</span>
        {scene.id && <StatusBadge status={state === 'done' ? 'succeeded' : state === 'running' ? 'running' : state === 'failed' ? 'failed' : state === 'stale' ? 'stale' : 'pending'}
          label={t(SCENE_LABEL[state])} />}
      </div>
      {open && (
        <div className="scene-body">
          {state === 'done' && scene.clip_gen_seconds != null && (
            <div className="faint small row" style={{ gap: 6 }}>
              <Icon name="clock" size={13} /> {t('sb.clipMadeInLabel')} <b style={{ color: 'var(--text)' }}>{fmtDuration(scene.clip_gen_seconds, t)}</b>
              {scene.clip_attempts > 1 && <span>· {t('sb.succeededAttempt', { n: scene.clip_attempts })}</span>}
            </div>
          )}
          {scene.clip_error && state === 'failed' && (
            <div className="alert bad"><Icon name="alert" /><div>
              <strong>{t('sb.clipFailed')}</strong> {scene.clip_error}
              {/hak cipta|filter konten|copyright|content filter/i.test(scene.clip_error) && <div className="small muted" style={{ marginTop: 4 }}>
                {t('sb.clipFailedTip')}</div>}
            </div></div>
          )}
          <label className="field"><span>{t('sb.visualLabel')} <span className="hint">— {t('sb.visualHint')}</span></span>
            <textarea rows={3} value={scene.visual_prompt} onChange={(e) => onChange('visual_prompt', e.target.value)} />
          </label>
          <label className="field"><span>{t('sb.narrationLabel')} <span className="hint">— {t('sb.narrationHint')}</span></span>
            <textarea rows={2} value={scene.narration || ''} onChange={(e) => onChange('narration', e.target.value)} />
          </label>
          {index > 0 && (
            <Switch checked={scene.continues} onChange={(v) => onChange('continues', v)} label={t('sb.continuesLabel')}
              hint={t('sb.continuesHint')} />
          )}
          <div className="row between">
            <label className="field" style={{ width: 150 }}>{t('sb.durationLabel')}
              <input type="number" min={1} max={30} value={scene.duration} onChange={(e) => onChange('duration', e.target.value)} />
            </label>
            <div className="scene-actions">
              <button className="btn ghost icon sm" title={t('sb.moveUp')} disabled={busy || index === 0} onClick={() => onMove(-1)}><Icon name="up" /></button>
              <button className="btn ghost icon sm" title={t('sb.moveDown')} disabled={busy || index === count - 1} onClick={() => onMove(1)}><Icon name="down" /></button>
              {scene.id && (
                <Button className="sm" icon="refresh" disabled={busy || dirty} onClick={onRegenerate}
                  title={dirty ? t('sb.saveFirst') : t('sb.regenTitle')}>{t('sb.regenerate')}</Button>
              )}
              <Button className="danger sm" icon="trash" disabled={busy} onClick={onRemove}>{t('action.delete')}</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function Storyboard({ project, scenes, setScenes, dirty, setDirty, busy, selected, onSelect,
  onSave, onReset, onRegenerate, onPlan, saving, run }) {
  const t = useT();
  const [open, setOpen] = React.useState(() => new Set());
  const keyOf = (s, i) => s.id || `new-${i}`;
  const allOpen = scenes.length > 0 && scenes.every((s, i) => open.has(keyOf(s, i)));

  React.useEffect(() => {
    if (selected == null || !scenes[selected]) return;
    const k = keyOf(scenes[selected], selected);
    setOpen((prev) => (prev.has(k) ? prev : new Set(prev).add(k)));
  }, [selected]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggle = (k) => setOpen((prev) => { const next = new Set(prev); if (next.has(k)) next.delete(k); else next.add(k); return next; });
  const mutate = (fn) => { setDirty(true); setScenes(fn(scenes)); };
  const edit = (i, key, value) => mutate((list) => list.map((s, idx) => (idx === i ? { ...s, [key]: value } : s)));
  const move = (i, delta) => {
    mutate((list) => { const next = [...list]; const [s] = next.splice(i, 1); next.splice(i + delta, 0, s); return next; });
    onSelect(i + delta);
  };
  const add = () => {
    const i = scenes.length;
    mutate((list) => [...list, { visual_prompt: '', narration: '', duration: 5 }]);
    setOpen((prev) => new Set(prev).add(`new-${i}`));
    onSelect(i);
  };

  let cursor = 0;
  const starts = scenes.map((s) => { const at = cursor; cursor += Number(s.duration || 0); return at; });
  const failed = scenes.filter((s) => sceneState(s) === 'failed').length;
  const timed = scenes.filter((s) => sceneState(s) === 'done' && s.clip_gen_seconds != null);
  const avgGen = timed.length ? timed.reduce((t, s) => t + s.clip_gen_seconds, 0) / timed.length : 0;

  if (!scenes.length) {
    return (
      <Empty icon="layers" title={t('sb.noStoryboard')}>
        <span>{t('sb.noStoryboardHint')}</span>
        <Button className="primary" icon="sparkles" disabled={busy} onClick={onPlan} style={{ marginTop: 8 }}>{t('sb.planCta')}</Button>
      </Empty>
    );
  }

  return (
    <div>
      <div className="row between" style={{ marginBottom: 12 }}>
        <div className="small muted">
          <b style={{ color: 'var(--text)' }}>{t('sb.sceneCount', { n: scenes.length })}</b> · {fmtDuration(totalSeconds(scenes), t)}
          {failed > 0 && <span style={{ color: 'var(--bad)' }}> · {t('sb.failedCount', { n: failed })}</span>}
          {timed.length > 0 && <span> · {t('sb.avgPerClip', { dur: fmtClock(avgGen) })}</span>}
        </div>
        <div className="row">
          <button className="btn ghost sm" onClick={() => setOpen(allOpen ? new Set() : new Set(scenes.map(keyOf)))}>
            {allOpen ? t('sb.collapseAll') : t('sb.expandAll')}
          </button>
          <Button className="sm" icon="sparkles" disabled={busy} onClick={onPlan}>{t('sb.replanCta')}</Button>
        </div>
      </div>

      <BibleCard project={project} busy={busy} run={run} />
      <Timeline scenes={scenes} selected={selected} onSelect={onSelect} />

      <div className="scenes">
        {scenes.map((s, i) => (
          <SceneCard key={keyOf(s, i)} scene={s} index={i} count={scenes.length} start={starts[i]} project={project}
            open={open.has(keyOf(s, i))} selected={selected === i} busy={busy} dirty={dirty}
            onToggle={() => { toggle(keyOf(s, i)); onSelect(i); }}
            onChange={(key, value) => edit(i, key, value)}
            onMove={(delta) => move(i, delta)}
            onRemove={() => { mutate((list) => list.filter((_, idx) => idx !== i)); onSelect(null); }}
            onRegenerate={() => onRegenerate(i)} />
        ))}
      </div>

      <div className="row" style={{ marginTop: 12 }}>
        <Button icon="plus" disabled={busy} onClick={add}>{t('sb.addScene')}</Button>
        {busy && <span className="faint small">{t('sb.lockedWhileBusy')}</span>}
      </div>

      {dirty && (
        <div className="save-bar">
          <span className="row"><Icon name="edit" /> {t('sb.unsaved')} <span className="kbd">⌘/Ctrl + S</span></span>
          <div className="row">
            <button className="btn ghost" onClick={onReset}>{t('action.discard')}</button>
            <Button className="primary" icon="check" loading={saving} disabled={busy} onClick={onSave}>{t('sb.saveStoryboard')}</Button>
          </div>
        </div>
      )}
    </div>
  );
}
