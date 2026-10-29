// Browser E2E for the hero journey and the reviewer concession, driven only through the UI and
// demo drawer (PRD 15.1: one browser E2E for the main journey).
//
// Prerequisites: backend on :8000 and Vite on :5173 (see README). The run is deterministic manual
// mode; it refuses to run when the live agent is active (it would spend model quota and change
// the flow) unless E2E_ALLOW_LIVE=1. It resets demo data through the drawer.
//
//   npm run e2e                      # headless; screenshots go to ../docs/
//   PC_CHROMIUM=/path/to/chrome npm run e2e   # if the bundled browser is not found
import { mkdirSync } from 'node:fs'
import { chromium } from 'playwright'

const BASE = process.env.E2E_BASE_URL ?? 'http://127.0.0.1:5173'
const SHOTS = new URL('../../docs/', import.meta.url).pathname
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

try {
  const health = await (await fetch(`${BASE}/api/health`)).json()
  assert(health.reasoning_mode.mode !== 'live' || process.env.E2E_ALLOW_LIVE === '1',
    'live agent is active; start the backend with AGENT_AUTORUN=false or set E2E_ALLOW_LIVE=1')

  // --- Reset through the drawer ---------------------------------------------------------
  await page.goto(`${BASE}/cases`)
  await page.click('text=DSP-DEMO-001')
  await page.waitForSelector('[data-testid=status-banner]')
  await tab('Seed / reset')
  await page.check('text=I understand this deletes all demo data')
  await click('Reset demo data')
  await waitBanner('Collecting evidence')
  assert((await page.innerText('.badges')).includes('Synthetic data'), 'synthetic badge')
  assert((await page.innerText('.case-header')).includes('₹18,500.00'), 'amount at risk in header')

  // --- Hero: missing -> wrong -> correct -> verified --------------------------------------
  await click('Request delivery proof from staff')
  await waitBanner('Waiting for staff evidence')
  await tab('Staff inbox')
  await page.waitForSelector('.msg[lang=mr]')
  assert((await page.innerText('.msg[lang=mr]')).includes('पावती'), 'Marathi request in staff inbox')
  await click('Upload delivery receipt wrong order')
  await waitBanner('Submission blocked: contradiction found')
  const compare = await page.innerText('.compare')
  assert(compare.includes('ORD-DEMO-18500') && compare.includes('ORD-DEMO-OTHER'), 'side-by-side order IDs')
  await page.click('.finding-blocking button:has-text("Open source")')
  await page.waitForSelector('mark.focus')
  assert((await page.innerText('mark.focus')) === 'ORD-DEMO-OTHER', 'source opens at the cited span')
  await page.screenshot({ path: `${SHOTS}m4-blocked.png`, fullPage: true })

  await click('Request delivery proof from staff')
  await waitBanner('Waiting for staff evidence')
  await tab('Staff inbox')
  await click('Upload delivery receipt correct')
  await waitBanner('Evidence complete — ready to submit')
  await click('Build evidence pack')
  await page.waitForSelector('text=Pack v1')
  await tab('Fault injector')
  await click('Lose response after accepting (504)')
  await page.waitForSelector('text=action:drop_response_after')
  await click('Submit defense (simulator)')
  await waitBanner('Submission verified — dispute outcome pending')
  const steps = await page.innerText('.steps')
  for (const s of ['Observed gap', 'Evidence requested', 'Staff response', 'Contradiction detected', 'Pack built',
    'Submission requested', 'Receipt verified']) assert(steps.includes(s), `key step "${s}"`)
  const trail = await page.innerText('#pack-h ~ table')
  assert(trail.includes('action_response:unknown → reconcile') && trail.includes('verified'), 'lost response reconciled')
  await page.screenshot({ path: `${SHOTS}m4-verified.png`, fullPage: true })

  // --- Reviewer: concession needs approval + typed confirmation ------------------------------
  await tab('Seed / reset')
  await page.check('text=I understand this deletes all demo data')
  await click('Reset demo data')
  await waitBanner('Collecting evidence')
  await tab('Identity')
  await click('Ravi (Reviewer)')
  await page.waitForSelector('#reviewer-h')
  await click("Accept customer's dispute (concede)…")
  await page.waitForSelector('[role=dialog]')
  assert((await page.innerText('[role=dialog]')).includes('₹18,500.00'), 'modal shows the amount')
  await page.fill('[role=dialog] textarea', 'Customer evidence is credible; concede (synthetic demo).')
  await click('Step 1: approve concession')
  await page.waitForSelector('text=Type CONCEDE to confirm')
  assert(await page.isDisabled('button:has-text("Step 2")'), 'step 2 disabled until typed')
  await page.fill('[role=dialog] input', 'CONCEDE')
  await click("Step 2: accept customer's dispute (concede)")
  await waitBanner('Dispute closed — provider reports LOST')
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
