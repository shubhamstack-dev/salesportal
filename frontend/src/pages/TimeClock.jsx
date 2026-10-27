import { useEffect, useState } from 'react'
import { addressOf, api, DAYCODE, dmy, fmtH, getPosition, inr0 } from '../lib'
import MapView, { LocLink } from '../maps'
import { useSession } from '../session'
import { Modal, useLoad, useUi } from '../ui'

export const CTYPE = { out: 'Missed Time Out', in: 'Missed Time In', day: 'Whole day missed' }

function useClock() {
  const [now, setNow] = useState(new Date())
  useEffect(() => { const t = setInterval(() => setNow(new Date()), 1000); return () => clearInterval(t) }, [])
  return now
}

/* Time In / Time Out: posts the punch with the phone's location, then fills in the street address via Google Maps */
export function usePunch(reload) {
  const { settings } = useSession(); const { toast } = useUi()
  const [busy, setBusy] = useState(false)
  const punch = async (kind, note = '') => {
    setBusy(true)
    let p = {}
    try { p = await getPosition() } catch (e) {
      if (settings.punch_needs_location) { toast(e.message + ' Time In and Out need your location.'); setBusy(false); return }
      toast(e.message + ' Recorded without a location.')
    }
    try {
      const r = await api('/api/timeclock/punch', { method: 'POST', body: { kind, note, ...p } })
      toast(kind === 'in' ? `Timed in at ${r.session.in_local}${r.late ? ` (${r.late} min late)` : ''}` : `Timed out at ${r.session.out_local} · ${fmtH(r.hours_today)} today`)
      await reload()
      if (p.lat != null) { const a = await addressOf(settings.maps_key, p); if (a) { await api(`/api/attendance/${r.session.id}/address`, { method: 'PATCH', body: { side: kind, addr: a } }); reload() } }
    } catch (e) { toast(e.message) } finally { setBusy(false) }
  }
  return [punch, busy]
}

