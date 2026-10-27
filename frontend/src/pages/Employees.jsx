import { useEffect, useState } from 'react'
import { api, initials } from '../lib'
import { useSession } from '../session'
import { Modal, useLoad, useUi } from '../ui'

export default function Employees() {
  const { roles } = useSession()
  const [rows, reload] = useLoad(() => api('/api/users'), [])
  const [grades] = useLoad(() => api('/api/grades'), [])
  const [edit, setEdit] = useState(null)
  return (<>{grades && !grades.length && <div className="note warn">No expense grades yet. Set them up under <a href="#/grades">Expense policy</a>, then give each employee a grade.</div>}
    <div className="card"><div className="hd"><div><h2>Employees</h2><p className="sub">Every employee is a user. Sales representatives see their own customers, documents and attendance; sales managers their team; administrators everything. The employee code should match the employee or salesperson number in Dynamics.</p></div>
      <button className="btn pri" onClick={() => setEdit({ role: 'rep', active: true, customer_ids: [] })}>Add employee</button></div>
      {!rows ? <div className="loading">Loading…</div> : <div className="scroll"><table className="t"><thead><tr><th>Employee</th><th>Code</th><th>Username</th><th>Role</th><th>Grade</th><th>Reports to</th><th>Customers</th><th>Status</th></tr></thead><tbody>
        {rows.map((u) => <tr key={u.id} className="click" onClick={() => setEdit(u)}><td><div className="tools" style={{ flexWrap: 'nowrap' }}><div className="avatar">{initials(u.name)}</div><div><b>{u.name}</b><div className="fine">{u.email}</div></div></div></td>
          <td className="mono">{u.emp_code}</td><td>{u.username}</td><td>{u.role_label}</td><td>{u.grade || <span className="badge warn">No grade</span>}</td><td>{rows.find((x) => x.id === u.manager_id)?.name || '—'}</td>
          <td>{u.role === 'rep' ? (u.customer_ids.length ? `${u.customer_ids.length} assigned` : 'All') : '—'}</td><td>{u.active ? <span className="badge ok">Active</span> : <span className="badge bad">Inactive</span>}</td></tr>)}</tbody></table></div>}</div>
    <EmployeeDialog u={edit} all={rows || []} grades={grades || []} roles={roles} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); reload() }} /></>)
}

function EmployeeDialog({ u, all, grades, roles, onClose, onSaved }) {
  const { toast } = useUi()
  const [custs] = useLoad(() => (u ? api('/api/customers') : Promise.resolve([])), [!!u])
  const [f, setF] = useState(null); const [err, setErr] = useState(''); const [filter, setFilter] = useState('')
  useEffect(() => {
    if (!u) return
    setF({ _for: u, name: u.name || '', username: u.username || '', password: '', role: u.role || 'rep', emp_code: u.emp_code || '', phone: u.phone || '', email: u.email || '',
      manager_id: u.manager_id || '', territory: u.territory || '', grade: u.grade || '', active: u.active ?? true, customer_ids: u.customer_ids || [] })
    setErr(''); setFilter('')
  }, [u])
  if (!u || !f || f._for !== u) return <Modal open={false} />
  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })
  const save = async (e) => {
    e.preventDefault()
    const body = { ...f, manager_id: f.manager_id ? +f.manager_id : null, grade: f.grade || null, password: f.password || null }
    try { await api(u.id ? `/api/users/${u.id}` : '/api/users', { method: u.id ? 'PATCH' : 'POST', body }); toast('Employee saved'); onSaved() } catch (e2) { setErr(e2.message) }
  }
  const sel = new Set(f.customer_ids)
  return <Modal open onClose={onClose} wide><form className="dlg" onSubmit={save} noValidate><h2>{u.id ? `Edit ${u.name}` : 'Add employee'}</h2>
    <div className="form">
      <label className="field">Full name<input className="inp" name="name" value={f.name} onChange={set('name')} autoFocus /></label>
      <label className="field">Employee code<input className="inp" name="emp_code" value={f.emp_code} onChange={set('emp_code')} placeholder="As in Dynamics" /></label>
      <label className="field">Mobile<input className="inp" value={f.phone} onChange={set('phone')} /></label>
      <label className="field">E-mail<input className="inp" value={f.email} onChange={set('email')} /></label>
      <label className="field">Username<input className="inp" name="username" value={f.username} onChange={set('username')} autoCapitalize="none" /></label>
      <label className="field">{u.id ? 'New password (leave empty to keep)' : 'Password (at least 8 characters)'}<input className="inp" name="password" type="password" value={f.password} onChange={set('password')} autoComplete="new-password" /></label>
      <label className="field">Role<select className="inp" name="role" value={f.role} onChange={set('role')}>{Object.entries(roles).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
      <label className="field">Reports to<select className="inp" value={f.manager_id} onChange={set('manager_id')}><option value="">No one</option>{all.filter((x) => x.role !== 'rep' && x.id !== u.id).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
      <label className="field">Territory / beat<input className="inp" value={f.territory} onChange={set('territory')} /></label>
      <label className="field">Grade (expense policy)<select className="inp" name="grade" value={f.grade} onChange={set('grade')}><option value="">No grade: cannot claim expenses</option>{grades.map((g) => <option key={g.code} value={g.code}>{g.code} {g.name}</option>)}</select></label>
      <label className="chk"><input type="checkbox" checked={f.active} onChange={set('active')} /> Can sign in</label></div>
    {f.role === 'rep' && <fieldset style={{ border: '1px solid var(--rule)', borderRadius: 9, padding: '10px 12px' }}><legend className="fine" style={{ fontWeight: 700 }}>Customers</legend>
      <p className="fine" style={{ margin: '0 0 8px' }}>Tick the customers this person serves. With none ticked, they can sell to every customer.</p>
      <input className="inp" placeholder="Filter customers" value={filter} onChange={(e) => setFilter(e.target.value)} style={{ width: '100%', marginBottom: 6 }} />
      <div style={{ maxHeight: 200, overflow: 'auto', display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(220px,1fr))', gap: '2px 12px' }}>
        {(custs || []).filter((c) => !filter || `${c.code} ${c.name} ${c.city}`.toLowerCase().includes(filter.toLowerCase())).map((c) => <label key={c.id} className="chk"><input type="checkbox" checked={sel.has(c.id)}
          onChange={(e) => setF({ ...f, customer_ids: e.target.checked ? [...f.customer_ids, c.id] : f.customer_ids.filter((x) => x !== c.id) })} /> {c.code} {c.name}</label>)}</div></fieldset>}
    <p className="err">{err}</p><div className="btns"><button type="button" className="btn ghost" onClick={onClose}>Cancel</button><button className="btn pri">Save</button></div></form></Modal>
}
