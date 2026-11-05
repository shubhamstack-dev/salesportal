import { useRef, useState } from 'react'
import { api, download, dt, inr0 } from '../lib'
import { useSession } from '../session'
import { Modal, useLoad, useUi } from '../ui'

const FLABEL = { code: 'Code / No.', name: 'Name', gstin: 'GSTIN', state: 'State', address: 'Address', city: 'City', pin: 'PIN', phone: 'Phone', email: 'E-mail', price_group: 'Price group',
  terms: 'Payment terms', status: 'Status (only Active used)', price_type: 'Price type (purchase left out)', gst_group: 'GST group', credit_limit: 'Credit limit', balance: 'Balance', blocked: 'Blocked', uom: 'Unit', hsn: 'HSN/SAC', category: 'Category', price: 'Unit price', material: 'Item no.',
  value: 'Value / rate', type: 'Applies to (type)', min_qty: 'Minimum quantity', from: 'Valid from', to: 'Valid to', description: 'Description', rate: 'GST %', cess: 'Cess %',
  calc: 'Calculation', sign: 'Charge or discount', stage: 'Before / after GST', auto: 'Apply to every order', active: 'Active / blocked' }

const EPLABEL = { company: 'Company details (for printing)', customers: 'Customers', materials: 'Materials', attributes: 'Material attributes', prices: 'Prices', hsn: 'HSN codes', charges: 'Charges',
  quotes: 'Quotations (to Dynamics)', orders: 'Sales orders (to Dynamics)', payments: 'Payments (to Dynamics)', expenses: 'Expense claims (to Dynamics)' }
const EPHINT = { company: 'companyInformation or odata:Company_Information', customers: 'odata:Customer_Card', materials: 'odata:Item_Card', attributes: 'odata:…', prices: 'odata:PriceListLines', hsn: 'odata:HSN_SAC',
  charges: 'odata:… or leave empty', quotes: 'salesQuotes', orders: 'salesOrders', payments: 'customerPaymentJournals(<id>)/customerPayments', expenses: 'leave empty' }

