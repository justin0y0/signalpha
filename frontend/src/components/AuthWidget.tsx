import { useState, useEffect, useCallback } from 'react'

const ROLES = ['Student', 'Quant / QR', 'Software Engineer', 'PM / Analyst', 'Trader', 'Researcher', 'Other']

type Me = {
  email: string; name?: string; role?: string; tier?: string; verified?: boolean;
  tg_connected?: boolean; tg_link?: string; trial_ends_at?: string; active?: boolean
}

export function AuthWidget() {
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
        <button className="sa-cta" onClick={() => { setOpen(true); reset() }}>Start free trial</button>
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
              <button className="sa-menu-out" onClick={signOut}>Sign out</button>
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
                <h3 className="sa-title">Check your inbox</h3>
                <p className="sa-sub">We sent a confirmation link to <b className="sa-em">{email}</b>. Click it to activate your account.</p>
                <div className="sa-spam">
                  📬 Not there in a minute? <b>Check your spam / junk folder</b> and mark it “not spam”.
                </div>
                <button className="sa-ghost-btn" onClick={reset}>Use a different email</button>
              </div>
            ) : (
              <>
                <div className="sa-brand">
                  <span className="sa-logo"><svg viewBox="0 0 24 24" fill="none" width="18" height="18" xmlns="http://www.w3.org/2000/svg"><path d="M16 8.5C14.2 6.3 11.2 5.8 9 7.2C6.8 8.6 6 11.2 7 13.5C8 15.8 10.5 16.8 13 16C14.8 15.4 16 13.8 16 12V18" stroke="white" strokeWidth="2.1" strokeLinecap="round" strokeLinejoin="round"/><path d="M16 16 Q17.5 13.2 19 16 Q20.5 18.8 22 16" stroke="rgba(255,255,255,0.55)" strokeWidth="1.6" strokeLinecap="round" fill="none"/></svg></span>
                  <span className="sa-eyebrow">SignAlpha</span>
                </div>
                <h3 className="sa-title">Start your free trial</h3>
                <p className="sa-sub">30 days of ML earnings predictions, the Oracle signal scanner, and live track records. No card required.</p>

                <label className="sa-label">Email</label>
                <input className="sa-input" type="email" placeholder="you@email.com" value={form.email}
                  onChange={e => setForm(f => ({ ...f, email: e.target.value }))} />

                <label className="sa-label">Name <span className="sa-opt">optional</span></label>
                <input className="sa-input" type="text" placeholder="Your name" value={form.name}
                  onChange={e => setForm(f => ({ ...f, name: e.target.value }))} />

                <label className="sa-label">Background <span className="sa-opt">optional</span></label>
                <select className="sa-input" value={form.role}
                  onChange={e => setForm(f => ({ ...f, role: e.target.value }))}>
                  <option value="">Select one…</option>
                  {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
                </select>
                {form.role === 'Other' && (
                  <input className="sa-input sa-other" type="text" placeholder="Tell us your background" value={form.roleOther}
                    onChange={e => setForm(f => ({ ...f, roleOther: e.target.value }))} />
                )}

                {msg && status === 'error' && <div className="sa-err">{msg}</div>}
                <button className="sa-submit" disabled={status === 'sending'} onClick={submit}>
                  {status === 'sending' ? 'Sending…' : 'Create account'}
                </button>
                <p className="sa-fine">We'll email a confirmation link. If it's not in your inbox shortly, check your spam folder.</p>
              </>
            )}
          </div>
        </div>
      )}
    </>
  )
}

