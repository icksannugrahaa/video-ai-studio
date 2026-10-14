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

const EDIT_EXAMPLES = ['Ganti scene 2 jadi malam hari', 'Narasi lebih santai dan lucu', 'Tambah scene penutup ajakan follow', 'Perpendek jadi 30 detik'];

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
  const total = project.scenes.length;
  const o = project.options;
  const hasFinal = project.files.includes('final.mp4');
  let icon = 'sparkles';
  let title;
  let text;
  let actions;
  if (!project.profile_id) {
    icon = 'server';
    title = 'Pilih profil provider';
    text = 'Profil menentukan endpoint AI dan model chat/video/TTS yang dipakai.';
    actions = <Button className="primary" icon="sliders" onClick={() => onTab('settings')}>Buka pengaturan</Button>;
  } else if (!total) {
    title = 'Susun storyboard';
    text = 'AI memecah idemu menjadi scene. Kamu bisa mengedit semuanya sebelum render.';
    actions = <Button className="primary" icon="sparkles" onClick={onPlan}>Susun dengan AI</Button>;
  } else if (clipsReady === 0) {
    icon = 'play';
    title = 'Periksa storyboard, lalu render';
    text = `${total} scene · ${fmtDuration(totalSeconds(project.scenes))}. Render memakai kredit provider video.`;
    actions = <Button className="primary" icon="play" onClick={onRender}>Render video</Button>;
  } else if (clipsReady < total) {
    icon = 'play';
    title = `${clipsReady}/${total} clip sudah jadi`;
    text = 'Lanjutkan untuk membuat sisanya — clip yang sudah jadi tidak dibuat ulang.';
    actions = (
      <>
        <Button className="primary" icon="play" onClick={onResume}>Lanjutkan render</Button>
        <Button icon="eye" loading={previewBusy} onClick={onPreview}>{previewBusy ? 'Membuat render sementara…' : 'Render sementara'}</Button>
      </>
    );
  } else if (!hasFinal) {
    icon = 'layers';
    title = 'Semua clip siap';
    text = 'Tinggal narasi, subtitle, dan penggabungan menjadi satu video.';
    actions = <Button className="primary" icon="layers" onClick={onResume}>Gabungkan jadi video final</Button>;
  } else if (o.music_mode === 'external' && !o.music_file) {
    icon = 'music';
    title = 'Video jadi — tambahkan musik?';
    text = 'Buat musiknya di Gemini dari prompt yang sudah disiapkan, upload, lalu gabung ulang.';
    actions = <Button className="primary" icon="music" onClick={() => onTab('music')}>Buka musik</Button>;
  } else {
    icon = 'check';
    title = 'Video siap diunggah 🎉';
    text = 'Ubah scene, musik, atau subtitle kapan saja — hanya bagian yang berubah yang diproses ulang.';
    actions = <a className="btn primary" href={fileUrl(project.id, 'final.mp4', project.updated_at)} download><Icon name="download" /> Unduh MP4</a>;
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
        toast(`Render sementara siap · ${(previewJob.result?.scenes_used || []).length} scene`, 'ok');
      } else if (previewJob.status === 'failed') {
        toast(`Render sementara gagal: ${previewJob.message}`, 'bad');
      }
    }
    prevPreview.current = previewJob || null;
  }, [previewJob?.id, previewJob?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  // Final video appeared → show it.
  const hasFinal = project?.files.includes('final.mp4');
  const prevFinal = React.useRef(hasFinal);
  React.useEffect(() => {
    if (hasFinal && prevFinal.current === false) { setSource('final'); toast('Video final selesai dibuat!', 'ok'); }
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
      ? <div className="card"><Empty icon="alert" title="Project tidak bisa dibuka">{loadError}<a href="#/projects">← Kembali ke project</a></Empty></div>
      : <Empty icon="loader" title="Memuat project…" />;
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
    run(() => api.patch(`/projects/${projectId}`, { title: title.trim() }), 'Judul tersimpan.');
  }

  async function saveScenes() {
    const bad = scenes.findIndex((s) => !s.visual_prompt.trim() || !(Number(s.duration) >= 1 && Number(s.duration) <= 30));
    if (bad >= 0) {
      setSelected(bad);
      toast(`Scene ${bad + 1}: prompt visual wajib diisi dan durasi 1–30 detik.`, 'bad');
      return;
    }
    // The server matches scenes by position: a changed visual/duration at an index throws away that clip.
    const old = project.scenes;
    const lost = old.filter((s, i) => sceneState(s) === 'done' && (!scenes[i]
      || scenes[i].visual_prompt !== s.visual_prompt || Math.abs(Number(scenes[i].duration) - Number(s.duration)) > 0.01
      || Boolean(scenes[i].continues && i > 0) !== Boolean(s.continues))).length;
    if (lost && !(await dialog.confirm({
      title: 'Simpan storyboard?',
      body: <><strong>{lost} clip yang sudah jadi</strong> akan dibuat ulang saat render berikutnya, karena visual/durasi/urutan/sambungan scene-nya berubah. Ini memakai kredit provider.</>,
      confirmLabel: 'Simpan',
    }))) return;
    setSaving(true);
    const body = { scenes: scenes.map((s, i) => ({ visual_prompt: s.visual_prompt, narration: s.narration || '',
      duration: Number(s.duration), continues: i > 0 && Boolean(s.continues) })) };
    const result = await run(() => api.put(`/projects/${projectId}/scenes`, body));
    setSaving(false);
    if (result) {
      setDirty(false);
      setScenes(result.scenes.map((s) => ({ ...s })));
      toast(`Storyboard tersimpan · ${result.diff.changed_visual.length} scene perlu clip baru.`, 'ok');
    }
  }
  saveRef.current = saveScenes;

  function startPreview() {
    return run(() => api.post(`/projects/${projectId}/preview`),
      busy ? 'Render sementara dibuat di samping render utama…' : 'Membuat render sementara dari clip yang sudah jadi…');
  }

  function resetScenes() {
    setDirty(false);
    setScenes(project.scenes.map((s) => ({ ...s })));
  }

  function musicWarning() {
    if (o.music_mode !== 'external' || o.music_file) return null;
    return o.music_style === 'song'
      ? 'Mode lagu tapi file lagu belum diunggah — video akan tanpa suara karena narasi tidak dipakai. Upload lagunya nanti lalu “Gabung ulang video”.'
      : 'Musik belum diunggah — video dibuat tanpa musik. Bisa ditambahkan nanti lewat “Gabung ulang” tanpa membuat ulang clip.';
  }

  async function startRender(resume) {
    if (dirty) { toast('Simpan perubahan storyboard dulu.', 'bad'); return; }
    let estimate;
    try {
      ({ estimate } = await api.post(`/projects/${projectId}/render`, {}));
    } catch (e) { toast(e.message, 'bad'); return; }
    const warn = musicWarning();
    const first = estimate.pending_idx?.[0];
    const ok = await dialog.confirm({
      title: resume ? 'Lanjutkan render?' : 'Mulai render?',
      body: (
        <>
          <div className="stats">
            <div className="stat"><b>{estimate.clips_to_generate}</b><span>clip baru</span></div>
            <div className="stat"><b>{estimate.scenes - estimate.clips_to_generate}</b><span>clip dipakai ulang</span></div>
            <div className="stat"><b>{fmtDuration(estimate.total_seconds)}</b><span>durasi video</span></div>
          </div>
          {estimate.clips_to_generate
            ? <>Mulai dari <strong>scene {first + 1}</strong>. Membuat clip memakai kredit provider video.</>
            : 'Semua clip sudah ada — hanya narasi, subtitle, dan penggabungan yang diproses.'}
          {warn && <div className="alert warn" style={{ marginTop: 12 }}><Icon name="alert" /><div>{warn}</div></div>}
        </>
      ),
      confirmLabel: estimate.clips_to_generate ? `Render ${estimate.clips_to_generate} clip` : 'Gabungkan',
    });
    if (!ok) return;
    await run(() => api.post(`/projects/${projectId}/render`, { confirm: true }), resume ? 'Render dilanjutkan.' : 'Render dimulai.');
  }

  async function plan() {
    if (project.scenes.length && !(await dialog.confirm({
      title: 'Susun ulang storyboard?',
      body: 'AI akan menulis storyboard baru dari ide/prompt. Scene yang visualnya berubah perlu clip baru saat render.',
      confirmLabel: 'Susun ulang',
    }))) return;
    await run(() => api.post(`/projects/${projectId}/plan`), 'AI sedang menyusun storyboard…');
  }

  async function regenerate(i) {
    if (!(await dialog.confirm({
      title: `Regenerate scene ${i + 1}?`,
      body: 'Clip scene ini dibuat ulang dengan prompt yang sama (hasil bisa berbeda). Memakai kredit provider.',
      confirmLabel: 'Regenerate',
    }))) return;
    await run(() => api.post(`/projects/${projectId}/scenes/${i}/regenerate`), `Regenerate scene ${i + 1} dimulai.`);
  }

  async function removeProject() {
    if (!(await dialog.confirm({
      title: 'Hapus project?', danger: true, confirmLabel: 'Hapus permanen',
      body: <>Project <strong>{project.title || `#${project.id}`}</strong> beserta semua clip dan videonya akan dihapus. Tidak bisa dibatalkan.</>,
    }))) return;
    const ok = await run(() => api.del(`/projects/${projectId}`));
    if (ok) { toast('Project dihapus.', 'ok'); window.location.hash = '/projects'; }
  }

  const selectScene = (i) => {
    setSelected(i);
    if (i != null) { setSource('scene'); setTab('storyboard'); }
  };

  const steps = [
    { label: 'Ide', done: Boolean(project.prompt.trim()) },
    { label: 'Storyboard', done: project.scenes.length > 0 },
    { label: 'Render clip', done: project.scenes.length > 0 && clipsReady === project.scenes.length },
    { label: 'Musik', done: project.scenes.length > 0 && (o.music_mode === 'none' || Boolean(o.music_file)) },
    { label: 'Video final', done: hasFinal },
  ];
  const failedScenes = project.scenes.filter((s) => sceneState(s) === 'failed').length;
  const tabs = [
    ['storyboard', 'layers', 'Storyboard', project.scenes.length ? <span className="count">{project.scenes.length}</span> : null, failedScenes > 0],
    ['music', 'music', 'Musik', null, o.music_mode === 'external' && !o.music_file],
    ['edit', 'wand', 'Edit dengan AI', null, false],
    ['settings', 'sliders', 'Pengaturan', null, !project.profile_id],
  ];

  return (
    <>
      <a className="crumb" href="#/projects"><Icon name="left" size={14} /> Semua project</a>
      <div className="editor-title">
        <input className="title-input" value={title} placeholder={`Project #${project.id}`} aria-label="Judul project"
          onChange={(e) => setTitle(e.target.value)} onBlur={saveTitle}
          onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur(); }} />
        <StatusBadge status={busy ? 'rendering' : project.status} label={busy ? 'Memproses' : undefined} />
      </div>
      <Stepper steps={steps} />

      <div className="editor">
        <div className="editor-side">
          {lastJob && (busy || ['failed', 'canceled'].includes(lastJob.status)) && (
            <JobCard job={lastJob} scenes={project.scenes} onSelectScene={selectScene}
              onCancel={async () => {
                if (await dialog.confirm({ title: 'Batalkan job?', body: 'Clip yang sudah jadi tetap tersimpan — bisa dilanjutkan nanti.', confirmLabel: 'Batalkan job', danger: true })) {
                  run(() => api.post(`/jobs/${lastJob.id}/cancel`), 'Job dibatalkan.');
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
              <Icon name="check" size={13} /> Terakhir: {lastJob.message || lastJob.kind}
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
                Tulis perubahan dengan bahasa biasa. AI mengubah storyboard, lalu hanya scene yang berubah yang dibuat ulang.
              </p>
              <textarea rows={4} value={instruction} placeholder="Mis. ganti scene 2 jadi malam hari dan narasinya lebih dramatis"
                onChange={(e) => setInstruction(e.target.value)} />
              <div className="examples">
                {EDIT_EXAMPLES.map((ex) => <button key={ex} type="button" className="example" onClick={() => setInstruction(ex)}>{ex}</button>)}
              </div>
              <div className="row">
                <Button className="primary" icon="send" disabled={busy || !project.scenes.length || instruction.trim().length < 3}
                  onClick={() => run(() => api.post(`/projects/${projectId}/edit`, { instruction }), 'Edit dimulai.').then((r) => r && setInstruction(''))}>
                  Terapkan edit
                </Button>
                {!project.scenes.length && <span className="faint small">Susun storyboard dulu.</span>}
                {busy && <span className="faint small">Tunggu job yang berjalan selesai.</span>}
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
