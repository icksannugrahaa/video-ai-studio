// Pure helpers shared by the editor components.

export const JOB_LABEL = {
  plan: 'job.kind.plan', render: 'job.kind.render', edit: 'job.kind.edit', regenerate: 'job.kind.regenerate',
  compose: 'job.kind.compose', music_prompt: 'job.kind.music_prompt', preview: 'job.kind.preview',
};

export const RESUMABLE = ['render', 'edit', 'regenerate'];

/** done | stale (edited after its clip was made) | running | failed | pending */
export function sceneState(scene) {
  if (scene.clip_status === 'done') return scene.clip_version === scene.version ? 'done' : 'stale';
  if (scene.clip_status === 'running') return 'running';
  if (scene.clip_status === 'failed') return 'failed';
  return 'pending';
}

export const SCENE_LABEL = {
  done: 'sb.stateDone', stale: 'sb.stateStale', running: 'sb.stateRunning', failed: 'sb.stateFailed', pending: 'sb.statePending',
};

export const totalSeconds = (scenes) => scenes.reduce((a, s) => a + Number(s.duration || 0), 0);

export function isActive(job) {
  return Boolean(job) && (job.status === 'queued' || job.status === 'running');
}
