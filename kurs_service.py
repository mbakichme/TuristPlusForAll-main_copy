"""Srednji EUR kurs: baza je jedini izvor uspešno sačuvanih rezultata."""

import math
from datetime import date
from decimal import Decimal

import httpx
from sqlalchemy import text


# Dvodelni PG ključ odvaja kurs od drugih advisory lock korisnika.
_LOCK_NAMESPACE = 0x4B555253
_SELECT = text("SELECT iznos, datum_kursa FROM kurs WHERE datum = :datum")
_INSERT = text("""
    INSERT INTO kurs (iznos, datum, datum_kursa)
    VALUES (:iznos, :datum, :datum_kursa)
    ON CONFLICT (datum) DO NOTHING
    RETURNING iznos, datum_kursa
""")


def ensure_kurs_table(conn):
    """Poziva init_db, nikad import; SQLite ostaje podržan za lokalnu bazu."""
    primary_key = "INTEGER PRIMARY KEY" if conn.dialect.name == "sqlite" else "SERIAL PRIMARY KEY"
    conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS kurs (
            id {primary_key},
            iznos NUMERIC(18,8) NOT NULL CHECK (iznos > 0),
            datum DATE NOT NULL UNIQUE,
            datum_kursa DATE NOT NULL
        )
    """))


def _iso_date(value):
    if not isinstance(value, str):
        raise ValueError("Datum mora biti ISO string")
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("Datum mora biti YYYY-MM-DD")
    return parsed


def _amount(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("Neispravan kurs")
    amount = Decimal(str(value))
    if not amount.is_finite() or amount <= 0:
        raise ValueError("Kurs mora biti konačan i pozitivan")
    number = float(amount)
    if not math.isfinite(number) or number <= 0:
        raise ValueError("Kurs nije predstavljiv kao pozitivan float")
    return amount


def _row_rate(row, requested):
    if row is None:
        return None, None
    actual = row[1].isoformat() if isinstance(row[1], date) else row[1]
    if _iso_date(actual) > requested:
        raise ValueError("Datum kursa je posle traženog datuma")
    return float(_amount(row[0])), actual


def get_eur_rate(engine, iso_date: str) -> tuple[float | None, str | None]:
    """Bez poslednjeg poznatog kursa: neuspeh nikad ne menja traženi datum."""
    try:
        requested = _iso_date(iso_date)
    except (TypeError, ValueError):
        return None, None

    params = {"datum": requested}
    try:
        # Svaki poziv čita bazu; nema memorijskog keša uspešnih kurseva.
        with engine.connect() as conn:
            row = conn.execute(_SELECT, params).fetchone()
            if row is not None:
                return _row_rate(row, requested)

        with engine.begin() as conn:
            if conn.dialect.name == "postgresql":
                # Lock traje do commit/rollback i štiti popunjavanje između workera.
                conn.execute(
                    text("SELECT pg_advisory_xact_lock(:namespace, :date_key)"),
                    {"namespace": _LOCK_NAMESPACE, "date_key": requested.toordinal()},
                )
            # Drugi worker je možda sačuvao kurs dok smo čekali lock.
            row = conn.execute(_SELECT, params).fetchone()
            if row is not None:
                return _row_rate(row, requested)

            response = httpx.get(
                f"https://kurs.resenje.org/api/v1/currencies/EUR/rates/{iso_date}",
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
            amount = _amount(payload["exchange_middle"])
            actual = _iso_date(payload.get("date_from") or payload.get("date"))
            if actual > requested:
                raise ValueError("API je vratio kurs budućeg datuma")

            # SQLite DBAPI ne vezuje Decimal direktno; PG zadržava punu preciznost.
            stored_amount = str(amount) if conn.dialect.name == "sqlite" else amount
            row = conn.execute(
                _INSERT,
                {**params, "iznos": stored_amount, "datum_kursa": actual},
            ).fetchone()
            if row is None:
                row = conn.execute(_SELECT, params).fetchone()
            return _row_rate(row, requested)
    except Exception:
        # Mrežna/DB/validaciona greška: rollback, bez lažnog reda ili istorijskog fallback-a.
        return None, None
