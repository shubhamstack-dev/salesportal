import { useRef, useState } from 'react'
import { api, download, dt, inr0 } from '../lib'
import { useSession } from '../session'
import { Modal, useLoad, useUi } from '../ui'

const FLABEL = { code: 'Code / No.', name: 'Name', gstin: 'GSTIN', state: 'State', address: 'Address', city: 'City', pin: 'PIN', phone: 'Phone', email: 'E-mail', price_group: 'Price group',
  terms: 'Payment terms', credit_limit: 'Credit limit', balance: 'Balance', blocked: 'Blocked', uom: 'Unit', hsn: 'HSN/SAC', category: 'Category', price: 'Unit price', material: 'Item no.',
  value: 'Value / rate', type: 'Applies to (type)', min_qty: 'Minimum quantity', from: 'Valid from', to: 'Valid to', description: 'Description', rate: 'GST %', cess: 'Cess %',
  calc: 'Calculation', sign: 'Charge or discount', stage: 'Before / after GST', auto: 'Apply to every order', active: 'Active / blocked' }

export default function Integration() {
  const { toast, confirm } = useUi(); const { refreshCounts } = useSession()
  const [s, reload] = useLoad(() => api('/api/integration/summary'), [])
  const [imp, setImp] = useState(null)
  const fileRef = useRef(null), ackRef = useRef(null), entRef = useRef('')
  const after = () => { reload(); refreshCounts() }
  const pickFile = (ent) => { entRef.current = ent; fileRef.current.click() }
  const upload = async (file) => {
    const form = new FormData(); form.append('file', file)
    try { setImp(await api(`/api/integration/import/${entRef.current}/file`, { method: 'POST', form })) } catch (e) { toast(e.message) }
  }
  const pull = async (ent) => { toast('Downloading from Dynamics…'); try { setImp(await api(`/api/integration/import/${ent}/api`, { method: 'POST' })) } catch (e) { toast(e.message) } }
  const exportOut = async () => { try { await download('/api/integration/export', `To_Dynamics_${new Date().toISOString().slice(0, 10)}.xlsx`, { method: 'POST' }); toast('Exported. Import the Dynamics numbers back when they are posted.'); after() } catch (e) { toast(e.message) } }
  const push = async () => { if (!(await confirm('Send to Dynamics now?', 'Quotations, approved orders, payments and approved expense claims are posted to the Dynamics API.', 'Send'))) return
    try { const r = await api('/api/integration/push', { method: 'POST' }); toast(`${r.sent} sent${r.failed ? `, ${r.failed} failed (see each document)` : ''}`); after() } catch (e) { toast(e.message) } }
  const ack = async (file) => { const form = new FormData(); form.append('file', file)
    try { const r = await api('/api/integration/ack', { method: 'POST', form }); toast(`${r.matched} documents marked as in Dynamics${r.unknown ? `; ${r.unknown} not found` : ''}`); after() } catch (e) { toast(e.message) } }
  if (!s) return <div className="loading">Loading…</div>
  const o = s.out, nOut = o.quotes.count + o.orders.count + o.payments.count + o.expenses.count
  return (<>
    <div className="note">Masters come only from Dynamics. Transactions go back to Dynamics by <b>Excel file</b> (any Dynamics version) or the <b>API</b>. The API is called by the portal's server, so browser restrictions (CORS) do not apply.</div>
    <div className="grid g2">
      <div className="card"><h2>1. From Dynamics: masters</h2><p className="sub">Download customers and materials before prices and attributes. Records are matched by their Dynamics number; prices and charges are replaced as a whole.</p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>{s.masters.map((m) => <div key={m.entity} className="sync"><div className="meta"><b>{m.label}</b><span className="fine">{m.count} in the portal · {m.last ? 'downloaded ' + dt(m.last) : 'not downloaded yet'}</span></div>
          <button className="btn sm" onClick={() => pickFile(m.entity)}>Import file</button>{m.entity !== 'attributes' && <button className="btn sm" disabled={!m.api} title={m.api ? '' : 'No API endpoint set'} onClick={() => pull(m.entity)}>Download via API</button>}
          <button className="btn ghost sm" onClick={() => download(`/api/integration/template/${m.entity}`, `Template_${m.entity}.xlsx`)}>Template</button></div>)}</div></div>
      <div className="card"><h2>2. To Dynamics: transactions</h2><p className="sub">Saved quotations (sales quotes), approved orders, payments (cash receipt journal) and approved expense claims (employee journal).</p>
        <div className="grid g2" style={{ marginBottom: 12 }}>{[['Quotations', o.quotes], ['Sales orders', o.orders], ['Payments', o.payments], ['Expense claims', o.expenses]].map(([l, x]) =>
          <div key={l} className="kpi"><span>{l}</span><b>{x.count}</b><small>{inr0(x.value)}</small></div>)}</div>
        <div className="tools"><button className="btn pri" disabled={!nOut} onClick={exportOut}>Export file for Dynamics</button><button className="btn" disabled={!nOut} onClick={push}>Send via API</button></div>
        <h2 style={{ marginTop: 18 }}>3. Back from Dynamics: document numbers</h2>
        <p className="sub">{s.waiting_file} sent by file and waiting for their numbers. Import a list with <b>External Document No.</b> (the portal number) and <b>Document No.</b> (the Dynamics number).</p>
        <button className="btn" onClick={() => ackRef.current.click()}>Import Dynamics numbers</button>
        {s.errors > 0 && <div className="note bad" style={{ marginTop: 12 }}>{s.errors} failed to send. Open each document to see the error; they are sent again next time.</div>}</div>
    </div>
    <Connection />
    <div className="card"><h2>Sync log</h2>{s.log.length ? <div className="scroll"><table className="t"><thead><tr><th>When</th><th>Direction</th><th>What</th><th className="r">Records</th><th>Result</th><th>Details</th><th>By</th></tr></thead><tbody>
      {s.log.map((l, i) => <tr key={i}><td>{dt(l.at)}</td><td>{l.direction === 'in' ? 'From Dynamics' : 'To Dynamics'}</td><td>{l.entity}</td><td className="r">{l.count}</td><td><span className={`badge ${l.status === 'ok' ? 'ok' : l.status === 'error' ? 'bad' : 'warn'}`}>{l.status}</span></td><td>{l.message}</td><td>{l.user}</td></tr>)}</tbody></table></div>
      : <div className="empty">Nothing exchanged yet.</div>}</div>
    <input ref={fileRef} type="file" id="impInput" accept=".xlsx,.csv" hidden onChange={(e) => { const f = e.target.files[0]; e.target.value = ''; if (f) upload(f) }} />
    <input ref={ackRef} type="file" id="ackInput" accept=".xlsx,.csv" hidden onChange={(e) => { const f = e.target.files[0]; e.target.value = ''; if (f) ack(f) }} />
    <ImportDialog imp={imp} setImp={setImp} onDone={after} />
  </>)
}

