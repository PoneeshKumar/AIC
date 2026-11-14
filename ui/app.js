// ColdTrace demo screen. Polls GET /state once a second and renders it. Shape: docs/CONTRACTS.md, "UI state".
// Everything is written with textContent, never innerHTML, because log lines come from other systems.
window.ColdTrace = (() => {
  const $ = id => document.getElementById(id)
  const STALE_AFTER_MS = 3000

  // Plain language for each ledger action. Unknown actions fall back to their name.
  const ACTIONS = {
    set_quarantine: 'Ask the hospital to hold the shipment in quarantine on arrival',
    reserve_storage: 'Reserve a qualified cold storage bay for the layover',
    rebook_carrier: 'Book the shipment onto the new route',
    notify_hospital: 'Tell the hospital the new arrival time',
  }
  const STATUS = {
    planned: () => 'Waiting',
    sent: () => 'Sent, checking',
    verified: s => 'Confirmed by ' + s.system,
    failed: () => 'Did not take effect',
    skipped: () => 'No longer needed',
  }
  const SYSTEM_ORDER = ['carrier', 'warehouse', 'hospital', 'agent']

  let lastOk = 0, everOk = false, seenLog = 0, editing = false, currentProposal = null

  function el(tag, cls, text) {
    const n = document.createElement(tag)
    if (cls) n.className = cls
    if (text !== undefined && text !== null) n.textContent = text
    return n
  }

  function fmtBudget(min) {
    if (min === null || min === undefined) return '--'
    const m = Math.max(0, Math.round(min)), h = Math.floor(m / 60)
    return h ? `${h} h ${String(m % 60).padStart(2, '0')} min` : `${m} min`
  }

  function renderTiles(st) {
    const ship = st.shipment || {}, c = st.counters || {}
    $('shipment-id').textContent = ship.shipment_id || '--'
    const pill = $('shipment-status')
    pill.textContent = (ship.status || 'unknown').replace(/_/g, ' ')
    pill.className = 'pill ' + (ship.status || '')

    const min = ship.budget_remaining_min
    $('budget').textContent = fmtBudget(min)
    $('budget-tile').className = 'tile ' + (min == null ? '' : min >= 120 ? 'ok' : min >= 60 ? 'warn' : 'bad')

    const d = c.duplicate_actions
    $('dupes').textContent = d == null ? '--' : String(d)
    $('dupes-tile').className = 'tile ' + (d === 0 ? 'zero' : d > 0 ? 'some' : '')
    $('dupes-hint').textContent = d > 0
      ? 'Something was done more than once. Check the log.'
      : 'Counted from the warehouse and carrier, not from the agent'

    const done = c.steps_verified || 0, total = c.steps_total || 0
    $('verified').textContent = total ? `${done} of ${total}` : 'No plan'
    $('verified-bar').style.width = total ? (100 * done / total) + '%' : '0'
  }

  function renderSteps(steps) {
    const list = $('steps')
    list.replaceChildren()
    if (!steps || !steps.length) {
      list.append(el('li', 'empty', 'No recovery plan yet. The agent writes its plan here as soon as a disruption starts.'))
      return
    }
    for (const s of steps) {
      const li = el('li', 'step ' + (s.status || 'planned'))
      li.append(el('div', 'num', s.seq))
      const body = el('div')
      body.append(el('div', 'what', ACTIONS[s.action] || (s.action || '').replace(/_/g, ' ')))
      const why = el('div', 'why')
      why.append(el('span', 'chip', s.system || ''))
      if (s.reason) why.append(document.createTextNode(s.reason))
      body.append(why)
      li.append(body)
      li.append(el('div', 'status', (STATUS[s.status] || (() => s.status))(s)))
      list.append(li)
    }
  }

  function systemDetail(name, s) {
    if (name === 'carrier') return [s.schema_version === 2 ? 'New API format (v2)' : 'API format v1', s.schema_version === 2]
    if (name === 'warehouse') return [`${s.reservations ?? 0} reservation${s.reservations === 1 ? '' : 's'} held`, false]
    if (name === 'agent') return [s.alive ? `${s.worker || 'worker'} running` : (s.worker ? `${s.worker} not responding` : 'Not running'), !s.alive]
    return [s.ok ? 'Receiving updates' : 'Not reachable', false]
  }

  function renderSystems(systems) {
    const box = $('systems')
    box.replaceChildren()
    for (const name of SYSTEM_ORDER) {
      const s = (systems || {})[name] || {}
      const ok = name === 'agent' ? s.alive : s.ok
      const card = el('div', 'sys ' + (ok ? 'ok' : 'down'))
      card.append(el('div', 'name', name))
      const [text, flag] = ok || name === 'agent' ? systemDetail(name, s) : ['Not reachable', false]
      card.append(el('div', 'detail' + (flag ? ' flag' : ''), text))
      box.append(card)
    }
  }

  function renderProposal(p) {
    const box = $('proposal')
    if (!p) { box.hidden = true; currentProposal = null; editing = false; return }
    if (currentProposal && currentProposal.proposal_id === p.proposal_id) return  // keep any edit in progress
    currentProposal = p
    box.hidden = false
    $('proposal-summary').textContent = p.summary || `The ${p.system || 'system'} answered in a shape the agent does not know.`
    $('proposal-memory').textContent = p.memory_hit
      ? `Based on a similar past incident: "${p.memory_hit}"` + (p.score != null ? ` (match ${Number(p.score).toFixed(2)})` : '')
      : ''
    const tbody = $('proposal-map')
    tbody.replaceChildren()
    const map = (p.fix && p.fix.map) || {}
    for (const [from, to] of Object.entries(map)) {
      const tr = el('tr')
      tr.append(el('td', null, from), el('td', null, to))
      tbody.append(tr)
    }
    if (!Object.keys(map).length) {
      const tr = el('tr'), td = el('td', null, JSON.stringify(p.fix || {}))
      td.colSpan = 2; tr.append(td); tbody.append(tr)
    }
    $('proposal-edit').hidden = true
    $('proposal-edit').value = JSON.stringify(p.fix || {}, null, 2)
    $('correct').textContent = 'Correct it'
    $('approve').textContent = 'Approve'
    $('proposal-error').textContent = ''
  }

  function renderLog(log) {
    const list = $('log')
    const atBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 40
    list.replaceChildren()
    if (!log || !log.length) { list.append(el('li', 'empty', 'Nothing has happened yet.')); return }
    log.forEach((line, i) => {
      const li = el('li', i >= seenLog && seenLog ? 'new' : '')
      li.append(el('span', 'ts', line.ts), el('span', 'msg', line.message))
      list.append(li)
    })
    seenLog = log.length
    if (atBottom) list.scrollTop = list.scrollHeight
  }

  function setConnection(state, text) {
    $('live').className = 'live ' + state
    $('live-text').textContent = text
  }

  function checkStale() {
    if (!everOk) return  // the first failure is handled in poll()
    const age = Date.now() - lastOk
    $('error-banner').hidden = age <= STALE_AFTER_MS * 3
    const stale = age > STALE_AFTER_MS
    $('stale-banner').hidden = !stale
    if (stale) {
      $('stale-banner').textContent = `Data is ${Math.round(age / 1000)} seconds old. The numbers may have changed.`
      setConnection(age > STALE_AFTER_MS * 3 ? 'off' : 'stale', 'Out of date')
    }
  }

  async function poll() {
    try {
      const res = await fetch('/state', { cache: 'no-store' })
      if (!res.ok) throw new Error('state ' + res.status)
      const st = await res.json()
      lastOk = Date.now(); everOk = true
      $('error-banner').hidden = true
      renderTiles(st); renderSteps(st.steps); renderSystems(st.systems); renderProposal(st.proposal); renderLog(st.log)
      setConnection('on', 'Live, updated just now')
    } catch (e) {
      if (!everOk) { $('error-banner').hidden = false; setConnection('off', 'Not connected') }
    }
    checkStale()
  }

  function toast(text, isError) {
    const t = $('toast')
    t.textContent = text
    t.className = 'toast' + (isError ? ' err' : '')
    clearTimeout(t._timer)
    t._timer = setTimeout(() => { t.textContent = '' }, 6000)
  }

  async function errorText(res) {
    try { const b = await res.json(); return b.detail || b.message || res.statusText } catch { return res.statusText || 'Request failed' }
  }

  function wireChaos() {
    document.querySelectorAll('button[data-event]').forEach(b => {
      b.onclick = async () => {
        b.disabled = true
        try {
          const res = await fetch('/chaos/' + b.dataset.event, { method: 'POST' })
          if (!res.ok) return toast(await errorText(res), true)
          const body = await res.json()
          toast(body.message || (b.querySelector('b').textContent + ' sent'))
          poll()
        } catch { toast('Could not reach the server', true) } finally { b.disabled = false }
      }
    })
  }

  function wireProposal() {
    $('correct').onclick = () => {
      editing = !editing
      $('proposal-edit').hidden = !editing
      $('correct').textContent = editing ? 'Cancel edit' : 'Correct it'
      $('approve').textContent = editing ? 'Save correction' : 'Approve'
    }
    $('approve').onclick = async () => {
      if (!currentProposal) return
      const body = { proposal_id: currentProposal.proposal_id, decision: editing ? 'corrected' : 'approved', by: 'operator' }
      if (editing) {
        try { body.fix = JSON.parse($('proposal-edit').value) } catch { $('proposal-error').textContent = 'The correction is not valid JSON.'; return }
      }
      $('approve').disabled = true
      try {
        const res = await fetch('/approve', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
        if (!res.ok) { $('proposal-error').textContent = await errorText(res); return }
        toast(editing ? 'Correction saved as a rule' : 'Fix approved')
        currentProposal = null; editing = false
        poll()
      } catch { $('proposal-error').textContent = 'Could not reach the server.' } finally { $('approve').disabled = false }
    }
  }

  function start() {
    wireChaos(); wireProposal()
    poll()
    setInterval(poll, 1000)
  }

  return { start }
})()
