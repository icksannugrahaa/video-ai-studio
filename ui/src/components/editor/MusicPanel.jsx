import React from 'react';
import { api, fileUrl } from '../../api.js';
import Icon from '../Icon.jsx';
import { Button, CopyButton, Dropzone, fmtClock } from '../kit.jsx';
import { totalSeconds } from './shared.js';
import { useT } from '../../i18n.jsx';

const GEMINI_URL = 'https://gemini.google.com/app';
const MODES = [
  ['none', 'x', 'music.modeNone', 'music.modeNoneDesc'],
  ['external', 'music', 'music.modeExternal', 'music.modeExternalDesc'],
  ['generate', 'sparkles', 'music.modeGenerate', 'music.modeGenerateDesc'],
];
const STYLES = [
  ['instrumental', 'volume', 'music.styleInstrumental', 'music.styleInstrumentalDesc'],
  ['song', 'mic', 'music.styleSong', 'music.styleSongDesc'],
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
  const t = useT();
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
  const save = (options, msg = t('music.savedDefault')) => run(() => api.patch(`/projects/${id}`, { options }), msg);

  async function generate(path, msg) {
    setGenerating(true);
    await run(() => api.post(`/projects/${id}/${path}`, { hint }), msg);
    setGenerating(false);
  }

  async function upload(file) {
    if (file.size > 30 * 1024 * 1024) { toast(t('music.fileTooLarge'), 'bad'); return; }
    setUploading(true);
    await run(() => api.upload(`/projects/${id}/music`, file), t('music.uploaded', { name: file.name }));
    setUploading(false);
  }

  return (
    <div className="stack" style={{ gap: 20 }}>
      {busy && (
        <div className="alert info"><Icon name="info" /><div>
          {t('music.busyNote')}
        </div></div>
      )}

      <div>
        <div className="opt-label">{t('music.modeLabel')}</div>
        <div className="choices">
          {MODES.map(([value, icon, title, desc]) => (
            <Choice key={value} active={o.music_mode === value} icon={icon} title={t(title)} desc={t(desc)}
              disabled={value === 'generate'} onClick={() => save({ music_mode: value })} />
          ))}
        </div>
      </div>

      {o.music_mode !== 'none' && (
        <div>
          <div className="opt-label">{t('music.typeLabel')}</div>
          <div className="choices">
            {STYLES.map(([value, icon, title, desc]) => (
              <Choice key={value} active={(o.music_style || 'instrumental') === value} icon={icon} title={t(title)} desc={t(desc)}
                onClick={() => save({ music_style: value })} />
            ))}
          </div>
        </div>
      )}

      {o.music_mode === 'external' && (
        <div className="steps">
          {song && (
            <div className="s"><div>
              <h3>{t('music.lyricsTitle')}</h3>
              <p className="muted small" style={{ margin: 0 }}>
                {t('music.lyricsHint1')} <code>[m:ss] {t('music.lyricsHintText')}</code>{t('music.lyricsHint2')}
              </p>
              <div className="row">
                <input className="grow" style={{ minWidth: 200 }} value={hint} placeholder={t('music.songHintPlaceholder')}
                  onChange={(e) => setHint(e.target.value)} />
                <Button className="primary" icon="sparkles" loading={generating} disabled={!project.scenes.length}
                  onClick={() => generate('song', t('music.lyricsReady'))}>
                  {generating ? t('music.writing') : o.lyrics ? t('music.rewrite') : t('music.generateLyrics')}
                </Button>
              </div>
              <textarea rows={10} className="mono" value={lyrics} placeholder={t('music.lyricsPlaceholder')}
                onChange={(e) => setLyrics(e.target.value)} />
              {lyrics !== (o.lyrics || '') && (
                <div className="row"><Button className="sm primary" icon="check" onClick={() => save({ lyrics }, t('music.lyricsSaved'))}>{t('music.saveLyrics')}</Button>
                  <button className="btn ghost sm" onClick={() => setLyrics(o.lyrics || '')}>{t('action.discard')}</button></div>
              )}
            </div></div>
          )}

          <div className="s"><div>
            <h3>{song ? t('music.copyPromptSong') : t('music.copyPromptMusic')}</h3>
            <p className="muted small" style={{ margin: 0 }}>
              {t('music.copyPromptHint1')}<b>{fmtClock(total)}</b>{t('music.copyPromptHint2')}
            </p>
            <textarea rows={5} value={prompt}
              placeholder={project.scenes.length ? t('music.promptPlaceholderReady') : t('music.promptPlaceholderEmpty')}
              onChange={(e) => setPrompt(e.target.value)} />
            <div className="row">
              <CopyButton text={prompt} label={t('music.copyPrompt')} className="primary" />
              <a className="btn" href={GEMINI_URL} target="_blank" rel="noreferrer"><Icon name="external" /> {t('music.openGemini')}</a>
              {prompt !== (o.music_prompt || '') && <Button icon="check" onClick={() => save({ music_prompt: prompt }, t('music.promptSaved'))}>{t('action.save')}</Button>}
            </div>
            {!song && (
              <div className="row">
                <input className="grow" style={{ minWidth: 200 }} value={hint} placeholder={t('music.extraHintPlaceholder')}
                  onChange={(e) => setHint(e.target.value)} />
                <Button icon="refresh" loading={generating} disabled={!project.scenes.length}
                  onClick={() => generate('music-prompt', t('music.promptReady'))}>
                  {generating ? t('music.generatingPrompt') : t('music.regenPrompt')}
                </Button>
              </div>
            )}
          </div></div>

          <div className="s"><div>
            <h3>{t('music.uploadTitle')}</h3>
            {o.music_file ? (
              <div className="audio-file">
                <Icon name="music" />
                <span className="small"><b>{o.music_file}</b></span>
                <audio controls preload="none" src={fileUrl(id, o.music_file, project.updated_at)} />
                <Button className="sm danger" icon="trash" onClick={() => run(() => api.del(`/projects/${id}/music`), t('music.deleted'))}>{t('action.delete')}</Button>
              </div>
            ) : null}
            <Dropzone accept="audio/*" onFile={upload} disabled={uploading}>
              {uploading ? <span>{t('music.uploading')}</span> : (
                <span><b>{o.music_file ? t('music.replaceFile') : t('music.dropFile')}</b> {t('music.orClick')}
                  <br /><span className="faint small">{t('music.fileTypes')}</span></span>
              )}
            </Dropzone>
          </div></div>
        </div>
      )}

      {o.music_mode !== 'none' && !song && (
        <label className="field" style={{ maxWidth: 420 }}>
          <span className="row between">{t('music.volumeLabel')} <b style={{ color: 'var(--text)' }}>{Math.round(o.music_volume * 100)}%</b></span>
          <input type="range" min={0} max={1} step={0.05} value={o.music_volume}
            onChange={(e) => setOption('music_volume', Number(e.target.value))}
            onMouseUp={(e) => save({ music_volume: Number(e.target.value) }, t('music.volumeSaved'))}
            onTouchEnd={(e) => save({ music_volume: Number(e.target.value) }, t('music.volumeSaved'))}
            onKeyUp={(e) => save({ music_volume: Number(e.target.value) }, t('music.volumeSaved'))} />
          <span className="hint">{t('music.volumeHint')}</span>
        </label>
      )}

      {allClips && (
        <div className="card flat row between" style={{ margin: 0 }}>
          <div className="small">
            <b>{t('music.applyTitle')}</b>
            <div className="muted">{busy ? t('music.applyBusy') : t('music.applyHint')}</div>
          </div>
          <Button className="primary" icon="layers" disabled={busy}
            onClick={() => run(() => api.post(`/projects/${id}/compose`), t('music.composing'))}>{t('music.recompose')}</Button>
        </div>
      )}
    </div>
  );
}
