import React from 'react';
import { createPortal } from 'react-dom';
import Icon from '../Icon.jsx';
import { Button, Ring, StatusBadge, fmtDuration } from '../kit.jsx';

const fmtClock = (sec) => {
  const t = Math.max(0, Math.floor(sec));
  const h = Math.floor(t / 3600);
  const mm = String(Math.floor((t % 3600) / 60)).padStart(h ? 2 : 1, '0');
  return `${h ? `${h}:` : ''}${mm}:${String(t % 60).padStart(2, '0')}`;
};
import { JOB_LABEL, RESUMABLE, isActive, sceneState } from './shared.js';

function useNow(active) {
  const [now, setNow] = React.useState(() => Date.now() / 1000);
  React.useEffect(() => {
    if (!active) return undefined;
    const t = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(t);
  }, [active]);
  return now;
}

/** True while ``ref``'s element is scrolled out of the viewport. */
function useOffscreen(ref, enabled) {
  const [off, setOff] = React.useState(false);
  React.useEffect(() => {
    const el = ref.current;
    if (!enabled || !el || typeof IntersectionObserver === 'undefined') { setOff(false); return undefined; }
    const io = new IntersectionObserver(([entry]) => setOff(!entry.isIntersecting), { threshold: 0.15 });
    io.observe(el);
    return () => io.disconnect();
  }, [ref, enabled]);
  return off;
}

/** Compact progress pill shown while the full job card is scrolled away. */
function FloatingJob({ job, pct, label, meta, elapsed, onShow, onCancel }) {
  return createPortal(
    <div className="job-float" role="status" aria-live="polite">
      <button className="job-float-main" onClick={onShow} title="Lihat detail progres">
        <Ring value={pct} size={40} stroke={4} />
        <span className="grow" style={{ minWidth: 0 }}>
          <span className="row between" style={{ flexWrap: 'nowrap', gap: 8 }}>
            <b className="ellipsis">{label}</b>
            <span className="job-float-timer mono" title="Waktu berjalan"><Icon name="clock" size={11} /> {fmtClock(elapsed)}</span>
          </span>
          <span className="faint small ellipsis" style={{ display: 'block' }}>{meta}</span>
        </span>
      </button>
      <button className="btn ghost icon sm" title="Batalkan job" onClick={onCancel}><Icon name="stop" size={14} /></button>
      <div className="job-float-bar"><div style={{ width: `${Math.max(2, pct * 100)}%` }} /></div>
    </div>,
    document.body,
  );
}

