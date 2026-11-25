import { useEffect, useRef, useState } from 'react'
import { go } from '../App'
import { printSalesDoc } from '../printdoc'
import { addDays, api, dmy, download, esc, getPosition, inr, inr0, num, printDoc, SYNC, todayISO } from '../lib'
import { LocLink } from '../maps'
import { useSession } from '../session'
import { Modal, useLoad, useUi } from '../ui'

const OSTAT = { draft: ['Draft', ''], submitted: ['Waiting for approval', 'warn'], approved: ['Approved', 'ok'], cancelled: ['Cancelled', 'bad'],
  open: ['Open', 'info'], converted: ['Converted to order', 'ok'], expired: ['Expired', 'warn'],
  unpaid: ['Unpaid', 'warn'], partly: ['Partly paid', 'info'], paid: ['Paid', 'ok'], overdue: ['Overdue', 'bad'],
  partial: ['Partly invoiced', 'info'], full: ['Invoiced', 'ok'] }
const K = { quote: { one: 'quotation', list: '#/quotes', title: 'Quotations' }, order: { one: 'sales order', list: '#/orders', title: 'Sales orders' },
  inv: { one: 'invoice', list: '#/invoices', title: 'Sales invoices' } }
const INV_FILTER = [['due', 'Payment due'], ['unpaid', 'Unpaid'], ['partly', 'Partly paid'], ['overdue', 'Overdue'], ['paid', 'Paid'], ['cancelled', 'Cancelled']]
export const Status = ({ s }) => <span className={`badge ${(OSTAT[s] || ['', ''])[1]}`}>{(OSTAT[s] || [s])[0]}</span>
export const Sync = ({ x }) => <><span className={`badge ${SYNC[x.status][1]}`} title={x.error || ''}>{SYNC[x.status][0]}</span>{x.no && <div className="fine mono">{x.no}</div>}</>

export function DocList({ kind, route }) {
  const { isMgr, settings } = useSession(); const { toast } = useUi()
  const q = route.q, st = q.get('status') || '', sy = q.get('sync') || '', from = q.get('from') || '', to = q.get('to') || '', pay = q.get('pay') || ''
  const [rows, reloadRows] = useLoad(() => api(`/api/docs?kind=${kind}&status=${st}&sync=${sy}&date_from=${from}&date_to=${to}&pay=${pay}`), [kind, st, sy, from, to, pay])
  const [view, setView] = useState(+q.get('view') || null)
  if (kind === 'inv') return <InvoiceList rows={rows} q={q} view={view} setView={(v) => { setView(v); if (!v) reloadRows() }} />
  const setQ = (k, v) => { const p = new URLSearchParams(q); v ? p.set(k, v) : p.delete(k); go(`${K[kind].list}?${p}`) }
  const statuses = kind === 'quote' ? ['draft', 'open', 'converted', 'expired', 'cancelled'] : ['draft', 'submitted', 'approved', 'cancelled']
  return (<div className="card"><div className="hd"><div><h2>{K[kind].title}</h2><p className="sub">{kind === 'quote'
    ? 'Saved quotations go to Dynamics as sales quotes. When the customer accepts, convert the quotation into a sales order.'
    : settings.need_approval ? 'Orders are submitted by sales staff, approved by a manager, then sent to Dynamics.' : 'Orders go to Dynamics once saved.'}</p></div>
    <div className="tools"><select className="inp" value={st} onChange={(e) => setQ('status', e.target.value)} aria-label="Status"><option value="">All statuses</option>{statuses.map((s) => <option key={s} value={s}>{OSTAT[s][0]}</option>)}</select>
      <select className="inp" value={sy} onChange={(e) => setQ('sync', e.target.value)} aria-label="Dynamics"><option value="">Any Dynamics status</option>{['pending', 'exported', 'synced', 'error'].map((s) => <option key={s} value={s}>{SYNC[s][0]}</option>)}</select>
      <input type="date" className="inp" value={from} onChange={(e) => setQ('from', e.target.value)} aria-label="From" /><input type="date" className="inp" value={to} onChange={(e) => setQ('to', e.target.value)} aria-label="To" />
      {isMgr && <button className="btn" onClick={() => download(`/api/docs-export?kind=${kind}`, `${K[kind].title.replace(' ', '_')}.xlsx`).catch((e) => toast(e.message))}>Download Excel</button>}
      <a className="btn pri" href={`#/${kind}/new`}>New {K[kind].one}</a></div></div>
    {!rows ? <div className="loading">Loading…</div> : rows.length ? <div className="scroll"><table className="t"><thead><tr><th>No.</th><th>Date</th>{kind === 'quote' && <th>Valid until</th>}<th>Customer</th><th>Sales staff</th><th className="r">Lines</th><th className="r">Total</th><th>Status</th><th>Dynamics</th></tr></thead><tbody>
      {rows.map((d) => <tr key={d.id} className="click" onClick={() => setView(d.id)}><td className="mono"><b>{d.no}</b></td><td>{dmy(d.date)}</td>{kind === 'quote' && <td>{dmy(d.valid_to)}</td>}
        <td>{d.customer}<div className="fine">{d.customer_code}</div></td><td>{d.rep}</td><td className="r">{d.lines_count}</td><td className="r"><b>{inr(d.total)}</b></td><td><Status s={d.status} />{d.invoiced && <> <Status s={d.invoiced} /></>}</td><td>{d.status === 'draft' ? '—' : <Sync x={d.sync} />}</td></tr>)}
    </tbody><tfoot><tr><td colSpan={kind === 'quote' ? 6 : 5}>{rows.length} documents</td><td className="r">{inr(rows.filter((d) => d.status !== 'cancelled').reduce((s, d) => s + d.total, 0))}</td><td colSpan={2} /></tr></tfoot></table></div>
      : <div className="empty">Nothing yet.</div>}
    <DocView id={view} onClose={() => setView(null)} />
  </div>)
}

