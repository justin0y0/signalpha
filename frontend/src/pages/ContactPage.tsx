import { useState } from 'react'
import { ArrowUpRight, Check, Copy } from 'lucide-react'
import { PageHead } from '../components/PageHead'
import { useT } from '../i18n'
import './ContactPage.css'

/**
 * Contact — four reasons to write, and a card with the address.
 *
 * This was a tilting 3D card, magnetic buttons and a terminal typing `whoami`. None of
 * it helped anyone send a message. Each reason below opens a draft with its subject
 * already filled in, which does.
 */

const EMAIL = 'justinyu0315@gmail.com'
const LINKEDIN_URL = 'https://www.linkedin.com/in/justin-yu-881727291'
const LINKEDIN_DISPLAY = 'in/justin-yu-881727291'

const REASONS = [
  { k: 'wrong', subject: 'A number on SignAlpha looks wrong' },
  { k: 'role', subject: 'A role that might fit' },
  { k: 'data', subject: 'SignAlpha data / MCP access' },
  { k: 'other', subject: 'Hello' },
] as const

export function ContactPage() {
  const { t } = useT()
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try { await navigator.clipboard.writeText(EMAIL); setCopied(true); setTimeout(() => setCopied(false), 1600) } catch { /* clipboard blocked */ }
  }

  return (
    <div className="page-stack contact">
      <PageHead
        kicker={t('nav.contact')}
        title={<>{t('contact.h.a')} <em>{t('contact.h.b')}</em></>}
        lede={t('contact.h.lede')}
        spike={0.58}
      />

      <div className="contact__grid">
        <ul className="contact-why">
          {REASONS.map((r) => (
            <li key={r.k}>
              <a href={`mailto:${EMAIL}?subject=${encodeURIComponent(r.subject)}`}>
                <b className="serif">{t(`contact.why.${r.k}` as 'contact.why.wrong')}</b>
                <p>{t(`contact.why.${r.k}.d` as 'contact.why.wrong.d')}</p>
                <span className="contact-why__go">{t('contact.why.draft')} <ArrowUpRight size={13} /></span>
              </a>
            </li>
          ))}
        </ul>

        <aside className="paper contact-card">
          <span className="contact-card__kicker">{t('contact.card.kicker')}</span>
          <h2 className="serif">Justin Yu</h2>
          <p className="contact-card__role">{t('contact.card.role')}</p>
          <dl>
            <div>
              <dt>{t('contact.card.email')}</dt>
              <dd>
                <a href={`mailto:${EMAIL}`}>{EMAIL}</a>
                <button type="button" onClick={copy} aria-label={t('contact.card.copy')}>
                  {copied ? <Check size={13} /> : <Copy size={13} />}
                </button>
              </dd>
            </div>
            <div>
              <dt>{t('contact.linkedin')}</dt>
              <dd><a href={LINKEDIN_URL} target="_blank" rel="noreferrer noopener">{LINKEDIN_DISPLAY}</a></dd>
            </div>
            <div>
              <dt>{t('contact.card.where')}</dt>
              <dd>Los Angeles</dd>
            </div>
            <div>
              <dt>{t('contact.card.reply')}</dt>
              <dd>{t('contact.card.reply.v')}</dd>
            </div>
          </dl>
          <span className="contact-card__copied" aria-live="polite">{copied ? t('contact.card.copied') : ''}</span>
        </aside>
      </div>
    </div>
  )
}
