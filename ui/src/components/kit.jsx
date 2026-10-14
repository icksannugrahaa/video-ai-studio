import React from 'react';
import Icon from './Icon.jsx';

/* ---------- formatting ---------- */
export function fmtDuration(seconds) {
  const s = Math.max(0, Math.round(Number(seconds) || 0));
  if (s < 60) return `${s} dtk`;
  const m = Math.floor(s / 60);
  const rest = s % 60;
  if (m < 60) return rest ? `${m}:${String(rest).padStart(2, '0')} mnt` : `${m} mnt`;
  return `${Math.floor(m / 60)} j ${m % 60} mnt`;
}

export function fmtClock(seconds) {
  const s = Math.max(0, Math.round(Number(seconds) || 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

export function timeAgo(epochSeconds) {
  if (!epochSeconds) return '';
  const diff = Math.max(0, Date.now() / 1000 - epochSeconds);
  if (diff < 60) return 'baru saja';
  if (diff < 3600) return `${Math.floor(diff / 60)} mnt lalu`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} jam lalu`;
  if (diff < 86400 * 30) return `${Math.floor(diff / 86400)} hari lalu`;
  return new Date(epochSeconds * 1000).toLocaleDateString('id-ID');
}

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const area = document.createElement('textarea');
    area.value = text;
    document.body.appendChild(area);
    area.select();
    document.execCommand('copy');
    area.remove();
  }
}

/* ---------- status vocab ---------- */
const STATUS = {
  draft: ['Draft', ''],
  planned: ['Storyboard siap', 'accent'],
  rendering: ['Rendering', 'warn live'],
  done: ['Selesai', 'ok'],
  error: ['Gagal', 'bad'],
  queued: ['Antre', 'warn live'],
  running: ['Berjalan', 'info live'],
  succeeded: ['Berhasil', 'ok'],
  failed: ['Gagal', 'bad'],
  canceled: ['Dibatalkan', ''],
  pending: ['Belum', ''],
  stale: ['Perlu dibuat ulang', 'warn'],
};

export function StatusBadge({ status, label }) {
  const [text, tone] = STATUS[status] || [status, ''];
  return <span className={`badge ${tone}`}><span className="dot" />{label || text}</span>;
}

/* ---------- small controls ---------- */
export function RatioIcon({ aspect, size = 14 }) {
  const [w, h] = (aspect || '9:16').split(':').map(Number);
  const scale = size / Math.max(w, h);
  return <span className="ratio" style={{ width: Math.round(w * scale), height: Math.round(h * scale) }} />;
}

export function Button({ icon, loading, children, className = '', ...rest }) {
  return (
    <button className={`btn ${className}`} disabled={loading || rest.disabled} {...rest}>
      {loading ? <Icon name="loader" className="spin" /> : icon && <Icon name={icon} />}
      {children}
    </button>
  );
}

export function Switch({ checked, onChange, label, hint, disabled }) {
  return (
    <label className="switch">
      <input type="checkbox" checked={Boolean(checked)} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span className="track" />
      <span className="label"><strong>{label}</strong>{hint && <span>{hint}</span>}</span>
    </label>
  );
}

export function Ring({ value, size = 52, stroke = 5 }) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(1, value || 0));
  return (
    <div className="ring" style={{ width: size, height: size }}>
      <svg width={size} height={size}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--surface-3)" strokeWidth={stroke} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--accent)" strokeWidth={stroke}
          strokeLinecap="round" strokeDasharray={c} strokeDashoffset={c * (1 - pct)} />
      </svg>
      <span className="val">{Math.round(pct * 100)}%</span>
    </div>
  );
}

export function Alert({ tone = 'info', children }) {
  const icon = tone === 'bad' ? 'alert' : tone === 'warn' ? 'alert' : 'info';
  return <div className={`alert ${tone}`}><Icon name={icon} /><div>{children}</div></div>;
}

export function Empty({ icon = 'film', title, children }) {
  return (
    <div className="empty">
      <Icon name={icon} size={34} strokeWidth={1.5} />
      {title && <strong style={{ color: 'var(--text)' }}>{title}</strong>}
      {children}
    </div>
  );
}

export function CopyButton({ text, label = 'Salin', className = 'sm' }) {
  const [done, setDone] = React.useState(false);
  return (
    <Button className={className} icon={done ? 'check' : 'copy'} disabled={!text}
      onClick={async () => { await copyText(text); setDone(true); setTimeout(() => setDone(false), 1800); }}>
      {done ? 'Tersalin' : label}
    </Button>
  );
}

export function Dropzone({ accept, onFile, children, disabled }) {
  const [over, setOver] = React.useState(false);
  const input = React.useRef(null);
  return (
    <div className={`dropzone${over ? ' over' : ''}`} role="button" tabIndex={0}
      onClick={() => !disabled && input.current?.click()}
      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && input.current?.click()}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); const f = e.dataTransfer.files[0]; if (f && !disabled) onFile(f); }}>
      <Icon name="upload" size={22} />
      {children}
      <input ref={input} type="file" accept={accept} onChange={(e) => { const f = e.target.files[0]; e.target.value = ''; if (f) onFile(f); }} />
    </div>
  );
}

/* ---------- toasts ---------- */
const ToastCtx = React.createContext(() => {});
export const useToast = () => React.useContext(ToastCtx);

export function ToastProvider({ children }) {
  const [items, setItems] = React.useState([]);
  const dismiss = React.useCallback((id) => setItems((list) => list.filter((t) => t.id !== id)), []);
  const push = React.useCallback((message, tone = 'ok') => {
    if (!message) return;
    const id = Math.random().toString(36).slice(2);
    setItems((list) => [...list.slice(-3), { id, message, tone }]);
    setTimeout(() => dismiss(id), tone === 'bad' ? 9000 : 4000);
  }, [dismiss]);
  const icons = { ok: 'check', bad: 'alert', info: 'info' };
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={`toast ${t.tone}`}>
            <Icon name={icons[t.tone] || 'info'} />
            <span>{t.message}</span>
            <button className="btn ghost icon sm" aria-label="Tutup" onClick={() => dismiss(t.id)}><Icon name="x" size={14} /></button>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

/* ---------- dialogs (confirm / prompt) ---------- */
const DialogCtx = React.createContext(null);
export const useDialog = () => React.useContext(DialogCtx);

function Dialog({ spec, onClose }) {
  const [value, setValue] = React.useState(spec.defaultValue || '');
  const ok = React.useRef(null);
  React.useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(null); };
    window.addEventListener('keydown', onKey);
    if (!spec.input) ok.current?.focus();
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose, spec.input]);
  const submit = (e) => { e.preventDefault(); onClose(spec.input ? value : true); };
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose(null)}>
      <form className="modal" role="dialog" aria-modal="true" onSubmit={submit}>
        <h2>{spec.title}</h2>
        <div className="body">{spec.body}</div>
        {spec.input && (
          <input autoFocus type={spec.input === 'password' ? 'password' : 'text'} value={value}
            placeholder={spec.placeholder} onChange={(e) => setValue(e.target.value)} style={{ marginBottom: 18 }} />
        )}
        <div className="actions">
          <button type="button" className="btn ghost" onClick={() => onClose(null)}>{spec.cancelLabel || 'Batal'}</button>
          <button ref={ok} type="submit" className={`btn ${spec.danger ? 'danger solid' : 'primary'}`}
            disabled={spec.input && !value.trim()}>{spec.confirmLabel || 'Lanjutkan'}</button>
        </div>
      </form>
    </div>
  );
}

export function DialogProvider({ children }) {
  const [spec, setSpec] = React.useState(null);
  const resolver = React.useRef(null);
  const open = React.useCallback((s) => new Promise((resolve) => { resolver.current = resolve; setSpec(s); }), []);
  const close = React.useCallback((result) => { resolver.current?.(result); resolver.current = null; setSpec(null); }, []);
  const api = React.useMemo(() => ({
    confirm: (s) => open(s).then(Boolean),
    prompt: (s) => open({ ...s, input: s.input || 'text' }),
  }), [open]);
  return (
    <DialogCtx.Provider value={api}>
      {children}
      {spec && <Dialog spec={spec} onClose={close} />}
    </DialogCtx.Provider>
  );
}
