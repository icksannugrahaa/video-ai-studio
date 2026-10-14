import React from 'react';
import { api } from '../../api.js';
import { Button, RatioIcon, Switch } from '../kit.jsx';

const LANGUAGES = [['id-ID', 'Indonesia'], ['en-US', 'English (US)'], ['en-GB', 'English (UK)'], ['ms-MY', 'Melayu'],
  ['jv-ID', 'Jawa'], ['su-ID', 'Sunda'], ['ja-JP', '日本語'], ['ko-KR', '한국어'], ['zh-CN', '中文'], ['ar-SA', 'العربية']];

const pick = (p) => ({
  prompt: p.prompt, preset: p.preset, target_seconds: p.target_seconds, language: p.language,
  profile_id: p.profile_id || '', voice: p.options.voice || '', continuity: p.options.continuity,
  burn_subtitles: p.options.burn_subtitles, keep_clip_audio: p.options.keep_clip_audio,
  transition: p.options.transition ?? 0.5,
});

export default function SettingsPanel({ project, profiles, presets, busy, run, onDelete }) {
  const [form, setForm] = React.useState(() => pick(project));
  const [saving, setSaving] = React.useState(false);
  const saved = pick(project);
  const changed = Object.keys(form).some((k) => String(form[k]) !== String(saved[k]));
  const set = (k) => (v) => setForm((f) => ({ ...f, [k]: v }));
  const profile = profiles.find((p) => String(p.id) === String(form.profile_id));

  async function save() {
    setSaving(true);
    const result = await run(() => api.patch(`/projects/${project.id}`, {
      prompt: form.prompt, preset: form.preset, language: form.language, target_seconds: Number(form.target_seconds),
      profile_id: form.profile_id ? Number(form.profile_id) : null,
      options: { continuity: form.continuity, burn_subtitles: form.burn_subtitles, keep_clip_audio: form.keep_clip_audio,
        voice: form.voice, transition: Number(form.transition) },
    }), 'Pengaturan tersimpan.');
    if (result) setForm(pick(result));
    setSaving(false);
  }

  return (
    <div className="stack" style={{ gap: 20 }}>
      <label className="field"><span>Ide / prompt video <span className="hint">— dipakai AI saat menyusun (ulang) storyboard</span></span>
        <textarea rows={3} value={form.prompt} onChange={(e) => set('prompt')(e.target.value)} />
      </label>

      <div>
        <div className="opt-label">Platform</div>
        <div className="chips">
          {presets.map((p) => (
            <button type="button" key={p.id} className={`chip${form.preset === p.id ? ' active' : ''}`} onClick={() => set('preset')(p.id)}>
              <RatioIcon aspect={p.aspect} /> {p.label}
            </button>
          ))}
        </div>
      </div>

      <div className="grid">
        <label className="field">Target durasi (detik)
          <input type="number" min={5} max={3600} value={form.target_seconds} onChange={(e) => set('target_seconds')(e.target.value)} />
        </label>
        <label className="field">Bahasa narasi
          <input list="sav-langs" value={form.language} onChange={(e) => set('language')(e.target.value)} />
          <datalist id="sav-langs">{LANGUAGES.map(([code, label]) => <option key={code} value={code}>{label}</option>)}</datalist>
        </label>
        <label className="field">Profil provider
          <select value={form.profile_id} onChange={(e) => set('profile_id')(e.target.value)}>
            <option value="">— pilih profil —</option>
            {profiles.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          {!profiles.length && <span className="hint"><a href="#/settings">Buat profil dulu →</a></span>}
        </label>
        <label className="field">Voice TTS
          <input value={form.voice} placeholder={profile?.tts_voice ? `default: ${profile.tts_voice}` : 'default profil'}
            onChange={(e) => set('voice')(e.target.value)} />
        </label>
      </div>

      <div>
        <div className="opt-label">Transisi antar scene</div>
        <div className="chips">
          {[[0, 'Potong langsung'], [0.5, 'Crossfade halus · 0,5 dtk'], [1, 'Crossfade lambat · 1 dtk']].map(([v, label]) => (
            <button type="button" key={v} className={`chip${Number(form.transition) === v ? ' active' : ''}`} onClick={() => set('transition')(v)}>{label}</button>
          ))}
        </div>
        <p className="faint small" style={{ margin: '8px 0 0' }}>Scene yang ditandai “lanjutan” selalu menyambung tanpa crossfade. Cukup “Gabung ulang video” untuk menerapkan — clip tidak dibuat ulang.</p>
      </div>

      <div className="stack tight">
        <Switch checked={form.continuity} onChange={set('continuity')} label="Kontinuitas antar scene"
          hint="Scene bertanda “lanjutan” dimulai dari frame terakhir scene sebelumnya — gerak & latar menyambung." />
        <Switch checked={form.burn_subtitles} onChange={set('burn_subtitles')} label="Tempel subtitle ke video"
          hint="Subtitle ikut terbakar di video. File SRT tetap tersedia untuk diunduh." />
        <Switch checked={form.keep_clip_audio} onChange={set('keep_clip_audio')} label="Pakai audio bawaan clip"
          hint="Jika model video menghasilkan suara, ikut dicampur." />
      </div>

      <div className="row">
        <Button className="primary" icon="check" loading={saving} disabled={!changed || busy} onClick={save}>Simpan pengaturan</Button>
        {changed && <button className="btn ghost" onClick={() => setForm(pick(project))}>Buang perubahan</button>}
        {busy && <span className="faint small">Bisa disimpan setelah job selesai.</span>}
      </div>

      <hr style={{ border: 0, borderTop: '1px solid var(--line)', width: '100%', margin: '4px 0' }} />
      <div className="row between">
        <div className="small"><b>Hapus project</b><div className="muted">Semua clip, narasi, dan video ikut terhapus permanen.</div></div>
        <Button className="danger" icon="trash" disabled={busy} onClick={onDelete}>Hapus project</Button>
      </div>
    </div>
  );
}
