import React from 'react';
import Icon from '../Icon.jsx';
import { fmtClock, fmtDuration } from '../kit.jsx';
import { JOB_LABEL, sceneState } from './shared.js';

const KIND_ORDER = ['plan', 'render', 'edit', 'regenerate', 'compose', 'preview', 'music_prompt'];
const KIND_LABEL = { ...JOB_LABEL, preview: 'Render sementara', compose: 'Gabung ulang' };

/** "Ringkasan produksi": where the time went, shown once a final video exists. */
export default function SummaryCard({ project, onSelectScene }) {
  const stats = project.stats;
  const [open, setOpen] = React.useState(true);
  if (!stats?.final) return null;
  const clips = stats.clips || {};
  const wall = stats.final_at && stats.first_at ? stats.final_at - stats.first_at : null;
  const kinds = KIND_ORDER.filter((k) => stats.jobs?.[k]);
  const bars = project.scenes.map((s, i) => ({
    i, seconds: sceneState(s) === 'done' ? s.clip_gen_seconds : null, attempts: s.clip_attempts || 1,
  }));
  const maxBar = Math.max(1, ...bars.map((b) => b.seconds || 0));

  return (
    <div className="card summary">
      <div className="row between" style={{ cursor: 'pointer' }} onClick={() => setOpen(!open)}>
        <h3 className="row" style={{ gap: 8 }}><Icon name="check" /> Ringkasan produksi</h3>
        <Icon name="chevron" className={`chev${open ? ' open' : ''}`} />
      </div>
      {open && (
        <>
          <div className="stats">
            <div className="stat"><b>{fmtDuration(stats.job_seconds)}</b><span>total waktu proses</span></div>
            {wall != null && <div className="stat"><b>{fmtDuration(wall)}</b><span>dari ide ke video</span></div>}
            <div className="stat"><b>{fmtClock(stats.final.duration)}</b><span>durasi video</span></div>
            <div className="stat"><b>{stats.final.scenes}</b><span>scene · {stats.final.cues} subtitle</span></div>
          </div>

          {clips.count > 0 && (
            <>
              <div className="opt-label" style={{ marginTop: 14 }}>Waktu pembuatan clip</div>
              <div className="kv" style={{ marginBottom: 10 }}>
                <span>Total <b>{fmtDuration(clips.total)}</b></span>
                <span>Rata-rata <b>{fmtClock(clips.avg)}</b></span>
                <span>Tercepat <b>{fmtClock(clips.min)}</b></span>
                <span>Terlama <b>{fmtClock(clips.max)}</b></span>
                {clips.retried > 0 && <span style={{ color: 'var(--warn)' }}>{clips.retried} clip diulang</span>}
              </div>
              <div className="gen-bars">
                {bars.map((b) => (
                  <button key={b.i} type="button" className="gen-bar" onClick={() => onSelectScene?.(b.i)}
                    title={b.seconds != null ? `Scene ${b.i + 1}: ${fmtDuration(b.seconds)}${b.attempts > 1 ? ` · ${b.attempts} percobaan` : ''}` : `Scene ${b.i + 1}: waktu tidak tercatat`}>
                    <span className="n">{b.i + 1}</span>
                    <span className="track"><span className={b.attempts > 1 ? 'warn' : ''} style={{ width: `${((b.seconds || 0) / maxBar) * 100}%` }} /></span>
                    <span className="t mono">{b.seconds != null ? fmtClock(b.seconds) : '–'}</span>
                  </button>
                ))}
              </div>
            </>
          )}

          {kinds.length > 0 && (
            <>
              <div className="opt-label" style={{ marginTop: 14 }}>Per tahap</div>
              <div className="stack tight">
                {kinds.map((k) => {
                  const j = stats.jobs[k];
                  return (
                    <div key={k} className="row between small">
                      <span>{KIND_LABEL[k] || k} <span className="faint">×{j.count}</span>
                        {j.failed > 0 && <span style={{ color: 'var(--bad)' }}> · {j.failed} gagal/batal</span>}</span>
                      <b className="mono">{fmtDuration(j.seconds)}</b>
                    </div>
                  );
                })}
              </div>
            </>
          )}
          <p className="faint small" style={{ margin: '12px 0 0' }}>
            Waktu proses termasuk antre & percobaan ulang. Kredit dipantau terpisah (9router).
          </p>
        </>
      )}
    </div>
  );
}
