import { useEffect, useRef, useState } from 'react'
import { go } from '../App'
import { api, dmy, download, inr, inr0, num, parseNum, todayISO } from '../lib'
import { useSession } from '../session'
import { Modal, useLoad, useUi } from '../ui'
import { Sync } from './Docs'

const EXSTAT = { draft: ['Draft', ''], submitted: ['Waiting for approval', 'warn'], approved: ['Approved', 'ok'], rejected: ['Rejected', 'bad'] }
const STN = { in: 'In-station', out: 'Out-station' }

export function ExpenseList({ route }) {
  const { isMgr, user } = useSession(); const { toast } = useUi()
  const st = route.q.get('status') || '', month = route.q.get('m') || ''
  const [rows] = useLoad(() => api(`/api/expenses?status=${st}&month=${month}`), [st, month])
  const [meta] = useLoad(() => api('/api/expenses/meta'), [])
  const [view, setView] = useState(null)
  const setQ = (k, v) => { const p = new URLSearchParams(route.q); v ? p.set(k, v) : p.delete(k); go('#/expenses?' + p) }
  const mine = (rows || []).filter((x) => x.user_id === user.id && x.date_from.slice(0, 7) === todayISO().slice(0, 7))
  const g = meta?.grade
  return (<>
    <div className="grid g4" style={{ marginBottom: 16 }}>
      <div className="kpi"><span>My claims this month</span><b>{inr0(mine.filter((x) => x.status !== 'rejected').reduce((s, x) => s + x.total, 0))}</b><small>{mine.length} claims</small></div>
      <div className="kpi"><span>Approved this month</span><b>{inr0(mine.filter((x) => x.status === 'approved').reduce((s, x) => s + x.total, 0))}</b><small>paid through Dynamics</small></div>
      <div className="kpi"><span>My grade</span><b>{g ? g.code : '—'}</b><small>{g ? `${g.name} · DA ${inr0(g.in.da)} / ${inr0(g.out.da)}` : 'Not set: ask the administrator'}</small></div>
      <div className="kpi"><span>Waiting for my approval</span><b>{(rows || []).filter((x) => x.can_approve).length}</b><small>{isMgr ? 'claims from your team' : 'managers approve claims'}</small></div></div>
    <div className="card"><div className="hd"><div><h2>Expense claims</h2><p className="sub">Daily allowance and travel come from the employee's grade; hotel is filled in from the grade and can be changed to what was paid. Approved claims go to Dynamics for payment.</p></div>
      <div className="tools"><input type="month" className="inp" value={month} onChange={(e) => setQ('m', e.target.value)} aria-label="Month" />
        <select className="inp" value={st} onChange={(e) => setQ('status', e.target.value)} aria-label="Status"><option value="">All statuses</option>{Object.entries(EXSTAT).map(([k, v]) => <option key={k} value={k}>{v[0]}</option>)}</select>
        {isMgr && <button className="btn" onClick={() => download('/api/expenses-export/all', 'Expense_claims.xlsx').catch((e) => toast(e.message))}>Download Excel</button>}<a className="btn pri" href="#/expense/new">New claim</a></div></div>
      {!rows ? <div className="loading">Loading…</div> : rows.length ? <div className="scroll"><table className="t"><thead><tr><th>Claim</th><th>Employee</th><th>Dates</th><th>Type and purpose</th><th className="r">Fixed (DA)</th><th className="r">Variable (travel)</th><th className="r">Hotel</th><th className="r">Other</th><th className="r">Total</th><th>Status</th><th>Dynamics</th></tr></thead><tbody>
        {rows.map((x) => <tr key={x.id} className="click" onClick={() => setView(x.id)}><td className="mono"><b>{x.no}</b></td><td>{x.employee}<div className="fine">{x.emp_code} · {x.grade}</div></td>
          <td>{dmy(x.date_from)}{x.date_to !== x.date_from && ' to ' + dmy(x.date_to)}<div className="fine">{x.calc.days} days</div></td><td>{x.type_label}<div className="fine">{x.purpose}</div></td>
          <td className="r">{inr0(x.calc.fixed)}</td><td className="r">{inr0(x.calc.variable)}<div className="fine">{num(x.km)} km</div></td><td className="r">{inr0(x.calc.hotel)}{x.calc.hotel_over > 0 && <span className="badge warn"> Above policy</span>}</td>
          <td className="r">{inr0(x.calc.other)}</td><td className="r"><b>{inr(x.total)}</b></td><td><span className={`badge ${EXSTAT[x.status][1]}`}>{EXSTAT[x.status][0]}</span></td><td>{x.status === 'approved' ? <Sync x={x.sync} /> : '—'}</td></tr>)}</tbody></table></div>
        : <div className="empty">No claims yet.</div>}</div>
    <ClaimView id={view} onClose={() => setView(null)} /></>)
}

