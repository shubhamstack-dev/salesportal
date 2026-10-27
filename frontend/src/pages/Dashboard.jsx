import { api, inr0, initials } from '../lib'
import MapView from '../maps'
import { useSession } from '../session'
import { useLoad } from '../ui'

export default function Dashboard() {
  const { isAdmin } = useSession()
  const [d] = useLoad(() => api('/api/dashboard'), [])
  const [m] = useLoad(() => api('/api/materials'), [])
  if (!d) return <div className="loading">Loading…</div>
  return (<>
    {m && !m.length && <div className="note warn">Masters have not been downloaded from Dynamics yet{isAdmin ? <>: go to <a href="#/integration">Dynamics sync</a></> : ''}. Quotations and orders need them.</div>}
    <div className="grid g4" style={{ marginBottom: 16 }}>
      <div className="kpi"><span>On duty now</span><b>{d.on_duty} / {d.staff}</b><small>staff timed in · <a href="#/attendance">muster</a></small></div>
      <div className="kpi"><span>Orders today</span><b>{inr0(d.orders.value)}</b><small>{d.orders.count} orders · {d.quotes.count} quotations</small></div>
      <div className="kpi"><span>Collected today</span><b>{inr0(d.collected.value)}</b><small>{d.collected.count} receipts</small></div>
      <div className="kpi"><span>{isAdmin ? 'Waiting for Dynamics' : 'Waiting for my approval'}</span><b>{isAdmin ? d.to_dynamics : d.approvals}</b>
        <small>{isAdmin ? <><a href="#/integration">to send</a> · {d.approvals} to approve</> : 'orders, expenses, corrections'}</small></div>
    </div>
    <div className="card"><h2>Live location</h2><p className="sub">Each person's latest location today, from Time In and Out, quotations, orders and payments. Green is on duty, red is off duty.</p>
      <MapView points={d.team.filter((t) => t.last).map((t) => ({ ...t.last, title: t.name, sub: `${t.last.what} ${t.last.at}`, color: t.status === 'on' ? 'green' : 'red', label: initials(t.name) }))} /></div>
    <div className="card"><div className="hd"><div><h2>Team today</h2><p className="sub">One card per person.</p></div><a className="btn sm" href="#/attendance">Attendance muster</a></div>
      {d.team.length ? <div className="cards">{d.team.map((t) => (
        <div key={t.id} className={`rcard ${t.status === 'on' ? 'on' : t.status === 'off' ? 'off' : ''}`}>
          <div className="row"><div className="avatar">{initials(t.name)}</div><div style={{ flex: 1, minWidth: 0 }}><b>{t.name}</b><div className="fine">{t.emp_code} {t.phone}</div></div></div>
          <div className="st">{t.status === 'on' ? `Timed in · ${t.since}` : t.status === 'off' ? `Timed out · ${t.since}` : 'Not timed in today'}</div>
          <div className="loc">{t.last ? `${t.last.what} at ${t.last.at}` : 'No location today'}</div>
          <div className="fine" style={{ marginTop: 6 }}>{t.orders} orders {inr0(t.orders_value)} · collected {inr0(t.collected)}</div></div>))}</div>
        : <div className="empty">No staff yet.{isAdmin && <> <a href="#/employees">Add employees</a>.</>}</div>}</div>
  </>)
}
