import React from 'react';
import { fileUrl } from '../../api.js';
import Icon from '../Icon.jsx';
import { sceneState } from './shared.js';
import { useT } from '../../i18n.jsx';

/** One player for the final video, the partial preview, or a single scene clip. */
export default function Player({ project, source, setSource, selected }) {
  const t = useT();
  const bust = project.updated_at;
  const has = (name) => project.files.includes(name);
  const scene = selected != null ? project.scenes[selected] : null;
  const sceneClip = scene?.clip_file && ['done', 'stale'].includes(sceneState(scene)) ? scene.clip_file : null;

  const options = [
    has('final.mp4') && ['final', t('player.final')],
    has('preview.mp4') && ['preview', t('player.preview')],
    scene && ['scene', t('sb.sceneN', { n: selected + 1 })],
  ].filter(Boolean);
  const current = options.some(([id]) => id === source) ? source : options[0]?.[0];

  let src = null;
  let downloads = [];
  if (current === 'final') {
    src = fileUrl(project.id, 'final.mp4', bust);
    downloads = [['final.mp4', 'MP4'], has('final.srt') && ['final.srt', 'SRT']].filter(Boolean);
  } else if (current === 'preview') {
    src = fileUrl(project.id, 'preview.mp4', bust);
    downloads = [['preview.mp4', 'MP4'], has('preview.srt') && ['preview.srt', 'SRT']].filter(Boolean);
  } else if (current === 'scene' && sceneClip) {
    src = fileUrl(project.id, sceneClip, scene.clip_version);
    downloads = [[sceneClip, t('player.clip')]];
  }

  return (
    <div className="card player">
      {options.length > 1 && (
        <div className="player-tabs">
          {options.map(([id, label]) => (
            <button key={id} className={`chip${current === id ? ' active' : ''}`} style={{ padding: '4px 10px', fontSize: 12 }}
              onClick={() => setSource(id)}>{label}</button>
          ))}
        </div>
      )}
      <div className="player-stage" style={{ marginTop: options.length > 1 ? 8 : 0 }}>
        {src ? <video key={src} controls playsInline preload="metadata" src={src} /> : (
          <div className="placeholder">
            <Icon name="film" size={30} strokeWidth={1.4} />
            {current === 'scene'
              ? t('player.sceneMissing', { n: selected + 1, state: sceneState(scene) === 'running' ? t('player.sceneRendering') : t('player.sceneRenderHint') })
              : t('player.empty')}
          </div>
        )}
      </div>
      {downloads.length > 0 && (
        <div className="player-bar">
          {current === 'final' && <span className="badge ok"><span className="dot" />{t('player.readyUpload')}</span>}
          {current === 'preview' && <span className="badge warn"><span className="dot" />{t('player.temporary')}</span>}
          <span className="grow" />
          {downloads.map(([name, label]) => (
            <a key={name} className="btn sm" href={fileUrl(project.id, name, bust)} download>
              <Icon name="download" size={14} /> {label}
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