function ImportDialog({ imp, setImp, onDone }) {
  const { toast } = useUi()
  if (!imp) return <Modal open={false} />
  const remap = async (patch) => { try { setImp(await api(`/api/integration/import/${imp.entity}/preview`, { method: 'POST', body: { import_id: imp.import_id, sheet: imp.sheet, map: imp.map, ...patch } })) } catch (e) { toast(e.message) } }
  const apply = async () => { try { const r = await api(`/api/integration/import/${imp.entity}/apply`, { method: 'POST', body: { import_id: imp.import_id, sheet: imp.sheet, map: imp.map } }); setImp(null); toast(`${imp.label}: ${r.added} new, ${r.updated} updated`); onDone() } catch (e) { toast(e.message) } }
  const r = imp.result
  return <Modal open onClose={() => setImp(null)} wide><div className="dlg"><h2>Download {imp.label.toLowerCase()} from Dynamics</h2><p className="fine" style={{ margin: '-8px 0 0' }}>{imp.source}</p>
    {imp.sheets.length > 1 && <label className="field">Sheet<select className="inp" value={imp.sheet} onChange={(e) => remap({ sheet: +e.target.value, map: null })}>{imp.sheets.map((s, i) => <option key={i} value={i}>{s.name} ({s.rows} rows)</option>)}</select></label>}
    <div><b style={{ fontSize: 13 }}>Columns</b><p className="fine" style={{ margin: '2px 0 8px' }}>Matched automatically by name. Change any that are wrong.</p>
      <div className="form">{imp.fields.map((k) => <label key={k} className="field">{FLABEL[k] || k}<select className="inp" value={imp.map[k] || ''} onChange={(e) => remap({ map: { ...imp.map, [k]: e.target.value } })}>
        <option value="">Not in the file</option>{imp.headers.map((h) => <option key={h}>{h}</option>)}</select></label>)}</div></div>
    <div className={`note ${r.errors.length ? 'warn' : ''}`}>{imp.entity === 'prices' ? `${r.added} prices will replace the ${r.updated} in the portal` : `${r.added} new, ${r.updated} updated`}{r.skipped ? `, ${r.skipped} rows skipped` : ''}.
      {r.errors.slice(0, 6).map((e) => <div key={e}>{e}</div>)}</div>
    <div className="btns"><button className="btn ghost" onClick={() => setImp(null)}>Cancel</button><button className="btn pri" disabled={!(r.added + r.updated)} onClick={apply}>Apply</button></div></div></Modal>
}

