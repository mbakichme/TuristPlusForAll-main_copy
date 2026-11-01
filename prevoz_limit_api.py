"""Limiti prevoz po destinaciji i grupi termina.

  destinacija_prevoz: jedan red po (destinacija, grupa termina) — iz mesto_grupa + mesto.destinacija.
                      naziv = "<naziv destinacije>-<naziv grupe termina>"
  prevoz_limit:       jedan red po (destinacija_prevoz, datum, smer).
                      Odlazak = datum_od perioda grupe, Povratak = datum_do perioda grupe.

Veze su samo ID-jevi (bez FK, po konvenciji projekta).
"""
from datetime import date

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

SMEROVI = ("Odlazak", "Povratak")

# Veza destinacija ↔ grupa termina: preko mesta (mesto_grupa + mesto.destinacija)
DESTINACIJE_PREVOZ_SQL = """
    SELECT DISTINCT m.destinacija AS id_destinacije, x.grupa_id AS id_grupe_termina,
           d.naziv || '-' || pg.naziv AS naziv
    FROM mesto_grupa x
    JOIN mesto m ON m.id = x.mesto_id
    JOIN destinacija d ON d.id = m.destinacija
    JOIN period_grupa pg ON pg.id = x.grupa_id
    WHERE m.destinacija IS NOT NULL
"""


class PrevozLimitIn(BaseModel):
    id_destinacije_prevoza: int
    datum: date
    smer: str
    limit: int = Field(..., ge=0, le=999)
    dodatna_mesta: int = Field(0, ge=-999, le=999)

    @field_validator("smer")
    @classmethod
    def smer_ispravan(cls, value):
        if value not in SMEROVI:
            raise ValueError("Smer mora biti Odlazak ili Povratak")
        return value


def init_prevoz_limit(engine):
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS destinacija_prevoz (
                id SERIAL PRIMARY KEY,
                id_destinacije INTEGER NOT NULL,
                id_grupe_termina INTEGER NOT NULL,
                naziv VARCHAR(300) NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                CONSTRAINT destinacija_prevoz_uniq UNIQUE (id_destinacije, id_grupe_termina)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS prevoz_limit (
                id SERIAL PRIMARY KEY,
                id_destinacije_prevoza INTEGER NOT NULL,
                datum DATE NOT NULL,
                smer VARCHAR(20) NOT NULL,
                limit_mesta INTEGER NOT NULL DEFAULT 0 CHECK (limit_mesta >= 0),
                dodatna_mesta INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """))
        # Migracija sa stare šeme (država/destinacija/mesto/grupa po redu) na destinacija_prevoz
        for kolona in ("naziv", "drzava_id", "destinacija_id", "mesto_id", "grupa_datuma_id"):
            conn.execute(text(f"ALTER TABLE prevoz_limit DROP COLUMN IF EXISTS {kolona}"))
        conn.execute(text("ALTER TABLE prevoz_limit ADD COLUMN IF NOT EXISTS id_destinacije_prevoza INTEGER"))
        conn.execute(text("DROP INDEX IF EXISTS prevoz_limit_uniq"))
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS prevoz_limit_uniq
            ON prevoz_limit (id_destinacije_prevoza, datum, smer)
        """))


def _sync_destinacije_prevoz(conn) -> int:
    """Upisuje/osvežava destinacija_prevoz iz mesta i grupa termina. Vraća broj upisanih/izmenjenih."""
    res = conn.execute(text(f"""
        INSERT INTO destinacija_prevoz (id_destinacije, id_grupe_termina, naziv)
        SELECT s.id_destinacije, s.id_grupe_termina, s.naziv
        FROM ({DESTINACIJE_PREVOZ_SQL}) s
        ON CONFLICT (id_destinacije, id_grupe_termina)
        DO UPDATE SET naziv = EXCLUDED.naziv, updated_at = NOW()
        WHERE destinacija_prevoz.naziv <> EXCLUDED.naziv
    """))
    return res.rowcount


SELECT_SQL = """
    SELECT pl.id, pl.id_destinacije_prevoza, pl.datum, pl.smer, pl.limit_mesta, pl.dodatna_mesta,
           pl.created_at, pl.updated_at,
           dp.naziv AS destinacija_prevoz_naziv, dp.id_destinacije, dp.id_grupe_termina
    FROM prevoz_limit pl
    LEFT JOIN destinacija_prevoz dp ON dp.id = pl.id_destinacije_prevoza
"""