export default function TimeClock() {
  const { settings: s } = useSession()
  const [t, reload] = useLoad(() => api('/api/timeclock'), [])
  const [note, setNote] = useState('')
  const [corr, setCorr] = useState(null)
  const [punch, busy] = usePunch(reload)
  const now = useClock()
  if (!t) return <div className="loading">Loading…</div>
  const last = t.sessions[t.sessions.length - 1]
  return (<>
    {t.stale && <div className="note warn">You did not Time Out on {dmy(t.stale.date)} (in at {t.stale.in_local}). <a href="#" onClick={(e) => { e.preventDefault(); setCorr(t.stale.date) }}>Request a correction</a> so that day counts.</div>}
    <div className="grid g2">
      <div className="card punch"><div className="fine">{now.toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}</div>
        <div className="clock">{now.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</div>
        <div className="state" style={{ color: t.on_duty ? 'var(--ok)' : 'var(--muted)' }}>{t.on_duty ? `Timed in at ${last.in_local} · ${fmtH(t.status.hours)} today`
          : t.sessions.length ? `Timed out at ${last.out_local} · ${fmtH(t.status.hours)} today` : 'Not timed in yet today'}</div>
        <input className="inp" id="punchNote" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note (optional): office, field, client site…" maxLength={80} style={{ width: 'min(340px,100%)', marginBottom: 12 }} />
        <div><button id="punchBtn" className={`btn lg ${t.on_duty ? '' : 'ok'}`} style={{ minWidth: 200 }} disabled={busy} onClick={() => { punch(t.on_duty ? 'out' : 'in', note); setNote('') }}>
          {busy ? 'Getting your location…' : t.on_duty ? 'Time Out' : 'Time In'}</button></div>
        <p className="fine" style={{ margin: '12px 0 0' }}>Shift starts {s.shift_start} ({s.grace_min} min grace). Full day {s.full_day_hrs} h, half day {s.half_day_hrs} h.{s.punch_needs_location ? ' Your location is recorded with each punch.' : ''}</p></div>
      <div className="card"><h2>Today</h2><p className="sub">{t.sessions.length ? `${fmtH(t.status.hours)} worked${t.status.late ? `, Time In ${t.status.late} min late` : ''}.` : 'No punches yet.'} You can Time In and Out more than once a day; the hours add up.</p>
        {t.sessions.length ? <div className="scroll"><table className="t"><thead><tr><th>Time In</th><th>Time Out</th><th>Where</th></tr></thead><tbody>
          {t.sessions.map((a) => <tr key={a.id}><td><b>{a.in_local}</b>{a.in_note && <div className="fine">{a.in_note}</div>}</td>
            <td>{a.out_local ? <b>{a.out_local}</b> : <span className="badge ok">On duty</span>}{a.out_note && <div className="fine">{a.out_note}</div>}</td>
            <td>{a.in.addr} <LocLink p={a.in} label="in" />{a.out?.lat != null && <> · <LocLink p={a.out} label="out" /></>}{a.source === 'correction' && <span className="badge info"> Corrected</span>}</td></tr>)}</tbody></table></div>
          : <div className="empty">Select Time In to start your day.</div>}</div>
    </div>
    <div className="card"><h2>Last 14 days</h2><p className="sub">If a day is wrong, for example you forgot to Time Out, request a correction; your manager approves it.</p>
      <div className="scroll"><table className="t"><thead><tr><th>Date</th><th>First In</th><th>Last Out</th><th className="r">Hours</th><th>Status</th><th /></tr></thead><tbody>
        {t.history.map((h) => <tr key={h.date}><td>{dmy(h.date)} <span className="fine">{h.weekday}</span></td><td>{h.first_in || '—'}</td>
          <td>{h.last_out || (h.open_last ? (h.date === t.today ? <span className="badge ok">On duty</span> : <span className="badge warn">No Time Out</span>) : '—')}</td>
          <td className="r">{h.first_in ? fmtH(h.hours) : '—'}</td>
          <td><span className={`badge ${DAYCODE[h.code][1]}`}>{DAYCODE[h.code][0]}</span>{h.late ? <span className="badge warn"> Late {h.late} min</span> : null}{h.corrected && <span className="badge info"> Corrected</span>}</td>
          <td className="r">{h.correction_pending ? <span className="badge info">Correction requested</span> : (h.code === 'A' || h.first_in) && <button className="btn ghost sm" onClick={() => setCorr(h.date)}>Request correction</button>}</td></tr>)}
      </tbody></table></div></div>
    {t.corrections.length > 0 && <div className="card"><h2>My correction requests</h2><div className="scroll"><table className="t"><thead><tr><th>Date</th><th>Asked for</th><th>Reason</th><th>Status</th></tr></thead><tbody>
      {t.corrections.map((c) => <tr key={c.id}><td>{dmy(c.date)}</td><td>{corrText(c)}</td><td>{c.reason}</td><td><span className={`badge ${c.status === 'approved' ? 'ok' : c.status === 'rejected' ? 'bad' : 'warn'}`}>{c.status === 'pending' ? 'Waiting for approval' : c.status}</span></td></tr>)}</tbody></table></div></div>}
    <CorrectionDialog date={corr} history={t.history} sessions={t} onClose={() => setCorr(null)} onDone={reload} />
  </>)
}
export const corrText = (c) => `${CTYPE[c.type]}: ${c.in_time ? 'In ' + c.in_time : ''}${c.in_time && c.out_time ? ', ' : ''}${c.out_time ? 'Out ' + c.out_time : ''}`

function CorrectionDialog({ date, history, onClose, onDone }) {
  const { settings } = useSession(); const { toast } = useUi()
  const [f, setF] = useState(null); const [err, setErr] = useState('')
  useEffect(() => {
    if (!date) return
    const h = history.find((x) => x.date === date)
    setF({ date, type: h?.open_last ? 'out' : h?.first_in ? 'in' : 'day', in_time: settings.shift_start, out_time: '18:00', reason: '' }); setErr('')
  }, [date]) // eslint-disable-line react-hooks/exhaustive-deps
  if (!date || !f) return <Modal open={false} />
  const send = async (e) => {
    e.preventDefault()
    try { await api('/api/corrections', { method: 'POST', body: f }); onClose(); toast('Correction sent for approval'); onDone() } catch (e2) { setErr(e2.message) }
  }
  return <Modal open onClose={onClose}><form className="dlg" onSubmit={send} noValidate><h2>Request an attendance correction</h2>
    <div className="form"><label className="field">Date<input type="date" className="inp" value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} /></label>
      <label className="field">What happened<select className="inp" name="type" value={f.type} onChange={(e) => setF({ ...f, type: e.target.value })}>{Object.entries(CTYPE).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
      {f.type !== 'out' && <label className="field">Time In<input type="time" className="inp" name="inTime" value={f.in_time} onChange={(e) => setF({ ...f, in_time: e.target.value })} /></label>}
      {f.type !== 'in' && <label className="field">Time Out<input type="time" className="inp" name="outTime" value={f.out_time} onChange={(e) => setF({ ...f, out_time: e.target.value })} /></label>}
      <label className="field wide">Reason<input className="inp" name="reason" value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} placeholder="e.g. phone battery died" autoFocus /></label></div>
    <p className="err" id="cre">{err}</p><div className="btns"><button type="button" className="btn ghost" onClick={onClose}>Cancel</button><button className="btn pri">Send to my manager</button></div></form></Modal>
}

