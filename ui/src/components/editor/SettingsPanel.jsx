import React from 'react';
import { api } from '../../api.js';
import { Button, RatioIcon, Switch } from '../kit.jsx';
import { useT } from '../../i18n.jsx';

const LANGUAGES = [['id-ID', 'Indonesia'], ['en-US', 'English (US)'], ['en-GB', 'English (UK)'], ['ms-MY', 'Melayu'],
  ['jv-ID', 'Jawa'], ['su-ID', 'Sunda'], ['ja-JP', '日本語'], ['ko-KR', '한국어'], ['zh-CN', '中文'], ['ar-SA', 'العربية']];

const pick = (p) => ({
  prompt: p.prompt, preset: p.preset, target_seconds: p.target_seconds, language: p.language,
  profile_id: p.profile_id || '', voice: p.options.voice || '', continuity: p.options.continuity,
  burn_subtitles: p.options.burn_subtitles, keep_clip_audio: p.options.keep_clip_audio,
  transition: p.options.transition ?? 0.5,
});

export default function SettingsPanel({ project, profiles, presets, busy, run, onDelete }) {
  const t = useT();
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
    }), t('settings.savedProject'));
    if (result) setForm(pick(result));
    setSaving(false);
  }

  return (
    <div className="stack" style={{ gap: 20 }}>
      <label className="field"><span>{t('sp.prompt')} <span className="hint">{t('sp.promptHint')}</span></span>
        <textarea rows={3} value={form.prompt} onChange={(e) => set('prompt')(e.target.value)} />
      </label>

      <div>
        <div className="opt-label">{t('sp.platform')}</div>
        <div className="chips">
          {presets.map((p) => (
            <button type="button" key={p.id} className={`chip${form.preset === p.id ? ' active' : ''}`} onClick={() => set('preset')(p.id)}>
              <RatioIcon aspect={p.aspect} /> {p.label}
            </button>
          ))}
        </div>
      </div>

      <div className="grid">
        <label className="field">{t('sp.targetDuration')}
          <input type="number" min={5} max={3600} value={form.target_seconds} onChange={(e) => set('target_seconds')(e.target.value)} />
        </label>
        <label className="field">{t('sp.narrationLang')}
          <input list="sav-langs" value={form.language} onChange={(e) => set('language')(e.target.value)} />
          <datalist id="sav-langs">{LANGUAGES.map(([code, label]) => <option key={code} value={code}>{label}</option>)}</datalist>
        </label>
        <label className="field">{t('sp.providerProfile')}
          <select value={form.profile_id} onChange={(e) => set('profile_id')(e.target.value)}>
            <option value="">{t('sp.pickProfile')}</option>
            {profiles.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          {!profiles.length && <span className="hint"><a href="#/settings">{t('sp.createProfileFirst')}</a></span>}
        </label>
        <label className="field">{t('sp.voice')}
          <input value={form.voice} placeholder={profile?.tts_voice ? t('sp.voiceDefaultNamed', { name: profile.tts_voice }) : t('sp.voiceDefault')}
            onChange={(e) => set('voice')(e.target.value)} />
        </label>
      </div>

      <div>
        <div className="opt-label">{t('sp.transition')}</div>
        <div className="chips">
          {[[0, 'sp.transCut'], [0.5, 'sp.transCross'], [1, 'sp.transSlow']].map(([v, label]) => (
            <button type="button" key={v} className={`chip${Number(form.transition) === v ? ' active' : ''}`} onClick={() => set('transition')(v)}>{t(label)}</button>
          ))}
        </div>
        <p className="faint small" style={{ margin: '8px 0 0' }}>{t('sp.transitionNote')}</p>
      </div>

      <div className="stack tight">
        <Switch checked={form.continuity} onChange={set('continuity')} label={t('sp.continuity')}
          hint={t('sp.continuityHint')} />
        <Switch checked={form.burn_subtitles} onChange={set('burn_subtitles')} label={t('sp.burnSubtitles')}
          hint={t('sp.burnSubtitlesHint')} />
        <Switch checked={form.keep_clip_audio} onChange={set('keep_clip_audio')} label={t('sp.keepClipAudio')}
          hint={t('sp.keepClipAudioHint')} />
      </div>

      <div className="row">
        <Button className="primary" icon="check" loading={saving} disabled={!changed || busy} onClick={save}>{t('sp.saveSettings')}</Button>
        {changed && <button className="btn ghost" onClick={() => setForm(pick(project))}>{t('sp.discardChanges')}</button>}
        {busy && <span className="faint small">{t('sp.saveAfterJob')}</span>}
      </div>

      <hr style={{ border: 0, borderTop: '1px solid var(--line)', width: '100%', margin: '4px 0' }} />
      <div className="row between">
        <div className="small"><b>{t('sp.deleteProject')}</b><div className="muted">{t('sp.deleteProjectHint')}</div></div>
        <Button className="danger" icon="trash" disabled={busy} onClick={onDelete}>{t('sp.deleteProject')}</Button>
      </div>
    </div>
  );
}
