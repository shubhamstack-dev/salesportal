// Printed quotation and sales order, laid out like the Samurai Foods Word templates
// (Standard_Sales_Quote_V1_2 and SF_Sales_Invoice_V10). Opens in a new window and prints.
import { dmy, esc } from './lib'

const money = (n) => (+n || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const qty = (n) => (+n || 0).toLocaleString('en-IN', { maximumFractionDigits: 3 })

const ONES = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten', 'Eleven', 'Twelve', 'Thirteen',
  'Fourteen', 'Fifteen', 'Sixteen', 'Seventeen', 'Eighteen', 'Nineteen']
const TENS = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']
const two = (n) => (n < 20 ? ONES[n] : `${TENS[Math.floor(n / 10)]}${n % 10 ? ' ' + ONES[n % 10] : ''}`)
const three = (n) => [n >= 100 ? `${ONES[Math.floor(n / 100)]} Hundred` : '', two(n % 100)].filter(Boolean).join(' and ')
// Indian numbering: crore, lakh, thousand
export function inWords(amount) {
  const a = Math.round((Math.abs(+amount) || 0) * 100)
  let r = Math.floor(a / 100); const p = a % 100
  const parts = []
  const crore = Math.floor(r / 1e7); r %= 1e7
  const lakh = Math.floor(r / 1e5); r %= 1e5
  const th = Math.floor(r / 1e3); r %= 1e3
  if (crore) parts.push(`${crore >= 100 ? inWords(crore).replace(/^Rupees |\s*Only$/g, '') : two(crore)} Crore`)
  if (lakh) parts.push(`${two(lakh)} Lakh`)
  if (th) parts.push(`${two(th)} Thousand`)
  if (r) parts.push(three(r))
  const rupees = parts.join(' ') || 'Zero'
  return `Rupees ${rupees}${p ? ` and ${two(p)} Paise` : ''} Only`
}

// address: one line per row when typed on several rows, otherwise split at commas
const lines = (s) => { s = String(s || ''); return s.split(/\r?\n/.test(s) ? /\r?\n/ : /,\s*/).map((x) => x.trim()).filter(Boolean) }
const kv = (rows) => `<table class="kv">${rows.filter((r) => r[1]).map(([k, v, b]) => `<tr><th>${k}</th><td${b ? ' class="b"' : ''}>${esc(v)}</td></tr>`).join('')}</table>`

function terms(text, jurisdiction) {
  return String(text || '').replace('{jurisdiction}', jurisdiction || '').split(/\r?\n/).map((t) => t.trim()).filter(Boolean)
    .map((t) => { const i = t.indexOf(':'); return `<li>${i > 0 && i < 40 ? `<b>${esc(t.slice(0, i + 1))}</b>${esc(t.slice(i + 1))}` : esc(t)}</li>` }).join('')
}