export default function Integration() {
  const { toast, confirm } = useUi(); const { refreshCounts } = useSession()
  const [s, reload] = useLoad(() => api('/api/integration/summary'), [])
  const [imp, setImp] = useState(null)
  const [all, setAll] = useState(null)
  const fileRef = useRef(null), ackRef = useRef(null), entRef = useRef('')
  const after = () => { reload(); refreshCounts() }
  const pickFile = (ent) => { entRef.current = ent; fileRef.current.click() }
  const upload = async (file) => {
    const form = new FormData(); form.append('file', file)
    try { setImp(await api(`/api/integration/import/${entRef.current}/file`, { method: 'POST', form })) } catch (e) { toast(e.message) }
  }
  const pull = async (ent) => { toast('Downloading from Dynamics…'); try { setImp(await api(`/api/integration/import/${ent}/api`, { method: 'POST' })) } catch (e) { toast(e.message) } }
  const pullAll = async () => {
    setAll({ busy: true })
    try { const r = await api('/api/integration/pull-all', { method: 'POST' }); setAll(r); after() } catch (e) { setAll(null); toast(e.message) }
  }
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
      <div className="card"><div className="hd"><div><h2>1. From Dynamics: masters</h2><p className="sub">Download customers and materials before prices and attributes. Records are matched by their Dynamics number; prices and charges are replaced as a whole.</p></div>
        <button className="btn pri" disabled={!s.masters.some((m) => m.api)} onClick={pullAll}>Download all via API</button></div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>{s.masters.map((m) => <div key={m.entity} className="sync"><div className="meta"><b>{m.label}</b><span className="fine">{m.count} in the portal · {m.last ? 'downloaded ' + dt(m.last) : 'not downloaded yet'}</span></div>
          <button className="btn sm" onClick={() => pickFile(m.entity)}>Import file</button><button className="btn sm" disabled={!m.api} title={m.api ? '' : 'Set its endpoint under Dynamics connection'} onClick={() => pull(m.entity)}>Download via API</button>
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
    <PullAllDialog all={all} onClose={() => setAll(null)} />
  </>)
}

function PullAllDialog({ all, onClose }) {
  if (!all) return <Modal open={false} />
  const tone = { ok: 'ok', warning: 'warn', error: 'bad', skipped: '' }
  return <Modal open onClose={all.busy ? undefined : onClose} wide><div className="dlg"><h2>Download all masters from Dynamics</h2>
    {all.busy ? <div className="loading">Downloading customers, materials, HSN codes, attributes, prices and charges…</div>
      : <><div className="scroll"><table className="t"><thead><tr><th>Master</th><th>Result</th><th className="r">New</th><th className="r">Updated</th><th className="r">Skipped</th><th>Details</th></tr></thead><tbody>
        {all.results.map((x) => <tr key={x.entity}><td><b>{x.label}</b></td><td><span className={`badge ${tone[x.status]}`}>{x.status}</span></td>
          <td className="r">{x.added ?? ''}</td><td className="r">{x.updated ?? ''}</td><td className="r">{x.skipped ?? ''}</td>
          <td className="fine">{x.message || ''}{x.item_prices ? `${x.item_prices} item prices added where no price list line is for all customers. ` : ''}{(x.errors || []).slice(0, 3).map((e) => <div key={e}>{e}</div>)}</td></tr>)}</tbody></table></div>
        <div className="btns"><button className="btn pri" onClick={onClose}>Done</button></div></>}</div></Modal>
}

function ImportDialog({ imp, setImp, onDone }) {
  const { toast } = useUi()
  if (!imp) return <Modal open={false} />
  const rates = imp.rates || Object.fromEntries((imp.gst_groups || []).map((g) => [g.code, g.rate]))
  const remap = async (patch) => { try { const n = await api(`/api/integration/import/${imp.entity}/preview`, { method: 'POST', body: { import_id: imp.import_id, sheet: imp.sheet, map: imp.map, gst_rates: rates, ...patch } }); setImp({ ...n, rates: patch.gst_rates || rates }) } catch (e) { toast(e.message) } }
  const apply = async () => { try { const r = await api(`/api/integration/import/${imp.entity}/apply`, { method: 'POST', body: { import_id: imp.import_id, sheet: imp.sheet, map: imp.map, gst_rates: imp.gst_groups?.length ? rates : null } }); setImp(null); toast(`${imp.label}: ${r.added} new, ${r.updated} updated`); onDone() } catch (e) { toast(e.message) } }
  const setRate = (code, v) => setImp({ ...imp, rates: { ...rates, [code]: v } })
  const r = imp.result
  return <Modal open onClose={() => setImp(null)} wide><div className="dlg"><h2>Download {imp.label} from Dynamics</h2><p className="fine" style={{ margin: '-8px 0 0' }}>{imp.source}</p>
    {imp.sheets.length > 1 && <label className="field">Sheet<select className="inp" value={imp.sheet} onChange={(e) => remap({ sheet: +e.target.value, map: null })}>{imp.sheets.map((s, i) => <option key={i} value={i}>{s.name} ({s.rows} rows)</option>)}</select></label>}
    <div><b style={{ fontSize: 13 }}>Columns</b><p className="fine" style={{ margin: '2px 0 8px' }}>Matched automatically by name. Change any that are wrong.</p>
      <div className="form">{imp.fields.map((k) => <label key={k} className="field">{FLABEL[k] || k}<select className="inp" value={imp.map[k] || ''} onChange={(e) => remap({ map: { ...imp.map, [k]: e.target.value } })}>
        <option value="">Not in the file</option>{imp.headers.map((h) => <option key={h}>{h}</option>)}</select></label>)}</div></div>
    {imp.gst_groups?.length > 0 && <div><b style={{ fontSize: 13 }}>{imp.gst_groups[0].by_hsn ? 'GST rate of each HSN code' : 'GST rate of each GST group'}</b>
      <p className="fine" style={{ margin: '2px 0 8px' }}>Business Central keeps GST rates in its tax engine, not on the HSN code{imp.gst_groups[0].by_hsn ? ', and this page sends no GST group' : ''}, so enter the total GST % once (IGST, or CGST + SGST: for example 5, 12, 18). It is remembered for every later download.</p>
      <div className="scroll"><table className="t"><thead><tr><th>{imp.gst_groups[0].by_hsn ? 'HSN code' : 'GST group'}</th><th className="r">HSN codes</th><th style={{ width: 130 }}>GST %</th></tr></thead><tbody>
        {imp.gst_groups.map((g) => <tr key={g.code}><td className="mono">{g.code || '(blank)'}</td><td className="r">{g.hsn}</td>
          <td><input className="inp" type="number" min="0" max="40" step="0.01" value={rates[g.code] ?? ''} onChange={(e) => setRate(g.code, e.target.value === '' ? '' : +e.target.value)}
            onBlur={() => remap({ gst_rates: rates })} style={{ width: 110 }} /></td></tr>)}</tbody></table></div></div>}
    <div className={`note ${r.errors.length ? 'warn' : ''}`}>{imp.entity === 'prices' ? `${r.added} prices will replace the ${r.updated} in the portal` : `${r.added} new, ${r.updated} updated`}{r.skipped ? `, ${r.skipped} rows skipped` : ''}.
      {r.errors.slice(0, 6).map((e) => <div key={e}>{e}</div>)}</div>
    <div className="btns"><button className="btn ghost" onClick={() => setImp(null)}>Cancel</button><button className="btn pri" disabled={!(r.added + r.updated)} onClick={apply}>Apply</button></div></div></Modal>
}

function Connection() {
  const { toast } = useUi(); const { reloadMe } = useSession()
  const [s, reload] = useLoad(() => api('/api/settings'), [])
  const [svc, setSvc] = useState(null)
  if (!s) return null
  const d = s.dynamics
  const save = async (e) => {
    e?.preventDefault?.()
    const f = Object.fromEntries(new FormData(document.getElementById('dynForm')))
    const ep = Object.fromEntries(Object.keys(d.ep).map((k) => [k, (f['ep_' + k] || '').trim()]))
    try { await api('/api/settings', { method: 'PUT', body: { dynamics: { product: f.product, base_url: f.base_url.trim(), tenant_id: f.tenant_id.trim(), client_id: f.client_id.trim(), client_secret: f.client_secret,
      token: f.token, scope: f.scope.trim(), payments_negative: !!f.payments_negative, auto_push: !!f.auto_push, ep } } }); toast('Connection saved'); reload(); reloadMe() } catch (e2) { toast(e2.message) }
  }
  const test = async () => { await save(); try { const r = await api('/api/integration/test', { method: 'POST' }); toast(`Connected to ${r.company || 'Dynamics'}. Customers answered with ${r.rows} row(s).`) } catch (e) { toast(e.message) } }
  const find = async () => { try { const r = await api('/api/integration/services'); setSvc(r.services); toast(`${r.services.length} published pages found`) } catch (e) { toast(e.message) } }
  return <div className="card"><h2>Dynamics connection</h2><p className="sub">For the API route. The server gets its own token from Microsoft Entra ID with the app registration below, so nothing needs pasting.</p>
    <form className="form" id="dynForm" onSubmit={save}>
      <label className="field">Dynamics product<select className="inp" name="product" defaultValue={d.product}><option value="bc">Business Central (API v2.0)</option><option value="odata">Other OData endpoint</option></select></label>
      <label className="field wide">API address<input className="inp" name="base_url" defaultValue={d.base_url} placeholder="https://api.businesscentral.dynamics.com/v2.0/{tenant}/{environment}/api/v2.0/companies({id})" /></label>
      <label className="field">Entra ID tenant id<input className="inp" name="tenant_id" defaultValue={d.tenant_id} /></label>
      <label className="field">App (client) id<input className="inp" name="client_id" defaultValue={d.client_id} /></label>
      <label className="field">Client secret<input className="inp" name="client_secret" type="password" defaultValue={d.client_secret} autoComplete="off" /></label>
      <label className="field">Scope<input className="inp" name="scope" defaultValue={d.scope} /></label>
      <label className="field wide">Or a pasted access token (expires; for testing only)<input className="inp" name="token" type="password" defaultValue={d.token} autoComplete="off" /></label>
      {Object.entries(d.ep).map(([k, v]) => <label key={k} className="field">{EPLABEL[k] || k} endpoint<input className="inp" name={'ep_' + k} defaultValue={v} list="odataSvc" placeholder={EPHINT[k]} /></label>)}
      <datalist id="odataSvc">{(svc || []).map((x) => <option key={x.name} value={'odata:' + x.name} />)}</datalist>
      <label className="chk wide"><input type="checkbox" name="auto_push" defaultChecked={d.auto_push} /> <span><b>Send quotations and sales orders to Dynamics automatically</b> as soon as a quotation is saved or an order is approved, through the Quotations and Sales orders endpoints. If Dynamics cannot be reached, the document stays under "To Dynamics" with its error, for Send via API.</span></label>
      <label className="chk wide"><input type="checkbox" name="payments_negative" defaultChecked={d.payments_negative} /> Send payment amounts as negative numbers (Business Central cash receipt journals)</label></form>
    <div className="tools" style={{ marginTop: 12 }}><button className="btn pri" onClick={save}>Save connection</button><button className="btn" onClick={test}>Test connection</button><button className="btn" onClick={find}>Find published pages</button></div>
    {svc && <p className="fine">Published in Business Central: {svc.length ? svc.map((x) => x.name).join(', ') : 'none'}. Click an endpoint box to pick one.</p>}
    <div className="note"><b>Endpoints.</b> A plain name (<code>customers</code>, <code>items</code>, <code>salesOrders</code>) is the standard Business Central API. It has no GSTIN, state code, HSN codes or price lists, so for those publish the page in Business Central (<b>Web Services → New → Object Type Page</b>, tick <b>Published</b>) and enter <code>odata:</code> plus its Service Name, for example <code>odata:Customer_Card</code>, <code>odata:Item_Card</code>, <code>odata:HSN_SAC</code>, <code>odata:PriceListLines</code>. A filter can follow: <code>odata:PriceListLines?$filter=Price_Type eq 'Sale'</code>.</div>
    <div className="note warn">Secrets are stored in the database; restrict database access.</div></div>
}
