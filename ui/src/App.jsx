import React from 'react';
import { api } from './api.js';
import Icon from './components/Icon.jsx';
import { Button, DialogProvider, ToastProvider } from './components/kit.jsx';
import { useI18n } from './i18n.jsx';
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

function readCollapsed() {
  try { return localStorage.getItem('sav-sidebar') === 'collapsed'; } catch { return false; }
}

function useSidebar() {
  const [collapsed, setCollapsed] = React.useState(readCollapsed);
  React.useEffect(() => {
    try { localStorage.setItem('sav-sidebar', collapsed ? 'collapsed' : 'expanded'); } catch { /* private mode */ }
  }, [collapsed]);
  return [collapsed, () => setCollapsed((v) => !v)];
}

function Brand({ compact = false }) {
  const { t } = useI18n();
  return (
    <div className={`brand${compact ? ' compact' : ''}`}>
      <span className="brand-logo"><img src="/logo-sandroid.svg" alt="Sandroid" /></span>
      {!compact && <span>Sandroid<small>{t('brand.subtitle')}</small></span>}
    </div>
  );
}

function LangSwitcher({ collapsed = false }) {
  const { lang, setLang, locales, t } = useI18n();
  return (
    <label className={`lang-switch${collapsed ? ' collapsed' : ''}`} title={t('lang.name')}>
      <Icon name="globe" size={collapsed ? 18 : 16} />
      {collapsed
        ? <span className="lang-short">{locales.find((l) => l.code === lang)?.short}</span>
        : (
          <select value={lang} onChange={(e) => setLang(e.target.value)} aria-label={t('lang.name')}>
            {locales.map((l) => <option key={l.code} value={l.code}>{l.label}</option>)}
          </select>
        )}
    </label>
  );
}

function Login({ onLogin }) {
  const { t } = useI18n();
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
      <div className="login-lang"><LangSwitcher /></div>
      <form onSubmit={submit} className="login card stack">
        <Brand />
        <div>
          <h1>{t(mode === 'login' ? 'login.welcome' : 'login.register')}</h1>
          <p className="muted" style={{ margin: '4px 0 0' }}>
            {t(mode === 'login' ? 'login.hintLogin' : 'login.hintRegister')}
          </p>
        </div>
        <label className="field">{t('login.username')}
          <input autoFocus autoComplete="username" value={form.username}
            onChange={(e) => setForm({ ...form, username: e.target.value })} required />
        </label>
        <label className="field">{t('login.password')}
          <input type="password" autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required />
        </label>
        {error && <div className="alert bad"><Icon name="alert" /><div>{error}</div></div>}
        <Button className="primary lg" type="submit" loading={busy}>
          {t(mode === 'login' ? 'login.submit' : 'login.submitRegister')}
        </Button>
        {registrationOpen && (
          <button type="button" className="btn ghost" onClick={() => setMode(mode === 'login' ? 'register' : 'login')}>
            {t(mode === 'login' ? 'login.switchToRegister' : 'login.switchToLogin')}
          </button>
        )}
      </form>
    </div>
  );
}

function Shell() {
  const { t } = useI18n();
  const route = useHashRoute();
  const [user, setUser] = React.useState(undefined);
  const [theme, toggleTheme] = useTheme();
  const [collapsed, toggleSidebar] = useSidebar();

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
    ['/projects', 'folder', t('nav.projects')],
    ['/settings', 'settings', t('nav.settings')],
    ['/docs', 'book', t('nav.docs')],
    ...(user.role === 'admin' ? [['/admin', 'shield', t('nav.admin')]] : []),
  ];
  const nav = items.map(([path, icon, label]) => (
    <button key={path} className={`nav-item${route.startsWith(path) ? ' active' : ''}`}
      onClick={() => go(path)} title={collapsed ? label : undefined}>
      <Icon name={icon} size={18} /> {!collapsed && <span className="nav-label">{label}</span>}
    </button>
  ));
  const themeLabel = t(theme === 'dark' ? 'theme.toLight' : 'theme.toDark');
  const themeBtn = (
    <button className="btn ghost icon" onClick={toggleTheme} title={themeLabel} aria-label={themeLabel}>
      <Icon name={theme === 'dark' ? 'sun' : 'moon'} size={18} />
    </button>
  );

  return (
    <div className={`app${collapsed ? ' sidebar-collapsed' : ''}`}>
      <aside className="sidebar">
        <div className="sidebar-top">
          {collapsed ? <Brand compact /> : <Brand />}
          <button className="btn ghost icon sidebar-toggle" onClick={toggleSidebar}
            title={t(collapsed ? 'sidebar.expand' : 'sidebar.collapse')}
            aria-label={t(collapsed ? 'sidebar.expand' : 'sidebar.collapse')}>
            <Icon name={collapsed ? 'panel-left-open' : 'panel-left-close'} size={18} />
          </button>
        </div>
        <button className="btn primary new-video" onClick={() => go('/projects?new')}
          title={collapsed ? t('nav.newVideo') : undefined}>
          <Icon name="plus" /> {!collapsed && t('nav.newVideo')}
        </button>
        {nav}
        <div className="sidebar-foot">
          <LangSwitcher collapsed={collapsed} />
          <div className="user-chip">
            <span className="avatar" title={user.username}>{user.username.slice(0, 1)}</span>
            {!collapsed && (
              <span className="grow ellipsis">{user.username}<div className="faint small">{user.role}</div></span>
            )}
            {themeBtn}
          </div>
          <button className="nav-item" onClick={logout} title={collapsed ? t('nav.logout') : undefined}>
            <Icon name="logout" size={18} /> {!collapsed && <span className="nav-label">{t('nav.logout')}</span>}
          </button>
        </div>
      </aside>
      <div className="main">
        <header className="mobile-bar">
          <Brand />
          <LangSwitcher />
          {themeBtn}
          <button className="btn ghost icon" onClick={logout} title={t('nav.logout')} aria-label={t('nav.logout')}>
            <Icon name="logout" size={18} />
          </button>
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
