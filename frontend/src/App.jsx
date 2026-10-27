import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, getToken, initials, setToken, setUnauthorizedHandler } from './lib'
import { SessionContext } from './session'
import { Modal, UiProvider, useUi } from './ui'
import Dashboard from './pages/Dashboard'
import TimeClock, { MyDay } from './pages/TimeClock'
import Attendance from './pages/Attendance'
import { DocList, DocEditor } from './pages/Docs'
import { PaymentList, PaymentForm } from './pages/Payments'
import Customers from './pages/Customers'
import { Materials, Prices, Hsn, Charges } from './pages/Masters'
import { ExpenseList, ExpenseForm, Grades } from './pages/Expenses'
import Employees from './pages/Employees'
import Integration from './pages/Integration'
import Settings from './pages/Settings'

const ALL = ['admin', 'manager', 'rep']
const NAV = [
  { id: 'dashboard', label: 'Dashboard', roles: ['admin', 'manager'] },
  { id: 'myday', label: 'My day', roles: ['rep'] },
  { id: 'timeclock', label: 'Time in / Time out', roles: ALL },
  { id: 'attendance', label: 'Attendance', roles: ALL, badge: 'attendance' },
  { grp: 'Sales' },
  { id: 'quotes', label: 'Quotations', roles: ALL },
  { id: 'orders', label: 'Sales orders', roles: ALL, badge: 'orders' },
  { id: 'payments', label: 'Payments', roles: ALL },
  { id: 'customers', label: 'Customers', roles: ALL },
  { grp: 'Expenses' },
  { id: 'expenses', label: 'Expense claims', roles: ALL, badge: 'expenses' },
  { id: 'grades', label: 'Expense policy', roles: ['admin'] },
  { grp: 'Masters from Dynamics' },
  { id: 'materials', label: 'Materials', roles: ALL },
  { id: 'prices', label: 'Price lists', roles: ['admin', 'manager'] },
  { id: 'hsn', label: 'HSN and GST', roles: ['admin', 'manager'] },
  { id: 'charges', label: 'Charges', roles: ['admin', 'manager'] },
  { grp: 'Administration' },
  { id: 'employees', label: 'Employees and users', roles: ['admin'], badge: 'employees' },
  { id: 'integration', label: 'Dynamics sync', roles: ['admin'], badge: 'integration' },
  { id: 'settings', label: 'Settings', roles: ['admin'] },
]
const BOTTOM = {
  rep: [['myday', 'My day'], ['timeclock', 'Time in/out'], ['orders', 'Orders'], ['payment/new', 'Payment'], ['expenses', 'Expenses']],
  manager: [['dashboard', 'Dashboard'], ['timeclock', 'Time in/out'], ['orders', 'Orders'], ['expenses', 'Expenses']],
  admin: [['dashboard', 'Dashboard'], ['timeclock', 'Time in/out'], ['orders', 'Orders'], ['integration', 'Sync']],
}

