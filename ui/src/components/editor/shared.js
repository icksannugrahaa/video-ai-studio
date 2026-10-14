// Pure helpers shared by the editor components.

export const JOB_LABEL = {
  plan: 'Menyusun storyboard', render: 'Render video', edit: 'Edit via prompt', regenerate: 'Regenerate scene',
  compose: 'Menggabung video', music_prompt: 'Prompt musik',
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
  done: 'Clip jadi', stale: 'Perlu dibuat ulang', running: 'Sedang dibuat', failed: 'Gagal', pending: 'Belum dibuat',
};

export const totalSeconds = (scenes) => scenes.reduce((a, s) => a + Number(s.duration || 0), 0);

export function isActive(job) {
  return Boolean(job) && (job.status === 'queued' || job.status === 'running');
}
