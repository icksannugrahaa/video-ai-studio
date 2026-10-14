import React from 'react';
import { api } from '../api.js';
import Icon from '../components/Icon.jsx';
import { Button, StatusBadge, Switch, timeAgo, useDialog, useToast } from '../components/kit.jsx';
import { useT, useI18n } from '../i18n.jsx';

export default function Admin({ me }) {
  const t = useT();
  const { lang } = useI18n();
  const toast = useToast();
  const dialog = useDialog();
  const [users, setUsers] = React.useState([]);
  const [registrationOpen, setRegistrationOpen] = React.useState(false);
  const [form, setForm] = React.useState({ username: '', password: '', role: 'user' });
  const [adding, setAdding] = React.useState(false);

  const load = React.useCallback(() => Promise.all([api.get('/users'), api.get('/settings')])
    .then(([u, s]) => { setUsers(u); setRegistrationOpen(s.registration_open); })
    .catch((e) => toast(e.message, 'bad')), [toast]);
  React.useEffect(() => { load(); }, [load]);

  const act = (fn, msg) => fn().then(() => { if (msg) toast(msg, 'ok'); return load(); }).catch((e) => toast(e.message, 'bad'));

  async function resetPassword(u) {
    const password = await dialog.prompt({ title: t('admin.resetPasswordTitle', { name: u.username }), body: t('admin.resetPasswordBody'), input: 'password', confirmLabel: t('action.save') });
    if (password) act(() => api.patch(`/users/${u.id}`, { password }), t('admin.passwordChanged'));
  }

  return (
    <>
      <div className="page-head">
        <div><h1>{t('admin.title')}</h1><p className="muted">{t('admin.subtitle')}</p></div>
        <Button className="primary" icon="plus" onClick={() => setAdding((v) => !v)}>{t('admin.addUser')}</Button>
      </div>

      <div className="card">
        <Switch checked={registrationOpen} label={t('admin.allowRegistration')}
          hint={t('admin.allowRegistrationHint')}
          onChange={(v) => act(() => api.put('/settings', { registration_open: v }), v ? t('admin.registrationOpen') : t('admin.registrationClosed'))} />
      </div>

      {adding && (
        <form className="card stack" style={{ borderColor: 'var(--accent)' }} onSubmit={(e) => {
          e.preventDefault();
          act(() => api.post('/users', form).then(() => { setForm({ username: '', password: '', role: 'user' }); setAdding(false); }), t('admin.userCreated', { name: form.username }));
        }}>
          <h2>{t('admin.newUser')}</h2>
          <div className="grid">
            <label className="field">{t('login.username')}<input autoFocus value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} required /></label>
            <label className="field"><span>{t('login.password')} <span className="hint">{t('admin.passwordMin')}</span></span>
              <input type="password" minLength={8} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required /></label>
            <label className="field">{t('admin.role')}
              <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                <option value="user">user</option><option value="admin">admin</option>
              </select>
            </label>
          </div>
          <div className="row">
            <Button className="primary" icon="check" type="submit">{t('admin.createUser')}</Button>
            <button type="button" className="btn ghost" onClick={() => setAdding(false)}>{t('action.cancel')}</button>
          </div>
        </form>
      )}

      <div className="card">
        <div className="card-head"><h2>{t('admin.users')}</h2><span className="badge">{users.length}</span></div>
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>{t('admin.colUser')}</th><th>{t('admin.colRole')}</th><th>{t('admin.colStatus')}</th><th>{t('admin.colJoined')}</th><th /></tr></thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id}>
                  <td><span className="row"><span className="avatar">{u.username.slice(0, 1)}</span><strong>{u.username}</strong>{u.id === me.id && <span className="faint small">{t('admin.you')}</span>}</span></td>
                  <td><span className={`badge${u.role === 'admin' ? ' accent' : ''}`}>{u.role === 'admin' && <Icon name="shield" size={11} />}{u.role}</span></td>
                  <td>{u.active ? <StatusBadge status="succeeded" label={t('admin.active')} /> : <StatusBadge status="failed" label={t('admin.inactive')} />}</td>
                  <td className="muted">{timeAgo(u.created_at, t, lang === 'en' ? 'en-US' : 'id-ID')}</td>
                  <td style={{ textAlign: 'right' }}>
                    {u.id !== me.id && (
                      <span className="row" style={{ justifyContent: 'flex-end' }}>
                        <Button className="sm" icon="key" onClick={() => resetPassword(u)}>{t('admin.resetPassword')}</Button>
                        <Button className={`sm${u.active ? ' danger' : ''}`} onClick={() => act(() => api.patch(`/users/${u.id}`, { active: !u.active }), u.active ? t('admin.userDeactivated') : t('admin.userActivated'))}>
                          {u.active ? t('admin.deactivate') : t('admin.activate')}
                        </Button>
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
