import React from 'react';
import { api } from '../api.js';
import Icon from '../components/Icon.jsx';
import { Button, CopyButton, Empty, timeAgo, useDialog, useToast } from '../components/kit.jsx';

const EMPTY = { name: '', base_url: 'https://ai.sandroid.works', api_key: '', chat_model: '', video_model: '',
  tts_model: '', tts_voice: '', clip_seconds: 5 };

function groupByProvider(models) {
  const groups = new Map();
  for (const id of models) {
    const provider = id.includes('/') ? id.split('/')[0] : '(tanpa prefix)';
    if (!groups.has(provider)) groups.set(provider, []);
    groups.get(provider).push(id);
  }
  return [...groups.entries()];
}

function ModelSelect({ icon, label, hint, value, options, onChange, loading }) {
  const [query, setQuery] = React.useState('');
  const list = options || [];
  const q = query.trim().toLowerCase();
  const shown = q ? list.filter((m) => m.toLowerCase().includes(q)) : list;
  const missing = value && !list.includes(value);
  return (
    <div className="field" style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 12.5, color: 'var(--muted)', fontWeight: 500 }}>
      <span className="row between">
        <span className="row" style={{ gap: 6 }}><Icon name={icon} size={14} /> {label}</span>
        {options && <span className="faint">{list.length} model</span>}
      </span>
      {list.length > 8 && (
        <div className="input-icon">
          <Icon name="search" size={14} />
          <input placeholder="Cari model…" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
      )}
      <select value={value} onChange={(e) => onChange(e.target.value)} disabled={!options && !value}>
        <option value="">{loading ? 'Memuat model…' : options ? '— pilih model —' : 'Isi endpoint + API key dulu'}</option>
        {missing && <option value={value}>{value} (tersimpan, tidak ada di daftar)</option>}
        {groupByProvider(shown).map(([provider, ids]) => (
          <optgroup key={provider} label={`${provider} (${ids.length})`}>
            {ids.map((m) => <option key={m} value={m}>{m}</option>)}
          </optgroup>
        ))}
      </select>
      {hint && <span className="faint" style={{ fontWeight: 400 }}>{hint}</span>}
    </div>
  );
}

