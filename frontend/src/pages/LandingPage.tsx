import { Link } from 'react-router-dom'
import { BrandMark } from '../components/BrandMark'

const benefits = [
  { number: '01', title: 'See what needs attention', body: 'A simple case list shows the amount, deadline, missing proof, and next step for every dispute.' },
  { number: '02', title: 'Bring your proof together', body: 'Keep invoices, order details, delivery records, and staff replies linked to the right case.' },
  { number: '03', title: 'Respond with confidence', body: 'Review the evidence, approve the response, and follow the submission through to its receipt.' },
]

export function LandingPage() {
  return (
    <div className="landing">
      <section className="landing-hero" aria-labelledby="landing-title">
        <div className="landing-copy">
          <span className="landing-kicker"><span aria-hidden="true" /> Made for busy shop owners</span>
          <h1 id="landing-title">A payment dispute? <em>Know your next step.</em></h1>
          <p>ProofSaathi keeps your proof, deadlines, and response in one clear place, so you can get back to running your shop.</p>
          <div className="landing-actions">
            <Link className="button-primary" to="/cases">View disputes <span aria-hidden="true">→</span></Link>
            <Link className="button-secondary" to="/dashboard">Explore dashboard</Link>
          </div>
          <div className="landing-assurance"><span aria-hidden="true">✓</span> One case at a time. Every step clearly explained.</div>
        </div>

        <div className="landing-preview" aria-label="Example dispute summary">
          <div className="preview-window">
            <div className="preview-top"><BrandMark className="preview-brand-mark" /><span>ProofSaathi</span><span className="preview-top-right">CASE OVERVIEW</span></div>
            <div className="preview-case">
              <span className="preview-overline">EXAMPLE DISPUTE</span>
              <div className="preview-case-title"><strong>Order payment disputed</strong><span className="preview-pill">Needs attention</span></div>
              <p>Metro Furniture Demo · Order ORD-DEMO-18500</p>
              <div className="preview-facts"><div><small>Amount at risk</small><strong>₹18,500</strong></div><div><small>Next step</small><strong>Collect delivery proof</strong></div></div>
            </div>
            <div className="preview-steps">
              <div><span className="preview-step-dot complete">✓</span><span><strong>Invoice linked</strong><small>Proof is available in the case</small></span></div>
              <div><span className="preview-step-dot active">2</span><span><strong>Delivery record needed</strong><small>Ask the right staff member for help</small></span></div>
              <div><span className="preview-step-dot">3</span><span><strong>Review and respond</strong><small>Check the evidence before submission</small></span></div>
            </div>
          </div>
          <div className="preview-floating"><span aria-hidden="true">✓</span><div><strong>Your next step is clear</strong><small>Open the case to see what to do</small></div></div>
        </div>
      </section>

      <section id="how-it-works" className="landing-process" aria-labelledby="process-title">
        <div className="landing-section-head">
          <p className="eyebrow">How ProofSaathi helps</p>
          <h2 id="process-title">From a new dispute to a clear response.</h2>
          <p>No complicated reports to decode. Start with the dispute, see what is missing, and move through each step.</p>
        </div>
        <div className="landing-stage-grid">
          {benefits.map((benefit) => (
            <article className="landing-stage" key={benefit.number}>
              <span>{benefit.number}</span>
              <h3>{benefit.title}</h3>
              <p>{benefit.body}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="landing-final">
        <div><p className="eyebrow">Your workspace</p><h2>See every dispute in one place.</h2><p>Open a case to view its checklist, evidence, staff replies, and next action.</p></div>
        <Link className="button-primary" to="/cases">Open disputes <span aria-hidden="true">→</span></Link>
      </section>
    </div>
  )
}
