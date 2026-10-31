// Browser E2E for the hero journey and the reviewer concession, driven only through the UI
// (PRD 15.1: one browser E2E for the main journey). Each person signs in on /signin and sees only
// their own screens: Asha (owner) works the case, Sanjay (staff) answers on /staff, Ravi
// (reviewer) decides on /review. Reset and fault injection use the presenter's /operator page.
//
// Prerequisites: backend on :8000 and Vite on :5173 (see README). The run is deterministic manual
// mode; it refuses to run when the live agent is active (it would spend model quota and change
// the flow) unless E2E_ALLOW_LIVE=1. It resets demo data through /operator.
//
//   npm run e2e                      # headless; screenshots go to ../docs/
//   PC_CHROMIUM=/path/to/chrome npm run e2e   # if the bundled browser is not found
import { mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'

const BASE = process.env.E2E_BASE_URL ?? 'http://127.0.0.1:5173'
const SHOTS = fileURLToPath(new URL('../../docs/', import.meta.url)) // .pathname breaks on Windows (/C:/...)
mkdirSync(SHOTS, { recursive: true })

const log = (...a) => console.log('•', ...a)
function assert(cond, message) {
  if (!cond) throw new Error(`Assertion failed: ${message}`)
}

const browser = await chromium.launch(process.env.PC_CHROMIUM ? { executablePath: process.env.PC_CHROMIUM } : {})
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
const errors = []
page.on('pageerror', (e) => errors.push(String(e)))
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
page.on('response', (r) => r.status() >= 400 && console.log('HTTP', r.status(), r.request().method(), new URL(r.url()).pathname))

const banner = () => page.locator('[data-testid=status-banner]').innerText()
async function waitBanner(text, timeout = 30000) {
  await page.waitForFunction(
    (t) => document.querySelector('[data-testid=status-banner]')?.textContent?.includes(t),
    text,
    { timeout },
  )
  log('banner:', text)
}
const tab = (name) => page.click(`[role=tab]:has-text("${name}")`)
const click = (label) => page.click(`button:has-text("${label}")`)

// Sign in through the header's "Switch user" (or /signin directly when nobody is signed in).
async function signIn(name, home) {
  if (await page.isVisible('header a:has-text("Switch user")')) await page.click('header a:has-text("Switch user")')
  else await page.goto(`${BASE}/signin`)
  await page.waitForSelector('.signin')
  await click(`Sign in as ${name}`)
  await page.waitForURL((u) => u.pathname === home)
  log('signed in:', name)
}
async function asOwner() {
  await signIn('Asha', '/cases')
  await page.click('text=DSP-DEMO-001')
  await page.waitForSelector('[data-testid=status-banner]')
}
async function asStaff() {
  await signIn('Sanjay', '/staff')
  await page.waitForSelector('.staff-case')
}
async function staffDid(action) {
  await action()
  await page.waitForSelector('.staff-message')
}

// Simple view must not show hashes, code points, internal state or tool names, rule IDs, model or
// simulator labels. Real file names (delivery_receipt_correct.txt) are allowed.
const TECHNICAL = [/\b[a-z]+_[a-z_]+\b/, /\b[A-Z]{2,}_[A-Z_]{2,}\b/, /sha-?256/i, /code point/i, /gemini/i, /reconcil/i, /\bsimulator\b/i, /\bpack\b/i, /testimony/i, /\bconcede\b/i]
async function assertPlain(when) {
  for (const name of ['Next step', 'Proof', 'Response', 'History']) {
    await tab(name)
    const text = (await page.innerText('main')).replace(/\S+\.(txt|json|pdf|png|jpe?g|wav|ogg|webm|html)\b/g, '')
    for (const re of TECHNICAL) {
      const hit = text.match(re)
      assert(!hit, `simple view (${when}, ${name} tab) shows technical text "${hit?.[0]}"`)
    }
  }
  log('simple view is plain:', when)
}

// A reset reseeds the hero case under a new ID and re-issues every session.
async function resetDemo() {
  await page.click('footer a:has-text("Demo controls")')
  await page.waitForURL((u) => u.pathname === '/operator')
  await tab('Seed / reset')
  await page.check('text=I understand this deletes all demo data')
  await click('Reset demo data')
  await page.waitForSelector('[data-testid=reset-done]')
  await page.waitForSelector('#demo-controls')
  log('demo data reset')
}
async function operatorTab(name) {
  await page.click('footer a:has-text("Demo controls")')
  await page.waitForURL((u) => u.pathname === '/operator')
  await page.waitForSelector('#demo-controls')
  await tab(name)
}

try {
  const health = await (await fetch(`${BASE}/api/health`)).json()
  assert(health.reasoning_mode.mode !== 'live' || process.env.E2E_ALLOW_LIVE === '1',
    'live agent is active; start the backend with AGENT_AUTORUN=false or set E2E_ALLOW_LIVE=1')

  // --- Sign-in: language first, then only the four demo people --------------------------------
  await page.goto(`${BASE}/cases`)
  await page.waitForURL((u) => u.pathname === '/signin')
  await page.waitForSelector('#welcome-title')
  await click('Continue')
  await page.waitForSelector('.signin')
  const people = await page.innerText('.signin')
  for (const name of ['Asha', 'Sanjay', 'Meera', 'Ravi']) assert(people.includes(`Sign in as ${name}`), `sign-in offers ${name}`)
  for (const hidden of ['Eval', 'Other Owner', 'Operator']) assert(!people.includes(hidden), `sign-in hides ${hidden}`)
  assert((await page.locator('#demo-identity').count()) === 0, 'no "Viewing as" dropdown')
  await signIn('Asha', '/cases')
  assert((await page.innerText('#signed-in-user')) === 'Asha · Shop owner', 'header names the signed-in owner')
  assert((await page.innerText('.mainnav')).replace(/\s+/g, ' ').trim() === 'Dashboard Disputes', 'owner nav')

  // --- Reset through the operator page -----------------------------------------------------
  await resetDemo()
  await page.click('.mainnav a:has-text("Disputes")')
  await page.click('text=DSP-DEMO-001')
  await page.waitForSelector('[data-testid=status-banner]')
  await waitBanner('Collecting proof')
  const caseUrl = page.url()
  assert((await page.innerText('.badges')).includes('Synthetic data'), 'synthetic badge')
  assert((await page.innerText('.case-header')).includes('₹18,500.00'), 'amount at risk in header')
  assert((await page.locator('#reviewer-h, #demo-drawer').count()) === 0, 'owner sees no reviewer panel or demo drawer')

  // --- Hero: missing -> wrong -> correct -> verified --------------------------------------
  assert((await page.innerText('.case-progress')).includes('Collect proof'), 'three-stage progress')
  await tab('Response')
  await click('Ask staff for delivery proof')
  await waitBanner('Waiting for staff to send proof')

  await asStaff()
  assert((await page.innerText('.mainnav')).trim() === 'My requests', 'staff nav')
  await page.waitForSelector('.msg[lang=mr]')
  assert((await page.innerText('.msg[lang=mr]')).includes('पावती'), 'Marathi request on the staff screen')
  await staffDid(() => click('Upload delivery receipt wrong order'))
  await page.goto(caseUrl)
  await page.waitForURL((u) => u.pathname === '/staff')
  log('staff redirected away from the case page')

  await asOwner()
  await waitBanner("Blocked: a document doesn't match the order")
  await tab('Next step')
  const compare = await page.innerText('.compare')
  assert(compare.includes('ORD-DEMO-18500') && compare.includes('ORD-DEMO-OTHER'), 'side-by-side order IDs')
  await page.click('.finding-blocking button:has-text("See in document")')
  await page.waitForSelector('mark.focus')
  assert((await page.innerText('mark.focus')) === 'ORD-DEMO-OTHER', 'source opens at the cited span')
  await page.screenshot({ path: `${SHOTS}m4-blocked.png`, fullPage: true })
  await assertPlain('blocked')

  await tab('Response')
  await click('Ask staff for delivery proof')
  await waitBanner('Waiting for staff to send proof')

  // Staff voice note: testimony with audio provenance; it explains, it does not prove (M5).
  // Speech-to-text is disabled in this manual E2E, so the labelled human-transcription path runs.
  await asStaff()
  await click('Send demo voice note')
  await page.waitForSelector('.staff-page audio')
  await page.waitForSelector('.staff-page >> text=Speech-to-text unavailable')
  await click('Type what I said (human transcription)')
  await page.fill('.staff-page .voice-actions textarea', 'मी आधी चुकीची पावती पाठवली होती. आता योग्य पावती पाठवत आहे.')
  await page.click('.staff-page .voice-actions button:has-text("Save")')
  await page.waitForSelector('.staff-page .voice-actions textarea', { state: 'detached' })

  await asOwner()
  await tab('Proof')
  await click('Detailed view')
  await page.waitForSelector('section[aria-labelledby=testimony-h] .voice-note >> text=Human transcription typed by Sanjay (Delivery)')
  const testimony = await page.innerText('section[aria-labelledby=testimony-h] .voice-note')
  assert(testimony.includes('Confirmed by Sanjay (Delivery)') && testimony.includes('not a delivery document'),
    'testimony panel shows confirmation and the not-proof caveat')
  assert(testimony.includes('answers delivery record request round 2'), 'voice note linked to the open request')
  assert(!(await banner()).includes('ready to send'), 'testimony alone does not make the case ready')
  await page.screenshot({ path: `${SHOTS}m5-testimony-manual.png`, fullPage: true })
  await click('Simple view')

  await asStaff()
  await staffDid(() => click('Upload delivery receipt correct'))
  await asOwner()
  await waitBanner('All proof is in — ready to send')
  await tab('Response')
  await click('Prepare response file')
  await page.waitForSelector('text=Response file v1')
  await operatorTab('Fault injector')
  await click('Lose response after accepting (504)')
  await page.waitForSelector('text=action:drop_response_after')
  await page.click('.mainnav a:has-text("Disputes")')
  await page.click('text=DSP-DEMO-001')
  await tab('Response')
  await click('Send response')
  await waitBanner('Paytm received your response')
  await tab('History')
  const steps = await page.innerText('.steps')
  for (const s of ['Missing proof found', 'Proof requested', 'Staff replied', 'Mismatch found', 'Staff voice note',
    'Voice note confirmed', 'Response file prepared', 'Response sent', 'Paytm receipt checked']) assert(steps.includes(s), `key step "${s}"`)
  await assertPlain('verified')
  await tab('Response')
  await click('Detailed view')
  const trail = await page.innerText('#pack-h ~ table')
  assert(trail.includes('action_response:unknown → reconcile') && trail.includes('verified'), 'lost response reconciled')
  await page.screenshot({ path: `${SHOTS}m4-verified.png`, fullPage: true })
  await click('Simple view')

  // --- Reviewer: the owner asks for review; Ravi decides on /review --------------------------
  await resetDemo()
  await page.click('.mainnav a:has-text("Disputes")')
  await page.click('text=DSP-DEMO-001')
  await tab('Response')
  await click('Ask a reviewer')
  await waitBanner('A reviewer needs to decide')
  await signIn('Ravi', '/review')
  assert((await page.innerText('.mainnav')).trim() === 'Cases to review', 'reviewer nav')
  await page.goto(`${BASE}/cases`)
  await page.waitForURL((u) => u.pathname === '/review')
  await page.click('.review-item a:has-text("Open case")')
  await page.waitForSelector('#reviewer-h')
  assert((await page.locator('#actions-h, .assistant-card').count()) === 0, 'reviewer sees no owner actions')
  await click("Accept customer's claim…")
  await page.waitForSelector('[role=dialog]')
  assert((await page.innerText('[role=dialog]')).includes('₹18,500.00'), 'modal shows the amount')
  await page.fill('[role=dialog] textarea', 'Customer evidence is credible; concede (synthetic demo).')
  await click('Step 1: approve accepting the claim')
  await page.waitForSelector('text=Type ACCEPT to confirm')
  assert(await page.isDisabled('button:has-text("Step 2")'), 'step 2 disabled until typed')
  await page.fill('[role=dialog] input', 'ACCEPT')
  await click("Step 2: accept customer's claim")
  await waitBanner('Dispute closed — you lost')
  await page.screenshot({ path: `${SHOTS}m4-conceded.png`, fullPage: true })

  // --- Phone width: no horizontal page scroll -------------------------------------------------
  await page.setViewportSize({ width: 390, height: 900 })
  await page.waitForTimeout(300)
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  assert(overflow <= 0, `no horizontal scroll at 390px (overflow ${overflow}px)`)
  await page.screenshot({ path: `${SHOTS}m4-mobile.png`, fullPage: false })

  assert(errors.length === 0, `no page errors: ${errors.join(' | ')}`)
  log('E2E passed')
} catch (err) {
  console.error('E2E FAILED:', err.message, '\nbanner was:', await banner().catch(() => '?'))
  await page.screenshot({ path: `${SHOTS}m4-e2e-failure.png`, fullPage: true }).catch(() => undefined)
  process.exitCode = 1
} finally {
  await browser.close()
}
