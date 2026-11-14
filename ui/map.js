// Route map on Leaflet (vendored in ui/vendor). Tiles need the internet. Without them the routes still draw.
window.MapView = (() => {
  let map, layer, lines = {}, plane, lastKey = '', network = null
  const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  const dark = () => matchMedia('(prefers-color-scheme: dark)').matches && document.documentElement.dataset.theme !== 'light'

  function init(el) {
    if (!window.L) { el.textContent = 'Map library did not load.'; return }
    map = L.map(el, { zoomControl: true, scrollWheelZoom: false, attributionControl: true, zoomSnap: 0.25 })
    const canvas = dark() ? 'World_Dark_Gray_Base' : 'World_Light_Gray_Base'
    L.tileLayer(`https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/${canvas}/MapServer/tile/{z}/{y}/{x}`, {
      maxZoom: 16, attribution: 'Tiles &copy; Esri, HERE, Garmin, &copy; OpenStreetMap contributors',
    }).addTo(map)
    map.setView([51, -101], 3.5)
    layer = L.layerGroup().addTo(map)
    new ResizeObserver(() => map.invalidateSize()).observe(el)
  }

  // A gentle arc between two airports, so routes that share an airport stay apart.
  function arc(a, b, bend) {
    const pts = [], mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2
    const dx = b[1] - a[1], dy = b[0] - a[0]
    const c = [mx + dx * bend, my - dy * bend]
    for (let i = 0; i <= 32; i++) {
      const t = i / 32
      pts.push([(1 - t) ** 2 * a[0] + 2 * (1 - t) * t * c[0] + t ** 2 * b[0], (1 - t) ** 2 * a[1] + 2 * (1 - t) * t * c[1] + t ** 2 * b[1]])
    }
    return pts
  }

  function style(status, kind, hl) {
    const truck = kind === 'truck'
    if (status === 'booked') return { color: css('--series-1'), weight: hl ? 6 : 4, opacity: 1, dashArray: truck ? '1 8' : null }
    if (status === 'cancelled') return { color: css('--crit'), weight: hl ? 4 : 2, opacity: 0.85, dashArray: '6 6' }
    return { color: hl ? css('--ink-2') : '#8a94a3', weight: hl ? 4 : 2, opacity: 0.9, dashArray: truck ? '1 6' : null }
  }

  function path(net, route) {
    const out = []
    for (const leg of route.legs) {
      if (leg.kind === 'layover') continue
      const a = net.airports[leg.from], b = net.airports[leg.to]
      if (a && b) out.push({ leg, pts: arc([a.lat, a.lon], [b.lat, b.lon], route._bend) })
    }
    return out
  }

  function update(net, position) {
    if (!map || !net) return
    network = net
    net.routes.forEach((r, i) => { r._bend = [0, 0.1, -0.1, 0.18, -0.18][i % 5] })
    const key = JSON.stringify([net.routes.map(r => [r.route_id, r.status]), net.storage])
    if (key !== lastKey) {
      lastKey = key
      layer.clearLayers(); lines = {}
      const order = [...net.routes].sort((a, b) => (a.status === 'booked') - (b.status === 'booked'))
      for (const r of order) {
        lines[r.route_id] = path(net, r).map(({ leg, pts }) => {
          const pl = L.polyline(pts, { ...style(r.status, leg.kind), lineCap: 'round' }).addTo(layer)
          pl._meta = { status: r.status, kind: leg.kind }
          pl.bindTooltip(`${r.route_id}: ${leg.kind === 'truck' ? 'refrigerated truck' : 'flight ' + leg.flight}, ${Charts.dur(leg.duration_min)}`, { sticky: true, className: 'route-tip' })
          return pl
        })
      }
      for (const st of net.storage) {
        const a = net.airports[st.city]
        if (!a) continue
        const fill = st.bays_free > 0 ? css('--good') : '#8a94a3'
        L.marker([a.lat - 1.1, a.lon], {
          icon: L.divIcon({ className: '', iconSize: [12, 12], html: `<div style="width:12px;height:12px;background:${fill};border:2px solid ${css('--surface')};outline:1px solid ${fill}"></div>` }),
        }).bindTooltip(`${a.name} cold storage: ${st.bays_free} qualified bay${st.bays_free === 1 ? '' : 's'} free`, { className: 'route-tip' }).addTo(layer)
      }
      for (const [code, a] of Object.entries(net.airports)) {
        const end = code === net.origin || code === net.destination
        L.circleMarker([a.lat, a.lon], { radius: end ? 6 : 4.5, color: css('--ink'), weight: 2, fillColor: css('--surface'), fillOpacity: 1 })
          .bindTooltip(code, { permanent: true, direction: 'top', offset: [0, -6], className: 'code' })
          .addTo(layer)
      }
      const b = Object.values(net.airports).map(a => [a.lat, a.lon])
      if (b.length) map.fitBounds(b, { padding: [36, 36] })
    }
    placePlane(position)
  }

  function placePlane(position) {
    if (!position || !network) { if (plane) { plane.remove(); plane = null } return }
    const r = network.routes.find(x => x.route_id === position.route_id)
    if (!r) return
    const pts = path(network, r).flatMap(p => p.pts)
    const p = pts[Math.min(pts.length - 1, Math.floor(position.progress * (pts.length - 1)))]
    if (!plane) {
      plane = L.marker(p, { icon: L.divIcon({ className: 'plane-icon', iconSize: [24, 24], html: '<svg viewBox="0 0 24 24"><use href="#i-plane"/></svg>' }), zIndexOffset: 1000 })
        .bindTooltip('BIO-2048', { className: 'route-tip' }).addTo(map)
    } else plane.setLatLng(p)
  }

  function highlight(routeId) {
    for (const [id, pls] of Object.entries(lines)) {
      for (const pl of pls) {
        pl.setStyle(style(pl._meta.status, pl._meta.kind, id === routeId))
        if (id === routeId) pl.bringToFront()
      }
    }
  }

  return { init, update, highlight }
})()