export function MyDay() {
  const [t, reload] = useLoad(() => api('/api/timeclock'), [])
  const [d] = useLoad(() => api('/api/dashboard'), [t])
  const [punch, busy] = usePunch(reload)
  const now = useClock()
  if (!t) return <div className="loading">Loading…</div>
  const me = d?.team?.[0]
  const pts = t.sessions.flatMap((a, i) => [{ ...a.in, title: 'Time In ' + a.in_local, color: 'green', label: 2 * i + 1 }, ...(a.out ? [{ ...a.out, title: 'Time Out ' + a.out_local, color: 'red', label: 2 * i + 2 }] : [])])
  return (<>
    <div className="grid g2">
      <div className="card punch"><div className="fine">{now.toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long' })}</div>
        <div className="clock">{now.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}</div>
        <div className="state" style={{ color: t.on_duty ? 'var(--ok)' : 'var(--muted)' }}>{t.on_duty ? `On duty since ${t.sessions[t.sessions.length - 1].in_local}` : t.sessions.length ? 'Off duty' : 'Not timed in yet'}</div>
        <button id="punchBtn" className={`btn lg ${t.on_duty ? '' : 'ok'}`} disabled={busy} onClick={() => punch(t.on_duty ? 'out' : 'in')}>{busy ? 'Getting your location…' : t.on_duty ? 'Time Out' : 'Time In'}</button>
        <p className="fine" style={{ margin: '10px 0 0' }}><a href="#/timeclock">Time in / Time out history and corrections</a></p></div>
      <div className="card"><h2>Today</h2><p className="sub">Your orders and collections.</p>
        <div className="grid g2"><div className="kpi"><span>Orders</span><b>{inr0(me?.orders_value || 0)}</b><small>{me?.orders || 0} orders</small></div>
          <div className="kpi"><span>Collected</span><b>{inr0(me?.collected || 0)}</b><small>today</small></div></div>
        <div className="tools" style={{ marginTop: 14 }}><a className="btn pri" href="#/order/new">New order</a><a className="btn" href="#/quote/new">New quotation</a>
          <a className="btn" href="#/payment/new">Receive payment</a><a className="btn" href="#/expense/new">Claim expenses</a></div></div>
    </div>
    <div className="card"><h2>Where you were today</h2><MapView points={pts} small /></div>
  </>)
}
