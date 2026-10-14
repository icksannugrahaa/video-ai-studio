import React from 'react';
import { api, fileUrl } from '../../api.js';
import Icon from '../Icon.jsx';
import { Button, CopyButton, Dropzone, fmtClock } from '../kit.jsx';
import { totalSeconds } from './shared.js';

const GEMINI_URL = 'https://gemini.google.com/app';
const MODES = [
  ['none', 'x', 'Tanpa musik', 'Hanya narasi (dan audio clip jika aktif).'],
  ['external', 'music', 'Buat di luar app', 'Prompt dari AI → generate di Gemini → upload.'],
  ['generate', 'sparkles', 'Generate otomatis', 'Segera hadir.'],
];
const STYLES = [
  ['instrumental', 'volume', 'Backsound', 'Instrumental di bawah narasi, otomatis mengecil saat ada suara.'],
  ['song', 'mic', 'Lagu berlirik', 'Lirik mengikuti scene; narasi diganti, subtitle = lirik.'],
];

function Choice({ active, icon, title, desc, disabled, onClick }) {
  return (
    <button type="button" className={`choice${active ? ' active' : ''}`} disabled={disabled} onClick={onClick}>
      <span className="ico"><Icon name={icon} /></span>
      <span><strong>{title}</strong><span>{desc}</span></span>
    </button>
  );
}