def _red(r):
    return {
        "id": r.id,
        "id_destinacije_prevoza": r.id_destinacije_prevoza,
        "destinacija_prevoz_naziv": r.destinacija_prevoz_naziv,
        "id_destinacije": r.id_destinacije,
        "id_grupe_termina": r.id_grupe_termina,
        "datum": r.datum.isoformat() if r.datum else None,
        "smer": r.smer,
        "limit": r.limit_mesta,
        "dodatna_mesta": r.dodatna_mesta,
        "ukupno": r.limit_mesta + r.dodatna_mesta,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


def _proveri_destinaciju_prevoza(conn, id_dp: int) -> None:
    if not conn.execute(text("SELECT 1 FROM destinacija_prevoz WHERE id = :i"), {"i": id_dp}).first():
        raise HTTPException(status_code=400, detail="Nepoznata destinacija prevoza")


def _params(body: PrevozLimitIn) -> dict:
    return {
        "dp": body.id_destinacije_prevoza,
        "datum": body.datum,
        "smer": body.smer,
        "limit": body.limit,
        "dod": body.dodatna_mesta,
    }


def register_prevoz_limit(api, engine, get_current_user):
    @api.get("/destinacija-prevoz")
    def list_destinacija_prevoz(_: dict = Depends(get_current_user)):
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT id, id_destinacije, id_grupe_termina, naziv FROM destinacija_prevoz ORDER BY naziv"
            )).fetchall()
        return [
            {"id": r.id, "id_destinacije": r.id_destinacije,
             "id_grupe_termina": r.id_grupe_termina, "naziv": r.naziv}
            for r in rows
        ]

    @api.get("/prevoz-limit")
    def list_prevoz_limit(q: str = "", _: dict = Depends(get_current_user)):
        q = (q or "").strip()
        uslov = ""
        params: dict = {}
        if q:
            uslov = " WHERE dp.naziv ILIKE :q OR pl.smer ILIKE :q"
            params["q"] = f"%{q}%"
        with engine.connect() as conn:
            rows = conn.execute(
                text(SELECT_SQL + uslov + " ORDER BY pl.datum NULLS LAST, dp.naziv, pl.id"),
                params,
            ).fetchall()
        return [_red(r) for r in rows]

    @api.post("/prevoz-limit", status_code=201)
    def create_prevoz_limit(body: PrevozLimitIn, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            _proveri_destinaciju_prevoza(conn, body.id_destinacije_prevoza)
            try:
                new_id = conn.execute(text("""
                    INSERT INTO prevoz_limit (id_destinacije_prevoza, datum, smer, limit_mesta, dodatna_mesta)
                    VALUES (:dp, :datum, :smer, :limit, :dod)
                    RETURNING id
                """), _params(body)).scalar_one()
            except IntegrityError:
                raise HTTPException(status_code=409, detail="Limit za ovu destinaciju, datum i smer već postoji")
        return {"status": "kreirano", "id": new_id}

    @api.put("/prevoz-limit/{item_id}")
    def update_prevoz_limit(item_id: int, body: PrevozLimitIn, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            _proveri_destinaciju_prevoza(conn, body.id_destinacije_prevoza)
            try:
                res = conn.execute(text("""
                    UPDATE prevoz_limit
                    SET id_destinacije_prevoza = :dp, datum = :datum, smer = :smer,
                        limit_mesta = :limit, dodatna_mesta = :dod, updated_at = NOW()
                    WHERE id = :id
                """), {**_params(body), "id": item_id})
            except IntegrityError:
                raise HTTPException(status_code=409, detail="Limit za ovu destinaciju, datum i smer već postoji")
            if res.rowcount == 0:
                raise HTTPException(status_code=404, detail="Limit nije pronađen")
        return {"status": "sacuvano", "id": item_id}

    @api.delete("/prevoz-limit/{item_id}")
    def delete_prevoz_limit(item_id: int, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            res = conn.execute(text("DELETE FROM prevoz_limit WHERE id = :id"), {"id": item_id})
            if res.rowcount == 0:
                raise HTTPException(status_code=404, detail="Limit nije pronađen")
        return {"status": "obrisano", "id": item_id}

    @api.post("/prevoz-limit/generisi")
    def generisi_prevoz_limit(_: dict = Depends(get_current_user)):
        """Sinhronizuje destinacija_prevoz, pa za svaki period grupe pravi Odlazak (datum_od)
        i Povratak (datum_do). Postojeći redovi (destinacija, datum, smer) se ne diraju."""
        with engine.begin() as conn:
            destinacija_upisano = _sync_destinacije_prevoz(conn)
            dodato = 0
            for smer, kolona in (("Odlazak", "datum_od"), ("Povratak", "datum_do")):
                res = conn.execute(text(f"""
                    INSERT INTO prevoz_limit (id_destinacije_prevoza, datum, smer, limit_mesta, dodatna_mesta)
                    SELECT dp.id, pd.{kolona}, :smer, 0, 0
                    FROM destinacija_prevoz dp
                    JOIN period_datum pd ON pd.grupa_id = dp.id_grupe_termina
                    ON CONFLICT (id_destinacije_prevoza, datum, smer) DO NOTHING
                """), {"smer": smer})
                dodato += res.rowcount
        return {"status": "generisano", "destinacije_upisano": destinacija_upisano, "dodato": dodato}
