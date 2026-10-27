import { api } from '../lib'
import { useSession } from '../session'
import { useLoad, useUi } from '../ui'

export default function Settings() {
  const { toast } = useUi(); const { states, reloadMe } = useSession()
  const [s, reload] = useLoad(() => api('/api/settings'), [])
  if (!s) return <div className="loading">Loading…</div>
  const save = async (e) => {
    e.preventDefault()
    const f = Object.fromEntries(new FormData(e.target))
    const body = { company: { name: f.name, gstin: f.gstin.trim().toUpperCase(), state: f.state, address: f.address },
      prefixes: { order: f.p_order, quote: f.p_quote, payment: f.p_payment, expense: f.p_expense }, quote_days: +f.quote_days || 15,
      need_approval: !!f.need_approval, credit_check: f.credit_check, price_override: !!f.price_override, round_off: !!f.round_off,
      shift_start: f.shift_start, grace_min: +f.grace_min || 0, full_day_hrs: +f.full_day_hrs || 8, half_day_hrs: +f.half_day_hrs || 4, punch_needs_location: !!f.punch_needs_location,
      maps_key: f.maps_key.trim(), geofence_m: +f.geofence_m || 300 }
    try { await api('/api/settings', { method: 'PUT', body }); toast('Settings saved'); reload(); reloadMe() } catch (e2) { toast(e2.message) }
  }
  const c = s.company
  return (<form onSubmit={save}>
    <div className="card"><h2>Company</h2><p className="sub">The company state decides CGST + SGST (same state) or IGST (other states).</p><div className="form">
      <label className="field">Company name<input className="inp" name="name" defaultValue={c.name} /></label><label className="field">GSTIN<input className="inp" name="gstin" defaultValue={c.gstin} maxLength={15} /></label>
      <label className="field">State<select className="inp" name="state" defaultValue={c.state}>{Object.entries(states).map(([k, v]) => <option key={k} value={k}>{k} {v}</option>)}</select></label>
      <label className="field wide">Address (printed on documents)<input className="inp" name="address" defaultValue={c.address} /></label></div></div>
    <div className="card"><h2>Quotations, orders and payments</h2><div className="form">
      {['order', 'quote', 'payment', 'expense'].map((k) => <label key={k} className="field">{k[0].toUpperCase() + k.slice(1)} number prefix<input className="inp" name={'p_' + k} defaultValue={s.prefixes[k]} /></label>)}
      <label className="field">Quotations valid for (days)<input className="inp" name="quote_days" defaultValue={s.quote_days} /></label>
      <label className="field">Credit limit check<select className="inp" name="credit_check" defaultValue={s.credit_check}><option value="warn">Warn</option><option value="block">Block orders over the limit</option><option value="off">Off</option></select></label>
      <label className="chk"><input type="checkbox" name="need_approval" defaultChecked={s.need_approval} /> Sales representatives' orders need approval</label>
      <label className="chk"><input type="checkbox" name="price_override" defaultChecked={s.price_override} /> Sales staff may change prices</label>
      <label className="chk"><input type="checkbox" name="round_off" defaultChecked={s.round_off} /> Round totals to the rupee</label></div></div>
    <div className="card"><h2>Shift and Time In / Time Out</h2><div className="form">
      <label className="field">Shift starts at<input type="time" className="inp" name="shift_start" defaultValue={s.shift_start} /></label>
      <label className="field">Grace before late (minutes)<input className="inp" name="grace_min" defaultValue={s.grace_min} /></label>
      <label className="field">Hours for a full day<input className="inp" name="full_day_hrs" defaultValue={s.full_day_hrs} /></label>
      <label className="field">Hours for a half day<input className="inp" name="half_day_hrs" defaultValue={s.half_day_hrs} /></label>
      <label className="chk wide"><input type="checkbox" name="punch_needs_location" defaultChecked={s.punch_needs_location} /> Time In and Time Out need the phone's location</label></div></div>
    <div className="card"><h2>Google Maps and location</h2><div className="form">
      <label className="field wide">Google Maps JavaScript API key<input className="inp" name="maps_key" defaultValue={s.maps_key} placeholder="AIza…" autoComplete="off" /></label>
      <label className="field">Distance from customer that counts as away (m)<input className="inp" name="geofence_m" defaultValue={s.geofence_m} /></label></div>
      <p className="fine">Enable the Maps JavaScript API and Geocoding API for the key, and restrict it to the portal's web address. Phones share their location only over https.</p></div>
    <button className="btn pri">Save settings</button></form>)
}
