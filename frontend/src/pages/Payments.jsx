import { useEffect, useState } from 'react'
import { go } from '../App'
import { api, dmy, download, esc, getPosition, inr, inr0, MODES, parseNum, printDoc, todayISO } from '../lib'
import { LocLink } from '../maps'
import { useSession } from '../session'
import { Modal, useLoad, useUi } from '../ui'
import { Sync } from './Docs'

export function PaymentList({ route }) {
  const { isMgr } = useSession(); const { toast } = useUi()
  const from = route.q.get('from') || '', to = route.q.get('to') || ''
  const [rows] = useLoad(() => api(`/api/payments?date_from=${from}&date_to=${to}`), [from, to])
  const [view, setView] = useState(+route.q.get('view') || null)
  const setQ = (k, v) => { const p = new URLSearchParams(route.q); v ? p.set(k, v) : p.delete(k); p.delete('view'); go('#/payments?' + p) }
  const live = (rows || []).filter((p) => !p.cancelled)
  return (<div className="card"><div className="hd"><div><h2>Payments received</h2><p className="sub">Collections from customers, allocated to their orders and sent to Dynamics as customer payments.</p></div>
    <div className="tools"><input type="date" className="inp" value={from} onChange={(e) => setQ('from', e.target.value)} aria-label="From" /><input type="date" className="inp" value={to} onChange={(e) => setQ('to', e.target.value)} aria-label="To" />
      {isMgr && <button className="btn" onClick={() => download('/api/payments-export', 'Payments.xlsx').catch((e) => toast(e.message))}>Download Excel</button>}<a className="btn pri" href="#/payment/new">Receive payment</a></div></div>
    {!rows ? <div className="loading">Loading…</div> : rows.length ? <div className="scroll"><table className="t"><thead><tr><th>Receipt</th><th>Date</th><th>Customer</th><th>Received by</th><th>Mode</th><th className="r">Amount</th><th>Dynamics</th></tr></thead><tbody>
      {rows.map((p) => <tr key={p.id} className="click" onClick={() => setView(p.id)}><td className="mono"><b>{p.no}</b></td><td>{dmy(p.date)}</td><td>{p.customer}<div className="fine">{p.customer_code}</div></td><td>{p.rep}</td>
        <td>{p.mode_label}{p.ref && <div className="fine">{p.ref}</div>}</td><td className="r"><b>{inr(p.amount)}</b></td><td>{p.cancelled ? <span className="badge bad">Cancelled</span> : <Sync x={p.sync} />}</td></tr>)}</tbody>
      <tfoot><tr><td colSpan={5}>{live.length} receipts</td><td className="r">{inr(live.reduce((s, p) => s + p.amount, 0))}</td><td /></tr></tfoot></table></div> : <div className="empty">No payments yet.</div>}
    <PaymentView id={view} onClose={() => setView(null)} /></div>)
}

function PaymentView({ id, onClose }) {
  const { settings } = useSession(); const { toast, confirm } = useUi()
  const [p] = useLoad(() => (id ? api(`/api/payments/${id}`) : Promise.resolve(null)), [id])
  if (!id) return <Modal open={false} />
  const print = () => {
    const co = settings.company
    printDoc(`Receipt ${p.no}`, `<h1 style="margin:0">${esc(co.name)}</h1><div>${esc(co.address)} · GSTIN ${esc(co.gstin || '—')}</div><hr><h2>Payment receipt ${esc(p.no)}</h2><p>Date ${dmy(p.date)}</p>
      <p>Received with thanks from <b>${esc(p.customer)}</b> (${esc(p.customer_code)}) the sum of <b>${inr(p.amount)}</b> by ${p.mode_label}${p.ref ? ', reference ' + esc(p.ref) : ''}${p.bank ? ', ' + esc(p.bank) : ''}.</p>
      ${p.allocations.length ? `<table><tr><th>Against order</th><th class="r">Amount</th></tr>${p.allocations.map((a) => `<tr><td>${esc(a.order_no)}</td><td class="r">${inr(a.amount)}</td></tr>`).join('')}</table>` : ''}
      ${p.mode === 'cheque' ? '<p class="fine">Subject to realisation of the cheque.</p>' : ''}<br><p>Received by ${esc(p.rep)}</p>`) || toast('Allow pop-ups to print.')
  }
  const cancel = async () => {
    if (!(await confirm(`Cancel ${p.no}?`, p.sync.status === 'exported' ? 'It was sent to Dynamics by file; reverse it there as well.' : 'It will not be sent to Dynamics.', 'Cancel receipt'))) return
    try { await api(`/api/payments/${id}/cancel`, { method: 'POST' }); toast('Receipt cancelled'); onClose(); go('#/payments') } catch (e) { toast(e.message) }
  }
  return <Modal open onClose={onClose}>{!p ? <div className="loading">Loading…</div> : <div className="dlg">
    <div className="hd" style={{ margin: 0 }}><div><h2>{p.no} · {inr(p.amount)}</h2><p className="fine" style={{ margin: 0 }}>{p.customer} · {dmy(p.date)} · {p.mode_label} {p.ref}</p></div>{p.cancelled ? <span className="badge bad">Cancelled</span> : <Sync x={p.sync} />}</div>
    {p.allocations.length ? <table className="t"><thead><tr><th>Allocated to order</th><th className="r">Amount</th></tr></thead><tbody>{p.allocations.map((a) => <tr key={a.order_id}><td className="mono">{a.order_no}</td><td className="r">{inr(a.amount)}</td></tr>)}</tbody></table>
      : <p className="mut">On account (not allocated to an order).</p>}
    <p className="fine">Received by {p.rep} · {p.loc ? <LocLink p={p.loc} /> : 'no location'}{p.remarks && <><br />{p.remarks}</>}</p>
    <div className="btns">{p.can_cancel && <button className="btn danger" onClick={cancel}>Cancel receipt</button>}<button className="btn" onClick={print}>Print receipt</button><button className="btn pri" onClick={onClose}>Close</button></div></div>}</Modal>
}

