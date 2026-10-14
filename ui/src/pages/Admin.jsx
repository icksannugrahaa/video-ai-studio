import React from 'react';
import { api } from '../api.js';
import Icon from '../components/Icon.jsx';
import { Button, StatusBadge, Switch, timeAgo, useDialog, useToast } from '../components/kit.jsx';

export default function Admin({ me }) {
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
    const password = await dialog.prompt({ title: `Reset password ${u.username}`, body: 'Password baru minimal 8 karakter.', input: 'password', confirmLabel: 'Simpan' });
    if (password) act(() => api.patch(`/users/${u.id}`, { password }), 'Password diganti.');
  }

  return (
    <>
      <div className="page-head">
        <div><h1>Admin</h1><p className="muted">Kelola user dan akses pendaftaran.</p></div>
        <Button className="primary" icon="plus" onClick={() => setAdding((v) => !v)}>Tambah user</Button>
      </div>

      <div className="card">
        <Switch checked={registrationOpen} label="Izinkan registrasi publik"
          hint="Jika aktif, siapa pun yang membuka halaman login bisa membuat akun sendiri."
          onChange={(v) => act(() => api.put('/settings', { registration_open: v }), v ? 'Registrasi dibuka.' : 'Registrasi ditutup.')} />
      </div>

      {adding && (
        <form className="card stack" style={{ borderColor: 'var(--accent)' }} onSubmit={(e) => {
          e.preventDefault();
          act(() => api.post('/users', form).then(() => { setForm({ username: '', password: '', role: 'user' }); setAdding(false); }), `User ${form.username} dibuat.`);
        }}>
          <h2>User baru</h2>
          <div className="grid">
            <label className="field">Username<input autoFocus value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} required /></label>
            <label className="field"><span>Password <span className="hint">— min. 8 karakter</span></span>
              <input type="password" minLength={8} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required /></label>
            <label className="field">Role
              <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                <option value="user">user</option><option value="admin">admin</option>
              </select>
            </label>
          </div>
          <div className="row">
            <Button className="primary" icon="check" type="submit">Buat user</Button>
            <button type="button" className="btn ghost" onClick={() => setAdding(false)}>Batal</button>
          </div>
        </form>
      )}

      <div className="card">
        <div className="card-head"><h2>User</h2><span className="badge">{users.length}</span></div>
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>User</th><th>Role</th><th>Status</th><th>Bergabung</th><th /></tr></thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id}>
                  <td><span className="row"><span className="avatar">{u.username.slice(0, 1)}</span><strong>{u.username}</strong>{u.id === me.id && <span className="faint small">(kamu)</span>}</span></td>
                  <td><span className={`badge${u.role === 'admin' ? ' accent' : ''}`}>{u.role === 'admin' && <Icon name="shield" size={11} />}{u.role}</span></td>
                  <td>{u.active ? <StatusBadge status="succeeded" label="Aktif" /> : <StatusBadge status="failed" label="Nonaktif" />}</td>
                  <td className="muted">{timeAgo(u.created_at)}</td>
                  <td style={{ textAlign: 'right' }}>
                    {u.id !== me.id && (
                      <span className="row" style={{ justifyContent: 'flex-end' }}>
                        <Button className="sm" icon="key" onClick={() => resetPassword(u)}>Reset password</Button>
                        <Button className={`sm${u.active ? ' danger' : ''}`} onClick={() => act(() => api.patch(`/users/${u.id}`, { active: !u.active }), u.active ? 'User dinonaktifkan.' : 'User diaktifkan.')}>
                          {u.active ? 'Nonaktifkan' : 'Aktifkan'}
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
