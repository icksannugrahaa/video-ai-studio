// Tells the user a long job needs them. The toast covers a visible tab; a hidden
// one gets a system notification, plus a title mark because system notifications
// need HTTPS and do not work on Android without a service worker.
const MARK = '● ';

export function askNotifyPermission() {
  if (typeof Notification !== 'undefined' && Notification.permission === 'default') {
    Notification.requestPermission().catch(() => {});
  }
}

export function alertHidden(title, body) {
  if (!document.hidden) return;
  if (!document.title.startsWith(MARK)) {
    document.title = MARK + document.title;
    document.addEventListener('visibilitychange', () => {
      document.title = document.title.replace(MARK, '');
    }, { once: true });
  }
  if (typeof Notification === 'undefined' || Notification.permission !== 'granted') return;
  try {
    const shown = new Notification(title, { body, icon: '/logo-sandroid.png' });
    shown.onclick = () => { window.focus(); shown.close(); };
  } catch { /* mobile browsers only allow this from a service worker */ }
}

// What changed since the previous poll and is worth telling: `before` holds the
// job that was running and the clip counts seen then.
export function pickNotice(before, project) {
  if (!before) return null;
  const finished = before.jobId && project.jobs.find((j) => j.id === before.jobId);
  if (finished && finished.status === 'failed') return { key: 'notify.failed', tone: 'bad', msg: finished.message };
  if (finished && finished.status === 'succeeded') {
    if ((finished.result?.files || []).includes('final.mp4')) return { key: 'notify.final', tone: 'ok' };
    if (finished.kind === 'plan') return { key: 'notify.planned', tone: 'ok' };
  }
  const total = project.scenes.length;
  if (total && before.total === total && before.ready < total && project.clips_ready === total) {
    return { key: project.active_job ? 'notify.clipsMerging' : 'notify.clipsReady', tone: 'ok' };
  }
  return null;
}