async function upiQr(upi, payee, amount, note) {
  if (!upi) return ''
  try {
    const QR = (await import('qrcode')).default
    const url = `upi://pay?pa=${encodeURIComponent(upi)}&pn=${encodeURIComponent(payee)}&am=${(+amount).toFixed(2)}&cu=INR&tn=${encodeURIComponent(note)}`
    return await QR.toString(url, { type: 'svg', margin: 0, width: 120, errorCorrectionLevel: 'M' })
  } catch { return '' }
}

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
const longDate = (iso) => (iso ? `${+iso.slice(8, 10)} ${MONTHS[+iso.slice(5, 7) - 1]} ${iso.slice(0, 4)}` : '')
const n2 = (n) => (+n || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

const CSS = `
@page{size:A4;margin:8mm;@top-left{content:counter(page) " / " counter(pages);font:9pt Calibri,Carlito,Arial,sans-serif;color:#333;padding:4mm 0 0 9mm}}
*{box-sizing:border-box}
body{font:9pt Calibri,Carlito,"Segoe UI",Arial,sans-serif;color:#1d1d1f;margin:0;-webkit-print-color-adjust:exact;print-color-adjust:exact}
.page{border:2.2px solid #1f3a57;padding:6mm 8mm;min-height:280mm;-webkit-box-decoration-break:clone;box-decoration-break:clone}
.brk{break-before:page}
.mast{display:grid;grid-template-columns:1fr auto 1fr;align-items:end;margin-top:6mm}
.mast .kind{font-size:7.5pt;letter-spacing:.32em;word-spacing:.4em;color:#6b7a8c;font-weight:700}
.mast h1{font-size:16pt;letter-spacing:.14em;color:#1f3a57;margin:0;font-weight:700;text-align:center}
.mast .logo{justify-self:end;align-self:start;height:15mm;margin-top:-6mm}
.subrule{border:0;border-top:1px solid #c9d1db;margin:2.5mm 0 4mm}
.top{display:flex;gap:8mm;justify-content:space-between;align-items:flex-start}
.co .nm{font-size:11.5pt;font-weight:700;color:#111}
.co .ad{font-size:8.6pt;line-height:1.35}
.kv{border-collapse:collapse;margin-top:1.5mm;font-size:8.4pt}
.kv th{color:#6b7a8c;font-weight:700;text-align:left;padding:.35mm 6mm .35mm 2mm;white-space:nowrap}
.kv td{padding:.35mm 0}
.b{font-weight:700}
.grid{border-collapse:collapse;font-size:8.3pt;width:104mm}
.grid th,.grid td{border:1px solid #c9d1db;padding:1mm 2mm;text-align:left;vertical-align:top}
.grid th{color:#6b7a8c;font-weight:700;width:20mm}
.grid td{width:32mm}
.boxes{display:flex;border:1px solid #c9d1db;margin:5mm 0 4mm}
.boxes>div{flex:1}
.boxes>div+div{border-left:1px solid #c9d1db}
.bh{background:#1f3a57;color:#fff;font-weight:700;font-size:7.8pt;letter-spacing:.14em;padding:2mm 3mm;text-transform:uppercase}
.bb{padding:2.5mm 3mm}
.bb .nm{font-weight:700;font-size:10pt}
.bb .ad{font-size:8.6pt;line-height:1.35}
table.items{width:100%;border-collapse:collapse;font-size:8pt}
.items thead th{background:#1f3a57;color:#fff;padding:2.6mm 1.4mm;font-weight:700;text-align:right;white-space:nowrap}
.items thead th.l{text-align:left}
.items td{padding:2.2mm 1.4mm;border-bottom:1px solid #e3e8ee;text-align:right;vertical-align:top}
.items td.l{text-align:left}
.items .code{font-weight:700}
.items .meta{font-size:7pt;color:#6b7a8c}
.items tr.gt td{font-weight:700;border-top:1.5px solid #1f3a57;border-bottom:0;padding-top:2.5mm}
.sum{margin-left:auto;width:96mm;margin-top:2mm;font-size:9pt}
.sum .r{display:flex;justify-content:flex-end;gap:10mm;padding:1.6mm 0}
.sum .r span:last-child{min-width:28mm;text-align:right}
.sum .r.k span:first-child{color:#6b7a8c;font-weight:700}
.sum .r.k span:last-child{font-weight:700}
.sum .r.big{font-size:9.6pt}
.sum .r.big span:first-child{color:#1f3a57;font-weight:700}
.sum .r.big span:last-child{font-weight:700}
.sum .r.t span:first-child{color:#6b7a8c}
.sum .sep{height:2mm}
.sum .r.tot{border-top:1.6px solid #1f3a57;margin-top:1mm;font-size:11pt}
.sum .r.tot span{font-weight:700;color:#111}
.words{display:flex;gap:6mm;align-items:baseline;border-top:1px solid #c9d1db;border-bottom:1px solid #c9d1db;padding:2mm 0;margin-top:4mm;font-size:8.6pt}
.words .lb{color:#6b7a8c;font-weight:700;white-space:nowrap}
.words .tx{font-weight:700}
.note{font-size:7.6pt;color:#6b7a8c;font-style:italic;margin-top:1.5mm}
.decl{display:flex;justify-content:space-between;align-items:flex-start;font-size:8.2pt;margin-top:4mm}
.decl .d{max-width:105mm;line-height:1.35}
.decl .d b{color:#1f3a57;display:block;margin-bottom:.8mm}
.sig{text-align:right;min-width:62mm}
.sig .for{color:#6b7a8c;font-size:7.6pt}
.sig .nm{font-weight:700;font-size:9pt}
.sig .line{margin-top:12mm;color:#6b7a8c}
.sig .as{font-weight:700;color:#1f3a57}
h2{font-size:12pt;letter-spacing:.12em;color:#1f3a57;margin:8mm 0 2.5mm}
.rule{border:0;border-top:1.6px solid #1f3a57;margin:0 0 3mm}
ul.tc{margin:3mm 0 0;padding-left:5mm;font-size:8.6pt;line-height:1.5}
ul.tc li{margin-bottom:1.2mm;text-align:justify}
.eoe{text-align:right;font-style:italic;color:#6b7a8c;font-size:7.5pt}
.pay{display:flex;border:1px solid #c9d1db;margin-top:5mm}
.pay>div{flex:1;padding:2.5mm 3mm}
.pay>div+div{border-left:1px solid #c9d1db;text-align:center}
.pay .t{font-weight:700;color:#1f3a57;font-size:10.5pt;margin-bottom:1.5mm}
.pay svg{width:30mm;height:30mm}
.pay .hint{font-size:7.5pt;color:#6b7a8c}
.foot{display:flex;justify-content:space-between;align-items:flex-start;margin-top:3mm;font-size:8pt}
.foot .l{color:#6b7a8c;font-style:italic}
`

export async function printSalesDoc(d, settings) {
  const w = window.open('', '_blank')
  if (!w) return false
  w.document.write('<p style="font:14px sans-serif;padding:20px">Preparing the print…</p>')
  const co = settings.company || {}, pr = settings.print || {}, c = d.customer_detail, t = d.totals
  const quote = d.kind === 'quote'
  const title = quote ? 'QUOTATION' : 'SALES ORDER'
  const coName = co.legal_name || co.name

  // Lines worked out as the Business Central report (SF Sales Invoice GST, CalcLineValues) does:
  //   Rate/Kg = amount without GST / qty; Nett Rate = (amount + GST) / qty; MRP/Kg = the item's Unit Price;
  //   gross (before discount, with GST) = amount / (1 - disc) x (1 + GST %) / qty;
  //   gross equal to the MRP (within 0.05): sold at MRP, discount = MRP x qty x disc;
  //   otherwise a customer rate: discount only when one was given, = gross x qty - nett amount.
  //   Pkts. = qty / the PACKET unit, rounded.
  const uoms = [...new Set(d.lines.map((l) => (l.uom || '').toUpperCase()).filter(Boolean))]
  const unit = uoms.length === 1 ? uoms[0][0] + uoms[0].slice(1).toLowerCase() : ''
  let tq = 0, tp = 0, tg = 0, ta = 0, disc = 0, anyPk = false
  const rows = d.lines.map((l, i) => {
    const q = +l.qty || 0, tax = +l.taxable || 0, gst = (+l.gst || 0) + (+l.cess || 0)
    const nettAmt = tax + gst
    const frac = (+l.disc || 0) / 100
    const mrp = +l.mrp || 0
    const gross = q && frac < 1 ? tax / (1 - frac) * (1 + ((+l.gst_rate || 0) + (+l.cess_rate || 0)) / 100) / q : mrp
    let lineDisc = 0, discPct = 0
    if (mrp && Math.abs(gross - mrp) <= 0.05) { discPct = frac * 100; lineDisc = Math.round(mrp * q * frac * 100) / 100 }
    else if (frac > 0) { discPct = frac * 100; lineDisc = Math.round((gross * q - nettAmt) * 100) / 100 }
    const pk = +l.pack_qty > 0 ? Math.round(q / +l.pack_qty) : null
    if (pk != null) { anyPk = true; tp += pk }
    tq += q; tg += gst; ta += nettAmt; disc += lineDisc
    return `<tr><td class="l">${i + 1}</td><td class="l"><div class="code">${esc(l.material)}</div>${esc(l.name)}
      <div class="meta">${l.hsn ? `HSN: ${esc(l.hsn)}` : ''}</div></td>
      <td>${n2(q)}${unit ? '' : ' ' + esc(l.uom)}</td><td>${pk != null ? n2(pk) : ''}</td><td>${mrp ? n2(mrp) : ''}</td>
      <td>${n2(discPct)}</td><td>${n2(q ? tax / q : 0)}</td><td>${n2(gst)}</td><td>${n2(q ? nettAmt / q : 0)}</td><td>${n2(nettAmt)}</td></tr>`
  }).join('')
  if (disc < 0) disc = 0
  // invoice rounding: its own row with only the amount, as in the Business Central invoice
  const roundRow = t.round_off ? `<tr><td></td><td class="l">Rounding</td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td>${n2(t.round_off)}</td></tr>` : ''
  ta += +t.round_off || 0
  const per = unit ? `/${esc(unit)}` : ''
  const items = `<table class="items"><thead><tr><th class="l">S.No.</th><th class="l">Description of Goods</th><th>Qty${unit ? ` (${esc(unit)})` : ''}</th>
    <th>Pkts.</th><th>MRP${per}</th><th>Disc %</th><th>Rate${per}</th><th>GST</th><th>Nett Rate</th><th>Amount</th></tr></thead>
    <tbody>${rows}${roundRow}<tr class="gt"><td></td><td class="l">GRAND TOTAL</td><td>${unit ? n2(tq) : ''}</td><td>${anyPk ? n2(tp) : ''}</td><td></td><td></td><td></td>
    <td>${n2(tg)}</td><td></td><td>${n2(ta)}</td></tr></tbody></table>`

  const r = (k, v, cls = 't') => `<div class="r ${cls}"><span>${k}</span><span>${v}</span></div>`
  const taxRows = t.intra ? r('CGST', n2(t.cgst)) + r('SGST', n2(t.sgst)) : r('IGST', n2(t.igst))
  const sum = `<div class="sum">${r('Total Discount', n2(disc), 'k')}${r('TOTAL AMOUNT PAYABLE', n2(t.total), 'big')}<div class="sep"></div>
    ${r('Taxable Value', n2(t.taxable))}${(t.pre || []).map((x) => r(esc(x.name), n2(x.amount))).join('')}${taxRows}
    ${t.cess ? r('Cess', n2(t.cess)) : ''}${(t.post || []).map((x) => r(esc(x.name), n2(x.amount))).join('')}
    ${r('Total', n2(t.total), 'tot')}</div>`
  const words = `<div class="words"><span class="lb">Amount Chargeable (in words)</span><span class="tx">${inWords(t.total)}</span></div>
    ${d.remarks ? `<div class="note">Remarks: ${esc(d.remarks)}</div>` : ''}`

  // header: company, document details
  const coBlock = `<div class="co"><div class="nm">${esc(coName)}</div><div class="ad">${lines(co.address).map(esc).join('<br>')}</div>
    ${kv([['GSTIN', co.gstin, 1], ['PAN', co.pan], ['FSSAI', co.fssai], ['Phone', co.phone], ['Email', co.email]])}</div>`
  const pairs = quote
    ? [['Quotation No.', d.no, 'Dated', longDate(d.date), 1], ['Valid Until', longDate(d.valid_to), 'Customer No.', c.code],
      ['Terms', c.terms, 'Your Ref.', d.po_ref], ['Salesperson', d.rep, 'Dynamics No.', d.sync?.no]]
    : [['Order No.', d.no, 'Dated', longDate(d.date), 1], ['Quotation No.', d.quote_no, 'Delivery Date', longDate(d.delivery)],
      ['Terms', c.terms, 'Buyer Ref.', d.po_ref], ['Salesperson', d.rep, 'Dynamics No.', d.sync?.no]]
  pairs.splice(pairs.length - 1, 0, ['Price Group', c.price_group || 'MRP', 'Customer No.', quote ? '' : c.code])
  if (quote) pairs[pairs.length - 2][2] = '', pairs[pairs.length - 2][3] = ''
  const grid = `<table class="grid">${pairs.map(([a, av, b2, bv, bold]) => `<tr><th>${a}</th><td${bold ? ' class="b"' : ''}>${esc(av || '')}</td>
    <th>${b2}</th><td${bold ? ' class="b"' : ''}>${esc(bv || '')}</td></tr>`).join('')}</table>`
  const addr = `<div class="nm">${esc(c.name)}</div><div class="ad">${[...lines(c.street), [c.city, c.pin].filter(Boolean).join(', ')].filter(Boolean).map(esc).join('<br>')}</div>`
  const ship = `${addr}${kv([['GSTIN', c.gstin || 'Unregistered', 1], ['State Code', c.state_abbr || c.state_code], ['Phone', c.phone]])}`
  const bill = `${addr}${kv([['GSTIN', c.gstin || 'Unregistered', 1], ['State', c.state], ['Phone', c.phone]])}`
  const boxes = quote
    ? `<div class="boxes"><div><div class="bh">Quotation to (Bill to)</div><div class="bb">${bill}</div></div><div><div class="bh">Ship to / Delivery address</div><div class="bb">${ship}</div></div></div>`
    : `<div class="boxes"><div><div class="bh">Consignee (Ship to)</div><div class="bb">${ship}</div></div><div><div class="bh">Buyer (Bill to)</div><div class="bb">${bill}</div></div></div>`
  const sign = `<div class="sig"><div class="for">for</div><div class="nm">${esc(coName.toUpperCase())}</div><div class="line">______________________________</div><div class="as">Authorised Signatory</div></div>`

  const qr = await upiQr(pr.upi_id, coName, t.total, d.no)
  const bank = `<div class="pay"><div><div class="t">Bank Details</div>${kv([['Bank', pr.bank_name], ['A/c Name', pr.account_name], ['A/c No.', pr.account_no, 1],
    ['Branch', pr.branch], ['IFSC', pr.ifsc], ['UPI ID', pr.upi_id, 1]])}</div>
    <div><div class="t">${quote ? 'Scan to Pay (Advance)' : 'Scan to Pay'}</div>${qr || '<div class="hint">Add a UPI ID under Settings to print a payment QR code.</div>'}
    ${qr ? '<div class="hint">Kisi bhi UPI app se scan karein</div>' : ''}</div></div>`

  const page1 = `<div class="page"><div class="mast"><div class="kind">${title}</div><h1>${title}</h1>
    <img class="logo" src="${location.origin}/logo.png" alt=""></div><hr class="subrule">
    <div class="top">${coBlock}${grid}</div>${boxes}${items}${sum}${words}</div>`
  const page2 = `<div class="page brk"><div class="decl"><div class="d"><b>Declaration</b>${esc(quote ? pr.quote_declaration : pr.order_declaration)}</div>${sign}</div>
    <h2>TERMS &amp; CONDITIONS</h2><hr class="rule"><ul class="tc">${terms(pr.terms, pr.jurisdiction)}</ul><div class="eoe">E. &amp; O.E.</div>
    ${bank}<div class="foot"><div class="l">This is a computer generated ${quote ? 'quotation' : 'sales order'}.</div>${sign}</div></div>`

  w.document.open()
  w.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>${quote ? 'Quotation' : 'Sales order'} ${esc(d.no)}</title><style>${CSS}</style></head>
    <body>${page1}${page2}<script>onload=()=>setTimeout(()=>print(),150)<\/script></body></html>`)
  w.document.close()
  return true
}
