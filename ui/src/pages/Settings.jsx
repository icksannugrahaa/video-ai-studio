import React from 'react';
import { api } from '../api.js';
import Icon from '../components/Icon.jsx';
import { Button, CopyButton, Empty, timeAgo, useDialog, useToast } from '../components/kit.jsx';
import { useT, useI18n } from '../i18n.jsx';

const EMPTY = { name: '', base_url: 'https://ai.sandroid.works', api_key: '', chat_model: '', video_model: '',
  tts_model: '', tts_voice: '', clip_seconds: 5 };

function groupByProvider(models, noPrefix) {
  const groups = new Map();
  for (const id of models) {
    const provider = id.includes('/') ? id.split('/')[0] : noPrefix;
    if (!groups.has(provider)) groups.set(provider, []);
    groups.get(provider).push(id);
  }
  return [...groups.entries()];
}

function ModelSelect({ icon, label, hint, value, options, onChange, loading }) {
  const t = useT();
  const [query, setQuery] = React.useState('');
  const list = options || [];
  const q = query.trim().toLowerCase();
  const shown = q ? list.filter((m) => m.toLowerCase().includes(q)) : list;
  const missing = value && !list.includes(value);
  return (
    <div className="field" style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 12.5, color: 'var(--muted)', fontWeight: 500 }}>
      <span className="row between">
        <span className="row" style={{ gap: 6 }}><Icon name={icon} size={14} /> {label}</span>
        {options && <span className="faint">{t('common.modelCount', { n: list.length })}</span>}
      </span>
      {list.length > 8 && (
        <div className="input-icon">
          <Icon name="search" size={14} />
          <input placeholder={t('settings.searchModel')} value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
      )}
      <select value={value} onChange={(e) => onChange(e.target.value)} disabled={!options && !value}>
        <option value="">{loading ? t('settings.loadingModels') : options ? t('settings.selectModel') : t('settings.fillEndpoint')}</option>
        {missing && <option value={value}>{t('settings.storedMissing', { value })}</option>}
        {groupByProvider(shown, t('common.noPrefix')).map(([provider, ids]) => (
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
  const t = useT();
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
      toast(t('settings.profileSaved', { name: saved.name }), 'ok');
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
      setModelError(t('settings.modelsError', { msg: err.message }));
    } finally {
      setLoadingModels(false);
    }
  }

  // Editing: fetch right away with the stored key. New profile: once a key is entered.
  React.useEffect(() => { if (initial?.id) loadModels(); }, [initial?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <form className="card stack" onSubmit={save} style={{ gap: 18, borderColor: 'var(--accent)' }}>
      <div className="card-head" style={{ margin: 0 }}>
        <h2>{initial?.id ? t('settings.editProfile', { name: initial.name }) : t('settings.newProfileTitle')}</h2>
        {onCancel && <button type="button" className="btn ghost icon" onClick={onCancel} aria-label={t('action.close')}><Icon name="x" /></button>}
      </div>

      <div className="steps">
        <div className="s"><div>
          <h3>{t('settings.connection')}</h3>
          <div className="grid">
            <label className="field">{t('settings.nameLabel')}<input value={form.name} placeholder={t('settings.namePlaceholder')} onChange={(e) => set('name')(e.target.value)} required /></label>
            <label className="field"><span>{t('settings.endpoint')} <span className="hint">{t('settings.openaiCompat')}</span></span>
              <input value={form.base_url} onChange={(e) => set('base_url')(e.target.value)} required />
            </label>
            <label className="field"><span>{t('settings.apiKey')} {initial?.id && <span className="hint">{t('settings.apiKeyKeep', { mask: initial.api_key_masked })}</span>}</span>
              <input type="password" autoComplete="off" value={form.api_key} onChange={(e) => set('api_key')(e.target.value)}
                onBlur={() => form.api_key && loadModels()} required={!initial?.id} />
            </label>
          </div>
          <div className="row">
            <Button type="button" icon="refresh" loading={loadingModels} disabled={!canProbe} onClick={loadModels}>
              {models ? t('settings.reloadModels') : t('settings.loadModels')}
            </Button>
            {models && <span className="faint small">Chat {models.chat.length} · Video {models.video.length} · TTS {models.tts.length}</span>}
          </div>
          {modelError && <div className="alert bad"><Icon name="alert" /><div>{modelError}</div></div>}
        </div></div>

        <div className="s"><div>
          <h3>{t('settings.models')}</h3>
          <div className="grid">
            <ModelSelect icon="message" label={t('common.chat')} hint={t('settings.modelChatHint')} value={form.chat_model}
              options={models?.chat} loading={loadingModels} onChange={set('chat_model')} />
            <ModelSelect icon="video" label={t('common.video')} hint={t('settings.modelVideoHint')} value={form.video_model}
              options={models?.video} loading={loadingModels} onChange={set('video_model')} />
            <ModelSelect icon="mic" label={t('common.tts')} hint={t('settings.modelTtsHint')} value={form.tts_model}
              options={models?.tts} loading={loadingModels} onChange={set('tts_model')} />
          </div>
        </div></div>

        <div className="s"><div>
          <h3>{t('settings.defaults')}</h3>
          <div className="grid">
            <label className="field">{t('settings.ttsVoice')}
              <input value={form.tts_voice} placeholder={t('settings.ttsVoicePlaceholder')} onChange={(e) => set('tts_voice')(e.target.value)} />
            </label>
            <label className="field"><span>{t('settings.clipSeconds')} <span className="hint">{t('settings.clipSecondsHint')}</span></span>
              <input type="number" min={2} max={30} value={form.clip_seconds} onChange={(e) => set('clip_seconds')(e.target.value)} />
            </label>
          </div>
        </div></div>
      </div>

      <div className="row">
        <Button className="primary" icon="check" type="submit" loading={saving}>{t('settings.saveProfile')}</Button>
        {onCancel && <button type="button" className="btn ghost" onClick={onCancel}>{t('action.cancel')}</button>}
      </div>
    </form>
  );
}

export default function Settings() {
  const t = useT();
  const { lang } = useI18n();
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
    if (!(await dialog.confirm({ title: t('settings.deleteProfile'), danger: true, confirmLabel: t('action.delete'),
      body: t('settings.deleteProfileBody', { name: p.name }) }))) return;
    api.del(`/profiles/${p.id}`).then(() => { toast(t('settings.profileDeleted'), 'ok'); load(); }).catch((e) => toast(e.message, 'bad'));
  }

  async function createToken() {
    const name = await dialog.prompt({ title: t('settings.newTokenTitle'), body: t('settings.newTokenBody'), defaultValue: 'api', confirmLabel: t('settings.createToken') });
    if (!name) return;
    api.post('/auth/tokens', { name: name.trim() }).then((tok) => { setNewToken(tok.token); load(); }).catch((e) => toast(e.message, 'bad'));
  }

  async function revoke(tok) {
    if (!(await dialog.confirm({ title: t('settings.revokeToken'), danger: true, confirmLabel: t('settings.revoke'),
      body: t('settings.revokeTokenBody', { name: tok.name }) }))) return;
    api.del(`/auth/tokens/${tok.id}`).then(() => { toast(t('settings.tokenRevoked'), 'ok'); load(); }).catch((e) => toast(e.message, 'bad'));
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{t('settings.title')}</h1>
          <p className="muted">{t('settings.subtitle')}</p>
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <div><h2>{t('settings.providers')}</h2><div className="sub faint small">{t('settings.providersHint')}</div></div>
          {!editing && <Button className="primary" icon="plus" onClick={() => setEditing({})}>{t('settings.newProfile')}</Button>}
        </div>
        {profiles && !profiles.length && !editing && (
          <Empty icon="server" title={t('settings.noProfiles')}>
            {t('settings.noProfilesHint')}
            <Button className="primary" icon="plus" onClick={() => setEditing({})} style={{ marginTop: 6 }}>{t('settings.addProfile')}</Button>
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
                <Button className="sm" icon="edit" onClick={() => setEditing(p)}>{t('action.edit')}</Button>
                <Button className="sm danger" icon="trash" onClick={() => removeProfile(p)}>{t('action.delete')}</Button>
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
          <div><h2>{t('settings.tokens')}</h2><div className="sub faint small">{t('settings.tokensHint')} <code>Authorization: Bearer &lt;token&gt;</code> {t('settings.tokensHintAfter')}</div></div>
          <div className="row">
            <a className="btn" href="#/docs"><Icon name="book" /> {t('settings.documentation')}</a>
            <Button icon="key" onClick={createToken}>{t('settings.newToken')}</Button>
          </div>
        </div>
        {newToken && (
          <div className="stack tight" style={{ marginBottom: 14 }}>
            <div className="alert warn"><Icon name="alert" /><div>{t('common.copyNow')}</div></div>
            <div className="token-box"><span className="mono grow">{newToken}</span><CopyButton text={newToken} /></div>
          </div>
        )}
        {!tokens.length && <p className="faint small" style={{ margin: 0 }}>{t('settings.noTokens')}</p>}
        {tokens.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>{t('settings.colName')}</th><th>{t('settings.colPrefix')}</th><th>{t('settings.colCreated')}</th><th>{t('settings.colLastUsed')}</th><th /></tr></thead>
              <tbody>
                {tokens.map((tok) => (
                  <tr key={tok.id}>
                    <td><strong>{tok.name}</strong></td>
                    <td className="mono faint">{tok.prefix}…</td>
                    <td className="muted">{timeAgo(tok.created_at, t, lang === 'en' ? 'en-US' : 'id-ID')}</td>
                    <td className="muted">{tok.last_used_at ? timeAgo(tok.last_used_at, t, lang === 'en' ? 'en-US' : 'id-ID') : t('common.never')}</td>
                    <td style={{ textAlign: 'right' }}><Button className="sm danger" icon="trash" onClick={() => revoke(tok)}>{t('settings.revoke')}</Button></td>
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