function ClaimView({ id, onClose }) {
  const { toast, confirm } = useUi()
  const [x] = useLoad(() => (id ? api(`/api/expenses/${id}`) : Promise.resolve(null)), [id])
  const [rej, setRej] = useState(null)
  if (!id) return <Modal open={false} />
  const decide = async (approve, reason = '') => { try { await api(`/api/expenses/${id}/decide`, { method: 'POST', body: { approve, reason } }); toast(approve ? `${x.no} approved and queued for Dynamics` : `${x.no} rejected`); onClose(); go(window.location.hash) } catch (e) { toast(e.message) } }
  const del = async () => { if (!(await confirm(`Delete ${x.no}?`, 'The claim will be deleted.', 'Delete'))) return; try { await api(`/api/expenses/${id}`, { method: 'DELETE' }); onClose(); go('#/expenses') } catch (e) { toast(e.message) } }
  if (!x) return <Modal open onClose={onClose}><div className="loading">Loading…</div></Modal>
  const c = x.calc
  return <Modal open onClose={onClose} wide>{rej !== null ? <form className="dlg" onSubmit={(e) => { e.preventDefault(); decide(false, rej) }}><h2>Reject {x.no}</h2>
    <label className="field">Reason, shown to the employee<textarea className="inp" value={rej} onChange={(e) => setRej(e.target.value)} autoFocus /></label>
    <div className="btns"><button type="button" className="btn ghost" onClick={() => setRej(null)}>Back</button><button className="btn danger">Reject claim</button></div></form>
    : <div className="dlg"><div className="hd" style={{ margin: 0 }}><div><h2>{x.no} · {x.employee}</h2><p className="fine" style={{ margin: 0 }}>{x.type_label} · {dmy(x.date_from)}{x.date_to !== x.date_from && ' to ' + dmy(x.date_to)} · grade {x.grade} · {x.purpose}{x.places && ' · ' + x.places}</p></div>
      <span className={`badge ${EXSTAT[x.status][1]}`}>{EXSTAT[x.status][0]}</span>{x.status === 'approved' && <Sync x={x.sync} />}</div>
      {x.status === 'rejected' && x.reject_reason && <div className="note bad">Rejected: {x.reject_reason}</div>}
      <table className="t"><thead><tr><th>Item</th><th>Basis</th><th className="r">Amount</th></tr></thead><tbody>
        <tr><td>Daily allowance (fixed)</td><td>{c.days} days × {inr0(x.rates.da)}</td><td className="r">{inr(c.fixed)}</td></tr>
        <tr><td>Travel (variable)</td><td>{num(x.km)} km × {inr(x.rates.km)}{x.gps_km > 0 && <div className="fine">Recorded locations: {num(x.gps_km)} km straight-line</div>}</td><td className="r">{inr(c.variable)}</td></tr>
        <tr><td>Hotel{x.hotel_name && ': ' + x.hotel_name}{x.hotel_bill && <span className="fine"> bill {x.hotel_bill}</span>}</td><td>{x.nights} nights; policy {inr0(c.hotel_policy)}{c.hotel_over > 0 && <span className="badge warn"> {inr0(c.hotel_over)} above policy</span>}</td><td className="r">{inr(c.hotel)}</td></tr>
        {x.others.map((o, i) => <tr key={i}><td>{o.category}</td><td>{o.note}</td><td className="r">{inr(o.amount)}</td></tr>)}</tbody>
        <tfoot><tr><td colSpan={2}>Total</td><td className="r">{inr(c.total)}</td></tr></tfoot></table>
      {x.approved_by && <p className="fine" style={{ margin: 0 }}>Approved by {x.approved_by}</p>}
      <div className="btns">{x.can_edit && <><button className="btn danger" onClick={del}>Delete</button><a className="btn" href={`#/expense/${x.id}`} onClick={onClose}>Edit</a></>}
        {x.can_approve && <><button className="btn danger" onClick={() => setRej('')}>Reject</button><button className="btn ok" onClick={() => decide(true)}>Approve {inr0(c.total)}</button></>}
        <button className="btn" onClick={onClose}>Close</button></div></div>}</Modal>
}

