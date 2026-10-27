import { go } from '../App'
import { api, dmy, inr, num } from '../lib'
import { useSession } from '../session'
import { useLoad } from '../ui'
import { RoNote } from './Customers'

export function Materials({ route }) {
  const q = route.q.get('q') || ''
  const [rows] = useLoad(() => api(`/api/materials?q=${encodeURIComponent(q)}`), [q])
  return (<><RoNote what="Materials, their attributes and units" /><div className="card"><div className="hd"><div><h2>Materials</h2><p className="sub">With attributes, HSN code, GST rate and base price.</p></div>
    <input className="inp" placeholder="Search code, name, attribute, HSN" defaultValue={q} onKeyDown={(e) => e.key === 'Enter' && go('#/materials?q=' + encodeURIComponent(e.target.value))} style={{ minWidth: 240 }} /></div>
    {!rows ? <div className="loading">Loading…</div> : rows.length ? <div className="scroll"><table className="t"><thead><tr><th>Code</th><th>Material and attributes</th><th>UOM</th><th>HSN</th><th className="r">GST</th><th className="r">Base price</th></tr></thead><tbody>
      {rows.map((m) => <tr key={m.id}><td className="mono">{m.code}</td><td><b>{m.name}</b>{m.blocked && <span className="badge bad"> Blocked</span>}<div>{Object.entries(m.attrs).map(([k, v]) => <span key={k} className="chip">{k}: {v}</span>)}</div></td>
        <td>{m.uom}</td><td className="mono">{m.hsn}{m.hsn && !m.hsn_known && <span className="badge warn"> HSN not downloaded</span>}</td><td className="r">{m.gst}%{m.cess ? ` + ${m.cess}% cess` : ''}</td>
        <td className="r">{m.base_price != null ? inr(m.base_price) : <span className="mut">No base price</span>}</td></tr>)}</tbody></table></div> : <div className="empty">No materials.</div>}</div></>)
}

const PTYPE = { all: 'All customers', group: 'Price group', customer: 'Customer' }
export function Prices({ route }) {
  const g = route.q.get('g') || ''
  const [rows] = useLoad(() => api(`/api/prices?group=${encodeURIComponent(g)}`), [g])
  const [groups] = useLoad(() => api('/api/price-groups'), [])
  return (<><RoNote what="Prices" /><div className="card"><div className="hd"><div><h2>Price lists</h2><p className="sub">Quotations and orders use the customer's own price first, then its price group, then the price for all customers, within the valid dates and minimum quantity.</p></div>
    <select className="inp" value={g} onChange={(e) => go('#/prices?g=' + encodeURIComponent(e.target.value))}><option value="">All price lists</option><option value="*all">All customers (base)</option>{(groups || []).map((x) => <option key={x}>{x}</option>)}</select></div>
    {!rows ? <div className="loading">Loading…</div> : rows.length ? <div className="scroll"><table className="t"><thead><tr><th>Applies to</th><th>Material</th><th>Description</th><th>Unit</th><th className="r">Unit price</th><th className="r">Min qty</th><th>From</th><th>To</th></tr></thead><tbody>
      {rows.map((p) => <tr key={p.id}><td>{PTYPE[p.type]}{p.code && <>: <b>{p.code}</b></>}</td><td className="mono">{p.material}</td><td>{p.name}</td><td>{p.uom}</td><td className="r">{inr(p.price)}</td><td className="r">{p.min_qty ? num(p.min_qty) : ''}</td><td>{dmy(p.from) || '—'}</td><td>{dmy(p.to) || '—'}</td></tr>)}</tbody></table></div>
      : <div className="empty">No prices.</div>}</div></>)
}

export function Hsn() {
  const { settings, states } = useSession()
  const [d] = useLoad(() => api('/api/hsn'), [])
  return (<><RoNote what="HSN / SAC codes and GST rates" /><div className="card"><h2>HSN / SAC codes and GST rates</h2><p className="sub">Each material takes its GST rate from its HSN code. Same state as the company: CGST + SGST; other states: IGST. Company state: {states[settings.company.state] || 'not set'}.</p>
    {d?.materials_without_hsn > 0 && <div className="note warn">{d.materials_without_hsn} materials have an HSN code that has not been downloaded, so they are charged 0% GST.</div>}
    {!d ? <div className="loading">Loading…</div> : <div className="scroll"><table className="t"><thead><tr><th>HSN / SAC</th><th>Description</th><th className="r">GST</th><th className="r">CGST + SGST</th><th className="r">IGST</th><th className="r">Cess</th><th className="r">Materials</th></tr></thead><tbody>
      {d.codes.map((h) => <tr key={h.code}><td className="mono"><b>{h.code}</b></td><td>{h.description}</td><td className="r">{h.rate}%</td><td className="r">{h.rate / 2}% + {h.rate / 2}%</td><td className="r">{h.rate}%</td><td className="r">{h.cess ? h.cess + '%' : '—'}</td><td className="r">{h.materials}</td></tr>)}</tbody></table></div>}</div></>)
}

export function Charges() {
  const [rows] = useLoad(() => api('/api/charges'), [])
  return (<><RoNote what="Charges and discounts" /><div className="card"><h2>Percentage and fixed charges</h2><p className="sub">Charges before GST change the taxable value and take GST at the weighted rate of the lines; charges after GST (such as TCS) are worked on the invoice value.</p>
    {!rows ? <div className="loading">Loading…</div> : rows.length ? <div className="scroll"><table className="t"><thead><tr><th>Code</th><th>Name</th><th className="r">Rate</th><th>Worked on</th><th>Applied to</th><th>Status</th></tr></thead><tbody>
      {rows.map((c) => <tr key={c.code}><td className="mono"><b>{c.code}</b></td><td>{c.name}</td><td className="r">{c.sign < 0 ? '−' : '+'}{c.calc === 'fixed' ? inr(c.value) : c.value + '%'}</td>
        <td>{c.stage === 'post' ? 'Invoice value, after GST' : 'Taxable value, before GST'}</td><td>{c.auto ? <span className="badge acc">Every order</span> : <span className="badge">When chosen</span>}</td>
        <td>{c.active ? <span className="badge ok">Active</span> : <span className="badge">Inactive</span>}</td></tr>)}</tbody></table></div> : <div className="empty">No charges.</div>}</div></>)
}