const CSS = `
.sa-cta{font-family:var(--font-mono,monospace);font-size:13px;font-weight:600;color:#06121c;
  background:linear-gradient(120deg,var(--accent-cyan,#E2703A),#7dd3fc);border:none;border-radius:11px;
  padding:9px 16px;cursor:pointer;white-space:nowrap;transition:transform .15s,box-shadow .15s}
.sa-cta:hover{transform:translateY(-1px);box-shadow:0 8px 24px -8px rgba(226, 112, 58,.6)}
.sa-acct{position:relative}
.sa-acct-btn{display:flex;align-items:center;gap:8px;font-size:13px;font-weight:500;color:#e8edf5;
  background:#111827;border:1px solid rgba(127, 169, 155,.16);border-radius:11px;padding:8px 14px;
  cursor:pointer;white-space:nowrap}
.sa-acct-btn:hover{border-color:rgba(127, 169, 155,.32)}
.sa-dot{width:7px;height:7px;border-radius:50%;background:#64748b;flex:0 0 auto}
.sa-dot[data-on="1"]{background:var(--up,#6FA287);box-shadow:0 0 8px var(--up,#6FA287)}
.sa-menu{position:absolute;right:0;top:46px;width:248px;background:#0d1322;
  border:1px solid rgba(127, 169, 155,.18);border-radius:14px;padding:12px;z-index:1200;
  box-shadow:0 24px 60px -24px rgba(0,0,0,.8)}
.sa-menu-h{font-size:12px;color:#8a99b0;word-break:break-all;margin-bottom:8px;font-family:var(--font-mono,monospace)}
.sa-menu-row{font-size:12.5px;color:#cbd5e1;padding:6px 2px}
.sa-menu-row.ok{color:var(--up,#6FA287)}
.sa-menu-btn{display:block;text-align:center;text-decoration:none;font-size:13px;font-weight:600;color:#06121c;
  background:linear-gradient(120deg,var(--accent-cyan,#E2703A),#7dd3fc);border-radius:9px;padding:9px;margin:8px 0}
.sa-menu-out{width:100%;font-size:12px;color:#8a99b0;background:transparent;
  border:1px solid rgba(127, 169, 155,.16);border-radius:9px;padding:7px;cursor:pointer;margin-top:4px}
.sa-menu-out:hover{color:#e8edf5}

.sa-overlay{position:fixed;inset:0;background:rgba(2,5,11,.82);backdrop-filter:blur(6px);
  display:grid;place-items:center;z-index:2000;padding:20px}
.sa-modal{position:relative;width:100%;max-width:418px;
  background:#0b1019;background-image:radial-gradient(420px 200px at 80% -10%,rgba(226, 112, 58,.10),transparent 65%);
  border:1px solid rgba(127, 169, 155,.18);border-radius:20px;padding:32px 30px 28px;
  box-shadow:0 40px 90px -30px rgba(0,0,0,.9)}
.sa-close{position:absolute;right:16px;top:14px;font-size:23px;line-height:1;color:#8a99b0;
  background:none;border:none;cursor:pointer}
.sa-close:hover{color:#e8edf5}
.sa-brand{display:flex;align-items:center;gap:9px;margin-bottom:18px}
.sa-logo{display:grid;place-items:center;width:30px;height:30px;border-radius:9px;
  background:linear-gradient(135deg,var(--accent-cyan,#E2703A),var(--accent-purple,#7FA99B))}
.sa-eyebrow{font-family:var(--font-mono,monospace);font-size:11px;letter-spacing:.26em;
  color:var(--accent-cyan,#E2703A);text-transform:uppercase}
.sa-title{font-size:22px;font-weight:720;letter-spacing:-.02em;color:#e8edf5;margin:0 0 8px}
.sa-sub{font-size:13.5px;color:#8a99b0;line-height:1.55;margin:0 0 22px}
.sa-em{color:#e8edf5;font-weight:600}
.sa-label{display:block;font-size:11px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;
  color:#8a99b0;margin:0 0 6px 2px}
.sa-opt{font-weight:400;text-transform:none;letter-spacing:0;color:#5b6678;font-size:11px;margin-left:4px}
.sa-input{width:100%;font-family:inherit;font-size:14px;color:#e8edf5;
  background:#070b14;border:1px solid rgba(127, 169, 155,.18);border-radius:11px;
  padding:11px 13px;margin-bottom:15px;outline:none;transition:border-color .15s}
.sa-input:focus{border-color:var(--accent-cyan,#E2703A)}
.sa-other{margin-top:-7px}
.sa-submit{width:100%;font-weight:650;font-size:14px;color:#06121c;
  background:linear-gradient(120deg,var(--accent-cyan,#E2703A),#7dd3fc);border:none;border-radius:11px;
  padding:13px;cursor:pointer;margin-top:4px;transition:transform .12s}
.sa-submit:hover:not(:disabled){transform:translateY(-1px)}
.sa-submit:disabled{opacity:.6;cursor:default}
.sa-err{font-size:12.5px;color:var(--down,#C4726A);margin:-4px 0 12px}
.sa-fine{font-size:11.5px;color:#5b6678;margin:14px 0 0;line-height:1.5}

.sa-done{text-align:center;padding:8px 4px 4px}
.sa-check{width:54px;height:54px;margin:6px auto 18px;border-radius:50%;display:grid;place-items:center;
  font-size:26px;color:#06121c;background:linear-gradient(120deg,var(--up,#6FA287),#6ee7b7);
  box-shadow:0 10px 30px -8px rgba(111, 162, 135,.6)}
.sa-spam{font-size:12.5px;color:#cbd5e1;line-height:1.55;text-align:left;
  background:rgba(217, 164, 65,.08);border:1px solid rgba(217, 164, 65,.25);border-radius:11px;
  padding:12px 14px;margin:18px 0 16px}
.sa-spam b{color:#D9A441}
.sa-ghost-btn{font-size:12.5px;color:#8a99b0;background:transparent;border:1px solid rgba(127, 169, 155,.2);
  border-radius:10px;padding:9px 16px;cursor:pointer}
.sa-ghost-btn:hover{color:#e8edf5;border-color:rgba(127, 169, 155,.36)}
@media(max-width:760px){.sa-cta,.sa-acct-btn{font-size:12px;padding:7px 11px}}
`
