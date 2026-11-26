import { useEffect, useState } from 'react'
import { go } from '../App'
import { api, dmy, dt, getPosition, inr, inr0, MODES } from '../lib'
import { LocLink } from '../maps'
import { useSession } from '../session'
import { Modal, useLoad, useUi } from '../ui'
import { Status } from './Docs'

export function RoNote({ what }) {
  const { isAdmin } = useSession()
  return <div className="note">{what} come from Microsoft Dynamics and cannot be created or changed here. {isAdmin ? <>Download them under <a href="#/integration">Dynamics sync</a>.</> : 'Ask the office if something is missing or wrong.'}</div>
}

export function CustBadges({ c }) {
  return <>{c.kind === 'prospect' && <span className="badge info"> Prospect</span>}
    {c.status === 'pending' && <span className="badge warn"> Waiting for approval</span>}
    {c.status === 'rejected' && <span className="badge bad"> Not approved</span>}
    {c.status === 'active' && c.sync && c.sync.status !== 'synced' && <span className={`badge ${c.sync.status === 'error' ? 'bad' : 'warn'}`}> {c.sync.status === 'error' ? 'Not created in Dynamics' : 'Being sent to Dynamics'}</span>}
    {c.blocked && <span className="badge bad"> Blocked</span>}</>
}

export default function Customers({ route }) {
  const { role, isMgr } = useSession()
  const q = route.q.get('q') || ''
  const view = route.q.get('view') || 'all'
  const [rows, reload] = useLoad(() => api(`/api/customers?view=${view}&q=${encodeURIComponent(q)}`), [q, view])
  const [open, setOpen] = useState(null)
  const [form, setForm] = useState(null)
  return (<><div className="note">Customers come from Microsoft Dynamics. A new customer or prospect added here {role === 'rep' ? 'waits for your manager\'s approval, then ' : ''}is created in Dynamics and gets its customer number there; until then it cannot be used for quotations, orders or payments.</div>
    <div className="card"><div className="hd"><div><h2>{role === 'rep' ? 'My customers' : 'Customers'}</h2><p className="sub">Outstanding is the Dynamics balance at download, plus orders and less payments made here since.</p></div>
    <div className="tools">{isMgr && <select className="inp" value={view} onChange={(e) => go(`#/customers?view=${e.target.value}`)}><option value="all">All customers</option><option value="pending">Waiting for my approval</option></select>}
      <input className="inp" placeholder="Search name, code, city, GSTIN, phone" defaultValue={q} onKeyDown={(e) => e.key === 'Enter' && go(`#/customers?view=${view}&q=` + encodeURIComponent(e.target.value))} style={{ minWidth: 240 }} />
      <button className="btn pri" onClick={() => setForm({})}>Add customer</button></div></div>
    {!rows ? <div className="loading">Loading…</div> : rows.length ? <div className="scroll"><table className="t"><thead><tr><th>Code</th><th>Customer</th><th>GSTIN</th><th>Price group</th><th className="r">Outstanding</th><th className="c">Visit location</th></tr></thead><tbody>
      {rows.map((c) => <tr key={c.id} className="click" onClick={() => setOpen(c.id)}><td className="mono">{c.code}</td><td><b>{c.name}</b><CustBadges c={c} /><div className="fine">{c.city}{c.state_name && ', ' + c.state_name}</div></td>
        <td className="mono">{c.gstin}</td><td>{c.price_group}</td><td className="r">{inr0(c.outstanding)}</td><td className="c">{c.lat != null ? <span className="badge ok">Tagged</span> : <span className="badge">No</span>}</td></tr>)}</tbody></table></div>
      : <div className="empty">{view === 'pending' ? 'Nothing waiting for your approval.' : 'No customers.'}</div>}</div>
    <CustomerView id={open} onClose={() => { setOpen(null); reload() }} onEdit={(c) => { setOpen(null); setForm(c) }} />
    <CustomerForm c={form} onClose={(saved) => { setForm(null); if (saved) { reload(); setOpen(saved.id) } }} /></>)
}

