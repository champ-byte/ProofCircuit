import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { BrandMark } from '../components/BrandMark'

const benefits = ['b1', 'b2', 'b3'] as const

export function LandingPage() {
  const { t } = useTranslation()
  return (
    <div className="landing">
      <section className="landing-hero" aria-labelledby="landing-title">
        <div className="landing-copy">
          <span className="landing-kicker"><span aria-hidden="true" /> {t('landing.kicker')}</span>
          <h1 id="landing-title">{t('landing.titleA')} <em>{t('landing.titleB')}</em></h1>
          <p>{t('landing.body')}</p>
          <div className="landing-actions">
            <Link className="button-primary" to="/cases">{t('app.viewDisputes')} <span aria-hidden="true">→</span></Link>
            <Link className="button-secondary" to="/dashboard">{t('landing.exploreDashboard')}</Link>
          </div>
          <div className="landing-assurance"><span aria-hidden="true">✓</span> {t('landing.assurance')}</div>
        </div>

        <div className="landing-preview" aria-label={t('landing.previewLabel')}>
          <div className="preview-window">
            <div className="preview-top"><BrandMark className="preview-brand-mark" /><span>ProofSaathi</span><span className="preview-top-right">{t('landing.caseOverview')}</span></div>
            <div className="preview-case">
              <span className="preview-overline">{t('landing.exampleDispute')}</span>
              <div className="preview-case-title"><strong>{t('landing.orderDisputed')}</strong><span className="preview-pill">{t('landing.needsAttention')}</span></div>
              <p>Metro Furniture Demo · Order ORD-DEMO-18500</p>
              <div className="preview-facts"><div><small>{t('landing.amountAtRisk')}</small><strong>₹18,500</strong></div><div><small>{t('landing.nextStep')}</small><strong>{t('landing.collectProof')}</strong></div></div>
            </div>
            <div className="preview-steps">
              <div><span className="preview-step-dot complete">✓</span><span><strong>{t('landing.invoiceLinked')}</strong><small>{t('landing.invoiceLinkedSub')}</small></span></div>
              <div><span className="preview-step-dot active">2</span><span><strong>{t('landing.deliveryNeeded')}</strong><small>{t('landing.deliveryNeededSub')}</small></span></div>
              <div><span className="preview-step-dot">3</span><span><strong>{t('landing.reviewRespond')}</strong><small>{t('landing.reviewRespondSub')}</small></span></div>
            </div>
          </div>
          <div className="preview-floating"><span aria-hidden="true">✓</span><div><strong>{t('landing.clearTitle')}</strong><small>{t('landing.clearSub')}</small></div></div>
        </div>
      </section>

      <section id="how-it-works" className="landing-process" aria-labelledby="process-title">
        <div className="landing-section-head">
          <p className="eyebrow">{t('landing.howEyebrow')}</p>
          <h2 id="process-title">{t('landing.howTitle')}</h2>
          <p>{t('landing.howBody')}</p>
        </div>
        <div className="landing-stage-grid">
          {benefits.map((key, index) => (
            <article className="landing-stage" key={key}>
              <span>{String(index + 1).padStart(2, '0')}</span>
              <h3>{t(`landing.${key}Title`)}</h3>
              <p>{t(`landing.${key}Body`)}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="landing-final">
        <div><p className="eyebrow">{t('landing.finalEyebrow')}</p><h2>{t('landing.finalTitle')}</h2><p>{t('landing.finalBody')}</p></div>
        <Link className="button-primary" to="/cases">{t('landing.openDisputes')} <span aria-hidden="true">→</span></Link>
      </section>
    </div>
  )
}