export function PaymentForm({ route }) {
  const { toast } = useUi()
  const [custs] = useLoad(() => api('/api/customers'), [])
  const cid = +route.q.get('c') || null
  const [open] = useLoad(() => (cid ? api(`/api/customers/${cid}/open-orders`) : Promise.resolve(null)), [cid])
  const [f, setF] = useState({ date: todayISO(), amount: '', mode: 'cash', ref: '', bank: '', cheque_date: '', remarks: '' })
  const [alloc, setAlloc] = useState({})
  const [busy, setBusy] = useState(false)
  useEffect(() => setAlloc({}), [cid])
  if (!custs) return <div className="loading">Loading…</div>
  const pick = (v) => { const c = custs.find((x) => `${x.code} · ${x.name}` === v || x.code === v.split(' · ')[0]); if (!c) return toast('Choose a customer from the list'); go(`#/payment/new?c=${c.id}`) }
  const auto = () => { let left = parseNum(f.amount); const a = {}; (open?.orders || []).forEach((o) => { const x = Math.min(left, o.due); if (x > 0) { a[o.id] = x; left -= x } }); setAlloc(a) }
  const save = async () => {
    setBusy(true)
    let loc = {}; try { loc = await getPosition(8000) } catch { /* saved without a location */ }
    try {
      const p = await api('/api/payments', { method: 'POST', body: { customer_id: cid, ...f, amount: parseNum(f.amount), cheque_date: f.cheque_date || null,
        allocations: Object.entries(alloc).filter(([, v]) => parseNum(v) > 0).map(([k, v]) => ({ order_id: +k, amount: parseNum(v) })), ...loc } })
      toast(`${p.no} saved for ${inr(p.amount)}`); go(`#/payments?view=${p.id}`)
    } catch (e) { toast(e.message); setBusy(false) }
  }
  const c = open?.customer
  return (<div className="grid g2"><div className="card"><h2>Payment</h2><p className="sub">Record money received from a customer. A receipt can be printed for them.</p>
    <div className="form"><label className="field wide">Customer<input className="inp" list="payCust" defaultValue={c ? `${c.code} · ${c.name}` : ''} placeholder="Type a code or name" data-ch="payCustomer"
      onChange={(e) => { if (custs.some((x) => `${x.code} · ${x.name}` === e.target.value)) pick(e.target.value) }} autoFocus={!cid} /></label>
      <datalist id="payCust">{custs.map((x) => <option key={x.id} value={`${x.code} · ${x.name}`} />)}</datalist>
      <label className="field">Date<input type="date" className="inp" value={f.date} max={todayISO()} onChange={(e) => setF({ ...f, date: e.target.value })} /></label>
      <label className="field">Amount received<input className="inp" name="amount" inputMode="decimal" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} autoFocus={!!cid} /></label>
      <label className="field">Mode<select className="inp" name="mode" value={f.mode} onChange={(e) => setF({ ...f, mode: e.target.value })}>{Object.entries(MODES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
      <label className="field">{f.mode === 'cheque' ? 'Cheque number' : f.mode === 'cash' ? 'Reference (optional)' : 'Reference / UTR'}<input className="inp" name="ref" value={f.ref} onChange={(e) => setF({ ...f, ref: e.target.value })} /></label>
      {f.mode === 'cheque' && <><label className="field">Bank<input className="inp" value={f.bank} onChange={(e) => setF({ ...f, bank: e.target.value })} /></label>
        <label className="field">Cheque date<input type="date" className="inp" value={f.cheque_date} onChange={(e) => setF({ ...f, cheque_date: e.target.value })} /></label></>}
      <label className="field wide">Remarks<input className="inp" value={f.remarks} onChange={(e) => setF({ ...f, remarks: e.target.value })} /></label></div></div>
    <div className="card"><h2>{c ? c.name : 'Customer account'}</h2>
      {c ? <><p className="sub">Outstanding {inr0(c.outstanding)}. Allocate the payment to open orders; any balance stays on account.</p>
        {open.orders.length ? <><div className="scroll"><table className="t"><thead><tr><th>Order</th><th>Date</th><th className="r">Due</th><th className="r" style={{ width: 130 }}>Allocate</th></tr></thead><tbody>
          {open.orders.map((o) => <tr key={o.id}><td className="mono">{o.no}</td><td>{dmy(o.date)}</td><td className="r">{inr(o.due)}</td>
            <td><input className="inp alloc" style={{ textAlign: 'right', width: '100%' }} inputMode="decimal" value={alloc[o.id] ?? ''} onChange={(e) => setAlloc({ ...alloc, [o.id]: e.target.value })} /></td></tr>)}</tbody></table></div>
          <button className="btn sm" style={{ marginTop: 8 }} onClick={auto}>Allocate oldest first</button></> : <p className="mut">No open orders. The payment goes on account.</p>}</>
        : <p className="mut">Choose a customer to see what they owe.</p>}
      <div className="tools" style={{ marginTop: 16 }}><button className="btn pri lg" disabled={!cid || busy} onClick={save}>Save payment</button><a className="btn ghost" href="#/payments">Cancel</a></div></div></div>)
}
