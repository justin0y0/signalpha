import { PageHead } from '../components/PageHead'
import { useT } from '../i18n'
import './LegalPage.css'

/**
 * Terms, privacy and risk — in plain language, one page.
 *
 * The site trades in people's brokerage accounts (Autopilot), stores the tokens that let it
 * do so, and publishes strategy numbers; each of those needs to be said clearly before
 * anyone is invited. This is not a substitute for counsel — the owner should have it
 * reviewed — but every statement on it is true of the code as it runs.
 */
const SECTIONS = ['what', 'advice', 'risk', 'auto', 'brokers', 'data', 'privacy', 'liability', 'contact'] as const

export function LegalPage() {
  const { t } = useT()
  return (
    <div className="page-stack legal">
      <PageHead kicker={t('legal.kicker')} title={<>{t('legal.h.a')} <em>{t('legal.h.b')}</em></>} lede={t('legal.lede')} spike={0.3} />
      <p className="legal__date">{t('legal.updated')}</p>
      {SECTIONS.map((k) => (
        <section key={k} className="legal__sec" id={k}>
          <h2>{t(`legal.${k}.h` as 'legal.what.h')}</h2>
          {t(`legal.${k}.p` as 'legal.what.p').split('\n').map((para, i) => <p key={i}>{para}</p>)}
        </section>
      ))}
    </div>
  )
}
