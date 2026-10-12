import { useState, useEffect, useCallback } from 'react'
import { useT } from '../i18n'

// Value stays English — it is what the API stores and what the admin table reads.
const ROLES = [
  { v: 'Student', k: 'role.student' }, { v: 'Quant / QR', k: 'role.quant' },
  { v: 'Software Engineer', k: 'role.swe' }, { v: 'PM / Analyst', k: 'role.pm' },
  { v: 'Trader', k: 'role.trader' }, { v: 'Researcher', k: 'role.researcher' },
  { v: 'Other', k: 'role.other' },
] as const

type Me = {
  email: string; name?: string; role?: string; tier?: string; verified?: boolean;
  tg_connected?: boolean; tg_link?: string; trial_ends_at?: string; active?: boolean
}

export function AuthWidget() {
  const { t } = useT()
  const [email, setEmail] = useState<string>(() => localStorage.getItem('sa_email') || '')
  const [me, setMe] = useState<Me | null>(null)
  const [open, setOpen] = useState(false)
  const [menu, setMenu] = useState(false)
  const [form, setForm] = useState({ email: '', name: '', role: '', roleOther: '' })
  const [status, setStatus] = useState<'idle' | 'sending' | 'sent' | 'error'>('idle')
  const [msg, setMsg] = useState('')

  const loadMe = useCallback(async (e: string) => {
    if (!e) return
    try {
      const r = await fetch('/api/v1/auth/me?email=' + encodeURIComponent(e))
      if (r.ok) { const d = await r.json(); setMe(d.found ? d : null) }
      else setMe(null)
    } catch { /* keep prior */ }
  }, [])

  useEffect(() => { if (email) loadMe(email) }, [email, loadMe])

  const submit = async () => {
    if (!form.email.trim()) { setMsg('Please enter your email.'); setStatus('error'); return }
    setStatus('sending'); setMsg('')
    const role = form.role === 'Other' ? (form.roleOther.trim() || 'Other') : form.role
    try {
      const r = await fetch('/api/v1/auth/register', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: form.email, name: form.name, role }),
      })
      const d = await r.json()
      if (d.ok === false) { setStatus('error'); setMsg(d.error || 'Something went wrong.'); return }
      const e = form.email.trim().toLowerCase()
      localStorage.setItem('sa_email', e); setEmail(e)
      setStatus('sent')
      setMsg(d.verified ? "You're already verified — you're all set." : (d.message || ''))
      loadMe(e)
    } catch {
      setStatus('error'); setMsg('Network error — please try again.')
    }
  }

  const signOut = () => { localStorage.removeItem('sa_email'); setEmail(''); setMe(null); setMenu(false) }
  const reset = () => { setStatus('idle'); setMsg(''); setForm({ email: '', name: '', role: '', roleOther: '' }) }

  const daysLeft = me?.trial_ends_at
    ? Math.max(0, Math.ceil((new Date(me.trial_ends_at).getTime() - Date.now()) / 86400000))
    : null

  return (
    <>
      <style>{CSS}</style>

      {!me && (
        <button className="sa-cta" onClick={() => { setOpen(true); reset() }}>{t('nav.trial')}</button>
      )}

      {me && (
        <div className="sa-acct">
          <button className="sa-acct-btn" onClick={() => setMenu(m => !m)}>
            <span className="sa-dot" data-on={me.tg_connected ? '1' : '0'} />
            {me.name || me.email.split('@')[0]}
          </button>
          {menu && (
            <div className="sa-menu">
              <div className="sa-menu-h">{me.email}</div>
              <div className="sa-menu-row">
                {me.verified
                  ? (daysLeft != null ? `Free trial · ${daysLeft}d left` : 'Verified')
                  : 'Unverified — check your inbox & spam'}
              </div>
              {me.verified && !me.tg_connected && me.tg_link && (
                <a className="sa-menu-btn" href={me.tg_link} target="_blank" rel="noreferrer">Connect Telegram →</a>
              )}
              {me.tg_connected && <div className="sa-menu-row ok">✓ Telegram connected</div>}
              <button className="sa-menu-out" onClick={signOut}>{t('auth.signOut')}</button>
            </div>
          )}
        </div>
      )}

      {open && (
        <div className="sa-overlay" onClick={() => setOpen(false)}>
          <div className="sa-modal" onClick={e => e.stopPropagation()}>
            <button className="sa-close" onClick={() => setOpen(false)} aria-label="Close">×</button>

            {status === 'sent' ? (
              <div className="sa-done">
                <div className="sa-check">✓</div>
                <h3 className="sa-title">{t('auth.checkInbox')}</h3>
                <p className="sa-sub">{t('auth.sentTo')} <b className="sa-em">{email}</b>. {t('auth.sentBody')}</p>
                <div className="sa-spam">
                  {t('auth.notThere')} <b>{t('auth.checkSpam')}</b> {t('auth.markNotSpam')}
                </div>
                <button className="sa-ghost-btn" onClick={reset}>{t('auth.differentEmail')}</button>
              </div>
            ) : (
              <>
                <div className="sa-brand">
                  <span className="sa-logo"><svg viewBox="0 0 24 24" fill="none" width="18" height="18" xmlns="http://www.w3.org/2000/svg"><path d="M16 8.5C14.2 6.3 11.2 5.8 9 7.2C6.8 8.6 6 11.2 7 13.5C8 15.8 10.5 16.8 13 16C14.8 15.4 16 13.8 16 12V18" stroke="white" strokeWidth="2.1" strokeLinecap="round" strokeLinejoin="round"/><path d="M16 16 Q17.5 13.2 19 16 Q20.5 18.8 22 16" stroke="rgba(255,255,255,0.55)" strokeWidth="1.6" strokeLinecap="round" fill="none"/></svg></span>
                  <span className="sa-eyebrow">SignAlpha</span>
                </div>
                <h3 className="sa-title">{t('auth.startTrial')}</h3>
                <p className="sa-sub">{t('auth.pitch')}</p>

                <label className="sa-label">{t('auth.email')}</label>
                <input className="sa-input" type="email" placeholder="you@email.com" value={form.email}
                  onChange={e => setForm(f => ({ ...f, email: e.target.value }))} />

                <label className="sa-label">{t('auth.name')} <span className="sa-opt">{t('auth.optional')}</span></label>
                <input className="sa-input" type="text" placeholder={t('auth.namePlaceholder')} value={form.name}
                  onChange={e => setForm(f => ({ ...f, name: e.target.value }))} />

                <label className="sa-label">{t('auth.background')} <span className="sa-opt">{t('auth.optional')}</span></label>
                <select className="sa-input" value={form.role}
                  onChange={e => setForm(f => ({ ...f, role: e.target.value }))}>
                  <option value="">{t('auth.selectOne')}</option>
                  {ROLES.map(r => <option key={r.v} value={r.v}>{t(r.k)}</option>)}
                </select>
                {form.role === 'Other' && (
                  <input className="sa-input sa-other" type="text" placeholder={t('auth.otherPlaceholder')} value={form.roleOther}
                    onChange={e => setForm(f => ({ ...f, roleOther: e.target.value }))} />
                )}

                {msg && status === 'error' && <div className="sa-err">{msg}</div>}
                <button className="sa-submit" disabled={status === 'sending'} onClick={submit}>
                  {status === 'sending' ? t('auth.sending') : t('auth.createAccount')}
                </button>
                <p className="sa-fine">{t('auth.emailNote')}</p>
              </>
            )}
          </div>
        </div>
      )}
    </>
  )
}

