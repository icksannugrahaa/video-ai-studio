import React from 'react';
import { fileUrl } from '../../api.js';
import Icon from '../Icon.jsx';
import { api } from '../../api.js';
import { Button, Empty, StatusBadge, Switch, fmtClock, fmtDuration } from '../kit.jsx';
import { SCENE_LABEL, sceneState, totalSeconds } from './shared.js';

const STATE_TONE = { done: 'done', stale: 'stale', running: 'running', failed: 'failed', pending: 'pending' };
const LEGEND = [['var(--ok)', 'Jadi'], ['var(--info)', 'Dibuat'], ['var(--bad)', 'Gagal'], ['var(--warn)', 'Perlu ulang'], ['var(--surface-3)', 'Belum']];

function Timeline({ scenes, selected, onSelect }) {
  return (
    <>
      <div className="timeline" role="tablist" aria-label="Timeline scene">
        {scenes.map((s, i) => {
          const state = sceneState(s);
          return (
            <button key={s.id || `new-${i}`} role="tab" aria-selected={selected === i}
              className={`tl-block ${STATE_TONE[state]}${selected === i ? ' selected' : ''}${s.continues && i > 0 ? ' cont' : ''}`}
              style={{ flex: `${Math.max(1, Number(s.duration) || 1)} 1 0` }}
              title={`Scene ${i + 1} · ${s.duration} dtk · ${SCENE_LABEL[state]}${s.continues && i > 0 ? ' · lanjutan scene sebelumnya' : ''}`}
              onClick={() => onSelect(i)}>{i + 1}</button>
          );
        })}
      </div>
      <div className="legend">
        {LEGEND.map(([color, label]) => <span key={label}><i style={{ background: color }} />{label}</span>)}
      </div>
    </>
  );
}

const BIBLE_FIELDS = [
  ['bible_character', 'Karakter utama', 'Ciri fisik yang dikunci: bentuk tubuh, warna & pola bulu, mata, aksesori dan posisinya.', 4],
  ['bible_world', 'Dunia / lokasi', 'Satu kota/wilayah untuk seluruh cerita: arsitektur, kendaraan, papan nama, iklim.', 3],
  ['bible_style', 'Gaya visual', 'Satu kalimat gaya render. Jangan sebut nama studio/franchise.', 2],
];

function BibleCard({ project, busy, run }) {
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
    await run(() => api.patch(`/projects/${project.id}`, { options: form }), 'Karakter & dunia tersimpan.');
    setSaving(false);
  }

  return (
    <div className="card flat" style={{ marginBottom: 14, padding: 14 }}>
      <div className="row between" style={{ cursor: 'pointer' }} onClick={() => setOpen(!open)}>
        <div className="row" style={{ gap: 10 }}>
          <Icon name="chevron" className={`chev${open ? ' open' : ''}`} />
          <div>
            <b>Karakter & dunia</b>
            <div className="faint small">
              {empty ? 'Belum ada — susun ulang storyboard dengan AI untuk membuatnya otomatis.'
                : 'Ditempel persis sama ke prompt setiap clip supaya karakter & lokasi konsisten.'}
            </div>
          </div>
        </div>
        {!open && !empty && <span className="badge ok"><span className="dot" />Aktif</span>}
      </div>
      {open && (
        <div className="stack" style={{ marginTop: 14 }}>
          {BIBLE_FIELDS.map(([key, label, hint, rows]) => (
            <label key={key} className="field"><span>{label} <span className="hint">— {hint}</span></span>
              <textarea rows={rows} value={form[key]} onChange={(e) => setForm({ ...form, [key]: e.target.value })} />
            </label>
          ))}
          <div className="row">
            <Button className="primary sm" icon="check" loading={saving} disabled={!changed} onClick={save}>Simpan</Button>
            {changed && <button className="btn ghost sm" onClick={() => setForm(saved)}>Buang</button>}
            <span className="faint small">Berlaku untuk clip yang dibuat (ulang) setelah disimpan{busy ? ', termasuk sisa clip render yang sedang berjalan' : ''}.</span>
          </div>
        </div>
      )}
    </div>
  );
}