function parseHash() {
  const raw = window.location.hash.replace(/^#\/?/, '')
  const [path, query] = raw.split('?')
  const [page, arg] = path.split('/')
  return { page: page || '', arg: arg || '', q: new URLSearchParams(query || '') }
}
export const go = (h) => { if (window.location.hash === h) window.dispatchEvent(new HashChangeEvent('hashchange')); else window.location.hash = h }

export default function App() { return <UiProvider><Root /></UiProvider> }

function Root() {
  const [stage, setStage] = useState('loading')
  const [me, setMe] = useState(null)
  const [msg, setMsg] = useState('')
  const [company, setCompany] = useState('Sales Portal')
  const signOutLocal = useCallback((m = '') => { setToken(null); setMe(null); setMsg(m); setStage('login') }, [])
  useEffect(() => {
    setUnauthorizedHandler((m) => signOutLocal(m))
    ;(async () => {
      try {
        const st = await api('/api/auth/status'); setCompany(st.company)
        if (getToken()) { setMe(await api('/api/auth/me')); setStage('ready'); return }
        setStage(st.needs_setup ? 'setup' : 'login')
      } catch (e) { if (e.status !== 401) { setMsg(e.message); setStage('login') } }
    })()
  }, [signOutLocal])
  if (stage === 'loading') return <div className="loading">Loading…</div>
  if (stage !== 'ready') return <SignIn mode={stage} company={company} message={msg} onDone={(d) => {
    setToken(d.token); setMe(d); setMsg(''); setStage('ready')
    history.replaceState(null, '', '#/' + (d.user.role === 'rep' ? 'myday' : 'dashboard'))
  }} />
  return <Shell me={me} setMe={setMe} onSignOut={() => signOutLocal()} />
}

function SignIn({ mode, company, message, onDone }) {
  const setup = mode === 'setup'
  const [view, setView] = useState('login')          // login | register (ignored during first setup)
  const register = !setup && view === 'register'
  const blank = { name: '', username: '', phone: '', password: '', password2: '', company }
  const [f, setF] = useState(blank)
  const [err, setErr] = useState(message)
  const [info, setInfo] = useState('')
  const [busy, setBusy] = useState(false)
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  const switchTo = (v) => { setView(v); setErr(''); setInfo(''); setF({ ...blank, username: v === 'login' ? f.username : '' }) }
  const submit = async (e) => {
    e.preventDefault()
    if ((setup || register) && f.password !== f.password2) return setErr('The passwords do not match.')
    setErr(''); setBusy(true)
    try {
      if (register) {
        const r = await api('/api/auth/register', { method: 'POST', body: { name: f.name, username: f.username, phone: f.phone, password: f.password } })
        setView('login'); setF({ ...blank, username: f.username }); setInfo(r.message)
        return
      }
      onDone(await api(setup ? '/api/auth/setup' : '/api/auth/login', { method: 'POST',
        body: setup ? { name: f.name, username: f.username, password: f.password, company: f.company } : { username: f.username, password: f.password } }))
    } catch (e2) { setErr(e2.message) } finally { setBusy(false) }
  }
  const heading = setup ? 'Create the administrator' : register ? 'Create an account' : 'Sign in'
  const lead = setup ? 'First use. The administrator adds employees, who sign in with their own username.'
    : register ? 'Your account can be used once an administrator approves it.'
      : 'Use the username and password your administrator gave you.'
  return (
    <div className="login"><form onSubmit={submit} noValidate key={register ? 'r' : 'l'}>
      <div className="brand-login"><img src="/logo.png" alt={company} /><small>Sales portal</small></div>
      <div className="login-head"><h1>{heading}</h1><p className="fine">{lead}</p></div>
      {info && <p className="note ok" role="status">{info}</p>}
      {setup && <label className="field">Company name<input className="inp" value={f.company} onChange={set('company')} /></label>}
      {(setup || register) && <label className="field">Full name<input className="inp" value={f.name} onChange={set('name')} autoComplete="name" autoFocus /></label>}
      <label className="field">Username<input className="inp" id="lUser" placeholder={register ? 'Your e-mail works well' : undefined} value={f.username} onChange={set('username')} autoCapitalize="none" autoComplete="username" autoFocus={!setup && !register} /></label>
      {register && <label className="field">Mobile<input className="inp" type="tel" value={f.phone} onChange={set('phone')} autoComplete="tel" /></label>}
      <label className="field">Password<input className="inp" id="lPw" type="password" placeholder={setup || register ? 'At least 8 characters' : undefined} value={f.password} onChange={set('password')} autoComplete={setup || register ? 'new-password' : 'current-password'} /></label>
      {(setup || register) && <label className="field">Repeat password<input className="inp" type="password" value={f.password2} onChange={set('password2')} autoComplete="new-password" /></label>}
      <p className="err">{err}</p>
      <button className="btn pri lg" disabled={busy}>{setup ? 'Create and sign in' : register ? 'Register' : 'Sign in'}</button>
      {!setup && <div className="login-alt">
        <span>{register ? 'Already have an account?' : 'New here?'}</span>
        <button type="button" className="btn lg" onClick={() => switchTo(register ? 'login' : 'register')}>{register ? 'Back to sign in' : 'Register'}</button>
      </div>}
    </form></div>)
}

function Shell({ me, setMe, onSignOut }) {
  const { toast } = useUi()
  const [route, setRoute] = useState(parseHash())
  const [counts, setCounts] = useState({})
  const [open, setOpen] = useState(false)
  const [pwOpen, setPwOpen] = useState(false)
  const role = me.user.role
  const refreshCounts = useCallback(() => { api('/api/counts').then(setCounts).catch(() => {}) }, [])
  useEffect(() => { const h = () => { setRoute(parseHash()); setOpen(false); refreshCounts() }; window.addEventListener('hashchange', h); refreshCounts(); return () => window.removeEventListener('hashchange', h) }, [refreshCounts])
  const reloadMe = useCallback(async () => setMe(await api('/api/auth/me')), [setMe])
  const session = useMemo(() => ({ me, user: me.user, settings: me.settings, states: me.states, roles: me.roles, role, isAdmin: role === 'admin',
    isMgr: role !== 'rep', reloadMe, refreshCounts }), [me, role, reloadMe, refreshCounts])
  const home = role === 'rep' ? 'myday' : 'dashboard'
  let page = route.page || home
  const nav = NAV.find((n) => n.id === page)
  if (nav && !nav.roles.includes(role)) page = home
  const P = { route }
  const views = {
    dashboard: () => <Dashboard />, myday: () => <MyDay />, timeclock: () => <TimeClock />, attendance: () => <Attendance {...P} />,
    quotes: () => <DocList kind="quote" {...P} />, orders: () => <DocList kind="order" {...P} />,
    quote: () => <DocEditor kind="quote" {...P} />, order: () => <DocEditor kind="order" {...P} />,
    payments: () => <PaymentList {...P} />, payment: () => <PaymentForm {...P} />, customers: () => <Customers {...P} />,
    expenses: () => <ExpenseList {...P} />, expense: () => <ExpenseForm {...P} />, grades: () => <Grades />,
    materials: () => <Materials {...P} />, prices: () => <Prices {...P} />, hsn: () => <Hsn />, charges: () => <Charges />,
    employees: () => <Employees />, integration: () => <Integration />, settings: () => <Settings />,
  }
  const titles = { quote: route.arg === 'new' ? 'New quotation' : 'Edit quotation', order: route.arg === 'new' ? 'New sales order' : 'Edit sales order',
    payment: 'Receive payment', expense: route.arg === 'new' ? 'New expense claim' : 'Edit expense claim' }
  const view = views[page] || views[home]
  const title = titles[page] || NAV.find((n) => n.id === page)?.label || 'Dashboard'
  const visible = NAV.filter((n) => n.grp || n.roles.includes(role))
  const co = me.settings.company.name
  return (
    <SessionContext.Provider value={session}>
      <div className={`shell ${open ? 'open' : ''}`} onClick={(e) => { if (open && e.target.classList.contains('shell')) setOpen(false) }}>
        <aside className="side">
          <div className="brand brand-img"><div className="logo-card"><img src="/logo.png" alt={co} /></div><small>Sales portal</small></div>
          <nav className="nav" aria-label="Main">{visible.map((n, i) => n.grp
            ? (visible[i + 1] && !visible[i + 1].grp ? <div key={n.grp} className="grp">{n.grp}</div> : null)
            : <a key={n.id} href={`#/${n.id}`} className={page === n.id || page + 's' === n.id ? 'on' : ''}>{n.label}{counts[n.badge] ? <span className="cnt">{counts[n.badge]}</span> : null}</a>)}</nav>
          <div className="foot">Connected to the company server</div>
        </aside>
        <div className="main">
          <header className="top"><button className="burger" onClick={() => setOpen(!open)} aria-label="Menu">☰</button><h1>{title}</h1><span className="sp" />
            <div className="who"><div className="avatar">{initials(me.user.name)}</div><div className="txt"><b>{me.user.name}</b><small>{me.user.role_label}{me.user.emp_code ? ' · ' + me.user.emp_code : ''}</small></div>
              <button className="btn sm" onClick={() => setPwOpen(true)}>Password</button><button className="btn sm" onClick={onSignOut}>Sign out</button></div></header>
          <main className="content" key={window.location.hash}>{view()}</main>
        </div>
        <nav className="bottomnav" aria-label="Quick">{(BOTTOM[role] || []).map(([h, l]) => <a key={h} href={`#/${h}`} className={window.location.hash === '#/' + h || page === h ? 'on' : ''}>{l}</a>)}</nav>
      </div>
      <PasswordDialog open={pwOpen} onClose={() => setPwOpen(false)} onSaved={() => toast('Password changed')} />
    </SessionContext.Provider>)
}

function PasswordDialog({ open, onClose, onSaved }) {
  const [f, setF] = useState({ o: '', n1: '', n2: '' }); const [err, setErr] = useState('')
  useEffect(() => { if (open) { setF({ o: '', n1: '', n2: '' }); setErr('') } }, [open])
  const save = async (e) => {
    e.preventDefault()
    if (f.n1 !== f.n2) return setErr('The new passwords do not match.')
    try { await api('/api/auth/password', { method: 'POST', body: { old_password: f.o, new_password: f.n1 } }); onClose(); onSaved() } catch (e2) { setErr(e2.message) }
  }
  return <Modal open={open} onClose={onClose}><form className="dlg" onSubmit={save}><h2>Change your password</h2>
    <label className="field">Current password<input className="inp" type="password" value={f.o} onChange={(e) => setF({ ...f, o: e.target.value })} autoFocus /></label>
    <label className="field">New password<input className="inp" type="password" value={f.n1} onChange={(e) => setF({ ...f, n1: e.target.value })} /></label>
    <label className="field">Repeat new password<input className="inp" type="password" value={f.n2} onChange={(e) => setF({ ...f, n2: e.target.value })} /></label>
    <p className="err">{err}</p><div className="btns"><button type="button" className="btn ghost" onClick={onClose}>Cancel</button><button className="btn pri">Save</button></div></form></Modal>
}
