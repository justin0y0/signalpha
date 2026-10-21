/**
 * The market rules store why they hold what they hold as {"code", ...values}
 * (services/strategies.py gen_targets); this turns that into a sentence in the reader's
 * language. Anything that is not such a record is shown as it is.
 */
export function whyText(raw: string | null | undefined, t: (k: any, v?: Record<string, string | number>) => string): string {
  if (!raw) return ''
  try {
    const w = JSON.parse(raw)
    if (w && typeof w === 'object' && w.code) return t(`why.${w.code}`, w)
  } catch { /* plain text */ }
  return raw
}