function InvoiceList({ rows, q, view, setView }) {
  const { isMgr } = useSession(); const { toast } = useUi()
  const pay = q.get('pay') || (q.get('status') === 'cancelled' ? 'cancelled' : ''), from = q.get('from') || '', to = q.get('to') || ''
  const setQ = (patch) => { const p = new URLSearchParams(q); Object.entries(patch).forEach(([k, v]) => (v ? p.set(k, v) : p.delete(k))); p.delete('view'); go(`#/invoices?${p}`) }
  const live = (rows || []).filter((d) => d.status !== 'cancelled')
  return (<div className="card"><div className="hd"><div><h2>Sales invoices</h2><p className="sub">Invoices are made from approved sales orders (open the order and choose <b>Create invoice</b>). Payments are received against them.</p></div>
    <div className="tools"><select className="inp" value={pay} onChange={(e) => setQ(e.target.value === 'cancelled' ? { status: 'cancelled', pay: '' } : { pay: e.target.value, status: '' })} aria-label="Payment">
      <option value="">All invoices</option>{INV_FILTER.map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
      <input type="date" className="inp" value={from} onChange={(e) => setQ({ from: e.target.value })} aria-label="From" /><input type="date" className="inp" value={to} onChange={(e) => setQ({ to: e.target.value })} aria-label="To" />
      {isMgr && <button className="btn" onClick={() => download('/api/docs-export?kind=inv', 'Sales_invoices.xlsx').catch((e) => toast(e.message))}>Download Excel</button>}
      <a className="btn" href="#/orders?status=approved">Approved orders</a></div></div>
    {!rows ? <div className="loading">Loading…</div> : rows.length ? <div className="scroll"><table className="t"><thead><tr><th>Invoice</th><th>Date</th><th>Due date</th><th>Customer</th><th>Order</th><th className="r">Total</th><th className="r">Paid</th><th className="r">Due</th><th>Status</th><th>Dynamics</th></tr></thead><tbody>
      {rows.map((d) => <tr key={d.id} className="click" onClick={() => setView(d.id)}><td className="mono"><b>{d.no}</b></td><td>{dmy(d.date)}</td><td>{dmy(d.due_date)}</td>
        <td>{d.customer}<div className="fine">{d.customer_code}</div></td><td className="mono">{d.order_no || ''}</td><td className="r"><b>{inr(d.total)}</b></td>
        <td className="r">{d.paid ? inr(d.paid) : ''}</td><td className="r">{d.due ? <b>{inr(d.due)}</b> : ''}</td><td><Status s={d.pay} /></td><td>{d.sync.status === 'na' ? '—' : <Sync x={d.sync} />}</td></tr>)}</tbody>
      <tfoot><tr><td colSpan={5}>{live.length} invoices</td><td className="r">{inr(live.reduce((s, d) => s + d.total, 0))}</td><td className="r">{inr(live.reduce((s, d) => s + (d.paid || 0), 0))}</td>
        <td className="r">{inr(live.reduce((s, d) => s + (d.due || 0), 0))}</td><td colSpan={2} /></tr></tfoot></table></div> : <div className="empty">No invoices yet.</div>}
    <DocView id={view} onClose={() => setView(null)} /></div>)
}

function InvoiceDialog({ d, onClose, onDone }) {
  const { toast } = useUi()
  const [f, setF] = useState({ date: todayISO(), due_date: '', remarks: '' })
  const [qty, setQty] = useState(() => Object.fromEntries(d.lines.filter((l) => l.to_invoice > 0).map((l) => [l.line_id, l.to_invoice])))
  const [busy, setBusy] = useState(false)
  const lines = d.lines.filter((l) => l.to_invoice > 0)
  const est = lines.reduce((s, l) => s + (l.taxable / l.qty) * (+qty[l.line_id] || 0) * (1 + l.gst_rate / 100), 0)
  const save = async () => {
    setBusy(true)
    try {
      const inv = await api(`/api/docs/${d.id}/invoice`, { method: 'POST', body: { date: f.date, due_date: f.due_date || null, remarks: f.remarks,
        lines: lines.map((l) => ({ line_id: l.line_id, qty: +qty[l.line_id] || 0 })).filter((x) => x.qty > 0) } })
      toast(`Invoice ${inv.no} made for ${inr(inv.total)}${inv.paid ? `; ${inr(inv.paid)} advance applied` : ''}`); onDone(inv)
    } catch (e) { toast(e.message); setBusy(false) }
  }
  return <Modal open onClose={onClose} wide><div className="dlg"><h2>Create invoice · order {d.no}</h2>
    <p className="fine" style={{ marginTop: 0 }}>{d.customer}. Prices, discounts and GST are the order's. Invoice everything, or less of a line to bill the rest later.</p>
    <div className="form"><label className="field">Invoice date<input type="date" className="inp" value={f.date} max={todayISO()} onChange={(e) => setF({ ...f, date: e.target.value })} /></label>
      <label className="field">Due date<input type="date" className="inp" value={f.due_date} onChange={(e) => setF({ ...f, due_date: e.target.value })} /><span className="fine">Empty: from the payment terms ({d.customer_detail.terms || 'cash'})</span></label>
      <label className="field wide">Remarks<input className="inp" value={f.remarks} placeholder={d.remarks} onChange={(e) => setF({ ...f, remarks: e.target.value })} /></label></div>
    <div className="scroll"><table className="t"><thead><tr><th>Material</th><th className="r">Ordered</th><th className="r">Invoiced</th><th className="r" style={{ width: 140 }}>Invoice now</th></tr></thead><tbody>
      {lines.map((l) => <tr key={l.line_id}><td><b>{l.material}</b> {l.name}</td><td className="r">{num(l.qty)} {l.uom}</td><td className="r">{l.invoiced ? num(l.invoiced) : ''}</td>
        <td><input className="inp inv-qty" style={{ textAlign: 'right', width: '100%' }} inputMode="decimal" value={qty[l.line_id] ?? ''} onChange={(e) => setQty({ ...qty, [l.line_id]: e.target.value })} /><div className="fine r">of {num(l.to_invoice)} left</div></td></tr>)}</tbody></table></div>
    <p className="fine">About {inr0(est)} before order charges and rounding; the server works out the exact amount.{d.paid ? ` Advances of ${inr0(d.paid)} on this order will be applied.` : ''}</p>
    <div className="btns"><button className="btn ghost" onClick={onClose}>Cancel</button><button className="btn pri" disabled={busy || !lines.some((l) => +qty[l.line_id] > 0)} onClick={save}>Create invoice</button></div></div></Modal>
}

export function TotalsTable({ t }) {
  return <table className="t" style={{ maxWidth: 420, marginLeft: 'auto' }}><tbody>
    <tr><td>Items</td><td className="r">{inr(t.sub)}</td></tr>
    {t.pre.map((c) => <tr key={c.code}><td>{c.name}</td><td className="r">{inr(c.amount)}</td></tr>)}
    <tr><td><b>Taxable value</b></td><td className="r"><b>{inr(t.taxable)}</b></td></tr>
    {t.intra ? <><tr><td>CGST</td><td className="r">{inr(t.cgst)}</td></tr><tr><td>SGST</td><td className="r">{inr(t.sgst)}</td></tr></> : <tr><td>IGST</td><td className="r">{inr(t.igst)}</td></tr>}
    {t.cess ? <tr><td>Cess</td><td className="r">{inr(t.cess)}</td></tr> : null}
    {t.post.map((c) => <tr key={c.code}><td>{c.name}</td><td className="r">{inr(c.amount)}</td></tr>)}
    {t.round_off ? <tr><td>Round off</td><td className="r">{inr(t.round_off)}</td></tr> : null}
    <tr className="grand"><td><b>Total</b></td><td className="r"><b>{inr(t.total)}</b></td></tr></tbody></table>
}

function DocView({ id, onClose }) {
  const { settings } = useSession(); const { toast, confirm } = useUi()
  const [d, reload] = useLoad(() => (id ? api(`/api/docs/${id}`) : Promise.resolve(null)), [id])
  const [invoicing, setInvoicing] = useState(false)
  if (!id) return <Modal open={false} />
  if (invoicing && d) return <InvoiceDialog d={d} onClose={() => setInvoicing(false)} onDone={(inv) => { setInvoicing(false); onClose(); go(`#/invoices?view=${inv.id}`) }} />
  const inv = d?.kind === 'inv' 
  const act = async (path, msg) => { try { await api(`/api/docs/${id}/${path}`, { method: 'POST' }); toast(msg); onClose(); go(window.location.hash) } catch (e) { toast(e.message) } }
  const print = async () => { if (!(await printSalesDoc(d, settings))) toast('Allow pop-ups to print.') }
  return <Modal open onClose={onClose} wide>{!d ? <div className="loading">Loading…</div> : <div className="dlg">
    <div className="hd" style={{ margin: 0 }}><div><h2>{inv ? 'Invoice' : d.kind === 'quote' ? 'Quotation' : 'Order'} {d.no} · {d.customer}</h2>
      <p className="fine" style={{ margin: 0 }}>{dmy(d.date)} · {d.rep}{d.po_ref && ` · ref ${d.po_ref}`}{inv ? ` · due ${dmy(d.due_date)}` : d.valid_to && ` · valid until ${dmy(d.valid_to)}`}{!inv && d.delivery && ` · deliver by ${dmy(d.delivery)}`}</p></div>
      {inv ? <><Status s={d.pay} /> {d.sync.status !== 'na' && <Sync x={d.sync} />}</> : <><Status s={d.status} />{d.invoiced && <> <Status s={d.invoiced} /></>} {d.status !== 'draft' && <Sync x={d.sync} />}</>}</div>
    {inv && d.order_no && <p className="fine" style={{ margin: 0 }}>For order {d.order_no}{d.quote_no && ` (quotation ${d.quote_no})`}</p>}
    {d.invoices?.length > 0 && <div className="note">Invoices: {d.invoices.map((x, i) => <span key={x.id}>{i ? ', ' : ''}<a href={`#/invoices?view=${x.id}`} onClick={onClose}>{x.no}</a> {inr0(x.total)} ({(OSTAT[x.pay] || [x.pay])[0].toLowerCase()})</span>)}</div>}
    {d.sync.error && <div className="note bad">Dynamics: {d.sync.error}</div>}
    {inv && d.sync.status === 'synced' && <div className="note">Posted in Dynamics as invoice <b>{d.sync.no}</b>.</div>}
    {inv && d.sync.status === 'pending' && <div className="note">Posting the order in Dynamics… refresh in a moment.</div>}
    {!inv && d.quote_no && <p className="fine" style={{ margin: 0 }}>From quotation {d.quote_no}</p>}{!inv && d.order_no && <div className="note">Converted to order {d.order_no}.</div>}
    <div className="scroll"><table className="t"><thead><tr><th>Material</th><th>HSN</th><th className="r">Qty</th><th className="r">Price</th><th className="r">Disc %</th><th className="r">Taxable</th><th className="r">GST</th></tr></thead><tbody>
      {d.lines.map((l, i) => <tr key={i}><td><b>{l.material}</b> {l.name}<div className="fine">{l.price_source}{l.invoiced ? ` · invoiced ${num(l.invoiced)}` : ''}</div></td><td className="mono">{l.hsn}</td><td className="r">{num(l.qty)} {l.uom}</td><td className="r">{inr(l.price)}</td><td className="r">{l.disc || ''}</td><td className="r">{inr(l.taxable)}</td><td className="r">{l.gst_rate}%</td></tr>)}</tbody></table></div>
    <TotalsTable t={d.totals} />
    {inv && <div className="scroll"><table className="t" style={{ maxWidth: 520, marginLeft: 'auto' }}><thead><tr><th>Payment received</th><th>Date</th><th>Mode</th><th className="r">Amount</th></tr></thead><tbody>
      {d.payments.map((p) => <tr key={p.id + '-' + p.amount}><td className="mono"><a href={`#/payments?view=${p.id}`} onClick={onClose}>{p.no}</a></td><td>{dmy(p.date)}</td><td>{p.mode}</td><td className="r">{inr(p.amount)}</td></tr>)}
      {!d.payments.length && <tr><td colSpan={4} className="mut">No payment yet.</td></tr>}</tbody>
      <tfoot><tr><td colSpan={3}>Paid {inr(d.paid)}</td><td className="r"><b>Due {inr(d.due)}</b></td></tr></tfoot></table></div>}
    <p className="fine">{d.loc ? <>Recorded {d.distance_m != null ? `${d.distance_m >= 1000 ? (d.distance_m / 1000).toFixed(1) + ' km' : d.distance_m + ' m'} from the customer's visit location` : 'here'}: <LocLink p={d.loc} />
      {d.distance_m != null && d.distance_m > settings.geofence_m && <span className="badge warn"> Away from customer</span>}</> : 'No location recorded.'}{d.kind === 'order' && d.paid ? ` · Paid ${inr0(d.paid)}` : ''}{d.remarks && <><br />Remarks: {d.remarks}</>}</p>
    <div className="btns">
      {d.can_cancel && <button className="btn danger" onClick={async () => { if (await confirm(`Cancel ${d.no}?`, inv ? 'The order quantities become free to invoice again.' : d.sync.status === 'exported' ? 'It was already sent to Dynamics by file; cancel it there as well.' : 'It will not be sent to Dynamics.', 'Cancel it')) act('cancel', `${d.no} cancelled`) }}>Cancel</button>}
      <button className="btn" onClick={print}>Print</button>
      {d.editable && <a className="btn" href={`#/${d.kind}/${d.id}`} onClick={onClose}>Edit</a>}
      {d.can_approve && <button className="btn ok" onClick={() => act('approve', `${d.no} approved and queued for Dynamics`)}>Approve</button>}
      {d.kind === 'quote' && d.raw_status === 'open' && <a className="btn pri" href={`#/order/new?q=${d.id}`} onClick={onClose}>Convert to order</a>}
      {d.can_invoice && <button className="btn pri" onClick={() => setInvoicing(true)}>Create invoice</button>}
      {d.can_post && <button className="btn" title="Posts the order in Dynamics for this invoice, or links the invoice if it was already posted there" onClick={async () => { try { const r = await api(`/api/docs/${id}/post-dynamics`, { method: 'POST' }); toast(r.sync.status === 'synced' ? `In Dynamics as invoice ${r.sync.no}` : `Not posted: ${r.sync.error}`); reload() } catch (e) { toast(e.message) } }}>Post in Dynamics</button>}
      {inv && d.status === 'open' && d.due > 0 && d.on_account > 0 && <button className="btn" onClick={async () => { try { const r = await api(`/api/docs/${id}/apply-on-account`, { method: 'POST' }); toast(r.due > 0 ? `Applied; ${inr(r.due)} still due` : 'Paid from money on account'); reload() } catch (e) { toast(e.message) } }}>Apply {inr0(Math.min(d.on_account, d.due))} on account</button>}
      {inv && d.status === 'open' && d.due > 0 && <a className="btn pri" href={`#/payment/new?c=${d.customer_id}&inv=${d.id}`} onClick={onClose}>Receive payment</a>}
      <button className="btn" onClick={onClose}>Close</button></div></div>}</Modal>
}

/* ---------------- editor */
const blank = () => ({ key: Math.random().toString(36).slice(2), material: '', qty: 1, disc: 0, price: '' })
export function DocEditor({ kind, route }) {
  const { settings, user } = useSession(); const { toast } = useUi()
  const [custs] = useLoad(() => api('/api/customers'), [])
  const [mats] = useLoad(() => api('/api/materials'), [])
  const [charges] = useLoad(() => api('/api/charges'), [])
  const [ed, setEd] = useState(null)
  const [pv, setPv] = useState(null)
  const [busy, setBusy] = useState(false)
  const seq = useRef(0)
  const isQ = kind === 'quote'
  useEffect(() => {
    (async () => {
      const id = route.arg, qid = route.q.get('q')
      const base = { id: null, customer_id: +route.q.get('c') || null, date: todayISO(), delivery: '', valid_to: addDays(todayISO(), settings.quote_days), po_ref: '', remarks: '', charges: [], lines: [blank()], quote_id: null }
      try {
        if (id && id !== 'new') {
          const d = await api(`/api/docs/${id}`)
          if (!d.editable) { toast('This document can no longer be changed.'); go(K[kind].list); return }
          setEd({ ...base, id: d.id, customer_id: d.customer_id, date: d.date, delivery: d.delivery || '', valid_to: d.valid_to || '', po_ref: d.po_ref, remarks: d.remarks, charges: d.charges, quote_id: d.quote_id,
            lines: [...d.lines.map((l) => ({ ...blank(), material: l.material, qty: l.qty, disc: l.disc, price: l.price_source === 'entered' ? l.price : '' })), blank()] })
        } else if (qid) {
          const q = await api(`/api/docs/${qid}`)
          setEd({ ...base, customer_id: q.customer_id, po_ref: q.po_ref, remarks: q.remarks, charges: q.charges, quote_id: q.id, quote_no: q.no,
            lines: [...q.lines.map((l) => ({ ...blank(), material: l.material, qty: l.qty, disc: l.disc })), blank()] })
        } else setEd(base)
      } catch (e) { toast(e.message); go(K[kind].list) }
    })()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  const body = (submit, extra = {}) => ({ kind, customer_id: ed.customer_id, date: ed.date, delivery: ed.delivery || null, valid_to: ed.valid_to || null, po_ref: ed.po_ref,
    remarks: ed.remarks, charges: ed.charges, quote_id: ed.quote_id, submit, lines: ed.lines.filter((l) => l.material).map((l) => ({ material: l.material, qty: +l.qty || 0, disc: +l.disc || 0, price: l.price === '' ? null : +l.price })), ...extra })
  useEffect(() => {
    if (!ed || !ed.customer_id) { setPv(null); return }
    const n = ++seq.current
    const t = setTimeout(() => api('/api/docs/preview', { method: 'POST', body: body(false) }).then((r) => { if (n === seq.current) setPv(r) }).catch((e) => toast(e.message)), 200)
    return () => clearTimeout(t)
  }, [JSON.stringify(ed && body(false))]) // eslint-disable-line react-hooks/exhaustive-deps
  if (!ed || !custs || !mats || !charges) return <div className="loading">Loading…</div>
  const c = custs.find((x) => x.id === ed.customer_id)
  const setLine = (i, patch) => { const lines = ed.lines.map((l, j) => (j === i ? { ...l, ...patch } : l)); if (lines[lines.length - 1].material) lines.push(blank()); setEd({ ...ed, lines }) }
  const pickCust = (v) => { const x = custs.find((y) => `${y.code} · ${y.name}` === v || y.code === v.split(' · ')[0]); if (!x) return toast('Choose a customer from the list'); if (x.blocked) return toast(`${x.name} is blocked in Dynamics`); setEd({ ...ed, customer_id: x.id }) }
  const pickMat = (i, v) => { const m = mats.find((y) => `${y.code} · ${y.name}` === v || y.code === v.split(' · ')[0]); if (!m) return toast('Choose a material from the list'); if (m.blocked) return toast(`${m.code} is blocked in Dynamics`); setLine(i, { material: m.code, price: '' }) }
  const filled = ed.lines.filter((l) => l.material)
  const lineOf = (l) => pv?.lines[filled.indexOf(l)]
  const save = async (submit) => {
    setBusy(true)
    let loc = {}
    if (submit) { try { loc = await getPosition(8000) } catch (e) { toast(e.message + ' Saved without a location.') } }
    try {
      const d = await api(ed.id ? `/api/docs/${ed.id}` : '/api/docs', { method: ed.id ? 'PUT' : 'POST', body: body(submit, { lat: loc.lat, lng: loc.lng }) })
      toast(!submit ? `${d.no} saved as draft` : isQ ? `Quotation ${d.no} saved and queued for Dynamics` : d.status === 'submitted' ? `${d.no} submitted for approval` : `${d.no} saved and queued for Dynamics`)
      go(K[kind].list)
    } catch (e) { toast(e.message); setBusy(false) }
  }
  const optional = charges.filter((x) => x.active && !x.auto), auto = charges.filter((x) => x.active && x.auto)
  return (<>
    {ed.quote_no && <div className="note">Order from quotation <b>{ed.quote_no}</b>. Prices are as of today's price list.</div>}
    <div className="ord"><div>
      <div className="card"><div className="form">
        <label className="field wide">Customer<input className="inp" list="edCust" defaultValue={c ? `${c.code} · ${c.name}` : ''} placeholder="Type a code or name" onChange={(e) => { const v = e.target.value; if (custs.some((y) => `${y.code} · ${y.name}` === v)) pickCust(v) }} onBlur={(e) => e.target.value && pickCust(e.target.value)} data-ch="edCustomer" /></label>
        <label className="field">{isQ ? 'Quotation date' : 'Order date'}<input type="date" className="inp" value={ed.date} onChange={(e) => setEd({ ...ed, date: e.target.value })} /></label>
        {isQ ? <label className="field">Valid until<input type="date" className="inp" value={ed.valid_to} onChange={(e) => setEd({ ...ed, valid_to: e.target.value })} /></label>
          : <label className="field">Deliver by<input type="date" className="inp" value={ed.delivery} onChange={(e) => setEd({ ...ed, delivery: e.target.value })} /></label>}
        <label className="field">Customer reference<input className="inp" value={ed.po_ref} onChange={(e) => setEd({ ...ed, po_ref: e.target.value })} /></label></div>
        <datalist id="edCust">{custs.filter((x) => !x.blocked).map((x) => <option key={x.id} value={`${x.code} · ${x.name}`}>{x.city}</option>)}</datalist>
        {pv && <p className="fine" style={{ margin: '10px 0 0' }}>{pv.customer.gstin || 'No GSTIN'} · {pv.customer.state} ({pv.customer.intra ? 'CGST + SGST' : 'IGST'}) · price group {pv.customer.price_group || 'none'}{pv.credit && ` · outstanding ${inr0(pv.credit.outstanding)}${pv.credit.limit ? ' of ' + inr0(pv.credit.limit) : ''}`}</p>}</div>
      <div className="card"><h2>Items</h2><p className="sub">Prices come from the Dynamics price list for this customer; GST from each material's HSN code. The server works them out.</p>
        <div className="scroll"><table className="t lines"><thead><tr><th style={{ minWidth: 240 }}>Material</th><th className="r" style={{ width: 90 }}>Qty</th><th className="r" style={{ width: 120 }}>Unit price</th><th className="r" style={{ width: 80 }}>Disc %</th><th className="r">GST</th><th className="r">Taxable</th><th /></tr></thead><tbody>
          {ed.lines.map((l, i) => { const p = l.material && lineOf(l); const m = mats.find((x) => x.code === l.material)
            return <tr key={l.key}><td className="mat" data-l="Material"><input className="inp" list="edMat" defaultValue={m ? `${m.code} · ${m.name}` : ''} placeholder="Type a code or name" data-i={i}
                onChange={(e) => { if (mats.some((y) => `${y.code} · ${y.name}` === e.target.value)) pickMat(i, e.target.value) }} onBlur={(e) => e.target.value && e.target.value !== (m ? `${m.code} · ${m.name}` : '') && pickMat(i, e.target.value)} />
                {m && <div className="fine">{m.uom} · HSN {m.hsn || '—'}{p && (p.price_source ? ` · ${p.price_source}` : <span style={{ color: 'var(--bad)' }}> · no price</span>)}</div>}</td>
              <td data-l="Qty"><input className="inp" style={{ textAlign: 'right' }} inputMode="decimal" value={l.qty} data-k="qty" onChange={(e) => setLine(i, { qty: e.target.value })} /></td>
              <td data-l="Price">{settings.price_override ? <input className="inp" style={{ textAlign: 'right' }} inputMode="decimal" placeholder={p ? String(p.price) : ''} value={l.price} onChange={(e) => setLine(i, { price: e.target.value })} />
                : <input className="inp" style={{ textAlign: 'right' }} readOnly value={p ? p.price : ''} data-k="price" />}</td>
              <td data-l="Disc %"><input className="inp" style={{ textAlign: 'right' }} inputMode="decimal" value={l.disc || ''} onChange={(e) => setLine(i, { disc: e.target.value })} /></td>
              <td className="r" data-l="GST">{p ? p.gst_rate + '%' : ''}</td><td className="r" data-l="Taxable">{p ? inr(p.taxable) : ''}</td>
              <td><button className="btn ghost sm" aria-label="Remove line" onClick={() => setEd({ ...ed, lines: ed.lines.length > 1 ? ed.lines.filter((_, j) => j !== i) : [blank()] })}>✕</button></td></tr> })}</tbody></table></div>
        <datalist id="edMat">{mats.filter((m) => !m.blocked).map((m) => <option key={m.code} value={`${m.code} · ${m.name}`}>{Object.values(m.attrs).join(', ')}</option>)}</datalist></div>
      <div className="card"><h2>Charges and remarks</h2>{auto.length > 0 && <p className="fine">Always applied: {auto.map((x) => x.name).join(', ')}</p>}
        <div className="tools" style={{ marginBottom: 10 }}>{optional.length ? optional.map((x) => <label key={x.code} className="chk"><input type="checkbox" data-code={x.code} checked={ed.charges.includes(x.code)}
          onChange={(e) => setEd({ ...ed, charges: e.target.checked ? [...ed.charges, x.code] : ed.charges.filter((y) => y !== x.code) })} /> {x.name} ({x.sign < 0 ? '−' : '+'}{x.calc === 'fixed' ? inr0(x.value) : x.value + '%'})</label>)
          : <span className="fine">No optional charges in Dynamics.</span>}</div>
        <textarea className="inp" placeholder="Remarks" value={ed.remarks} onChange={(e) => setEd({ ...ed, remarks: e.target.value })} /></div>
    </div>
    <div className="card totals"><h2>{isQ ? 'Quotation' : 'Order'} total</h2><div id="edTot">{pv ? <TotalsTable t={pv.totals} /> : <p className="mut">Choose a customer and materials.</p>}</div>
      {pv?.problems?.length > 0 && <div className="note warn">{pv.problems[0]}</div>}
      {pv?.credit?.over && <div className="note warn">This order takes the customer to {inr0(pv.credit.after)}, over the credit limit of {inr0(pv.credit.limit)}.{settings.credit_check === 'block' ? ' It cannot be submitted.' : ''}</div>}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 12 }}>
        <button id="edSubmitBtn" className="btn pri lg" disabled={busy || !pv} onClick={() => save(true)}>{isQ ? 'Save quotation' : settings.need_approval && user.role === 'rep' ? 'Submit for approval' : 'Save order'}</button>
        <button className="btn" disabled={busy || !ed.customer_id} onClick={() => save(false)}>Save as draft</button><a className="btn ghost" href={K[kind].list}>Cancel</a></div>
      <p className="fine">{isQ ? 'Saved quotations are sent to Dynamics as sales quotes.' : 'Your location is recorded with the order.'}</p></div></div>
  </>)
}