export default function MusicPanel({ project, busy, clipsReady, run, setOption, toast }) {
  const o = project.options;
  const id = project.id;
  const song = o.music_style === 'song';
  const [prompt, setPrompt] = React.useState(o.music_prompt || '');
  const [lyrics, setLyrics] = React.useState(o.lyrics || '');
  const [hint, setHint] = React.useState('');
  const [generating, setGenerating] = React.useState(false);
  const [uploading, setUploading] = React.useState(false);
  React.useEffect(() => { setPrompt(o.music_prompt || ''); }, [o.music_prompt]);
  React.useEffect(() => { setLyrics(o.lyrics || ''); }, [o.lyrics]);

  const total = Math.round(totalSeconds(project.scenes));
  const allClips = project.scenes.length > 0 && clipsReady === project.scenes.length;
  const save = (options, msg = 'Musik tersimpan.') => run(() => api.patch(`/projects/${id}`, { options }), msg);

  async function generate(path, msg) {
    setGenerating(true);
    await run(() => api.post(`/projects/${id}/${path}`, { hint }), msg);
    setGenerating(false);
  }

  async function upload(file) {
    if (file.size > 30 * 1024 * 1024) { toast('File musik maksimal 30 MB.', 'bad'); return; }
    setUploading(true);
    await run(() => api.upload(`/projects/${id}/music`, file), `Musik “${file.name}” diunggah.`);
    setUploading(false);
  }

  return (
    <div className="stack" style={{ gap: 20 }}>
      {busy && (
        <div className="alert info"><Icon name="info" /><div>
          Musik terpisah dari clip — boleh diubah atau diunggah sekarang walau render berjalan. Dipakai saat penggabungan akhir.
        </div></div>
      )}

      <div>
        <div className="opt-label">Mode musik</div>
        <div className="choices">
          {MODES.map(([value, icon, title, desc]) => (
            <Choice key={value} active={o.music_mode === value} icon={icon} title={title} desc={desc}
              disabled={value === 'generate'} onClick={() => save({ music_mode: value })} />
          ))}
        </div>
      </div>

      {o.music_mode !== 'none' && (
        <div>
          <div className="opt-label">Jenis</div>
          <div className="choices">
            {STYLES.map(([value, icon, title, desc]) => (
              <Choice key={value} active={(o.music_style || 'instrumental') === value} icon={icon} title={title} desc={desc}
                onClick={() => save({ music_style: value })} />
            ))}
          </div>
        </div>
      )}

      {o.music_mode === 'external' && (
        <div className="steps">
          {song && (
            <div className="s"><div>
              <h3>Tulis lirik yang mengikuti scene</h3>
              <p className="muted small" style={{ margin: 0 }}>
                Format tiap baris <code>[m:ss] teks</code>. Setelah dengar lagunya, geser waktunya kalau meleset lalu “Gabung ulang video”.
              </p>
              <div className="row">
                <input className="grow" style={{ minWidth: 200 }} value={hint} placeholder="Arahan lagu (mis. lagu anak ceria, vokal pria, dangdut)"
                  onChange={(e) => setHint(e.target.value)} />
                <Button className="primary" icon="sparkles" loading={generating} disabled={!project.scenes.length}
                  onClick={() => generate('song', 'Lirik & prompt lagu siap.')}>
                  {generating ? 'Menulis… (±30 dtk)' : o.lyrics ? 'Tulis ulang' : 'Buat lirik & prompt'}
                </Button>
              </div>
              <textarea rows={10} className="mono" value={lyrics} placeholder="[0:00] Baris lirik pertama…"
                onChange={(e) => setLyrics(e.target.value)} />
              {lyrics !== (o.lyrics || '') && (
                <div className="row"><Button className="sm primary" icon="check" onClick={() => save({ lyrics }, 'Lirik tersimpan.')}>Simpan lirik</Button>
                  <button className="btn ghost sm" onClick={() => setLyrics(o.lyrics || '')}>Buang</button></div>
              )}
            </div></div>
          )}

          <div className="s"><div>
            <h3>{song ? 'Salin prompt lagu ke Gemini' : 'Salin prompt musik ke Gemini'}</h3>
            <p className="muted small" style={{ margin: 0 }}>
              Minta durasi ±<b>{fmtClock(total)}</b> agar pas dengan video. Prompt dibuat AI dari storyboard — boleh diedit.
            </p>
            <textarea rows={5} value={prompt}
              placeholder={project.scenes.length ? 'Belum ada prompt — klik “Buat ulang prompt”.' : 'Susun storyboard dulu — prompt musik dibuat otomatis.'}
              onChange={(e) => setPrompt(e.target.value)} />
            <div className="row">
              <CopyButton text={prompt} label="Salin prompt" className="primary" />
              <a className="btn" href={GEMINI_URL} target="_blank" rel="noreferrer"><Icon name="external" /> Buka Gemini</a>
              {prompt !== (o.music_prompt || '') && <Button icon="check" onClick={() => save({ music_prompt: prompt }, 'Prompt tersimpan.')}>Simpan</Button>}
            </div>
            {!song && (
              <div className="row">
                <input className="grow" style={{ minWidth: 200 }} value={hint} placeholder="Arahan tambahan (mis. lebih ceria, gaya gamelan)"
                  onChange={(e) => setHint(e.target.value)} />
                <Button icon="refresh" loading={generating} disabled={!project.scenes.length}
                  onClick={() => generate('music-prompt', 'Prompt musik baru siap.')}>
                  {generating ? 'Membuat… (±30 dtk)' : 'Buat ulang prompt'}
                </Button>
              </div>
            )}
          </div></div>

          <div className="s"><div>
            <h3>Upload hasilnya</h3>
            {o.music_file ? (
              <div className="audio-file">
                <Icon name="music" />
                <span className="small"><b>{o.music_file}</b></span>
                <audio controls preload="none" src={fileUrl(id, o.music_file, project.updated_at)} />
                <Button className="sm danger" icon="trash" onClick={() => run(() => api.del(`/projects/${id}/music`), 'Musik dihapus.')}>Hapus</Button>
              </div>
            ) : null}
            <Dropzone accept="audio/*" onFile={upload} disabled={uploading}>
              {uploading ? <span>Mengunggah…</span> : (
                <span><b>{o.music_file ? 'Ganti file musik' : 'Tarik file musik ke sini'}</b> atau klik untuk memilih
                  <br /><span className="faint small">MP3, WAV, M4A, AAC, OGG, FLAC · maks 30 MB</span></span>
              )}
            </Dropzone>
          </div></div>
        </div>
      )}

      {o.music_mode !== 'none' && !song && (
        <label className="field" style={{ maxWidth: 420 }}>
          <span className="row between">Volume musik <b style={{ color: 'var(--text)' }}>{Math.round(o.music_volume * 100)}%</b></span>
          <input type="range" min={0} max={1} step={0.05} value={o.music_volume}
            onChange={(e) => setOption('music_volume', Number(e.target.value))}
            onMouseUp={(e) => save({ music_volume: Number(e.target.value) }, 'Volume tersimpan.')}
            onTouchEnd={(e) => save({ music_volume: Number(e.target.value) }, 'Volume tersimpan.')}
            onKeyUp={(e) => save({ music_volume: Number(e.target.value) }, 'Volume tersimpan.')} />
          <span className="hint">Otomatis turun saat narasi berbicara (ducking).</span>
        </label>
      )}

      {allClips && (
        <div className="card flat row between" style={{ margin: 0 }}>
          <div className="small">
            <b>Terapkan ke video</b>
            <div className="muted">{busy ? 'Tunggu job yang berjalan selesai dulu.' : 'Gabung ulang dengan musik/volume/subtitle terbaru — clip tidak dibuat ulang (±1–2 mnt).'}</div>
          </div>
          <Button className="primary" icon="layers" disabled={busy}
            onClick={() => run(() => api.post(`/projects/${id}/compose`), 'Menggabung ulang video…')}>Gabung ulang video</Button>
        </div>
      )}
    </div>
  );
}
