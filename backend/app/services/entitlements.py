"""Who is allowed to see what.

`platform_users.tier` and `trial_ends_at` have existed since accounts were added, and
`auth_service._active()` already knows how to read them — but nothing on the site ever
called it. Every surface was open to everyone, so the tier column described a state
that had no consequences.

This module is the missing middle: one place that answers "is this email entitled to
X", used by the routes that should be gated. It deliberately does NOT talk to a
payment provider. Wiring one needs Justin's own Stripe account and keys, and a pricing
decision that shouldn't be guessed at — see `upgrade_hint()` for the single seam a
provider would plug into.

Current policy, intentionally generous while the product is pre-launch:
  * anonymous            -> public surfaces only
  * verified, in trial   -> everything
  * paid tier            -> everything
  * verified, trial over -> public surfaces, plus a nudge
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.core.logging import get_logger

logger = get_logger(__name__)

PAID_TIERS = {"pro", "paid", "lifetime"}

# Surfaces that stay open to everyone. The transparency argument only works if the
# evidence is public — gating the track record would defeat the point of having one.
#
# The brief is public too, deliberately. It is the product's single best demo and the
# only surface built around the one thing the model measurably does well; hiding it
# behind a sign-in before launch means nobody ever sees the reason to sign in. What
# gets gated is what makes the brief *yours* — watchlist personalisation and push —
# which is also the honest thing to charge for later, since it is per-user work rather
# than a page of shared research.
PUBLIC_FEATURES = {"calendar", "model", "strategy", "about", "oracle", "pulse", "brief"}
GATED_FEATURES = {"watchlist", "telegram_push"}


@dataclass
class Entitlement:
    email: str | None
    tier: str
    verified: bool
    in_trial: bool
    active: bool

    def allows(self, feature: str) -> bool:
        if feature in PUBLIC_FEATURES:
            return True
        return self.active

    def as_dict(self) -> dict[str, Any]:
        return {
            "email": self.email,
            "tier": self.tier,
            "verified": self.verified,
            "in_trial": self.in_trial,
            "active": self.active,
            "public_features": sorted(PUBLIC_FEATURES),
            "gated_features": sorted(GATED_FEATURES),
        }


ANONYMOUS = Entitlement(email=None, tier="anonymous", verified=False, in_trial=False, active=False)


def resolve(db: Session, email: str | None) -> Entitlement:
    if not email:
        return ANONYMOUS
    try:
        row = db.execute(
            text("""SELECT email, tier, verified, trial_ends_at
                    FROM platform_users WHERE email = :e"""),
            {"e": email.lower().strip()},
        ).fetchone()
    except Exception as exc:  # noqa: BLE001 - never let entitlement lookup break a page
        logger.warning("entitlement lookup failed for %s: %s", email, exc)
        return ANONYMOUS
    if row is None:
        return ANONYMOUS

    m = dict(row._mapping)
    tier = (m.get("tier") or "free_trial").lower()
    verified = bool(m.get("verified"))
    if tier in PAID_TIERS:
        return Entitlement(m["email"], tier, verified, False, True)

    in_trial = False
    if verified:
        ends = m.get("trial_ends_at")
        if ends is None:
            in_trial = True
        else:
            import datetime as dt
            try:
                if ends.tzinfo is None:
                    ends = ends.replace(tzinfo=dt.timezone.utc)
                in_trial = dt.datetime.now(dt.timezone.utc) <= ends
            except Exception:  # noqa: BLE001
                in_trial = True
    return Entitlement(m["email"], tier, verified, in_trial, in_trial)


def upgrade_hint(ent: Entitlement) -> dict[str, Any] | None:
    """What the UI should say when something is gated.

    This is the one seam a payment provider plugs into: a real integration replaces
    `checkout_url` with a session created against Justin's own account. Everything
    upstream — who is entitled, what is gated, how the UI reacts — already works, so
    adding a provider is a contained change rather than a new subsystem.
    """
    if ent.active:
        return None
    if ent.email is None:
        return {"reason": "anonymous", "message": "Sign in to see your daily brief and watchlist.",
                "action": "sign_in", "checkout_url": None}
    if not ent.verified:
        return {"reason": "unverified", "message": "Verify your email to unlock the daily brief.",
                "action": "resend_verification", "checkout_url": None}
    return {"reason": "trial_expired", "message": "Your trial has ended.",
            "action": "upgrade", "checkout_url": None}