function ProfileForm({ initial, onSaved, onCancel }) {
  const toast = useToast();
  const [form, setForm] = React.useState({ ...EMPTY, ...initial, api_key: '' });
  const [models, setModels] = React.useState(null);
  const [loadingModels, setLoadingModels] = React.useState(false);
  const [modelError, setModelError] = React.useState('');
  const [saving, setSaving] = React.useState(false);
  const set = (key) => (value) => setForm((f) => ({ ...f, [key]: value }));
  const canProbe = form.base_url && (form.api_key || initial?.id);

  async function save(e) {
    e.preventDefault();
    setSaving(true);
    const body = { ...form, clip_seconds: Number(form.clip_seconds) };
    if (initial?.id && !body.api_key) delete body.api_key;
    try {
      const saved = initial?.id ? await api.patch(`/profiles/${initial.id}`, body) : await api.post('/profiles', body);
      toast(`Profil “${saved.name}” tersimpan.`, 'ok');
      onSaved(saved);
    } catch (err) {
      toast(err.message, 'bad');
    } finally {
      setSaving(false);
    }
  }

  async function loadModels() {
    if (!canProbe) return;
    setModelError('');
    setLoadingModels(true);
    try {
      const data = await api.post('/profiles/models', {
        base_url: form.base_url, api_key: form.api_key || undefined, profile_id: initial?.id,
      });
      setModels(data.by_field);
    } catch (err) {
      setModelError(`Gagal mengambil daftar model: ${err.message}`);
    } finally {
      setLoadingModels(false);
    }
  }

  // Editing: fetch right away with the stored key. New profile: once a key is entered.
  React.useEffect(() => { if (initial?.id) loadModels(); }, [initial?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <form className="card stack" onSubmit={save} style={{ gap: 18, borderColor: 'var(--accent)' }}>
      <div className="card-head" style={{ margin: 0 }}>
        <h2>{initial?.id ? `Edit profil “${initial.name}”` : 'Profil provider baru'}</h2>
        {onCancel && <button type="button" className="btn ghost icon" onClick={onCancel} aria-label="Tutup"><Icon name="x" /></button>}
      </div>

      <div className="steps">
        <div className="s"><div>
          <h3>Koneksi</h3>
          <div className="grid">
            <label className="field">Nama profil<input value={form.name} placeholder="mis. Router utama" onChange={(e) => set('name')(e.target.value)} required /></label>
            <label className="field"><span>Endpoint <span className="hint">— OpenAI-compatible</span></span>
              <input value={form.base_url} onChange={(e) => set('base_url')(e.target.value)} required />
            </label>
            <label className="field"><span>API key {initial?.id && <span className="hint">— kosongkan jika tidak diganti ({initial.api_key_masked})</span>}</span>
              <input type="password" autoComplete="off" value={form.api_key} onChange={(e) => set('api_key')(e.target.value)}
                onBlur={() => form.api_key && loadModels()} required={!initial?.id} />
            </label>
          </div>
          <div className="row">
            <Button type="button" icon="refresh" loading={loadingModels} disabled={!canProbe} onClick={loadModels}>
              {models ? 'Muat ulang daftar model' : 'Ambil daftar model'}
            </Button>
            {models && <span className="faint small">Chat {models.chat.length} · Video {models.video.length} · TTS {models.tts.length}</span>}
          </div>
          {modelError && <div className="alert bad"><Icon name="alert" /><div>{modelError}</div></div>}
        </div></div>

        <div className="s"><div>
          <h3>Model</h3>
          <div className="grid">
            <ModelSelect icon="message" label="Chat" hint="Menyusun storyboard, lirik & prompt musik" value={form.chat_model}
              options={models?.chat} loading={loadingModels} onChange={set('chat_model')} />
            <ModelSelect icon="video" label="Video" hint="Membuat clip tiap scene" value={form.video_model}
              options={models?.video} loading={loadingModels} onChange={set('video_model')} />
            <ModelSelect icon="mic" label="TTS" hint="Suara narasi" value={form.tts_model}
              options={models?.tts} loading={loadingModels} onChange={set('tts_model')} />
          </div>
        </div></div>

        <div className="s"><div>
          <h3>Default</h3>
          <div className="grid">
            <label className="field">Voice TTS
              <input value={form.tts_voice} placeholder="mis. id-ID-ArdiNeural / Cherry" onChange={(e) => set('tts_voice')(e.target.value)} />
            </label>
            <label className="field"><span>Panjang clip maks model video <span className="hint">— detik</span></span>
              <input type="number" min={2} max={30} value={form.clip_seconds} onChange={(e) => set('clip_seconds')(e.target.value)} />
            </label>
          </div>
        </div></div>
      </div>

      <div className="row">
        <Button className="primary" icon="check" type="submit" loading={saving}>Simpan profil</Button>
        {onCancel && <button type="button" className="btn ghost" onClick={onCancel}>Batal</button>}
      </div>
    </form>
  );
}

export default function Settings() {
  const toast = useToast();
  const dialog = useDialog();
  const [profiles, setProfiles] = React.useState(null);
  const [editing, setEditing] = React.useState(null);
  const [tokens, setTokens] = React.useState([]);
  const [newToken, setNewToken] = React.useState(null);

  const load = React.useCallback(() => Promise.all([api.get('/profiles'), api.get('/auth/tokens')])
    .then(([p, t]) => { setProfiles(p); setTokens(t); })
    .catch((e) => toast(e.message, 'bad')), [toast]);
  React.useEffect(() => { load(); }, [load]);

  async function removeProfile(p) {
    if (!(await dialog.confirm({ title: 'Hapus profil?', danger: true, confirmLabel: 'Hapus',
      body: <>Profil <strong>{p.name}</strong> dihapus. Project yang memakainya perlu memilih profil lain.</> }))) return;
    api.del(`/profiles/${p.id}`).then(() => { toast('Profil dihapus.', 'ok'); load(); }).catch((e) => toast(e.message, 'bad'));
  }

  async function createToken() {
    const name = await dialog.prompt({ title: 'Token API baru', body: 'Beri nama supaya mudah dikenali (mis. bot-wa).', defaultValue: 'api', confirmLabel: 'Buat token' });
    if (!name) return;
    api.post('/auth/tokens', { name: name.trim() }).then((t) => { setNewToken(t.token); load(); }).catch((e) => toast(e.message, 'bad'));
  }

  async function revoke(t) {
    if (!(await dialog.confirm({ title: 'Cabut token?', danger: true, confirmLabel: 'Cabut',
      body: <>Aplikasi yang memakai token <strong>{t.name}</strong> tidak bisa mengakses API lagi.</> }))) return;
    api.del(`/auth/tokens/${t.id}`).then(() => { toast('Token dicabut.', 'ok'); load(); }).catch((e) => toast(e.message, 'bad'));
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Pengaturan</h1>
          <p className="muted">Endpoint + API key milikmu sendiri. Key disimpan terenkripsi dan tidak pernah ditampilkan utuh.</p>
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <div><h2>Profil provider</h2><div className="sub faint small">Endpoint AI dan model yang dipakai project.</div></div>
          {!editing && <Button className="primary" icon="plus" onClick={() => setEditing({})}>Profil baru</Button>}
        </div>
        {profiles && !profiles.length && !editing && (
          <Empty icon="server" title="Belum ada profil">
            Tambahkan endpoint OpenAI-compatible (mis. router Sandroid) beserta API key-nya.
            <Button className="primary" icon="plus" onClick={() => setEditing({})} style={{ marginTop: 6 }}>Tambah profil</Button>
          </Empty>
        )}
        <div className="stack">
          {(profiles || []).map((p) => (
            <div key={p.id} className="profile-card">
              <span className="ico"><Icon name="server" size={20} /></span>
              <div className="grow stack tight">
                <strong>{p.name}</strong>
                <div className="kv">
                  <span className="ellipsis">{p.base_url}</span>
                  <span>Chat <b>{p.chat_model || '—'}</b></span>
                  <span>Video <b>{p.video_model || '—'}</b></span>
                  <span>TTS <b>{p.tts_model || '—'}</b></span>
                </div>
              </div>
              <div className="row">
                <Button className="sm" icon="edit" onClick={() => setEditing(p)}>Edit</Button>
                <Button className="sm danger" icon="trash" onClick={() => removeProfile(p)}>Hapus</Button>
              </div>
            </div>
          ))}
        </div>
      </div>

      {editing && (
        <ProfileForm key={editing.id || 'new'} initial={editing.id ? editing : null}
          onSaved={() => { setEditing(null); load(); }} onCancel={() => setEditing(null)} />
      )}

      <div className="card">
        <div className="card-head">
          <div><h2>Token API</h2><div className="sub faint small">Akses API dari aplikasi lain: <code>Authorization: Bearer &lt;token&gt;</code> · <a href="#/docs">Lihat dokumentasi API →</a></div></div>
          <div className="row">
            <a className="btn" href="#/docs"><Icon name="book" /> Dokumentasi</a>
            <Button icon="key" onClick={createToken}>Token baru</Button>
          </div>
        </div>
        {newToken && (
          <div className="stack tight" style={{ marginBottom: 14 }}>
            <div className="alert warn"><Icon name="alert" /><div>Salin sekarang — token hanya ditampilkan sekali.</div></div>
            <div className="token-box"><span className="mono grow">{newToken}</span><CopyButton text={newToken} /></div>
          </div>
        )}
        {!tokens.length && <p className="faint small" style={{ margin: 0 }}>Belum ada token.</p>}
        {tokens.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Nama</th><th>Prefix</th><th>Dibuat</th><th>Terakhir dipakai</th><th /></tr></thead>
              <tbody>
                {tokens.map((t) => (
                  <tr key={t.id}>
                    <td><strong>{t.name}</strong></td>
                    <td className="mono faint">{t.prefix}…</td>
                    <td className="muted">{timeAgo(t.created_at)}</td>
                    <td className="muted">{t.last_used_at ? timeAgo(t.last_used_at) : 'belum pernah'}</td>
                    <td style={{ textAlign: 'right' }}><Button className="sm danger" icon="trash" onClick={() => revoke(t)}>Cabut</Button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
