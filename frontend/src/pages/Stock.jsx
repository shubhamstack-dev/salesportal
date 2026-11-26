import { useEffect, useState } from 'react'
import { go } from '../App'
import { api, dmy, dt, num } from '../lib'
import { useSession } from '../session'
import { useLoad, useUi } from '../ui'

function Expiry({ days }) {
  if (days == null) return null
  if (days < 0) return <span className="badge bad">Expired</span>
  if (days <= 30) return <span className="badge warn">{days} days left</span>
  return null
}

export function Stock({ route }) {
  const { role } = useSession(); const { toast } = useUi()
  const loc = route.q.get('loc') || ''
  const q = route.q.get('q') || ''
  const lots = route.q.get('lots') === '1'
  const zero = route.q.get('zero') === '1'
  const [d, reload] = useLoad(() => api(`/api/stock?location=${encodeURIComponent(loc)}&q=${encodeURIComponent(q)}&zero=${zero}`), [loc, q, zero])
  const [busy, setBusy] = useState(false)
  const canRefresh = role === 'admin' || role === 'manager'
  const set = (k, v) => {
    const p = new URLSearchParams(route.q)
    if (v) p.set(k, v); else p.delete(k)
    go('#/stock' + (p.toString() ? '?' + p : ''))
  }
  // an automatic refresh runs on the server when the stock is old; look again once it has had time to finish
  useEffect(() => { if (d?.refreshing) { const t = setTimeout(reload, 8000); return () => clearTimeout(t) } }, [d, reload])
  const refresh = async () => {
    setBusy(true)
    try { const r = await api('/api/stock/refresh', { method: 'POST' }); toast(`Stock updated from Dynamics: ${r.items} items, ${r.lines} lines`); reload() } catch (e) { toast(e.message) }
    setBusy(false)
  }
  const locs = d?.locations || []
  const cols = loc ? locs.filter((l) => l.code === loc.toUpperCase()) : locs
  const lname = (c) => locs.find((l) => l.code === c)?.name
  return (<div className="card">
    <div className="hd"><div><h2>Stock by location</h2>
      <p className="sub">Stock on hand in Business Central, by item and location{d?.synced ? <> · updated {dt(d.synced)}</> : ''}{d?.refreshing ? ' · updating now…' : ''}
        {d?.minutes > 0 && d?.api ? <> · updates itself every {d.minutes} minutes when opened</> : ''}.</p></div>
      {canRefresh && <button className="btn" disabled={busy || !d?.api} onClick={refresh} title={d?.api ? '' : 'Set the Stock endpoint under Dynamics sync first'}>{busy ? 'Updating…' : 'Refresh from Dynamics'}</button>}</div>
    {d && !d.api && <div className="note warn">Stock is not linked to Dynamics yet. {role === 'admin' ? <>Under <a href="#/integration">Dynamics sync</a>, Dynamics connection, set the <b>Stock by location</b> endpoint (for example <code>odata:ItemLedgerEntries</code>, the Item Ledger Entries page published under Web Services), then Save connection.</> : 'Ask the administrator to set it up.'}</div>}
    {d?.error && <div className="note bad">The last automatic update failed ({dt(d.error.at)}): {d.error.message}</div>}
    <div className="tools" style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', margin: '10px 0' }}>
      <select className="inp" value={loc.toUpperCase()} onChange={(e) => set('loc', e.target.value)}>
        <option value="">All locations</option>
        {locs.map((l) => <option key={l.code} value={l.code}>{l.code}{l.name ? ` · ${l.name}` : ''} ({num(l.qty)})</option>)}
      </select>
      <input className="inp" placeholder="Search item code or name" defaultValue={q} onKeyDown={(e) => e.key === 'Enter' && set('q', e.target.value.trim())} style={{ minWidth: 220 }} />
      <label className="chk"><input type="checkbox" checked={lots} onChange={(e) => set('lots', e.target.checked ? '1' : '')} /> Show lots and expiry</label>
      <label className="chk"><input type="checkbox" checked={zero} onChange={(e) => set('zero', e.target.checked ? '1' : '')} /> Include items with no stock</label>
    </div>
    {!d ? <div className="loading">Loading…</div> : d.rows.length ? <div className="scroll"><table className="t"><thead><tr><th>Code</th><th>Material</th><th>UOM</th>
      {cols.map((l) => <th key={l.code} className="r" title={l.name}>{l.code}{l.name && <div className="fine">{l.name}</div>}</th>)}{cols.length !== 1 && <th className="r">Total</th>}</tr></thead>
      <tbody>{d.rows.map((r) => [
        <tr key={r.code}><td className="mono">{r.code}</td><td><b>{r.name || <span className="mut">Not among the materials here</span>}</b> <Expiry days={r.next_expiry_days} /></td><td>{r.uom}</td>
          {cols.map((l) => <td key={l.code} className="r">{r.by_loc[l.code] ? num(r.by_loc[l.code]) : <span className="mut">—</span>}</td>)}
          {cols.length !== 1 && <td className="r"><b>{num(r.total)}</b></td>}</tr>,
        lots && r.lots.length > 0 && <tr key={r.code + '-lots'}><td></td><td colSpan={2 + cols.length + (cols.length !== 1 ? 1 : 0)}>
          <table className="t" style={{ margin: '0 0 6px' }}><thead><tr><th>Location</th><th>Lot No.</th><th>Expiry</th><th className="r">Quantity</th></tr></thead><tbody>
            {r.lots.map((x, i) => <tr key={i}><td>{x.location}{lname(x.location) ? ` · ${lname(x.location)}` : ''}</td><td className="mono">{x.lot || '—'}</td><td>{dmy(x.expiry) || '—'} <Expiry days={x.days} /></td><td className="r">{num(x.qty)}</td></tr>)}
          </tbody></table></td></tr>,
      ])}</tbody></table></div>
      : <div className="empty">{d.synced || !d.api ? 'No stock found for this choice.' : 'No stock downloaded yet.'}</div>}
  </div>)
}