function CustomerForm({ c, onClose }) {
  const { states, refreshCounts } = useSession(); const { toast } = useUi()
  const [groups] = useLoad(() => api('/api/price-groups'), [])
  const [gstin, setGstin] = useState('')
  const [st, setSt] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { setGstin(c?.gstin || ''); setSt(c?.state || '') }, [c])
  if (!c) return <Modal open={false} />
  const fromGst = /^\d{2}/.test(gstin) ? gstin.slice(0, 2) : ''
  const save = async (e) => {
    e.preventDefault()
    const f = Object.fromEntries(new FormData(e.target))
    setBusy(true)
    try {
      const r = await api(c.id ? `/api/customers/${c.id}` : '/api/customers', { method: c.id ? 'PUT' : 'POST', body: { ...f, state: fromGst || f.state || '' } })
      toast(r.status === 'pending' ? `${r.name} saved; it waits for approval` : `${r.name} saved and being created in Dynamics`)
      refreshCounts(); onClose(r)
    } catch (e2) { toast(e2.message) } finally { setBusy(false) }
  }
  return <Modal open onClose={() => onClose()} wide><form className="dlg" onSubmit={save}>
    <h2>{c.id ? `Change ${c.name}` : 'Add customer or prospect'}</h2>
    <div className="form">
      <div className="field wide"><span>Type</span><div style={{ display: 'flex', gap: 16 }}>
        <label className="chk"><input type="radio" name="kind" value="customer" defaultChecked={(c.kind || 'customer') === 'customer'} /> Customer (buying now)</label>
        <label className="chk"><input type="radio" name="kind" value="prospect" defaultChecked={c.kind === 'prospect'} /> Prospect (may buy)</label></div></div>
      <label className="field wide">Business name *<input className="inp" name="name" defaultValue={c.name} required minLength={3} maxLength={100} /></label>
      <label className="field">Contact person<input className="inp" name="contact" defaultValue={c.contact} maxLength={80} /></label>
      <label className="field">Phone *<input className="inp" name="phone" defaultValue={c.phone} inputMode="tel" placeholder="10-digit mobile" /></label>
      <label className="field">GSTIN<input className="inp mono" name="gstin" value={gstin} onChange={(e) => setGstin(e.target.value.toUpperCase().replace(/\s/g, ''))} maxLength={15} placeholder="Leave empty if not registered" /></label>
      <label className="field">State *<select className="inp" name="state" value={fromGst || st} onChange={(e) => setSt(e.target.value)} disabled={!!fromGst}>
        <option value="">Choose</option>{Object.entries(states).map(([k, v]) => <option key={k} value={k}>{k} {v}</option>)}</select>{fromGst && <span className="fine">From the GSTIN</span>}</label>
      <label className="field wide">Address<input className="inp" name="address" defaultValue={c.address} maxLength={150} /></label>
      <label className="field">City<input className="inp" name="city" defaultValue={c.city} maxLength={30} /></label>
      <label className="field">PIN code<input className="inp" name="pin" defaultValue={c.pin} inputMode="numeric" maxLength={6} /></label>
      <label className="field">E-mail<input className="inp" name="email" type="email" defaultValue={c.email} maxLength={80} /></label>
      <label className="field">Price group<select className="inp" name="price_group" defaultValue={c.price_group || ''}><option value="">As in the template customer</option>{(groups || []).map((g) => <option key={g}>{g}</option>)}</select></label>
      <label className="field">Payment terms code<input className="inp" name="terms" defaultValue={c.terms} placeholder="As in the template customer" maxLength={10} /></label>
    </div>
    <p className="fine">Business Central needs the phone number or GSTIN; with a GSTIN the state comes from it and the customer is GST Registered. A customer with the same GSTIN or phone number cannot be added twice.</p>
    <div className="btns"><button type="button" className="btn" onClick={() => onClose()}>Cancel</button><button className="btn pri" disabled={busy}>{busy ? 'Saving…' : 'Save'}</button></div></form></Modal>
}

