"""Per-email starred tickers. Backs the Calendar star column and personalises the Brief."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

MAX_PER_USER = 100


def get(db: Session, email: str) -> list[str]:
    rows = db.execute(
        text("SELECT ticker FROM user_watchlist WHERE email = :e ORDER BY ticker"),
        {"e": email.lower().strip()},
    ).fetchall()
    return [r[0] for r in rows]


def add(db: Session, email: str, ticker: str) -> list[str]:
    email = email.lower().strip()
    ticker = ticker.upper().strip()
    if not ticker:
        return get(db, email)
    current = db.execute(
        text("SELECT count(*) FROM user_watchlist WHERE email = :e"), {"e": email}
    ).scalar_one()
    if current >= MAX_PER_USER:
        return get(db, email)
    db.execute(
        text("""INSERT INTO user_watchlist(email, ticker) VALUES (:e, :t)
                ON CONFLICT (email, ticker) DO NOTHING"""),
        {"e": email, "t": ticker},
    )
    db.commit()
    return get(db, email)


def remove(db: Session, email: str, ticker: str) -> list[str]:
    email = email.lower().strip()
    db.execute(
        text("DELETE FROM user_watchlist WHERE email = :e AND ticker = :t"),
        {"e": email, "t": ticker.upper().strip()},
    )
    db.commit()
    return get(db, email)
