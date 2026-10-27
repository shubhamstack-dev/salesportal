import { useEffect, useRef } from 'react'
import { gmapsLink, loadMaps } from './lib'
import { useSession } from './session'

const COLORS = { green: '#17784A', red: '#C0282D', blue: '#1D5FD1', orange: '#D9480F' }

/* points: [{lat, lng, title, sub, color, label}] — with no Maps key, a list with Google Maps links */
export default function MapView({ points, small }) {
  const { settings, isAdmin } = useSession()
  const ref = useRef(null)
  const pts = (points || []).filter((p) => p && p.lat != null && p.lng != null)
  const key = settings.maps_key
  const sig = JSON.stringify(pts)
  useEffect(() => {
    if (!key || !ref.current) return
    let cancelled = false
    loadMaps(key).then(() => {
      if (cancelled || !ref.current) return
      const g = window.google.maps
      const map = new g.Map(ref.current, { center: pts[0] || { lat: 26.85, lng: 80.95 }, zoom: 11, streetViewControl: false })
      const info = new g.InfoWindow(); const bounds = new g.LatLngBounds()
      pts.forEach((m) => {
        const mk = new g.Marker({ position: { lat: m.lat, lng: m.lng }, map, title: m.title,
          label: m.label ? { text: String(m.label), color: '#fff', fontSize: '11px', fontWeight: '700' } : undefined,
          icon: { path: g.SymbolPath.CIRCLE, scale: m.label ? 11 : 8, fillColor: COLORS[m.color] || COLORS.blue, fillOpacity: 1, strokeColor: '#fff', strokeWeight: 2 } })
        mk.addListener('click', () => { info.setContent(`<div style="color:#111;font:13px system-ui"><b>${m.title}</b><br>${m.sub || ''}</div>`); info.open({ map, anchor: mk }) })
        bounds.extend(mk.getPosition())
      })
      if (pts.length > 1) map.fitBounds(bounds, 40); else if (pts.length === 1) map.setZoom(15)
    }).catch((e) => { if (ref.current) ref.current.innerHTML = `<div class="mapfallback">${e.message}</div>` })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, sig])
  if (!key) {
    return (
      <div className={`mapbox ${small ? 'sm' : ''}`}><div className="mapfallback">
        {isAdmin && <p className="fine">Add a Google Maps API key in Settings to see these on a map.</p>}
        {pts.length ? pts.map((m, i) => (
          <div key={i} style={{ padding: '5px 0', borderBottom: '1px solid var(--rule)' }}>
            <span className={`dot ${m.color === 'green' ? 'on' : m.color === 'red' ? 'off' : 'na'}`} /><b>{m.title}</b> <span className="fine">{m.sub}</span><br />
            <a href={gmapsLink(m.lat, m.lng)} target="_blank" rel="noopener noreferrer">Open in Google Maps</a>
          </div>)) : <p className="mut">No locations to show.</p>}
      </div></div>)
  }
  return <div ref={ref} className={`mapbox ${small ? 'sm' : ''}`}><div className="mapfallback mut">Loading map…</div></div>
}

export const LocLink = ({ p, label = 'Open in Google Maps' }) => (p && p.lat != null
  ? <a href={gmapsLink(p.lat, p.lng)} target="_blank" rel="noopener noreferrer">{label}</a> : <span className="mut">No location</span>)
