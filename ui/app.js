// ColdTrace console. Polls GET /state every second (shape: docs/CONTRACTS.md, "UI state") and
// GET /network every 3 seconds for the map and route chart.
// Text from other systems is always set with textContent, never innerHTML.
window.ColdTrace = (() => {
  const $ = id => document.getElementById(id)
  const STALE_AFTER_MS = 3000
  const MAX_SAMPLES = 900

  const ACTIONS = {
    set_quarantine: 'Hold the shipment in quarantine on arrival',
    reserve_storage: 'Reserve qualified cold storage for the layover',
    rebook_carrier: 'Book the shipment onto the new route',
    notify_hospital: 'Send the hospital the new arrival time',
  }
  const STEP = {
    planned: { badge: '', text: () => 'Waiting' },
    sent: { badge: 'warn', text: () => 'Awaiting confirmation' },
    verified: { badge: 'good', text: s => `Confirmed by ${s.system}` },
    failed: { badge: 'crit', text: () => 'Did not take effect' },
    skipped: { badge: '', text: () => 'No longer needed' },
  }
  const SHIP = { in_transit: ['info', 'In transit'], recovering: ['warn', 'Recovery in progress'], recovered: ['good', 'Rerouted'],
    delivered: ['good', 'Delivered'], quarantined: ['crit', 'Quarantined'], waiting_approval: ['warn', 'Waiting for approval'] }

  let lastOk = 0, everOk = false, seenLog = 0, editing = false, currentProposal = null
  let net = null, lastState = null, samples = window.__previewHistory || []

  function el(tag, cls, text) {
    const n = document.createElement(tag)
    if (cls) n.className = cls
    if (text !== undefined && text !== null) n.textContent = text
    return n
  }
  function icon(id) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg'), use = document.createElementNS('http://www.w3.org/2000/svg', 'use')
    use.setAttribute('href', '#' + id); svg.append(use); return svg
  }
  function badge(cls, text) { return el('span', 'badge ' + (cls || ''), text) }
  const dur = m => Charts.dur(m)

  function routeLabel(r) {
    if (!r || !net) return null
    const via = r.legs.filter(l => l.kind === 'layover').map(l => (net.airports[l.from] || {}).name || l.from)
    const truck = r.legs.find(l => l.kind === 'truck')
    return `${r.route_id}` + (via.length ? ` via ${via.join(', ')}` : truck ? `, truck from ${(net.airports[truck.from] || {}).name || truck.from}` : ', nonstop')
  }

  function renderHeader(st) {
    const ship = st.shipment || {}
    $('shipment-id').textContent = 'Shipment ' + (ship.shipment_id || '')
    const [cls, text] = SHIP[ship.status] || ['', (ship.status || 'unknown').replace(/_/g, ' ')]
    const b = $('shipment-status'); b.className = 'badge ' + cls; b.textContent = text
    if (net) {
      const range = net.temp_range_c ? `${net.temp_range_c[0]} to ${net.temp_range_c[1]} °C` : ''
      $('shipment-meta').textContent = [net.product, `${net.origin} to ${net.destination}`, range, net.consignee].filter(Boolean).join('  ·  ')
    }
    const trace = $('trace-link')
    trace.hidden = !st.trace_url
    if (st.trace_url) trace.href = st.trace_url
  }

  function renderKpis(st) {
    const ship = st.shipment || {}, c = st.counters || {}
    const total = (net && net.budget_total_min) || ship.budget_remaining_min
    const min = ship.budget_remaining_min
    $('budget').textContent = min == null ? '--' : dur(min)
    $('kpi-budget').className = 'kpi ' + (min == null ? '' : min < 60 ? 'crit' : min < 120 ? 'warn' : '')
    $('budget-meter').style.width = total ? Math.max(0, Math.min(100, 100 * min / total)) + '%' : '0'
    $('budget-foot').textContent = total ? `of ${dur(total)} allowed out of range` : ''

    const d = c.duplicate_actions
    $('dupes').textContent = d == null ? '--' : String(d)
    $('kpi-dupes').className = 'kpi ' + (d === 0 ? 'good' : d > 0 ? 'crit' : '')
    $('dupes-foot').textContent = d > 0 ? 'An action happened more than once. See the event log.' : 'Counted from the warehouse and carrier'

    const done = c.steps_verified || 0, n = c.steps_total || 0
    $('verified').textContent = n ? `${done} of ${n}` : 'No plan yet'
    const seg = $('verified-segments'); seg.replaceChildren()
    for (const s of st.steps || []) seg.append(el('i', s.status))

    const routes = (net && net.routes) || []
    const booked = routes.find(r => r.status === 'booked'), original = routes.find(r => r.original)
    if (booked) {
      $('route').textContent = routeLabel(booked)
      $('route-foot').textContent = `Transit ${dur(booked.total_min)}, exposed ${dur(booked.exposed_min)}`
    } else if (original) {
      const flight = (original.legs.find(l => l.flight) || {}).flight
      const cancelled = original.status === 'cancelled'
      $('route').textContent = cancelled ? 'Awaiting rebooking' : routeLabel(original)
      $('route-foot').textContent = cancelled ? `${original.route_id} lost when flight ${flight} was cancelled` : `Original booking on flight ${flight}`
    } else {
      $('route').textContent = '--'; $('route-foot').textContent = 'Carrier not reachable'
    }
  }

  function renderSteps(steps, counters) {
    const list = $('steps')
    list.replaceChildren()
    $('plan-meta').textContent = steps && steps.length ? `${counters.steps_verified || 0} of ${steps.length} confirmed` : ''
    if (!steps || !steps.length) {
      list.append(el('li', 'empty', 'No recovery plan yet. The agent writes its plan here when a disruption starts.'))
      return
    }
    for (const s of steps) {
      const def = STEP[s.status] || { badge: '', text: () => s.status }
      const li = el('li', 'step ' + (s.status || 'planned'))
      const ico = el('div', 'ico')
      if (s.status === 'verified') ico.append(icon('i-check'))
      else if (s.status === 'failed') ico.append(icon('i-x'))
      else if (s.status === 'sent') ico.append(icon('i-send'))
      else if (s.status === 'skipped') ico.append(icon('i-dash'))
      else ico.textContent = s.seq
      const body = el('div')
      body.append(el('div', 'title', ACTIONS[s.action] || (s.action || '').replace(/_/g, ' ')))
      const meta = el('div', 'meta')
      meta.append(el('span', 'sys', s.system || ''))
      if (s.reason) meta.append(document.createTextNode('  ·  ' + s.reason))
      body.append(meta)
      li.append(ico, body, badge(def.badge, def.text(s)))
      list.append(li)
    }
  }

  function renderSystems(systems) {
    const list = $('systems')
    list.replaceChildren()
    const rows = [
      ['carrier', s => s.ok ? (s.schema_version === 2 ? ['warn', 'Format changed', 'Answering in API v2'] : ['good', 'Operational', 'API v1']) : null],
      ['warehouse', s => s.ok ? ['good', 'Operational', s.reservations == null ? 'Reservation count unknown' : `${s.reservations} reservation${s.reservations === 1 ? '' : 's'} held for this shipment`] : null],
      ['hospital', s => s.ok ? ['good', 'Operational', 'Receiving delivery updates'] : null],
      ['agent', s => s.alive ? ['good', 'Running', s.worker || 'worker'] : s.worker ? ['crit', 'Not responding', `${s.worker} missed its heartbeat`] : ['', 'Offline', 'No worker registered']],
    ]
    for (const [name, fn] of rows) {
      const s = (systems || {})[name] || {}
      const [cls, label, detail] = fn(s) || ['crit', 'Unreachable', 'No answer on its health check']
      const li = el('li')
      li.append(el('span', 'name', name), badge(cls, label), el('span', 'detail', detail))
      list.append(li)
    }
  }

  function renderProposal(p) {
    const box = $('proposal')
    if (!p) { box.hidden = true; currentProposal = null; editing = false; return }
    if (currentProposal && currentProposal.proposal_id === p.proposal_id) return  // keep an edit in progress
    currentProposal = p
    box.hidden = false
    $('proposal-summary').textContent = p.summary || `The ${p.system || 'system'} answered in a format the agent does not recognise. It proposes this mapping.`
    $('proposal-match').hidden = !p.memory_hit
    $('proposal-memory').textContent = p.memory_hit || ''
    const score = p.score != null ? Number(p.score) : null
    $('proposal-score').textContent = score != null ? score.toFixed(2) : ''
    $('proposal-score-bar').style.width = score != null ? (score * 100) + '%' : '0'
    const tbody = $('proposal-map'); tbody.replaceChildren()
    const map = (p.fix && p.fix.map) || {}
    for (const [from, to] of Object.entries(map)) { const tr = el('tr'); tr.append(el('td', null, from), el('td', null, to)); tbody.append(tr) }
    if (!Object.keys(map).length) { const tr = el('tr'), td = el('td', null, JSON.stringify(p.fix || {})); td.colSpan = 2; tr.append(td); tbody.append(tr) }
    $('proposal-edit').hidden = true
    $('proposal-edit').value = JSON.stringify(p.fix || {}, null, 2)
    $('correct').textContent = 'Edit mapping'
    $('approve').textContent = 'Approve and store rule'
    $('proposal-error').textContent = ''
  }

  function kindOf(msg) {
    const m = msg.toLowerCase()
    if (m.startsWith('chaos')) return ['chaos', 'Chaos']
    if (m.includes('resume') || m.includes('restart')) return ['resume', 'Resume']
    if (m.includes('memory') || m.includes('propos') || m.includes('rule')) return ['memory', 'Memory']
    if (m.startsWith('verified') || m.includes('confirmed')) return ['verify', 'Verified']
    if (m.includes('atlas')) return ['', 'System']
    return ['', 'Agent']
  }

  function renderLog(log) {
    const body = $('log'), box = $('log-scroll')
    const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40
    body.replaceChildren()
    $('log-meta').textContent = log && log.length ? `${log.length} event${log.length === 1 ? '' : 's'}` : ''
    if (!log || !log.length) { const tr = el('tr', 'empty'), td = el('td', null, 'Nothing has happened yet.'); td.colSpan = 3; tr.append(td); body.append(tr); return }
    log.forEach((line, i) => {
      const tr = el('tr', seenLog && i >= seenLog ? 'new' : '')
      const [cls, label] = kindOf(line.message || '')
      const kind = el('td', 'kind'); kind.append(el('span', 'tag ' + cls, label))
      tr.append(el('td', 'ts', line.ts), kind, el('td', 'msg', line.message))
      body.append(tr)
    })
    seenLog = log.length
    if (atBottom) box.scrollTop = box.scrollHeight
  }

  function renderCharts() {
    const left = lastState && lastState.shipment ? lastState.shipment.budget_remaining_min : null
    Charts.routes($('routes-chart'), net, left, id => MapView.highlight(id))
    Charts.routesTable($('routes-table'), net)
    Charts.burn($('burn-chart'), samples, net && net.budget_total_min)
  }

  function setConnection(state, text) { $('live').className = 'live ' + state; $('live-text').textContent = text }

  function checkStale() {
    if (!everOk) return
    const age = Date.now() - lastOk
    $('error-banner').hidden = age <= STALE_AFTER_MS * 3
    const stale = age > STALE_AFTER_MS
    $('stale-banner').hidden = !stale
    if (stale) {
      $('stale-banner').textContent = `Data is ${Math.round(age / 1000)} seconds old. Figures may have changed.`
      setConnection(age > STALE_AFTER_MS * 3 ? 'off' : 'stale', 'Out of date')
    }
  }

  async function pollNetwork() {
    try {
      const res = await fetch('/network', { cache: 'no-store' })
      if (!res.ok) return
      net = await res.json()
      MapView.update(net, net.shipment_position)
      if (lastState) { renderHeader(lastState); renderKpis(lastState) }
      renderCharts()
    } catch { /* the state poll reports connection problems */ }
  }

  async function poll() {
    try {
      const res = await fetch('/state', { cache: 'no-store' })
      if (!res.ok) throw new Error('state ' + res.status)
      const st = lastState = await res.json()
      lastOk = Date.now(); everOk = true
      $('error-banner').hidden = true
      const v = st.shipment && st.shipment.budget_remaining_min
      if (v != null) { samples.push({ t: Date.now(), v }); if (samples.length > MAX_SAMPLES) samples.shift() }
      renderHeader(st); renderKpis(st); renderSteps(st.steps, st.counters || {}); renderSystems(st.systems)
      renderProposal(st.proposal); renderLog(st.log); renderCharts()
      setConnection('on', 'Live')
    } catch {
      if (!everOk) { $('error-banner').hidden = false; setConnection('off', 'Not connected') }
    }
    checkStale()
  }

  function toast(text, isError) {
    const t = $('toast')
    t.textContent = text; t.className = 'toast' + (isError ? ' err' : ''); t.hidden = false
    clearTimeout(t._timer); t._timer = setTimeout(() => { t.hidden = true }, 4000)
  }
  async function errorText(res) {
    try { const b = await res.json(); return b.detail || b.message || res.statusText } catch { return res.statusText || 'Request failed' }
  }

  function wire() {
    document.querySelectorAll('button[data-event]').forEach(b => {
      b.onclick = async () => {
        b.disabled = true
        try {
          const res = await fetch('/chaos/' + b.dataset.event, { method: 'POST' })
          if (!res.ok) return toast(await errorText(res), true)
          const body = await res.json()
          toast(body.message || b.textContent.trim() + ' sent')
          poll(); pollNetwork()
        } catch { toast('Could not reach the server', true) } finally { b.disabled = false }
      }
    })
    $('correct').onclick = () => {
      editing = !editing
      $('proposal-edit').hidden = !editing
      $('correct').textContent = editing ? 'Cancel edit' : 'Edit mapping'
      $('approve').textContent = editing ? 'Save correction as rule' : 'Approve and store rule'
    }
    $('approve').onclick = async () => {
      if (!currentProposal) return
      const body = { proposal_id: currentProposal.proposal_id, decision: editing ? 'corrected' : 'approved', by: 'operator' }
      if (editing) { try { body.fix = JSON.parse($('proposal-edit').value) } catch { $('proposal-error').textContent = 'The mapping is not valid JSON.'; return } }
      $('approve').disabled = true
      try {
        const res = await fetch('/approve', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
        if (!res.ok) { $('proposal-error').textContent = await errorText(res); return }
        toast(editing ? 'Correction stored as a rule' : 'Fix approved and stored as a rule')
        currentProposal = null; editing = false
        poll()
      } catch { $('proposal-error').textContent = 'Could not reach the server.' } finally { $('approve').disabled = false }
    }
    let t; window.addEventListener('resize', () => { clearTimeout(t); t = setTimeout(renderCharts, 150) })
  }

  function start() {
    if (window.__previewHistory) samples = window.__previewHistory
    MapView.init($('map'))
    wire()
    pollNetwork(); poll()
    setInterval(poll, 1000)
    setInterval(pollNetwork, 3000)
  }

  return { start }
})()