export function ExpenseForm({ route }) {
  const { toast } = useUi()
  const [meta] = useLoad(() => api('/api/expenses/meta'), [])
  const [x, setX] = useState(null)
  const [pv, setPv] = useState(null)
  const [busy, setBusy] = useState(false)
  const seq = useRef(0)
  useEffect(() => {
    (async () => {
      const id = route.arg
      const blank = { id: null, type: 'in', date_from: todayISO(), date_to: todayISO(), purpose: '', places: '', km: '', nights: null, hotel: null, hotel_name: '', hotel_bill: '', others: [] }
      if (id && id !== 'new') {
        const c = await api(`/api/expenses/${id}`)
        if (!c.can_edit) { toast('This claim can no longer be changed.'); go('#/expenses'); return }
        setX({ ...blank, ...c, id: c.id, km: String(c.km), others: c.others })
      } else setX(blank)
    })().catch((e) => toast(e.message))
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  const body = (submit) => ({ type: x.type, date_from: x.date_from, date_to: x.date_to, purpose: x.purpose, places: x.places, km: parseNum(x.km), nights: x.nights,
    hotel: x.hotel, hotel_name: x.hotel_name, hotel_bill: x.hotel_bill, others: x.others.map((o) => ({ ...o, amount: parseNum(o.amount) })), submit })
  useEffect(() => {
    if (!x || !meta?.grade) return
    const n = ++seq.current
    const t = setTimeout(() => api('/api/expenses/preview', { method: 'POST', body: body(false) }).then((r) => { if (n === seq.current) setPv(r) }).catch((e) => toast(e.message)), 200)
    return () => clearTimeout(t)
  }, [JSON.stringify(x && body(false)), meta]) // eslint-disable-line react-hooks/exhaustive-deps
  if (!meta || !x) return <div className="loading">Loading…</div>
  if (!meta.grade) return <div className="card"><div className="empty">You have no grade, so the portal does not know your allowances. Ask the administrator to give you a grade under Employees and users.</div></div>
  const g = meta.grade, r = g[x.type]
  const set = (p) => setX({ ...x, ...p })
  const save = async (submit) => {
    setBusy(true)
    try { const c = await api(x.id ? `/api/expenses/${x.id}` : '/api/expenses', { method: x.id ? 'PUT' : 'POST', body: body(submit) }); toast(submit ? `${c.no} submitted for approval: ${inr(c.total)}` : `${c.no} saved as draft`); go('#/expenses') }
    catch (e) { toast(e.message); setBusy(false) }
  }
  const c = pv?.calc
  return (<div className="ord"><div>
    <div className="card"><h2>Trip</h2><p className="sub">Grade {g.code} {g.name}: {STN[x.type].toLowerCase()} daily allowance {inr0(r.da)}, travel {inr(r.km)} per km{r.hotel ? `, hotel ${inr0(r.hotel)} per night` : ''}.</p>
      <div className="tools" style={{ marginBottom: 12 }}>{Object.entries(STN).map(([k, v]) => <label key={k} className="chk"><input type="radio" name="xeType" value={k} checked={x.type === k} onChange={() => set({ type: k, nights: null, hotel: null })} /> {v}</label>)}</div>
      <div className="form"><label className="field">From<input type="date" className="inp" data-k="from" value={x.date_from} max={todayISO()} onChange={(e) => set({ date_from: e.target.value, date_to: e.target.value > x.date_to ? e.target.value : x.date_to, nights: null, hotel: x.hotel_touched ? x.hotel : null })} /></label>
        <label className="field">To<input type="date" className="inp" value={x.date_to} max={todayISO()} onChange={(e) => set({ date_to: e.target.value, nights: null, hotel: x.hotel_touched ? x.hotel : null })} /></label>
        <label className="field wide">Purpose<input className="inp" data-k="purpose" value={x.purpose} onChange={(e) => set({ purpose: e.target.value })} placeholder="e.g. Distributor visits" /></label>
        <label className="field wide">Places visited<input className="inp" value={x.places} onChange={(e) => set({ places: e.target.value })} /></label></div></div>
    <div className="card"><h2>Travel (variable)</h2><div className="form"><label className="field">Kilometres travelled<input className="inp" data-k="km" inputMode="decimal" value={x.km} onChange={(e) => set({ km: e.target.value.replace(/[^\d.]/g, '') })} /></label></div>
      <p className="fine" style={{ margin: '8px 0 0' }}>{pv?.gps_km ? <>Your recorded locations on these dates are {num(pv.gps_km)} km apart in straight lines; road distance is usually more. <a href="#" onClick={(e) => { e.preventDefault(); set({ km: String(pv.gps_km) }) }}>Use {num(pv.gps_km)} km</a></> : 'No recorded locations on these dates to suggest a distance.'}</p></div>
    <div className="card"><h2>Hotel stay</h2><p className="sub">{r.hotel ? `Defaulted from your grade: ${inr0(r.hotel)} per night. Change the amount to what you actually paid.` : 'Your grade has no hotel amount for this; enter what you paid if you stayed.'}</p>
      <div className="form"><label className="field">Nights<input className="inp" inputMode="numeric" value={x.nights ?? pv?.nights ?? 0} onChange={(e) => set({ nights: Math.max(0, parseInt(e.target.value, 10) || 0), hotel: x.hotel_touched ? x.hotel : null })} /></label>
        <label className="field">Hotel amount paid<input className="inp" id="xeHotelAmt" inputMode="decimal" value={x.hotel ?? pv?.hotel ?? 0} onChange={(e) => set({ hotel: parseNum(e.target.value), hotel_touched: true })} /></label>
        <label className="field">Hotel name<input className="inp" value={x.hotel_name} onChange={(e) => set({ hotel_name: e.target.value })} /></label>
        <label className="field">Bill number<input className="inp" value={x.hotel_bill} onChange={(e) => set({ hotel_bill: e.target.value })} /></label></div>
      {x.hotel_touched && <p className="fine" style={{ margin: '8px 0 0' }}><a href="#" onClick={(e) => { e.preventDefault(); set({ hotel: null, hotel_touched: false }) }}>Reset to the grade amount</a></p>}</div>
    <div className="card"><h2>Other expenses</h2>
      {x.others.map((o, i) => <div key={i} className="tools" style={{ marginBottom: 6 }}>
        <select className="inp" value={o.category} onChange={(e) => set({ others: x.others.map((y, j) => (j === i ? { ...y, category: e.target.value } : y)) })}>{meta.categories.map((k) => <option key={k}>{k}</option>)}</select>
        <input className="inp" style={{ width: 120, textAlign: 'right' }} inputMode="decimal" placeholder="Amount" value={o.amount} data-other="amount" onChange={(e) => set({ others: x.others.map((y, j) => (j === i ? { ...y, amount: e.target.value } : y)) })} />
        <input className="inp" style={{ flex: 1, minWidth: 140 }} placeholder="Note" value={o.note} data-other="note" onChange={(e) => set({ others: x.others.map((y, j) => (j === i ? { ...y, note: e.target.value } : y)) })} />
        <button className="btn ghost sm" onClick={() => set({ others: x.others.filter((_, j) => j !== i) })} aria-label="Remove">✕</button></div>)}
      <button className="btn sm" onClick={() => set({ others: [...x.others, { category: meta.categories[0], amount: '', note: '' }] })}>Add an expense</button></div>
  </div>
  <div className="card totals"><h2>Claim total</h2>{c && <div id="xeTot"><table><tbody>
    <tr><td>Daily allowance<div className="fine">{c.days} days × {inr0(pv.rates.da)}</div></td><td className="r">{inr(c.fixed)}</td></tr>
    <tr><td>Travel<div className="fine">{num(x.km)} km × {inr(pv.rates.km)}</div></td><td className="r">{inr(c.variable)}</td></tr>
    <tr><td>Hotel<div className="fine">{pv.nights} nights; policy {inr0(c.hotel_policy)}</div></td><td className="r">{inr(c.hotel)}</td></tr>
    <tr><td>Other</td><td className="r">{inr(c.other)}</td></tr><tr className="grand"><td>Total</td><td className="r">{inr(c.total)}</td></tr></tbody></table></div>}
    {c?.hotel_over > 0 && <div className="note warn" id="xeWarn">Hotel is {inr0(c.hotel_over)} above your grade's amount. Your approver will see this.</div>}
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 12 }}><button id="xeSubmitBtn" className="btn pri lg" disabled={busy} onClick={() => save(true)}>Submit for approval</button>
      <button className="btn" disabled={busy} onClick={() => save(false)}>Save as draft</button><a className="btn ghost" href="#/expenses">Cancel</a></div>
    <p className="fine">Keep the hotel bill and receipts; your approver may ask for them.</p></div></div>)
}

const GF = [['da_in', 'Daily allowance'], ['km_in', 'Per km'], ['hotel_in', 'Hotel / night'], ['da_out', 'Daily allowance'], ['km_out', 'Per km'], ['hotel_out', 'Hotel / night']]
export function Grades() {
  const { toast, confirm } = useUi()
  const [rows, reload] = useLoad(() => api('/api/grades'), [])
  const [edit, setEdit] = useState(null)
  const save = async (e) => {
    e.preventDefault()
    try { await api(`/api/grades/${encodeURIComponent(edit.code)}`, { method: 'PUT', body: { ...edit, ...Object.fromEntries(GF.map(([k]) => [k, parseNum(edit[k])])) } }); setEdit(null); toast('Grade saved'); reload() } catch (e2) { toast(e2.message) }
  }
  const del = async () => { if (!(await confirm(`Delete grade ${edit.code}?`, 'Only possible when no employee has it.', 'Delete'))) return; try { await api(`/api/grades/${edit.code}`, { method: 'DELETE' }); setEdit(null); reload() } catch (e) { toast(e.message) } }
  return (<div className="card"><div className="hd"><div><h2>Expense policy by grade</h2><p className="sub"><b>Fixed</b>: a daily allowance for each day of a claim. <b>Variable</b>: a rate per km. <b>Hotel</b>: the amount per night, filled in on the claim by default; the employee enters what was paid, and anything above is flagged for the approver.</p></div>
    <button className="btn pri" onClick={() => setEdit({ code: '', name: '', isNew: true, ...Object.fromEntries(GF.map(([k]) => [k, ''])) })}>Add grade</button></div>
    {!rows ? <div className="loading">Loading…</div> : rows.length ? <div className="scroll"><table className="t"><thead><tr><th rowSpan={2}>Grade</th><th rowSpan={2}>Name</th><th colSpan={3} className="c">In-station</th><th colSpan={3} className="c">Out-station</th><th rowSpan={2} className="r">Employees</th></tr>
      <tr>{GF.map(([k, l]) => <th key={k} className="r">{l}</th>)}</tr></thead><tbody>
      {rows.map((g) => <tr key={g.code} className="click" onClick={() => setEdit(g)}><td className="mono"><b>{g.code}</b></td><td>{g.name}</td>{GF.map(([k]) => <td key={k} className="r">{k.startsWith('km') ? inr(g[k]) : inr0(g[k])}</td>)}<td className="r">{g.employees}</td></tr>)}</tbody></table></div>
      : <div className="empty">No grades yet. Add one for each employee grade.</div>}
    <Modal open={!!edit} onClose={() => setEdit(null)} wide>{edit && <form className="dlg" onSubmit={save}><h2>{edit.isNew ? 'Add grade' : `Edit grade ${edit.code}`}</h2>
      <div className="form"><label className="field">Grade code<input className="inp" name="code" value={edit.code} readOnly={!edit.isNew} onChange={(e) => setEdit({ ...edit, code: e.target.value.toUpperCase() })} autoFocus /></label>
        <label className="field wide">Name<input className="inp" name="name" value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></label></div>
      {[['In-station', GF.slice(0, 3)], ['Out-station', GF.slice(3)]].map(([t, fs]) => <div key={t}><b style={{ fontSize: 13 }}>{t}</b><div className="form">{fs.map(([k, l]) => <label key={k} className="field">{l}<input className="inp" name={k} inputMode="decimal" value={edit[k]} onChange={(e) => setEdit({ ...edit, [k]: e.target.value })} /></label>)}</div></div>)}
      <p className="fine" style={{ margin: 0 }}>Changes apply to new claims; saved claims keep the rates they were made with.</p>
      <div className="btns">{!edit.isNew && <button type="button" className="btn danger" onClick={del}>Delete</button>}<button type="button" className="btn ghost" onClick={() => setEdit(null)}>Cancel</button><button className="btn pri">Save</button></div></form>}</Modal></div>)
}
