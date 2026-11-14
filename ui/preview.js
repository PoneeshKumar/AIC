// Preview mode, loaded only with ?preview. Replaces fetch with a scripted sample run so the screen
// can be designed and rehearsed before the agent exists. The banner on the page says so.
// The network layout (airports, routes, storage) is read from the server, the run itself is scripted.
// ?preview=proposal starts with the carrier fix waiting for approval.
(() => {
  document.getElementById('preview-banner').hidden = false
  const realFetch = window.fetch.bind(window)
  const clock = () => new Date().toTimeString().slice(0, 8)
  const PLAN = [
    ['set_quarantine', 'hospital', 'Held on arrival until a qualified person reviews the excursion'],
    ['reserve_storage', 'warehouse', 'WH-YYC-1 covers the 95 minute Calgary layover'],
    ['rebook_carrier', 'carrier', 'R-YYC leaves the most budget. R-YWG rejected, no free bay in Winnipeg'],
    ['notify_hospital', 'hospital', 'New arrival 18:00 UTC via Calgary'],
  ]
  const s = {
    status: 'in_transit', budget: 480, steps: [], schema: 1, reservations: 0, alive: true, proposal: null,
    pausedUntil: 0, waitingFix: false, ruleStored: false, cancelled: false, booked: false, progress: 0,
    log: [{ ts: clock(), message: 'Shipment BIO-2048 in transit YYZ to YVR on CT118' }],
  }
  const say = m => s.log.push({ ts: clock(), message: m })

  function startPlan() {
    s.status = 'recovering'; s.cancelled = true
    s.steps = PLAN.map(([action, system, reason], i) => ({ seq: i + 1, action, system, status: 'planned', reason }))
    say('Plan ready: 4 steps via R-YYC. R-DIRECT dropped because CT118 is cancelled')
  }

  function tick() {
    if (s.status === 'recovering') s.budget = Math.max(0, s.budget - 1.5)
    if (s.booked && s.progress < 1) s.progress = Math.min(1, s.progress + 0.02)
    if (!s.steps.length || !s.alive || s.waitingFix || Date.now() < s.pausedUntil) return
    const step = s.steps.find(x => x.status === 'planned' || x.status === 'sent')
    if (!step) { if (s.status !== 'recovered') { s.status = 'recovered'; say('All steps confirmed. Shipment rerouted inside the budget') } return }
    if (step.status === 'planned') { step.status = 'sent'; say(`Sent ${step.action} to the ${step.system}`); return }
    if (step.action === 'rebook_carrier' && s.schema === 2 && !s.ruleStored) {
      s.waitingFix = true
      s.proposal = {
        proposal_id: 'preview', system: 'carrier',
        summary: 'The carrier tracking response no longer has shipment_status or eta at the top level. The agent proposes this mapping.',
        fix: { map: { shipment_status: 'tracking.state', eta: 'tracking.estimated_arrival_epoch' }, transform: { eta: 'epoch_seconds_to_iso' } },
        memory_hit: 'Carrier tracking fields moved under a tracking object and the time became epoch seconds', score: 0.91,
      }
      say('Carrier read failed on unknown fields. Memory match 0.91. Proposal waiting for approval')
      return
    }
    step.status = 'verified'
    if (step.action === 'reserve_storage') s.reservations = 1
    if (step.action === 'rebook_carrier') s.booked = true
    say(`Verified ${step.action}: the ${step.system} confirmed it on a separate read`)
  }

  function chaos(event) {
    if (event === 'cancel_flight') { if (s.cancelled) return 'Flight CT118 is already cancelled'; say('Chaos: flight CT118 cancelled'); startPlan(); return 'Flight CT118 cancelled' }
    if (event === 'kill_agent') {
      s.alive = false; say('Chaos: agent process killed')
      setTimeout(() => {
        s.alive = true; s.pausedUntil = Date.now() + 1500
        say('Agent restarted. Resume: reading every sent step before acting')
        const sent = s.steps.find(x => x.status === 'sent')
        if (sent) say(`Resume: the ${sent.system} already shows ${sent.action}. Not sending it again`)
      }, 3000)
      return 'Agent killed. It restarts in 3 seconds'
    }
    if (event === 'change_carrier') { s.schema = 2; say('Chaos: carrier switched to API v2'); return 'Carrier switched to API v2' }
    say('Chaos: the warehouse dropped a response. The agent read the reservations instead of retrying')
    return 'The warehouse dropped a response'
  }

  // A short sample history so the budget chart has a line from the first frame.
  const now = Date.now()
  window.__previewHistory = Array.from({ length: 30 }, (_, i) => ({ t: now - (30 - i) * 2000, v: 480 }))

  if (new URLSearchParams(location.search).get('preview') === 'proposal') {
    startPlan(); s.schema = 2
    window.__previewHistory = Array.from({ length: 60 }, (_, i) => ({ t: now - (60 - i) * 2000, v: i < 12 ? 480 : 480 - (i - 12) * 1.6 }))
    s.budget = window.__previewHistory[59].v
    s.steps[0].status = 'verified'; s.steps[1].status = 'verified'; s.reservations = 1
    say('Verified set_quarantine: the hospital confirmed it on a separate read')
    say('Verified reserve_storage: the warehouse confirmed it on a separate read')
    say('Chaos: carrier switched to API v2')
    s.steps[2].status = 'sent'
    tick()
  }
  setInterval(tick, 1500)

  const json = (body, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))
  window.fetch = async (url, opts = {}) => {
    if (url === '/network') {
      const net = await (await realFetch('/network')).json()
      for (const r of net.routes) r.status = r.original && s.cancelled ? 'cancelled' : r.route_id === 'R-YYC' && s.booked ? 'booked' : 'available'
      for (const st of net.storage) if (st.city === 'YYC') st.bays_free = 2 - s.reservations
      net.booked_route_id = s.booked ? 'R-YYC' : null
      net.shipment_position = s.booked ? { route_id: 'R-YYC', progress: s.progress } : { route_id: 'R-DIRECT', progress: 0 }
      return json(net)
    }
    if (url === '/state') {
      const done = s.steps.filter(x => x.status === 'verified').length
      return json({
        shipment: { shipment_id: 'BIO-2048', status: s.status, budget_remaining_min: Math.round(s.budget) },
        counters: { duplicate_actions: 0, steps_verified: done, steps_total: s.steps.length },
        steps: s.steps,
        systems: {
          carrier: { ok: true, schema_version: s.schema }, warehouse: { ok: true, reservations: s.reservations },
          hospital: { ok: true }, agent: { worker: 'worker-1', alive: s.alive },
        },
        proposal: s.proposal, log: s.log.slice(-40),
      })
    }
    if (url.startsWith('/chaos/')) return json({ message: chaos(url.slice(7)) })
    if (url === '/approve') {
      const body = JSON.parse(opts.body)
      s.proposal = null; s.waitingFix = false; s.ruleStored = true
      say(body.decision === 'corrected' ? 'Operator corrected the mapping. Stored as a rule' : 'Operator approved the mapping. Stored as a rule for the carrier')
      return json({ status: body.decision })
    }
    return json({ detail: 'not available in preview' }, 404)
  }
})()
