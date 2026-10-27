import { useState } from 'react'
import { go } from '../App'
import { api, dmy, getPosition, inr, inr0, MODES } from '../lib'
import { LocLink } from '../maps'
import { useSession } from '../session'
import { Modal, useLoad, useUi } from '../ui'
import { Status } from './Docs'

export function RoNote({ what }) {
  const { isAdmin } = useSession()
  return <div className="note">{what} come from Microsoft Dynamics and cannot be created or changed here. {isAdmin ? <>Download them under <a href="#/integration">Dynamics sync</a>.</> : 'Ask the office if something is missing or wrong.'}</div>
}

export default function Customers({ route }) {
  const { role } = useSession()
  const q = route.q.get('q') || ''
  const [rows] = useLoad(() => api(`/api/customers?q=${encodeURIComponent(q)}`), [q])
  const [view, setView] = useState(null)
  return (<><RoNote what="Customers" /><div className="card"><div className="hd"><div><h2>{role === 'rep' ? 'My customers' : 'Customers'}</h2><p className="sub">Outstanding is the Dynamics balance at download, plus orders and less payments made here since.</p></div>
    <div className="tools"><input className="inp" placeholder="Search name, code, city, GSTIN" defaultValue={q} onKeyDown={(e) => e.key === 'Enter' && go('#/customers?q=' + encodeURIComponent(e.target.value))} style={{ minWidth: 240 }} /></div></div>
    {!rows ? <div className="loading">Loading…</div> : rows.length ? <div className="scroll"><table className="t"><thead><tr><th>Code</th><th>Customer</th><th>GSTIN</th><th>Price group</th><th className="r">Outstanding</th><th className="c">Visit location</th></tr></thead><tbody>
      {rows.map((c) => <tr key={c.id} className="click" onClick={() => setView(c.id)}><td className="mono">{c.code}</td><td><b>{c.name}</b>{c.blocked && <span className="badge bad"> Blocked</span>}<div className="fine">{c.city}{c.state_name && ', ' + c.state_name}</div></td>
        <td className="mono">{c.gstin}</td><td>{c.price_group}</td><td className="r">{inr0(c.outstanding)}</td><td className="c">{c.lat != null ? <span className="badge ok">Tagged</span> : <span className="badge">No</span>}</td></tr>)}</tbody></table></div>
      : <div className="empty">No customers.</div>}</div>
    <CustomerView id={view} onClose={() => setView(null)} /></>)
}

function CustomerView({ id, onClose }) {
  const { toast, confirm } = useUi()
  const [c, reload] = useLoad(() => (id ? api(`/api/customers/${id}`) : Promise.resolve(null)), [id])
  const [busy, setBusy] = useState(false)
  if (!id) return <Modal open={false} />
  const tag = async () => {
    if (c.lat != null && !(await confirm('Replace the visit location?', `${c.name} already has a visit location. Replace it with where you are now?`, 'Replace'))) return
    setBusy(true)
    try { const p = await getPosition(); await api(`/api/customers/${id}/tag`, { method: 'POST', body: p }); toast(`Visit location saved for ${c.name}`); reload() } catch (e) { toast(e.message) } finally { setBusy(false) }
  }
  const ro = (label, v) => <div className="field">{label}<span style={{ color: 'var(--ink)', fontWeight: 400 }}>{v}</span></div>
  return <Modal open onClose={onClose} wide>{!c ? <div className="loading">Loading…</div> : <div className="dlg">
    <div className="hd" style={{ margin: 0 }}><div><h2>{c.name}</h2><p className="fine" style={{ margin: 0 }}>{c.code} · {c.gstin || 'No GSTIN'} · {c.state_name} <span className="badge info">From Dynamics</span></p></div>
      <span className={`badge ${c.credit_limit && c.outstanding > c.credit_limit ? 'bad' : 'info'}`}>Outstanding {inr0(c.outstanding)}</span></div>
    <div className="form">{ro('Address', [c.address, c.city, c.pin].filter(Boolean).join(', ') || '—')}{ro('Phone / e-mail', `${c.phone || '—'} ${c.email || ''}`)}
      {ro('Price group / terms', `${c.price_group || '—'} / ${c.terms || '—'}`)}{ro('Credit limit', c.credit_limit ? inr0(c.credit_limit) : 'None')}
      {ro('Sales staff', c.reps.join(', ') || 'Everyone')}{ro('Visit location', c.lat != null ? <LocLink p={c} /> : 'Not tagged')}</div>
    {c.docs.length > 0 && <div className="scroll"><table className="t"><thead><tr><th>No.</th><th>Type</th><th>Date</th><th>Status</th><th className="r">Total</th></tr></thead><tbody>
      {c.docs.map((d) => <tr key={d.id}><td className="mono">{d.no}</td><td>{d.kind === 'quote' ? 'Quotation' : 'Order'}</td><td>{dmy(d.date)}</td><td><Status s={d.status} /></td><td className="r">{inr(d.total)}</td></tr>)}</tbody></table></div>}
    {c.payments.length > 0 && <div className="scroll"><table className="t"><thead><tr><th>Receipt</th><th>Date</th><th>Mode</th><th className="r">Amount</th></tr></thead><tbody>
      {c.payments.map((p) => <tr key={p.id}><td className="mono">{p.no}</td><td>{dmy(p.date)}</td><td>{MODES[p.mode]}</td><td className="r">{inr(p.amount)}</td></tr>)}</tbody></table></div>}
    <p className="fine" style={{ margin: 0 }}>The visit location is kept in the portal only, to check that orders are taken at the customer. It does not change the customer in Dynamics.</p>
    <div className="btns"><button className="btn" disabled={busy} onClick={tag}>{busy ? 'Getting your location…' : 'Tag visit location here'}</button>
      <a className="btn" href={`#/payment/new?c=${c.id}`} onClick={onClose}>Receive payment</a><a className="btn" href={`#/quote/new?c=${c.id}`} onClick={onClose}>New quotation</a><a className="btn pri" href={`#/order/new?c=${c.id}`} onClick={onClose}>New order</a></div></div>}</Modal>
}
