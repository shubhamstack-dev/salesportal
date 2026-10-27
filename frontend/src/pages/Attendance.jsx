import { useState } from 'react'
import { go } from '../App'
import { api, DAYCODE, dmy, download, fmtH, inr0, todayISO } from '../lib'
import MapView, { LocLink } from '../maps'
import { useSession } from '../session'
import { Modal, useLoad, useUi } from '../ui'
import { corrText } from './TimeClock'

export default function Attendance({ route }) {
  const { isMgr, settings: s } = useSession(); const { toast } = useUi()
  const month = route.q.get('m') || todayISO().slice(0, 7)
  const [mus] = useLoad(() => api(`/api/attendance/muster?month=${month}`), [month])
  const [corr, reloadCorr] = useLoad(() => (isMgr ? api('/api/corrections') : Promise.resolve([])), [])
  const [day, setDay] = useState(null)
  const decide = async (c, approve) => {
    try { await api(`/api/corrections/${c.id}/decide`, { method: 'POST', body: { approve } }); toast(approve ? 'Correction approved; attendance updated' : 'Correction rejected'); reloadCorr(); go(window.location.hash) } catch (e) { toast(e.message) }
  }
  const [y, m] = month.split('-').map(Number)
  return (<>
    {isMgr && <div className="card"><h2>Correction requests</h2><p className="sub">Missed Time In or Time Out reported by your team. Approving changes their attendance; corrected punches are marked and have no location.</p>
      {corr?.length ? <div className="scroll"><table className="t"><thead><tr><th>Employee</th><th>Date</th><th>Asked for</th><th>Recorded</th><th>Reason</th><th /></tr></thead><tbody>
        {corr.map((c) => <tr key={c.id}><td><b>{c.employee}</b><div className="fine">{c.emp_code}</div></td><td>{dmy(c.date)}</td><td>{corrText(c)}</td>
          <td className="fine">{c.recorded.map((a) => `in ${a.in_local}${a.out_local ? ', out ' + a.out_local : ''}`).join('; ') || 'nothing'}</td><td>{c.reason}</td>
          <td className="r" style={{ whiteSpace: 'nowrap' }}><button className="btn danger sm" onClick={() => decide(c, false)}>Reject</button> <button className="btn ok sm" onClick={() => decide(c, true)}>Approve</button></td></tr>)}
      </tbody></table></div> : <div className="empty">No requests waiting.</div>}</div>}
    <div className="card"><div className="hd"><div><h2>Attendance muster</h2><p className="sub">From Time In and Time Out against the shift (start {s.shift_start}, {s.grace_min} min grace): P present ({s.full_day_hrs} h or more), H half day ({s.half_day_hrs} h or more), S short day, A absent, WO Sunday. A red corner marks a late Time In.</p></div>
      <div className="tools"><input type="month" className="inp" value={month} onChange={(e) => go('#/attendance?m=' + e.target.value)} aria-label="Month" />
        {isMgr && <button className="btn" onClick={() => download(`/api/attendance/muster.xlsx?month=${month}`, `Attendance_${month}.xlsx`).catch((e) => toast(e.message))}>Download Excel</button>}</div></div>
      {!mus ? <div className="loading">Loading…</div> : mus.rows.length ? <div className="scroll"><table className="mus"><thead><tr><th className="nm">Employee</th>
        {Array.from({ length: mus.days }, (_, i) => <th key={i}>{i + 1}<br />{'SMTWTFS'[new Date(y, m - 1, i + 1).getDay()]}</th>)}</tr></thead><tbody>
        {mus.rows.map((r) => <tr key={r.user_id}><td className="nm"><b>{r.name}</b><div className="fine">{r.emp_code} · {r.present} days · {r.hours.toFixed(1)} h{r.late_days ? ` · ${r.late_days} late` : ''}</div></td>
          {r.cells.map((c) => <td key={c.date}><button className={`${c.code}${c.late ? ' late' : ''}`} title={`${dmy(c.date)}: ${DAYCODE[c.code][0]}${c.hours ? ', ' + fmtH(c.hours) : ''}${c.late ? `, late ${c.late} min` : ''}`}
            onClick={() => setDay({ user: r.user_id, date: c.date })}>{c.code}</button></td>)}</tr>)}</tbody></table></div>
        : <div className="empty">No employees to show.</div>}</div>
    <DayDialog day={day} onClose={() => setDay(null)} />
  </>)
}

function DayDialog({ day, onClose }) {
  const [d] = useLoad(() => (day ? api(`/api/attendance/day?user_id=${day.user}&date_=${day.date}`) : Promise.resolve(null)), [day?.user, day?.date])
  if (!day) return <Modal open={false} />
  return <Modal open onClose={onClose} wide>{!d ? <div className="loading">Loading…</div> : <div className="dlg"><h2>{d.employee}, {dmy(d.date)}</h2>
    <p style={{ margin: 0 }}><span className={`badge ${DAYCODE[d.status.code][1]}`}>{d.status.label}</span>{d.sessions.length ? ` ${fmtH(d.status.hours)}` : ''}{d.status.late ? ` · Time In ${d.status.late} min late` : ''}</p>
    {d.sessions.length ? <div className="scroll"><table className="t"><thead><tr><th>Time In</th><th>Where</th><th>Time Out</th><th>Where</th></tr></thead><tbody>
      {d.sessions.map((a) => <tr key={a.id}><td>{a.in_local}{a.source === 'correction' && <span className="badge info"> Corrected</span>}{a.in_note && <div className="fine">{a.in_note}</div>}</td>
        <td>{a.in.addr} {a.in.lat != null && <LocLink p={a.in} label="map" />}</td><td>{a.out_local || '—'}{a.out_note && <div className="fine">{a.out_note}</div>}</td>
        <td>{a.out?.addr} {a.out?.lat != null && <LocLink p={a.out} label="map" />}</td></tr>)}</tbody></table></div> : <p className="mut">No punches this day.</p>}
    <p className="fine">{d.orders} orders ({inr0(d.orders_total)}), {d.payments} payments ({inr0(d.payments_total)}).</p>
    <MapView small points={d.points.map((p, i) => ({ ...p, title: p.what, color: p.what === 'Time In' ? 'green' : p.what === 'Time Out' ? 'red' : 'blue', label: i + 1 }))} />
    <div className="btns"><button className="btn" onClick={onClose}>Close</button></div></div>}</Modal>
}