function SceneCard({ scene, index, count, start, project, open, selected, busy, dirty, onToggle, onChange, onMove, onRemove, onRegenerate }) {
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
          <div className="v ellipsis">{scene.visual_prompt || <span className="faint">(visual kosong)</span>}</div>
          <div className="n ellipsis">{scene.narration || <span className="faint">tanpa narasi</span>}</div>
        </div>
        {scene.continues && index > 0 && <span className="badge info" title="Lanjutan scene sebelumnya"><Icon name="link" size={11} /></span>}
        {state === 'done' && scene.clip_gen_seconds != null && (
          <span className="gen-time mono" title={`Clip dibuat dalam ${fmtDuration(scene.clip_gen_seconds)}${scene.clip_attempts > 1 ? ` · ${scene.clip_attempts} percobaan` : ''}`}>
            <Icon name="clock" size={11} />{fmtClock(scene.clip_gen_seconds)}{scene.clip_attempts > 1 && <span style={{ color: 'var(--warn)' }}>×{scene.clip_attempts}</span>}
          </span>
        )}
        <span className="faint small mono" style={{ flex: 'none' }}>{fmtClock(start)} · {scene.duration}s</span>
        {scene.id && <StatusBadge status={state === 'done' ? 'succeeded' : state === 'running' ? 'running' : state === 'failed' ? 'failed' : state === 'stale' ? 'stale' : 'pending'}
          label={SCENE_LABEL[state]} />}
      </div>
      {open && (
        <div className="scene-body">
          {state === 'done' && scene.clip_gen_seconds != null && (
            <div className="faint small row" style={{ gap: 6 }}>
              <Icon name="clock" size={13} /> Clip dibuat dalam <b style={{ color: 'var(--text)' }}>{fmtDuration(scene.clip_gen_seconds)}</b>
              {scene.clip_attempts > 1 && <span>· berhasil di percobaan ke-{scene.clip_attempts}</span>}
            </div>
          )}
          {scene.clip_error && state === 'failed' && (
            <div className="alert bad"><Icon name="alert" /><div>
              <strong>Clip gagal dibuat.</strong> {scene.clip_error}
              {/hak cipta|filter konten/i.test(scene.clip_error) && <div className="small muted" style={{ marginTop: 4 }}>
                Tip: ganti nama karakter/merek terkenal di prompt visual dengan deskripsi orisinal, lalu simpan & regenerate.</div>}
            </div></div>
          )}
          <label className="field"><span>Visual <span className="hint">— prompt video, sebaiknya bahasa Inggris</span></span>
            <textarea rows={3} value={scene.visual_prompt} onChange={(e) => onChange('visual_prompt', e.target.value)} />
          </label>
          <label className="field"><span>Narasi <span className="hint">— dibacakan TTS & jadi subtitle</span></span>
            <textarea rows={2} value={scene.narration || ''} onChange={(e) => onChange('narration', e.target.value)} />
          </label>
          {index > 0 && (
            <Switch checked={scene.continues} onChange={(v) => onChange('continues', v)} label="Lanjutan dari scene sebelumnya"
              hint="Tempat & momen sama — clip dimulai dari frame terakhir scene sebelumnya, tanpa crossfade. Matikan jika pindah lokasi." />
          )}
          <div className="row between">
            <label className="field" style={{ width: 150 }}>Durasi (detik)
              <input type="number" min={1} max={30} value={scene.duration} onChange={(e) => onChange('duration', e.target.value)} />
            </label>
            <div className="scene-actions">
              <button className="btn ghost icon sm" title="Pindah ke atas" disabled={busy || index === 0} onClick={() => onMove(-1)}><Icon name="up" /></button>
              <button className="btn ghost icon sm" title="Pindah ke bawah" disabled={busy || index === count - 1} onClick={() => onMove(1)}><Icon name="down" /></button>
              {scene.id && (
                <Button className="sm" icon="refresh" disabled={busy || dirty} onClick={onRegenerate}
                  title={dirty ? 'Simpan storyboard dulu' : 'Buat ulang clip scene ini'}>Regenerate</Button>
              )}
              <Button className="danger sm" icon="trash" disabled={busy} onClick={onRemove}>Hapus</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function Storyboard({ project, scenes, setScenes, dirty, setDirty, busy, selected, onSelect,
  onSave, onReset, onRegenerate, onPlan, saving, run }) {
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
      <Empty icon="layers" title="Belum ada storyboard">
        <span>AI akan memecah idemu menjadi scene: prompt visual, narasi, dan durasi tiap clip.</span>
        <Button className="primary" icon="sparkles" disabled={busy} onClick={onPlan} style={{ marginTop: 8 }}>Susun storyboard dengan AI</Button>
      </Empty>
    );
  }

  return (
    <div>
      <div className="row between" style={{ marginBottom: 12 }}>
        <div className="small muted">
          <b style={{ color: 'var(--text)' }}>{scenes.length} scene</b> · {fmtDuration(totalSeconds(scenes))}
          {failed > 0 && <span style={{ color: 'var(--bad)' }}> · {failed} gagal</span>}
          {timed.length > 0 && <span> · rata-rata {fmtClock(avgGen)}/clip</span>}
        </div>
        <div className="row">
          <button className="btn ghost sm" onClick={() => setOpen(allOpen ? new Set() : new Set(scenes.map(keyOf)))}>
            {allOpen ? 'Tutup semua' : 'Buka semua'}
          </button>
          <Button className="sm" icon="sparkles" disabled={busy} onClick={onPlan}>Susun ulang dengan AI</Button>
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
        <Button icon="plus" disabled={busy} onClick={add}>Tambah scene</Button>
        {busy && <span className="faint small">Storyboard terkunci selama job berjalan.</span>}
      </div>

      {dirty && (
        <div className="save-bar">
          <span className="row"><Icon name="edit" /> Ada perubahan storyboard yang belum disimpan <span className="kbd">⌘/Ctrl + S</span></span>
          <div className="row">
            <button className="btn ghost" onClick={onReset}>Buang</button>
            <Button className="primary" icon="check" loading={saving} disabled={busy} onClick={onSave}>Simpan storyboard</Button>
          </div>
        </div>
      )}
    </div>
  );
}