const CSS = `
.sa-cta{font:600 .7rem var(--font-mono);letter-spacing:.08em;text-transform:uppercase;color:var(--signal-ink);
  background:var(--signal);border:1px solid var(--signal);border-radius:var(--radius-sm);
  padding:.5rem .85rem;cursor:pointer;white-space:nowrap;transition:background .15s}
.sa-cta:hover{background:#ffc65e}
.sa-acct{position:relative}
.sa-acct-btn{display:flex;align-items:center;gap:8px;font-size:.8rem;font-weight:500;color:var(--text-primary);
  background:var(--bg-card);border:1px solid var(--border-strong);border-radius:var(--radius-sm);padding:.42rem .8rem;
  cursor:pointer;white-space:nowrap}
.sa-acct-btn:hover{border-color:var(--text-tertiary)}
.sa-dot{width:6px;height:6px;border-radius:50%;background:var(--text-muted);flex:0 0 auto}
.sa-dot[data-on="1"]{background:var(--up)}
.sa-menu{position:absolute;right:0;top:calc(100% + 8px);width:248px;background:var(--bg-2);
  border:1px solid var(--border-strong);border-radius:var(--radius-md);padding:12px;z-index:1200;
  box-shadow:0 24px 60px -24px rgba(0,0,0,.8)}
.sa-menu-h{font:500 .72rem var(--font-mono);color:var(--text-tertiary);word-break:break-all;margin-bottom:8px}
.sa-menu-row{font-size:.78rem;color:var(--text-secondary);padding:6px 2px}
.sa-menu-row.ok{color:var(--up)}
.sa-menu-btn{display:block;text-align:center;text-decoration:none;font-size:.8rem;font-weight:600;color:var(--signal-ink);
  background:var(--signal);border-radius:var(--radius-sm);padding:9px;margin:8px 0}
.sa-menu-out{width:100%;font-size:.75rem;color:var(--text-tertiary);background:transparent;
  border:1px solid var(--border-strong);border-radius:var(--radius-sm);padding:7px;cursor:pointer;margin-top:4px}
.sa-menu-out:hover{color:var(--text-primary)}

.sa-overlay{position:fixed;inset:0;background:rgba(8,7,6,.84);display:grid;place-items:center;z-index:2000;padding:20px}
.sa-modal{position:relative;width:100%;max-width:420px;background:var(--bg-1);
  border:1px solid var(--border-strong);border-radius:var(--radius-md);padding:30px 30px 26px;
  box-shadow:0 40px 90px -30px rgba(0,0,0,.9);animation:sa-in .28s cubic-bezier(.2,.7,.2,1)}
@keyframes sa-in{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
.sa-close{position:absolute;right:14px;top:10px;font-size:22px;line-height:1;color:var(--text-tertiary);
  background:none;border:none;cursor:pointer}
.sa-close:hover{color:var(--text-primary)}
.sa-brand{display:flex;align-items:center;gap:9px;margin-bottom:16px}
.sa-logo{display:grid;place-items:center;width:28px;height:28px;border-radius:var(--radius-sm);
  background:var(--signal);color:var(--signal-ink)}
.sa-eyebrow{font:600 .62rem var(--font-mono);letter-spacing:.2em;color:var(--text-tertiary);text-transform:uppercase}
.sa-title{font-family:var(--font-display);font-size:1.75rem;font-weight:430;letter-spacing:-.02em;line-height:1.1;
  color:var(--text-primary);margin:0 0 8px}
.sa-sub{font-size:.86rem;color:var(--text-secondary);line-height:1.55;margin:0 0 20px}
.sa-em{color:var(--text-primary);font-weight:600}
.sa-label{display:block;font:600 .58rem var(--font-mono);letter-spacing:.14em;text-transform:uppercase;
  color:var(--text-tertiary);margin:0 0 6px 1px}
.sa-opt{font-weight:400;text-transform:none;letter-spacing:0;color:var(--text-muted);margin-left:4px}
.sa-input{width:100%;font-family:inherit;font-size:.9rem;color:var(--text-primary);
  background:var(--bg-0);border:1px solid var(--border-strong);border-radius:var(--radius-sm);
  padding:.65rem .8rem;margin-bottom:14px;outline:none;transition:border-color .15s}
.sa-input:focus{border-color:var(--signal)}
.sa-other{margin-top:-6px}
.sa-submit{width:100%;font-weight:600;font-size:.9rem;color:var(--signal-ink);
  background:var(--signal);border:none;border-radius:var(--radius-sm);
  padding:.75rem;cursor:pointer;margin-top:4px;transition:background .15s}
.sa-submit:hover:not(:disabled){background:#ffc65e}
.sa-submit:disabled{opacity:.6;cursor:default}
.sa-err{font-size:.78rem;color:var(--down);margin:-4px 0 12px}
.sa-fine{font-size:.72rem;color:var(--text-tertiary);margin:14px 0 0;line-height:1.5}

.sa-done{text-align:center;padding:8px 4px 4px}
.sa-check{width:48px;height:48px;margin:6px auto 16px;border-radius:50%;display:grid;place-items:center;
  font-size:22px;color:var(--up);border:1.5px solid var(--up)}
.sa-spam{font-size:.78rem;color:var(--text-secondary);line-height:1.55;text-align:left;
  border-left:2px solid var(--signal);padding:2px 0 2px 12px;margin:18px 0 16px}
.sa-spam b{color:var(--signal)}
.sa-ghost-btn{font-size:.78rem;color:var(--text-tertiary);background:transparent;border:1px solid var(--border-strong);
  border-radius:var(--radius-sm);padding:.5rem 1rem;cursor:pointer}
.sa-ghost-btn:hover{color:var(--text-primary);border-color:var(--text-tertiary)}
@media(max-width:760px){.sa-cta,.sa-acct-btn{padding:.42rem .65rem}}
`
