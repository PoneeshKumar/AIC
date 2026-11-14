// Hand-drawn SVG charts for the console. No library. Colors come from CSS custom properties.
window.Charts = (() => {
  const NS = 'http://www.w3.org/2000/svg'

  function s(tag, attrs = {}, text) {
    const n = document.createElementNS(NS, tag)
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v)
    if (text !== undefined) n.textContent = text
    return n
  }

  function dur(min) {
    const m = Math.max(0, Math.round(min)), h = Math.floor(m / 60)
    return h ? `${h} h ${String(m % 60).padStart(2, '0')} m` : `${m} m`
  }

  // Bar with a 4px rounded data end on the right, square at the baseline.
  function barPath(x, y, w, h, roundEnd) {
    if (w <= 0) return ''
    const r = roundEnd ? Math.min(4, w / 2, h / 2) : 0
    return `M${x},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h - r}Q${x + w},${y + h} ${x + w - r},${y + h}H${x}Z`
  }

  const tip = {
    el: () => document.getElementById('tooltip'),
    show(lines, x, y) {
      const t = this.el()
      t.replaceChildren()
      lines.forEach((ln, i) => {
        const row = document.createElement('div')
        if (i === 0) { const b = document.createElement('b'); b.textContent = ln; row.append(b) } else row.textContent = ln
        t.append(row)
      })
      t.hidden = false
      const pad = 12, w = t.offsetWidth, h = t.offsetHeight
      t.style.left = Math.min(window.innerWidth - w - 8, x + pad) + 'px'
      t.style.top = Math.max(8, y - h - pad) + 'px'
    },
    hide() { this.el().hidden = true },
  }

  // Route options: one stacked bar per route, cooled then exposed minutes.
  function routes(el, data, budgetLeft, onHover) {
    const W = Math.max(320, el.clientWidth), rowH = 44, barH = 16, top = 8, bottom = 24
    const labelW = 112, valueW = 64, x0 = labelW, x1 = W - valueW
    const list = (data && data.routes) || []
    const H = top + list.length * rowH + bottom
    const maxMin = Math.max(240, ...list.map(r => r.total_min))
    const domain = Math.ceil(maxMin / 240) * 240
    const X = m => x0 + (x1 - x0) * (m / domain)
    const svg = s('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'Transit time by route, cooled and exposed minutes' })

    for (let m = 0; m <= domain; m += 240) {
      svg.append(s('line', { class: m ? 'gridline' : 'baseline', x1: X(m), x2: X(m), y1: top, y2: H - bottom }))
      svg.append(s('text', { class: 'tick', x: X(m), y: H - 6, 'text-anchor': 'middle' }, `${m / 60} h`))
    }

    list.forEach((r, i) => {
      const y = top + i * rowH, by = y + (rowH - barH) / 2
      const over = r.status !== 'cancelled' && budgetLeft != null && r.exposed_min > budgetLeft
      const status = r.status === 'cancelled' ? 'Cancelled' : r.status === 'booked' ? 'Booked' : over ? 'Exceeds budget' : r.status === 'unknown' ? 'Carrier unreachable' : 'Available'
      const g = s('g', { class: `row ${r.status}`, 'data-route': r.route_id })
      g.append(s('rect', { class: 'row-hit', x: 0, y, width: W, height: rowH, rx: 4 }))
      g.append(s('text', { class: 'lbl', x: 8, y: y + 19 }, r.route_id))
      const st = s('text', { x: 8, y: y + 35 }, status)
      g.append(st)
      const cooled = r.total_min - r.exposed_min
      const gap = r.exposed_min && cooled ? 2 : 0
      g.append(s('path', { class: 'seg-1', d: barPath(X(0), by, X(cooled) - X(0) - gap / 2, barH, !r.exposed_min) }))
      if (r.exposed_min) g.append(s('path', { class: 'seg-2', d: barPath(X(cooled) + gap / 2, by, X(r.total_min) - X(cooled) - gap / 2, barH, true) }))
      g.append(s('text', { class: 'val', x: X(r.total_min) + 8, y: by + barH - 3 }, dur(r.total_min)))

      const stops = [r.legs[0].from, ...r.legs.filter(l => l.kind !== 'layover').map(l => l.to)]
      const lines = [r.route_id + (r.original ? ' (original)' : ''), stops.join(' to '), `Transit ${dur(r.total_min)}`,
        `Cooled ${dur(cooled)}`, `Exposed ${dur(r.exposed_min)}` + (budgetLeft != null ? ` of ${dur(budgetLeft)} left` : ''), status]
      for (const ev of ['pointerdown', 'pointermove']) g.addEventListener(ev, e => { tip.show(lines, e.clientX, e.clientY); onHover && onHover(r.route_id) })
      g.addEventListener('pointerleave', e => { if (e.pointerType === 'mouse') { tip.hide(); onHover && onHover(null) } })
      svg.append(g)
    })
    el.replaceChildren(svg)
  }

  function routesTable(el, data) {
    const t = document.createElement('table')
    const head = t.createTHead().insertRow()
    for (const h of ['Route', 'Transit', 'Cooled', 'Exposed', 'Status']) { const th = document.createElement('th'); th.textContent = h; head.append(th) }
    const body = t.createTBody()
    for (const r of (data && data.routes) || []) {
      const row = body.insertRow()
      for (const v of [r.route_id, dur(r.total_min), dur(r.total_min - r.exposed_min), dur(r.exposed_min), r.status]) row.insertCell().textContent = v
    }
    el.replaceChildren(t)
  }

  // Budget over time: one series, area wash, end label, a 1 hour reference line, crosshair on hover.
  let burnHover = null
  function burn(el, samples, total) {
    const W = Math.max(320, el.clientWidth), H = 240, ml = 44, mr = 64, mt = 12, mb = 26
    const svg = s('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'Excursion budget remaining over time' })
    const yMax = Math.max(60, total || 0, ...samples.map(p => p.v))
    const step = yMax > 360 ? 120 : 60
    const Y = v => mt + (H - mt - mb) * (1 - v / yMax)
    for (let v = 0; v <= yMax; v += step) {
      svg.append(s('line', { class: v ? 'gridline' : 'baseline', x1: ml, x2: W - mr, y1: Y(v), y2: Y(v) }))
      svg.append(s('text', { class: 'tick', x: ml - 8, y: Y(v) + 4, 'text-anchor': 'end' }, `${v / 60} h`))
    }
    svg.append(s('line', { class: 'threshold', x1: ml, x2: W - mr, y1: Y(60), y2: Y(60) }))
    svg.append(s('text', { class: 'threshold-lbl', x: W - mr + 6, y: Y(60) + 4 }, '1 h left'))

    if (samples.length < 2) {
      svg.append(s('text', { class: 'empty-msg', x: (ml + W - mr) / 2, y: H / 2, 'text-anchor': 'middle' }, 'Collecting readings'))
      el.replaceChildren(svg)
      return
    }
    const t0 = samples[0].t, t1 = Math.max(samples[samples.length - 1].t, t0 + 60000)
    const X = t => ml + (W - ml - mr) * ((t - t0) / (t1 - t0))
    const clock = t => new Date(t).toTimeString().slice(0, 8)
    for (const t of [t0, (t0 + t1) / 2, t1]) svg.append(s('text', { class: 'tick', x: X(t), y: H - 6, 'text-anchor': t === t0 ? 'start' : t === t1 ? 'end' : 'middle' }, clock(t)))

    const pts = samples.map(p => [X(p.t), Y(p.v)])
    const line = 'M' + pts.map(p => p.join(',')).join('L')
    svg.append(s('path', { class: 'area', d: `${line}L${pts[pts.length - 1][0]},${Y(0)}L${pts[0][0]},${Y(0)}Z` }))
    svg.append(s('path', { class: 'line', d: line }))
    const last = samples[samples.length - 1], [lx, ly] = pts[pts.length - 1]
    svg.append(s('circle', { class: 'end', cx: lx, cy: ly, r: 4.5 }))
    svg.append(s('text', { class: 'end-lbl', x: lx + 8, y: ly + 4 }, dur(last.v)))

    const cross = s('g', { visibility: 'hidden' })
    const cl = s('line', { class: 'cross', y1: mt, y2: H - mb }), cd = s('circle', { class: 'end', r: 4.5 })
    cross.append(cl, cd); svg.append(cross)
    const hit = s('rect', { x: ml, y: mt, width: W - ml - mr, height: H - mt - mb, fill: 'transparent' })
    function at(clientX, clientY) {
      const box = svg.getBoundingClientRect(), x = (clientX - box.left) * (W / box.width)
      let best = 0
      pts.forEach((p, i) => { if (Math.abs(p[0] - x) < Math.abs(pts[best][0] - x)) best = i })
      cl.setAttribute('x1', pts[best][0]); cl.setAttribute('x2', pts[best][0])
      cd.setAttribute('cx', pts[best][0]); cd.setAttribute('cy', pts[best][1])
      cross.setAttribute('visibility', 'visible')
      tip.show([clock(samples[best].t), `${dur(samples[best].v)} remaining`], clientX, clientY)
    }
    hit.addEventListener('pointerdown', e => { burnHover = [e.clientX, e.clientY]; at(e.clientX, e.clientY) })
    hit.addEventListener('pointermove', e => { burnHover = [e.clientX, e.clientY]; at(e.clientX, e.clientY) })
    hit.addEventListener('pointerleave', e => { if (e.pointerType !== 'mouse') return; burnHover = null; cross.setAttribute('visibility', 'hidden'); tip.hide() })
    svg.append(hit)
    el.replaceChildren(svg)
    if (burnHover) at(...burnHover)
  }

  // Touch has no hover: tapping anywhere outside a chart dismisses the tooltip.
  document.addEventListener('pointerdown', e => { if (e.pointerType !== 'mouse' && !e.target.closest('.routes-chart, .burn-chart')) tip.hide() })

  return { routes, routesTable, burn, dur }
})()