export default function JobCard({ job, scenes, onCancel, onResume, onSelectScene, onPreview, previewJob }) {
  const cardRef = React.useRef(null);
  const active = isActive(job);
  const now = useNow(active);
  const offscreen = useOffscreen(cardRef, active);
  // Pace is measured from when this page first saw the job, so a resumed job
  // (that starts at, say, 60%) does not get an absurdly short estimate.
  const seen = React.useRef(null);
  if (job && job.status === 'running' && seen.current?.id !== job.id) {
    seen.current = { id: job.id, t: Date.now() / 1000, p: job.progress || 0 };
  }
  if (!job) return null;
  const pct = job.progress || 0;
  const elapsed = Math.max(0, now - job.created_at);
  const base = seen.current?.id === job.id ? seen.current : null;
  const rate = base && now - base.t > 30 && pct - base.p > 0.01 ? (pct - base.p) / (now - base.t) : 0;
  const done = scenes.filter((s) => sceneState(s) === 'done').length;
  // Clip-based estimate (average generation time of finished clips) beats the
  // progress-rate estimate while clips are still being generated.
  const timed = scenes.filter((s) => sceneState(s) === 'done' && s.clip_gen_seconds != null);
  const avgClip = timed.length ? timed.reduce((t, s) => t + s.clip_gen_seconds, 0) / timed.length : 0;
  const clipEta = avgClip && ['render', 'edit', 'regenerate'].includes(job.kind) && done < scenes.length
    ? (scenes.length - done) * avgClip : null;
  const eta = active && job.status === 'running' ? (clipEta || (rate ? (1 - pct) / rate : null)) : null;
  const failed = job.status === 'failed';
  const showDots = scenes.length > 0 && ['render', 'edit', 'regenerate'].includes(job.kind);

  const floatMeta = [
    job.status === 'queued' ? (job.queue_ahead ? `Antre · ${job.queue_ahead} job di depan` : 'Antre') : null,
    showDots ? `${done}/${scenes.length} clip` : null,
    eta ? `± ${fmtDuration(eta)} lagi` : null,
    !showDots && job.message ? job.message : null,
  ].filter(Boolean).join(' · ') || job.message || 'Memproses…';

  return (
    <>
    {active && offscreen && (
      <FloatingJob job={job} pct={pct} label={JOB_LABEL[job.kind] || job.kind} meta={floatMeta} elapsed={elapsed}
        onShow={() => cardRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })} onCancel={onCancel} />
    )}
    <div ref={cardRef} className={`card job${active ? ' active' : ''}${failed ? ' failed' : ''}`} role="status" aria-live="polite">
      <div className="job-top">
        {active ? <Ring value={pct} /> : (
          <div className="ring" style={{ width: 52, height: 52, display: 'grid', placeItems: 'center', borderRadius: '50%', background: failed ? 'var(--bad-soft)' : job.status === 'succeeded' ? 'var(--ok-soft)' : 'var(--surface-3)', color: failed ? 'var(--bad)' : job.status === 'succeeded' ? 'var(--ok)' : 'var(--muted)' }}>
            <Icon name={failed ? 'alert' : job.status === 'succeeded' ? 'check' : 'stop'} size={22} />
          </div>
        )}
        <div className="grow stack tight">
          <div className="row between">
            <strong>{JOB_LABEL[job.kind] || job.kind}</strong>
            <StatusBadge status={job.status} />
          </div>
          <div className="job-meta">
            {showDots && <span>{done}/{scenes.length} clip</span>}
            {active && <span><Icon name="clock" size={12} /> {fmtDuration(elapsed)}</span>}
            {eta && <span>± {fmtDuration(eta)} lagi</span>}
          </div>
        </div>
      </div>
      {active && <div className="progress striped" style={{ margin: '14px 0 10px' }}><div style={{ width: `${Math.max(2, pct * 100)}%` }} /></div>}
      <div className="job-msg" style={{ marginTop: active ? 0 : 12, color: failed ? 'var(--text)' : undefined }}>
        {job.status === 'queued' && job.queue_ahead
          ? `Menunggu antrean — ${job.queue_ahead} job lain diproses lebih dulu (render dijalankan satu per satu).`
          : job.message || (active ? 'Memulai…' : '')}
      </div>
      {showDots && (active || failed) && (
        <div className="scene-dots" style={{ marginTop: 12 }}>
          {scenes.map((s, i) => (
            <span key={s.id || i} className={sceneState(s)} title={`Scene ${i + 1}`} style={{ cursor: 'pointer' }}
              onClick={() => onSelectScene?.(i)} />
          ))}
        </div>
      )}
      <div className="row" style={{ marginTop: 14 }}>
        {active && onPreview && ['render', 'edit', 'regenerate'].includes(job.kind) && (
          <Button className="sm" icon="eye" loading={isActive(previewJob)} onClick={onPreview}
            title="Gabungkan clip yang sudah jadi sekarang, tanpa menunggu render selesai (tanpa kredit)">
            {isActive(previewJob)
              ? `Render sementara… ${Math.round((previewJob.progress || 0) * 100)}%`
              : `Render sementara (${done} clip)`}
          </Button>
        )}
        {active && <Button className="danger sm" icon="stop" onClick={onCancel}>Batalkan</Button>}
        {!active && RESUMABLE.includes(job.kind) && ['failed', 'canceled'].includes(job.status) && (
          <>
            <Button className="primary" icon="play" onClick={onResume}>Lanjutkan render</Button>
            <span className="faint small">Clip yang sudah jadi tidak dibuat ulang.</span>
          </>
        )}
      </div>
    </div>
    </>
  );
}
