import React from 'react';
import { api, fileUrl } from '../api.js';
import Icon from '../components/Icon.jsx';
import { Button, Empty, StatusBadge, fmtDuration, useDialog, useToast } from '../components/kit.jsx';
import JobCard from '../components/editor/JobCard.jsx';
import MusicPanel from '../components/editor/MusicPanel.jsx';
import Player from '../components/editor/Player.jsx';
import SettingsPanel from '../components/editor/SettingsPanel.jsx';
import Storyboard from '../components/editor/Storyboard.jsx';
import SummaryCard from '../components/editor/SummaryCard.jsx';
import { isActive, sceneState, totalSeconds } from '../components/editor/shared.js';
import { useT } from '../i18n.jsx';

const EDIT_EXAMPLES = ['editor.ex1', 'editor.ex2', 'editor.ex3', 'editor.ex4'];

function Stepper({ steps }) {
  const current = steps.findIndex((s) => !s.done);
  return (
    <div className="stepper">
      {steps.map((s, i) => (
        <div key={s.label} className={`step${s.done ? ' done' : ''}${i === current ? ' current' : ''}`}>
          <span className="num">{s.done ? <Icon name="check" size={14} strokeWidth={3} /> : i + 1}</span>
          <span style={{ whiteSpace: 'nowrap' }}>{s.label}</span>
          <span className="line" />
        </div>
      ))}
    </div>
  );
}

function NextStep({ project, clipsReady, onTab, onPlan, onRender, onResume, onPreview, previewBusy }) {
  const t = useT();
  const total = project.scenes.length;
  const o = project.options;
  const hasFinal = project.files.includes('final.mp4');
  let icon = 'sparkles';
  let title;
  let text;
  let actions;
  if (!project.profile_id) {
    icon = 'server';
    title = t('next.pickProfileTitle');
    text = t('next.pickProfileText');
    actions = <Button className="primary" icon="sliders" onClick={() => onTab('settings')}>{t('next.openSettings')}</Button>;
  } else if (!total) {
    title = t('next.planTitle');
    text = t('next.planText');
    actions = <Button className="primary" icon="sparkles" onClick={onPlan}>{t('next.planCta')}</Button>;
  } else if (clipsReady === 0) {
    icon = 'play';
    title = t('next.renderTitle');
    text = t('next.renderText', { total, duration: fmtDuration(totalSeconds(project.scenes), t) });
    actions = <Button className="primary" icon="play" onClick={onRender}>{t('next.renderCta')}</Button>;
  } else if (clipsReady < total) {
    icon = 'play';
    title = t('next.partialTitle', { ready: clipsReady, total });
    text = t('next.partialText');
    actions = (
      <>
        <Button className="primary" icon="play" onClick={onResume}>{t('next.resumeCta')}</Button>
        <Button icon="eye" loading={previewBusy} onClick={onPreview}>{previewBusy ? t('next.previewBusy') : t('next.previewCta')}</Button>
      </>
    );
  } else if (!hasFinal) {
    icon = 'layers';
    title = t('next.allClipsTitle');
    text = t('next.allClipsText');
    actions = <Button className="primary" icon="layers" onClick={onResume}>{t('next.composeCta')}</Button>;
  } else if (o.music_mode === 'external' && !o.music_file) {
    icon = 'music';
    title = t('next.musicTitle');
    text = t('next.musicText');
    actions = <Button className="primary" icon="music" onClick={() => onTab('music')}>{t('next.openMusic')}</Button>;
  } else {
    icon = 'check';
    title = t('next.doneTitle');
    text = t('next.doneText');
    actions = <a className="btn primary" href={fileUrl(project.id, 'final.mp4', project.updated_at)} download><Icon name="download" /> {t('next.download')}</a>;
  }
  return (
    <div className="card next-cta">
      <h3><Icon name={icon} /> {title}</h3>
      <p>{text}</p>
      <div className="row">{actions}</div>
    </div>
  );
}

