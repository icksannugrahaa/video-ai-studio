import React from 'react';
import { api } from './api.js';
import Icon from './components/Icon.jsx';
import { Button, DialogProvider, ToastProvider } from './components/kit.jsx';
import Projects from './pages/Projects.jsx';
import ProjectEditor from './pages/ProjectEditor.jsx';
import Settings from './pages/Settings.jsx';
import Admin from './pages/Admin.jsx';
import ApiDocs from './pages/ApiDocs.jsx';

function useHashRoute() {
  const [hash, setHash] = React.useState(window.location.hash || '#/projects');
  React.useEffect(() => {
    const onChange = () => setHash(window.location.hash || '#/projects');
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, []);
  return hash.replace(/^#/, '');
}

export const go = (path) => { window.location.hash = path; };

function readTheme() {
  try { return localStorage.getItem('sav-theme') || 'dark'; } catch { return 'dark'; }
}

function useTheme() {
  const [theme, setTheme] = React.useState(readTheme);
  React.useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem('sav-theme', theme); } catch { /* private mode */ }
  }, [theme]);
  return [theme, () => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))];
}

function Brand() {
  return (
    <div className="brand">
      <span className="brand-logo"><Icon name="film" size={17} /></span>
      <span>Sandroid<small>AI Video Studio</small></span>
    </div>
  );
}

function Login({ onLogin }) {
  const [mode, setMode] = React.useState('login');
  const [form, setForm] = React.useState({ username: '', password: '' });
  const [error, setError] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [registrationOpen, setRegistrationOpen] = React.useState(false);
  React.useEffect(() => {
    api.get('/auth/config').then((c) => setRegistrationOpen(c.registration_open)).catch(() => {});
  }, []);

  async function submit(e) {
    e.preventDefault();
    setError('');
    setBusy(true);
    try {
      onLogin(await api.post(mode === 'login' ? '/auth/login' : '/auth/register', form));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <form onSubmit={submit} className="login card stack">
        <Brand />
        <div>
          <h1>{mode === 'login' ? 'Selamat datang' : 'Buat akun'}</h1>
          <p className="muted" style={{ margin: '4px 0 0' }}>
            {mode === 'login' ? 'Masuk untuk lanjut membuat video.' : 'Daftar untuk mulai membuat video dari prompt.'}
          </p>
        </div>
        <label className="field">Username
          <input autoFocus autoComplete="username" value={form.username}
            onChange={(e) => setForm({ ...form, username: e.target.value })} required />
        </label>
        <label className="field">Password
          <input type="password" autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required />
        </label>
        {error && <div className="alert bad"><Icon name="alert" /><div>{error}</div></div>}
        <Button className="primary lg" type="submit" loading={busy}>{mode === 'login' ? 'Masuk' : 'Daftar'}</Button>
        {registrationOpen && (
          <button type="button" className="btn ghost" onClick={() => setMode(mode === 'login' ? 'register' : 'login')}>
            {mode === 'login' ? 'Belum punya akun? Daftar' : 'Sudah punya akun? Masuk'}
          </button>
        )}
      </form>
    </div>
  );
}

function Shell() {
  const route = useHashRoute();
  const [user, setUser] = React.useState(undefined);
  const [theme, toggleTheme] = useTheme();

  React.useEffect(() => {
    api.get('/auth/me').then(setUser).catch(() => setUser(null));
  }, []);

  if (user === undefined) {
    return <div className="login-wrap"><Icon name="loader" size={28} className="spin" /></div>;
  }
  if (!user) return <Login onLogin={setUser} />;

  async function logout() {
    await api.post('/auth/logout').catch(() => {});
    setUser(null);
  }

  const projectMatch = route.match(/^\/projects\/(\d+)/);
  let page;
  if (projectMatch) page = <ProjectEditor key={projectMatch[1]} projectId={Number(projectMatch[1])} />;
  else if (route.startsWith('/settings')) page = <Settings />;
  else if (route.startsWith('/docs')) page = <ApiDocs />;
  else if (route.startsWith('/admin') && user.role === 'admin') page = <Admin me={user} />;
  else page = <Projects />;

  const items = [
    ['/projects', 'folder', 'Project'],
    ['/settings', 'settings', 'Pengaturan'],
    ['/docs', 'book', 'API'],
    ...(user.role === 'admin' ? [['/admin', 'shield', 'Admin']] : []),
  ];
  const nav = items.map(([path, icon, label]) => (
    <button key={path} className={`nav-item${route.startsWith(path) ? ' active' : ''}`} onClick={() => go(path)}>
      <Icon name={icon} size={18} /> {label}
    </button>
  ));
  const themeBtn = (
    <button className="btn ghost icon" onClick={toggleTheme} title={theme === 'dark' ? 'Tema terang' : 'Tema gelap'}>
      <Icon name={theme === 'dark' ? 'sun' : 'moon'} size={18} />
    </button>
  );

  return (
    <div className="app">
      <aside className="sidebar">
        <Brand />
        <button className="btn primary" style={{ marginBottom: 12 }} onClick={() => go('/projects?new')}>
          <Icon name="plus" /> Video baru
        </button>
        {nav}
        <div className="sidebar-foot">
          <div className="user-chip">
            <span className="avatar">{user.username.slice(0, 1)}</span>
            <span className="grow ellipsis">{user.username}<div className="faint small">{user.role}</div></span>
            {themeBtn}
          </div>
          <button className="nav-item" onClick={logout}><Icon name="logout" size={18} /> Keluar</button>
        </div>
      </aside>
      <div className="main">
        <header className="mobile-bar">
          <Brand />
          {themeBtn}
          <button className="btn ghost icon" onClick={logout} title="Keluar"><Icon name="logout" size={18} /></button>
        </header>
        <main className="page">{page}</main>
        <nav className="bottom-nav">{nav}</nav>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <ToastProvider>
      <DialogProvider>
        <Shell />
      </DialogProvider>
    </ToastProvider>
  );
}