function CustomerView({ id, onClose, onEdit }) {
  const { toast, confirm } = useUi(); const { refreshCounts } = useSession()
  const [c, reload] = useLoad(() => (id ? api(`/api/customers/${id}`) : Promise.resolve(null)), [id])
  const [busy, setBusy] = useState(false)
  if (!id) return <Modal open={false} />
  const tag = async () => {
    if (c.lat != null && !(await confirm('Replace the visit location?', `${c.name} already has a visit location. Replace it with where you are now?`, 'Replace'))) return
    setBusy(true)
    try { const p = await getPosition(); await api(`/api/customers/${id}/tag`, { method: 'POST', body: p }); toast(`Visit location saved for ${c.name}`); reload() } catch (e) { toast(e.message) } finally { setBusy(false) }
  }
  const act = async (path, body, msg) => {
    setBusy(true)
    try { const r = await api(`/api/customers/${id}/${path}`, { method: 'POST', body }); toast(msg(r)); reload(); refreshCounts() } catch (e) { toast(e.message); reload() } finally { setBusy(false) }
  }
  const reject = () => { const reason = window.prompt(`Why is ${c.name} not approved? (shown to who added it)`); if (reason?.trim()) act('reject', { reason }, () => `${c.name} not approved`) }
  const ro = (label, v) => <div className="field">{label}<span style={{ color: 'var(--ink)', fontWeight: 400 }}>{v}</span></div>
  return <Modal open onClose={onClose} wide>{!c ? <div className="loading">Loading…</div> : <div className="dlg">
    <div className="hd" style={{ margin: 0 }}><div><h2>{c.name}</h2><p className="fine" style={{ margin: 0 }}>{c.code} · {c.gstin || 'No GSTIN'} · {c.state_name} {c.added ? <CustBadges c={c} /> : <span className="badge info">From Dynamics</span>}</p></div>
      <span className={`badge ${c.credit_limit && c.outstanding > c.credit_limit ? 'bad' : 'info'}`}>Outstanding {inr0(c.outstanding)}</span></div>
    {c.status === 'pending' && <div className="note warn">Added by {c.created_by} on {dt(c.created_at)}. {c.can_decide ? 'Check it and approve, so it is created in Dynamics.' : 'Waiting for a manager\'s approval.'}</div>}
    {c.status === 'rejected' && <div className="note bad">Not approved: {c.reject_reason}. {c.can_edit ? 'Change it and save to ask again.' : ''}</div>}
    {c.status === 'active' && c.sync?.status === 'error' && <div className="note bad">Creating it in Dynamics failed: {c.sync.error}</div>}
    {c.status === 'active' && c.sync?.status === 'pending' && <div className="note">Approved; being created in Dynamics. {c.can_send ? 'Use Send to Dynamics if it stays like this.' : ''}</div>}
    <div className="form">{c.contact && ro('Contact person', c.contact)}{ro('Address', [c.address, c.city, c.pin].filter(Boolean).join(', ') || '—')}{ro('Phone / e-mail', `${c.phone || '—'} ${c.email || ''}`)}
      {ro('Price group / terms', `${c.price_group || '—'} / ${c.terms || '—'}`)}{ro('Credit limit', c.credit_limit ? inr0(c.credit_limit) : 'None')}
      {ro('Sales staff', c.reps.join(', ') || 'Everyone')}{ro('Visit location', c.lat != null ? <LocLink p={c} /> : 'Not tagged')}</div>
    {c.docs.length > 0 && <div className="scroll"><table className="t"><thead><tr><th>No.</th><th>Type</th><th>Date</th><th>Status</th><th className="r">Total</th></tr></thead><tbody>
      {c.docs.map((d) => <tr key={d.id}><td className="mono">{d.no}</td><td>{d.kind === 'quote' ? 'Quotation' : 'Order'}</td><td>{dmy(d.date)}</td><td><Status s={d.status} /></td><td className="r">{inr(d.total)}</td></tr>)}</tbody></table></div>}
    {c.payments.length > 0 && <div className="scroll"><table className="t"><thead><tr><th>Receipt</th><th>Date</th><th>Mode</th><th className="r">Amount</th></tr></thead><tbody>
      {c.payments.map((p) => <tr key={p.id}><td className="mono">{p.no}</td><td>{dmy(p.date)}</td><td>{MODES[p.mode]}</td><td className="r">{inr(p.amount)}</td></tr>)}</tbody></table></div>}
    <p className="fine" style={{ margin: 0 }}>The visit location is kept in the portal only, to check that orders are taken at the customer. It does not change the customer in Dynamics.</p>
    {(!c.usable || c.can_decide || c.can_send || c.can_edit || c.kind === 'prospect') && <div className="btns">{!c.usable && <button className="btn" onClick={onClose} style={{ marginRight: 'auto' }}>Cancel</button>}{c.can_decide && <><button className="btn" disabled={busy} onClick={reject}>Reject</button><button className="btn pri" disabled={busy} onClick={() => act('approve', {}, (r) => `${r.name} approved`)}>Approve</button></>}
      {c.can_send && <button className="btn pri" disabled={busy} onClick={() => act('send', {}, (r) => `${r.name} is ${r.code} in Dynamics`)}>Send to Dynamics</button>}
      {c.can_edit && <button className="btn" onClick={() => onEdit(c)}>Change</button>}
      {c.kind === 'prospect' && c.usable && <button className="btn" disabled={busy} onClick={() => act('convert', {}, (r) => `${r.name} is a customer now`)}>Mark as customer</button>}</div>}
    {c.usable && <div className="btns"><button className="btn" onClick={onClose} style={{ marginRight: 'auto' }}>Cancel</button><button className="btn" disabled={busy} onClick={tag}>{busy ? 'Getting your location…' : 'Tag visit location here'}</button>
      <a className="btn" href={`#/payment/new?c=${c.id}`} onClick={onClose}>Receive payment</a><a className="btn" href={`#/quote/new?c=${c.id}`} onClick={onClose}>New quotation</a><a className="btn pri" href={`#/order/new?c=${c.id}`} onClick={onClose}>New order</a></div>}</div>}</Modal>
}
