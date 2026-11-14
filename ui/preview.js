// Preview mode, loaded only with ?preview. Replaces fetch with a scripted sample run so the screen
// can be designed and rehearsed before the agent exists. The banner on the page says so.
// ?preview=proposal starts with the carrier fix waiting for approval.
(() => {
  document.getElementById('preview-banner').hidden = false
  const t0 = Date.now()
  const clock = () => new Date().toTimeString().slice(0, 8)
  const PLAN = [
    ['set_quarantine', 'hospital', 'Hold on arrival until a qualified person reviews the excursion'],
    ['reserve_storage', 'warehouse', 'WH-YYC-1 covers the 95 min layover in Calgary, so it does not use the budget'],
    ['rebook_carrier', 'carrier', 'R-YYC leaves the most budget. R-YWG rejected: no free bay in Winnipeg'],
    ['notify_hospital', 'hospital', 'New arrival 18:00 UTC via Calgary'],
  ]
  const s = {
    status: 'in_transit', budget: 480, steps: [], log: [{ ts: clock(), message: 'Shipment BIO-2048 in transit YYZ to YVR on CT118' }],
    schema: 1, reservations: 0, alive: true, proposal: null, cursor: 0, pausedUntil: 0, waitingFix: false,
  }
  const say = m => s.log.push({ ts: clock(), message: m })

  function startPlan() {
    s.status = 'recovering'
    s.steps = PLAN.map(([action, system, reason], i) => ({ seq: i + 1, action, system, status: 'planned', reason }))
    say('Plan: 4 steps via R-YYC. R-DIRECT dropped, its flight was cancelled')
  }

  function tick() {
    if (s.status === 'recovering' || s.status === 'in_transit') s.budget = Math.max(0, s.budget - 0.5)
    if (!s.steps.length || !s.alive || s.waitingFix || Date.now() < s.pausedUntil) return
    const step = s.steps.find(x => x.status === 'planned' || x.status === 'sent')
    if (!step) { if (s.status !== 'recovered') { s.status = 'recovered'; say('All steps confirmed. Shipment rerouted inside the budget') } return }
    if (step.status === 'planned') { step.status = 'sent'; say(`Sent ${step.action} to ${step.system}`); return }
    if (step.action === 'rebook_carrier' && s.schema === 2 && !s.ruleStored) {
      s.waitingFix = true
      s.proposal = {
        proposal_id: 'preview', system: 'carrier', summary: 'The carrier answered in a new shape. shipment_status and eta are missing.',
        fix: { map: { shipment_status: 'tracking.state', eta: 'tracking.estimated_arrival_epoch' } },
        memory_hit: 'Carrier tracking fields moved under a tracking object and the time became epoch seconds', score: 0.91,
      }
      say('Carrier read failed: unknown fields. Memory hit 0.91, fix proposed, waiting for a human')
      return
    }
    step.status = 'verified'
    if (step.action === 'reserve_storage') s.reservations = 1
    say(`Verified ${step.action}: the ${step.system} confirmed it on a separate read`)
  }

  function chaos(event) {
    if (event === 'cancel_flight') { say('Chaos: flight CT118 cancelled'); startPlan(); return 'Flight CT118 cancelled' }
    if (event === 'kill_agent') {
      s.alive = false; say('Chaos: agent killed')
      setTimeout(() => {
        s.alive = true; s.pausedUntil = Date.now() + 1500
        const sent = s.steps.find(x => x.status === 'sent')
        say('Agent restarted. Resume: reading every sent step before acting')
        if (sent) say(`Resume: the ${sent.system} already has ${sent.action}. Not sending it again`)
      }, 3000)
      return 'Agent killed. It restarts in 3 seconds'
    }
    if (event === 'change_carrier') { s.schema = 2; say('Chaos: carrier switched to API v2'); return 'Carrier switched to its new API format' }
    say('Chaos: the warehouse dropped a response. The agent read the reservations instead of retrying')
    return 'The warehouse dropped a response'
  }

  if (new URLSearchParams(location.search).get('preview') === 'proposal') {
    startPlan(); s.budget = 402; s.schema = 2
    s.steps[0].status = 'verified'; s.steps[1].status = 'verified'; s.reservations = 1
    say('Verified set_quarantine: the hospital confirmed it on a separate read')
    say('Verified reserve_storage: the warehouse confirmed it on a separate read')
    say('Chaos: carrier switched to API v2')
    s.steps[2].status = 'sent'
    tick()
  }
  setInterval(tick, 1500)

  const json = (body, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))
  window.fetch = (url, opts = {}) => {
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
      say(body.decision === 'corrected' ? 'Human corrected the fix. Stored as a rule' : 'Human approved the fix. Stored as a rule for the carrier')
      return json({ status: body.decision })
    }
    return json({ detail: 'not in preview' }, 404)
  }
})()