export default function ProjectEditor({ projectId }) {
  const t = useT();
  const toast = useToast();
  const dialog = useDialog();
  const [project, setProject] = React.useState(null);
  const [loadError, setLoadError] = React.useState('');
  const [profiles, setProfiles] = React.useState([]);
  const [presets, setPresets] = React.useState([]);
  const [scenes, setScenes] = React.useState([]);
  const [dirty, setDirty] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [tab, setTab] = React.useState('storyboard');
  const [selected, setSelected] = React.useState(null);
  const [source, setSource] = React.useState(null);
  const [title, setTitle] = React.useState('');
  const [instruction, setInstruction] = React.useState('');

  const dirtyRef = React.useRef(dirty);
  dirtyRef.current = dirty;
  const apply = React.useCallback((data) => {
    setProject(data);
    if (!dirtyRef.current) setScenes(data.scenes.map((s) => ({ ...s })));
  }, []);
  const load = React.useCallback(() => api.get(`/projects/${projectId}`).then(apply)
    .catch((e) => setLoadError(e.message)), [projectId, apply]);

  React.useEffect(() => {
    load();
    api.get('/profiles').then(setProfiles).catch(() => {});
    api.get('/presets').then(setPresets).catch(() => {});
  }, [load]);
  React.useEffect(() => { if (project) setTitle(project.title); }, [project?.title]); // eslint-disable-line react-hooks/exhaustive-deps

  const active = project?.active_job;
  const previewJob = project?.preview_job;
  const previewBusy = isActive(previewJob);
  // Always poll: fast while a job runs, slow otherwise so jobs started elsewhere show up.
  React.useEffect(() => {
    const timer = setInterval(() => { if (!document.hidden) load(); }, active || previewBusy ? 3000 : 15000);
    return () => clearInterval(timer);
  }, [active?.id, previewBusy, load]); // eslint-disable-line react-hooks/exhaustive-deps

  // "Render sementara" finished (or failed) → show it / say why.
  const prevPreview = React.useRef(null);
  React.useEffect(() => {
    const prev = prevPreview.current;
    if (prev && previewJob && prev.id === previewJob.id && isActive(prev) && !isActive(previewJob)) {
      if (previewJob.status === 'succeeded') {
        setSource('preview');
        toast(t('editor.previewReady', { n: (previewJob.result?.scenes_used || []).length }), 'ok');
      } else if (previewJob.status === 'failed') {
        toast(t('editor.previewFailed', { msg: previewJob.message }), 'bad');
      }
    }
    prevPreview.current = previewJob || null;
  }, [previewJob?.id, previewJob?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  // Final video appeared → show it.
  const hasFinal = project?.files.includes('final.mp4');
  const prevFinal = React.useRef(hasFinal);
  React.useEffect(() => {
    if (hasFinal && prevFinal.current === false) { setSource('final'); toast(t('editor.finalReady'), 'ok'); }
    prevFinal.current = hasFinal;
  }, [hasFinal, toast]);

  // Unsaved storyboard: warn before leaving, Ctrl/Cmd+S to save.
  const saveRef = React.useRef(null);
  React.useEffect(() => {
    const onBeforeUnload = (e) => { if (dirtyRef.current) { e.preventDefault(); e.returnValue = ''; } };
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's' && dirtyRef.current) { e.preventDefault(); saveRef.current?.(); }
    };
    window.addEventListener('beforeunload', onBeforeUnload);
    window.addEventListener('keydown', onKey);
    return () => { window.removeEventListener('beforeunload', onBeforeUnload); window.removeEventListener('keydown', onKey); };
  }, []);

  if (!project) {
    return loadError
      ? <div className="card"><Empty icon="alert" title={t('editor.loadError')}>{loadError}<a href="#/projects">{t('editor.backToProjects')}</a></Empty></div>
      : <Empty icon="loader" title={t('editor.loadingProject')} />;
  }

  const busy = isActive(active);
  const lastJob = active || project.jobs[0];
  const clipsReady = project.clips_ready ?? project.scenes.filter((s) => sceneState(s) === 'done').length;
  const o = project.options;

  async function run(fn, okMessage) {
    try {
      const result = await fn();
      if (okMessage) toast(okMessage, 'ok');
      await load();
      return result;
    } catch (err) {
      toast(err.message, 'bad');
      return null;
    }
  }

  const setOption = (key, value) => setProject((p) => ({ ...p, options: { ...p.options, [key]: value } }));

  function saveTitle() {
    if (title.trim() === project.title) return;
    run(() => api.patch(`/projects/${projectId}`, { title: title.trim() }), t('editor.titleSaved'));
  }

  async function saveScenes() {
    const bad = scenes.findIndex((s) => !s.visual_prompt.trim() || !(Number(s.duration) >= 1 && Number(s.duration) <= 30));
    if (bad >= 0) {
      setSelected(bad);
      toast(t('editor.sceneInvalid', { n: bad + 1 }), 'bad');
      return;
    }
    // The server matches scenes by position: a changed visual/duration at an index throws away that clip.
    const old = project.scenes;
    const lost = old.filter((s, i) => sceneState(s) === 'done' && (!scenes[i]
      || scenes[i].visual_prompt !== s.visual_prompt || Math.abs(Number(scenes[i].duration) - Number(s.duration)) > 0.01
      || Boolean(scenes[i].continues && i > 0) !== Boolean(s.continues))).length;
    if (lost && !(await dialog.confirm({
      title: t('editor.saveStoryboardTitle'),
      body: <>{t('editor.saveStoryboardBody', { n: lost })}</>,
      confirmLabel: t('editor.saveStoryboardConfirm'),
    }))) return;
    setSaving(true);
    const body = { scenes: scenes.map((s, i) => ({ visual_prompt: s.visual_prompt, narration: s.narration || '',
      duration: Number(s.duration), continues: i > 0 && Boolean(s.continues) })) };
    const result = await run(() => api.put(`/projects/${projectId}/scenes`, body));
    setSaving(false);
    if (result) {
      setDirty(false);
      setScenes(result.scenes.map((s) => ({ ...s })));
      toast(t('editor.storyboardSaved', { n: result.diff.changed_visual.length }), 'ok');
    }
  }
  saveRef.current = saveScenes;

  function startPreview() {
    return run(() => api.post(`/projects/${projectId}/preview`),
      busy ? t('editor.previewStartedBusy') : t('editor.previewStarted'));
  }

  function resetScenes() {
    setDirty(false);
    setScenes(project.scenes.map((s) => ({ ...s })));
  }

  function musicWarning() {
    if (o.music_mode !== 'external' || o.music_file) return null;
    return o.music_style === 'song' ? t('editor.musicWarningSong') : t('editor.musicWarningNone');
  }

  async function startRender(resume) {
    if (dirty) { toast(t('editor.saveFirst'), 'bad'); return; }
    let estimate;
    try {
      ({ estimate } = await api.post(`/projects/${projectId}/render`, {}));
    } catch (e) { toast(e.message, 'bad'); return; }
    const warn = musicWarning();
    const first = estimate.pending_idx?.[0];
    const ok = await dialog.confirm({
      title: resume ? t('editor.resumeRenderTitle') : t('editor.startRenderTitle'),
      body: (
        <>
          <div className="stats">
            <div className="stat"><b>{estimate.clips_to_generate}</b><span>{t('editor.newClips')}</span></div>
            <div className="stat"><b>{estimate.scenes - estimate.clips_to_generate}</b><span>{t('editor.reusedClips')}</span></div>
            <div className="stat"><b>{fmtDuration(estimate.total_seconds, t)}</b><span>{t('editor.videoDuration')}</span></div>
          </div>
          {estimate.clips_to_generate
            ? <>{t('editor.startFromScene', { n: first + 1 })}</>
            : t('editor.allClipsExist')}
          {warn && <div className="alert warn" style={{ marginTop: 12 }}><Icon name="alert" /><div>{warn}</div></div>}
        </>
      ),
      confirmLabel: estimate.clips_to_generate ? t('editor.renderNClips', { n: estimate.clips_to_generate }) : t('editor.composeBtn'),
    });
    if (!ok) return;
    await run(() => api.post(`/projects/${projectId}/render`, { confirm: true }), resume ? t('editor.renderResumed') : t('editor.renderStarted'));
  }

  async function plan() {
    if (project.scenes.length && !(await dialog.confirm({
      title: t('editor.replanTitle'),
      body: t('editor.replanBody'),
      confirmLabel: t('editor.replanConfirm'),
    }))) return;
    await run(() => api.post(`/projects/${projectId}/plan`), t('editor.planStarted'));
  }

  async function regenerate(i) {
    if (!(await dialog.confirm({
      title: t('editor.regenTitle', { n: i + 1 }),
      body: t('editor.regenBody'),
      confirmLabel: t('editor.regenConfirm'),
    }))) return;
    await run(() => api.post(`/projects/${projectId}/scenes/${i}/regenerate`), t('editor.regenStarted', { n: i + 1 }));
  }

  async function removeProject() {
    if (!(await dialog.confirm({
      title: t('editor.deleteTitle'), danger: true, confirmLabel: t('editor.deleteConfirm'),
      body: <>{t('editor.deleteBody', { name: project.title || `#${project.id}` })}</>,
    }))) return;
    const ok = await run(() => api.del(`/projects/${projectId}`));
    if (ok) { toast(t('editor.projectDeleted'), 'ok'); window.location.hash = '/projects'; }
  }

  const selectScene = (i) => {
    setSelected(i);
    if (i != null) { setSource('scene'); setTab('storyboard'); }
  };

  const steps = [
    { label: t('step.idea'), done: Boolean(project.prompt.trim()) },
    { label: t('step.storyboard'), done: project.scenes.length > 0 },
    { label: t('step.renderClips'), done: project.scenes.length > 0 && clipsReady === project.scenes.length },
    { label: t('step.music'), done: project.scenes.length > 0 && (o.music_mode === 'none' || Boolean(o.music_file)) },
    { label: t('step.finalVideo'), done: hasFinal },
  ];
  const failedScenes = project.scenes.filter((s) => sceneState(s) === 'failed').length;
  const tabs = [
    ['storyboard', 'layers', t('editor.tabStoryboard'), project.scenes.length ? <span className="count">{project.scenes.length}</span> : null, failedScenes > 0],
    ['music', 'music', t('editor.tabMusic'), null, o.music_mode === 'external' && !o.music_file],
    ['edit', 'wand', t('editor.tabEdit'), null, false],
    ['settings', 'sliders', t('editor.tabSettings'), null, !project.profile_id],
  ];

  return (
    <>
      <a className="crumb" href="#/projects"><Icon name="left" size={14} /> {t('editor.allProjects')}</a>
      <div className="editor-title">
        <input className="title-input" value={title} placeholder={t('editor.projectPlaceholder', { id: project.id })} aria-label={t('editor.projectTitle')}
          onChange={(e) => setTitle(e.target.value)} onBlur={saveTitle}
          onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur(); }} />
        <StatusBadge status={busy ? 'rendering' : project.status} label={busy ? t('status.running') : undefined} />
      </div>
      <Stepper steps={steps} />

      <div className="editor">
        <div className="editor-side">
          {lastJob && (busy || ['failed', 'canceled'].includes(lastJob.status)) && (
            <JobCard job={lastJob} scenes={project.scenes} onSelectScene={selectScene}
              onCancel={async () => {
                if (await dialog.confirm({ title: t('editor.cancelJobTitle'), body: t('editor.cancelJobBody'), confirmLabel: t('editor.cancelJobConfirm'), danger: true })) {
                  run(() => api.post(`/jobs/${lastJob.id}/cancel`), t('editor.jobCanceled'));
                }
              }}
              onResume={() => startRender(true)}
              onPreview={clipsReady > 0 ? startPreview : null} previewJob={previewJob} />
          )}
          <Player project={project} source={source} setSource={setSource} selected={selected} />
          {!busy && (
            <NextStep project={project} clipsReady={clipsReady} onTab={setTab} onPlan={plan}
              onRender={() => startRender(false)} onResume={() => startRender(true)}
              onPreview={startPreview} previewBusy={previewBusy} />
          )}
          {!busy && hasFinal && <SummaryCard project={project} onSelectScene={selectScene} />}
          {lastJob && !busy && lastJob.status === 'succeeded' && (
            <div className="faint small row" style={{ padding: '0 4px' }}>
              <Icon name="check" size={13} /> {t('editor.lastJob', { msg: lastJob.message || t(`job.kind.${lastJob.kind}`) })}
            </div>
          )}
        </div>

        <div className="editor-main card">
          <div className="tabs" role="tablist">
            {tabs.map(([id, icon, label, extra, flag]) => (
              <button key={id} role="tab" aria-selected={tab === id} className={tab === id ? 'active' : ''} onClick={() => setTab(id)}>
                <Icon name={icon} /> {label} {extra} {flag && <span className="dot-warn" />}
              </button>
            ))}
          </div>

          {tab === 'storyboard' && (
            <Storyboard project={project} scenes={scenes} setScenes={setScenes} dirty={dirty} setDirty={setDirty}
              busy={busy} selected={selected} onSelect={selectScene} onSave={saveScenes} onReset={resetScenes}
              onRegenerate={regenerate} onPlan={plan} saving={saving} run={run} />
          )}
          {tab === 'music' && (
            <MusicPanel project={project} busy={busy} clipsReady={clipsReady} run={run} setOption={setOption} toast={toast} />
          )}
          {tab === 'edit' && (
            <div className="stack">
              <p className="muted" style={{ margin: 0 }}>
                {t('editor.editIntro')}
              </p>
              <textarea rows={4} value={instruction} placeholder={t('editor.editPlaceholder')}
                onChange={(e) => setInstruction(e.target.value)} />
              <div className="examples">
                {EDIT_EXAMPLES.map((ex) => <button key={ex} type="button" className="example" onClick={() => setInstruction(t(ex))}>{t(ex)}</button>)}
              </div>
              <div className="row">
                <Button className="primary" icon="send" disabled={busy || !project.scenes.length || instruction.trim().length < 3}
                  onClick={() => run(() => api.post(`/projects/${projectId}/edit`, { instruction }), t('editor.editStarted')).then((r) => r && setInstruction(''))}>
                  {t('editor.applyEdit')}
                </Button>
                {!project.scenes.length && <span className="faint small">{t('editor.planFirst')}</span>}
                {busy && <span className="faint small">{t('editor.waitJob')}</span>}
              </div>
            </div>
          )}
          {tab === 'settings' && (
            <SettingsPanel project={project} profiles={profiles} presets={presets} busy={busy} run={run} onDelete={removeProject} />
          )}
        </div>
      </div>
    </>
  );
}
