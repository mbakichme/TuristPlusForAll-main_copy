"""Koeficijenti prodaje: Adl/Chd/Inf + koeficijent po strukturi sobe.

Strukture se čitaju iz sobe.tip (DISTINCT, prazne se ignorišu) — svaka se
prikazuje tačno jednom; struktura koja nije u tabeli dobija red sa nulama.
Ručni redovi (rucno = TRUE) dozvoljavaju više zapisa za istu strukturu.
"""
import math

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text


class KoefRedIn(BaseModel):
    id: int | None = None
    struktura: str
    adl: int = 0
    chd: int = 0
    inf: int = 0
    koeficijent: float = 0.0
    rucno: bool = False

    @field_validator("struktura")
    @classmethod
    def validna_struktura(cls, value):
        value = (value or "").strip()
        if not value:
            raise ValueError("Struktura je obavezna")
        if len(value) > 100:
            raise ValueError("Struktura je predugačka (najviše 100 znakova)")
        return value

    @field_validator("adl", "chd", "inf")
    @classmethod
    def validan_broj(cls, value):
        if value < 0 or value > 99:
            raise ValueError("Broj osoba mora biti između 0 i 99")
        return value

    @field_validator("koeficijent")
    @classmethod
    def validan_koeficijent(cls, value):
        if not math.isfinite(value) or value < 0 or value >= 1000000:
            raise ValueError("Koeficijent mora biti konačan, nenegativan broj manji od 1.000.000")
        return value


class KoefPayload(BaseModel):
    redovi: list[KoefRedIn] = Field(default_factory=list, max_length=2000)


def init_koeficijenti(engine):
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS koeficijenti_prodaje (
                id SERIAL PRIMARY KEY,
                struktura TEXT NOT NULL,
                adl INTEGER NOT NULL DEFAULT 0,
                chd INTEGER NOT NULL DEFAULT 0,
                inf INTEGER NOT NULL DEFAULT 0,
                koeficijent DOUBLE PRECISION NOT NULL DEFAULT 0,
                rucno BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_koeficijenti_struktura ON koeficijenti_prodaje (struktura)"
        ))


def _vrati_sve(conn):
    strukture = [r[0] for r in conn.execute(text("""
        SELECT DISTINCT TRIM(tip) FROM sobe
        WHERE tip IS NOT NULL AND TRIM(tip) <> ''
        ORDER BY 1
    """)).fetchall()]
    redovi = [dict(r) for r in conn.execute(text("""
        SELECT id, struktura, adl, chd, inf, koeficijent, rucno
        FROM koeficijenti_prodaje
        ORDER BY struktura, id
    """)).mappings()]
    return {"strukture": strukture, "redovi": redovi}


def register_koeficijenti(api, engine, get_current_user):
    @api.get("/koeficijenti")
    def lista(_: dict = Depends(get_current_user)):
        with engine.connect() as conn:
            return _vrati_sve(conn)

    @api.put("/koeficijenti")
    def sacuvaj(body: KoefPayload, _: dict = Depends(get_current_user)):
        vidi_id = [r.id for r in body.redovi if r.id is not None]
        if len(vidi_id) != len(set(vidi_id)):
            raise HTTPException(status_code=400, detail="Duplirani redovi u zahtevu")
        with engine.begin() as conn:
            postojeci = {r[0] for r in conn.execute(
                text("SELECT id FROM koeficijenti_prodaje")
            ).fetchall()}
            zadrzi = {r.id for r in body.redovi if r.id is not None}
            nepoznat = zadrzi - postojeci
            if nepoznat:
                raise HTTPException(
                    status_code=400,
                    detail=f"Redovi ne postoje: {sorted(nepoznat)[:10]}",
                )
            brisanje = postojeci - zadrzi
            if brisanje:
                conn.execute(text(
                    "DELETE FROM koeficijenti_prodaje WHERE id = ANY(:ids)"
                ), {"ids": sorted(brisanje)})
            for red in body.redovi:
                if red.id is None:
                    conn.execute(text("""
                        INSERT INTO koeficijenti_prodaje (struktura, adl, chd, inf, koeficijent, rucno)
                        VALUES (:s, :a, :c, :i, :k, :r)
                    """), {"s": red.struktura, "a": red.adl, "c": red.chd,
                           "i": red.inf, "k": red.koeficijent, "r": red.rucno})
                else:
                    conn.execute(text("""
                        UPDATE koeficijenti_prodaje
                        SET struktura = :s, adl = :a, chd = :c, inf = :i,
                            koeficijent = :k, rucno = :r, updated_at = NOW()
                        WHERE id = :id
                    """), {"s": red.struktura, "a": red.adl, "c": red.chd,
                           "i": red.inf, "k": red.koeficijent, "r": red.rucno,
                           "id": red.id})
            return _vrati_sve(conn)
