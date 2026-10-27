// API client, formatting, location and map helpers.
const TOKEN_KEY = 'sales-portal.token'
let token = sessionStorage.getItem(TOKEN_KEY)
let onUnauthorized = () => {}
export const getToken = () => token
export function setToken(t) { token = t; t ? sessionStorage.setItem(TOKEN_KEY, t) : sessionStorage.removeItem(TOKEN_KEY) }
export function setUnauthorizedHandler(fn) { onUnauthorized = fn }
export class ApiError extends Error { constructor(status, message) { super(message); this.status = status } }

export async function api(path, { method = 'GET', body, form, raw } = {}) {
  const headers = {}
  if (token) headers.Authorization = `Bearer ${token}`
  let payload
  if (form) payload = form
  else if (body !== undefined) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body) }
  let res
  try { res = await fetch(path, { method, headers, body: payload }) } catch { throw new ApiError(0, 'The server could not be reached. Check your connection.') }
  if (!res.ok) {
    let msg = 'Something went wrong. Try again.'
    try { const j = await res.json(); msg = typeof j.detail === 'string' ? j.detail : (j.detail?.[0]?.msg || msg) } catch { /* not JSON */ }
    if (res.status === 401 && token) onUnauthorized(msg)
    throw new ApiError(res.status, msg)
  }
  return raw ? res : res.json()
}
export async function download(path, filename, opts = {}) {
  const res = await api(path, { ...opts, raw: true })
  const url = URL.createObjectURL(await res.blob())
  const a = document.createElement('a'); a.href = url; a.download = filename; document.body.appendChild(a); a.click(); a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 2000)
}

const pad = (n) => String(n).padStart(2, '0')
export const isoOf = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
export const todayISO = () => isoOf(new Date())
export const addDays = (iso, n) => { const d = new Date(iso + 'T12:00'); d.setDate(d.getDate() + n); return isoOf(d) }
export const dmy = (iso) => (iso ? `${iso.slice(8, 10)}-${iso.slice(5, 7)}-${iso.slice(0, 4)}` : '')
export const hm = (ts) => (ts ? new Date(ts).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' }) : '')
export const dt = (ts) => (ts ? `${dmy(isoOf(new Date(ts)))} ${hm(ts)}` : '')
export const r2 = (n) => Math.round((+n || 0) * 100) / 100
export const inr = (n) => (n < 0 ? '−' : '') + '₹\u202F' + Math.abs(r2(n)).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
export const inr0 = (n) => (n < 0 ? '−' : '') + '₹\u202F' + Math.round(Math.abs(+n || 0)).toLocaleString('en-IN')
export const num = (n) => (+n || 0).toLocaleString('en-IN', { maximumFractionDigits: 3 })
export const fmtH = (h) => { const m = Math.round((+h || 0) * 60); return `${Math.floor(m / 60)}h ${pad(m % 60)}m` }
export const parseNum = (v) => { const n = parseFloat(String(v ?? '').replace(/[,₹\s]/g, '')); return Number.isFinite(n) ? n : 0 }
export const initials = (n) => String(n || '?').split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join('').toUpperCase()

export const MODES = { cash: 'Cash', cheque: 'Cheque', upi: 'UPI', neft: 'NEFT / RTGS', card: 'Card' }
export const SYNC = { na: ['—', ''], pending: ['To send', 'warn'], exported: ['Sent by file', 'info'], synced: ['In Dynamics', 'ok'], error: ['Sync error', 'bad'] }
export const DAYCODE = { P: ['Present', 'ok'], H: ['Half day', 'warn'], S: ['Short day', 'warn'], A: ['Absent', 'bad'], WO: ['Weekly off', ''], '': ['—', ''] }

export function getPosition(timeout = 12000) {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) return reject(new Error('This browser cannot share its location.'))
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ lat: +p.coords.latitude.toFixed(6), lng: +p.coords.longitude.toFixed(6), acc: Math.round(p.coords.accuracy) }),
      (e) => reject(new Error(e.code === 1 ? 'Location permission was refused. Allow location for this site and try again.'
        : e.code === 3 ? 'Could not get a location fix in time. Try again in the open.' : 'Location is not available on this device.')),
      { enableHighAccuracy: true, timeout, maximumAge: 30000 })
  })
}
export const gmapsLink = (lat, lng) => `https://www.google.com/maps/search/?api=1&query=${lat},${lng}`

// Google Maps JavaScript API, loaded once with the key from Settings
let mapsPromise = null
export function loadMaps(key) {
  if (!key) return Promise.reject(new Error('nokey'))
  if (window.google?.maps?.Map) return Promise.resolve()
  if (!mapsPromise) {
    mapsPromise = new Promise((resolve, reject) => {
      window.__portalMapsReady = () => resolve()
      const s = document.createElement('script')
      s.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(key)}&callback=__portalMapsReady&loading=async`
      s.async = true
      s.onerror = () => { mapsPromise = null; reject(new Error('Google Maps could not load. Check the internet connection and the API key.')) }
      document.head.appendChild(s)
    })
  }
  return mapsPromise
}
export async function addressOf(key, p) {
  if (!key || !p || p.lat == null) return ''
  try {
    await loadMaps(key)
    const r = await new window.google.maps.Geocoder().geocode({ location: { lat: p.lat, lng: p.lng } })
    return r.results?.[0]?.formatted_address || ''
  } catch { return '' }
}

// Print a document in a new window
export function printDoc(title, html) {
  const w = window.open('', '_blank')
  if (!w) return false
  w.document.write(`<!doctype html><title>${title}</title><style>body{font:13px system-ui,Segoe UI,sans-serif;color:#111;margin:28px}table{width:100%;border-collapse:collapse;margin:8px 0}th,td{border-bottom:1px solid #ccc;padding:5px 6px;text-align:left}.r{text-align:right}.fine{color:#666;font-size:12px}</style>${html}<script>onload=()=>print()<\/script>`)
  w.document.close()
  return true
}
export const esc = (s) => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