function Connection() {
  const { toast } = useUi(); const { reloadMe } = useSession()
  const [s, reload] = useLoad(() => api('/api/settings'), [])
  if (!s) return null
  const d = s.dynamics
  const save = async (e) => {
    e?.preventDefault?.()
    const f = Object.fromEntries(new FormData(document.getElementById('dynForm')))
    const ep = Object.fromEntries(Object.keys(d.ep).map((k) => [k, (f['ep_' + k] || '').trim()]))
    try { await api('/api/settings', { method: 'PUT', body: { dynamics: { product: f.product, base_url: f.base_url.trim(), tenant_id: f.tenant_id.trim(), client_id: f.client_id.trim(), client_secret: f.client_secret,
      token: f.token, scope: f.scope.trim(), payments_negative: !!f.payments_negative, ep } } }); toast('Connection saved'); reload(); reloadMe() } catch (e2) { toast(e2.message) }
  }
  const test = async () => { await save(); try { const r = await api('/api/integration/test', { method: 'POST' }); toast(`Connected. Dynamics answered with ${r.rows} customer row.`) } catch (e) { toast(e.message) } }
  return <div className="card"><h2>Dynamics connection</h2><p className="sub">For the API route. The server gets its own token from Microsoft Entra ID with the app registration below, so nothing needs pasting.</p>
    <form className="form" id="dynForm" onSubmit={save}>
      <label className="field">Dynamics product<select className="inp" name="product" defaultValue={d.product}><option value="bc">Business Central (API v2.0)</option><option value="odata">Other OData endpoint</option></select></label>
      <label className="field wide">API address<input className="inp" name="base_url" defaultValue={d.base_url} placeholder="https://api.businesscentral.dynamics.com/v2.0/{tenant}/{environment}/api/v2.0/companies({id})" /></label>
      <label className="field">Entra ID tenant id<input className="inp" name="tenant_id" defaultValue={d.tenant_id} /></label>
      <label className="field">App (client) id<input className="inp" name="client_id" defaultValue={d.client_id} /></label>
      <label className="field">Client secret<input className="inp" name="client_secret" type="password" defaultValue={d.client_secret} autoComplete="off" /></label>
      <label className="field">Scope<input className="inp" name="scope" defaultValue={d.scope} /></label>
      <label className="field wide">Or a pasted access token (expires; for testing only)<input className="inp" name="token" type="password" defaultValue={d.token} autoComplete="off" /></label>
      {Object.entries(d.ep).map(([k, v]) => <label key={k} className="field">{k[0].toUpperCase() + k.slice(1)} endpoint<input className="inp" name={'ep_' + k} defaultValue={v} /></label>)}
      <label className="chk wide"><input type="checkbox" name="payments_negative" defaultChecked={d.payments_negative} /> Send payment amounts as negative numbers (Business Central cash receipt journals)</label></form>
    <div className="tools" style={{ marginTop: 12 }}><button className="btn pri" onClick={save}>Save connection</button><button className="btn" onClick={test}>Test connection</button></div>
    <div className="note warn">The standard Business Central API has customers, items, sales quotes, sales orders and customer payments, but not price lists, charges, HSN codes, GSTIN or employee expenses: use files for those, or ask your Dynamics partner for custom API pages. Secrets are stored in the database; restrict database access.</div></div>
}
