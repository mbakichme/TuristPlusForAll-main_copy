"""Limiti prevoz: broj mesta u autobusu po nazivu, destinaciji, mestu, grupi
termina i smeru (polazak/povratak), uz dodatna mesta (može pozitivno ili negativno).

Veze na destinacija / mesto / period_grupa su samo ID-jevi (bez FK, po konvenciji
projekta); nazivi se spajaju u listi.
"""
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text

SMEROVI = ("Polazak", "Povratak")


class PrevozLimitIn(BaseModel):
    naziv: str = Field(..., max_length=200)
    destinacija_id: Optional[int] = None
    mesto_id: Optional[int] = None
    grupa_datuma_id: Optional[int] = None
    smer: str
    limit: int = Field(..., ge=0, le=999)
    dodatna_mesta: int = Field(0, ge=-999, le=999)

    @field_validator("naziv")
    @classmethod
    def naziv_obavezan(cls, value):
        value = (value or "").strip()
        if not value:
            raise ValueError("Naziv je obavezan")
        return value

    @field_validator("smer")
    @classmethod
    def smer_ispravan(cls, value):
        if value not in SMEROVI:
            raise ValueError("Smer mora biti Polazak ili Povratak")
        return value


def init_prevoz_limit(engine):
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS prevoz_limit (
                id SERIAL PRIMARY KEY,
                naziv VARCHAR(200) NOT NULL,
                destinacija_id INTEGER,
                mesto_id INTEGER,
                grupa_datuma_id INTEGER,
                smer VARCHAR(20) NOT NULL,
                limit_mesta INTEGER NOT NULL DEFAULT 0 CHECK (limit_mesta >= 0),
                dodatna_mesta INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """))


SELECT_SQL = """
    SELECT p.id, p.naziv, p.destinacija_id, p.mesto_id, p.grupa_datuma_id, p.smer,
           p.limit_mesta, p.dodatna_mesta,
           de.naziv AS destinacija_naziv, m.naziv AS mesto_naziv, pg.naziv AS grupa_datuma_naziv
    FROM prevoz_limit p
    LEFT JOIN destinacija de ON de.id = p.destinacija_id
    LEFT JOIN mesto m ON m.id = p.mesto_id
    LEFT JOIN period_grupa pg ON pg.id = p.grupa_datuma_id
"""


def _red(r):
    return {
        "id": r.id,
        "naziv": r.naziv,
        "destinacija_id": r.destinacija_id,
        "destinacija_naziv": r.destinacija_naziv,
        "mesto_id": r.mesto_id,
        "mesto_naziv": r.mesto_naziv,
        "grupa_datuma_id": r.grupa_datuma_id,
        "grupa_datuma_naziv": r.grupa_datuma_naziv,
        "smer": r.smer,
        "limit": r.limit_mesta,
        "dodatna_mesta": r.dodatna_mesta,
        "ukupno": r.limit_mesta + r.dodatna_mesta,
    }


def _proveri_veze(conn, body: PrevozLimitIn):
    if body.destinacija_id is not None and not conn.execute(
        text("SELECT 1 FROM destinacija WHERE id = :i"), {"i": body.destinacija_id}
    ).first():
        raise HTTPException(status_code=400, detail="Nepoznata destinacija")
    if body.mesto_id is not None and not conn.execute(
        text("SELECT 1 FROM mesto WHERE id = :i"), {"i": body.mesto_id}
    ).first():
        raise HTTPException(status_code=400, detail="Nepoznato mesto")
    if body.grupa_datuma_id is not None and not conn.execute(
        text("SELECT 1 FROM period_grupa WHERE id = :i"), {"i": body.grupa_datuma_id}
    ).first():
        raise HTTPException(status_code=400, detail="Nepoznata grupa termina")


def _params(body: PrevozLimitIn) -> dict:
    return {
        "naziv": body.naziv,
        "dest": body.destinacija_id,
        "mesto": body.mesto_id,
        "grupa": body.grupa_datuma_id,
        "smer": body.smer,
        "limit": body.limit,
        "dod": body.dodatna_mesta,
    }


def register_prevoz_limit(api, engine, get_current_user):
    @api.get("/prevoz-limit")
    def list_prevoz_limit(q: str = "", _: dict = Depends(get_current_user)):
        q = (q or "").strip()
        uslov = ""
        params: dict = {}
        if q:
            uslov = """
                WHERE p.naziv ILIKE :q OR p.smer ILIKE :q
                   OR de.naziv ILIKE :q OR m.naziv ILIKE :q OR pg.naziv ILIKE :q
            """
            params["q"] = f"%{q}%"
        with engine.connect() as conn:
            rows = conn.execute(
                text(SELECT_SQL + uslov + " ORDER BY m.naziv NULLS LAST, p.naziv, p.id"),
                params,
            ).fetchall()
        return [_red(r) for r in rows]

    @api.post("/prevoz-limit", status_code=201)
    def create_prevoz_limit(body: PrevozLimitIn, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            _proveri_veze(conn, body)
            new_id = conn.execute(text("""
                INSERT INTO prevoz_limit (naziv, destinacija_id, mesto_id, grupa_datuma_id,
                                          smer, limit_mesta, dodatna_mesta)
                VALUES (:naziv, :dest, :mesto, :grupa, :smer, :limit, :dod)
                RETURNING id
            """), _params(body)).scalar_one()
        return {"status": "kreirano", "id": new_id}

    @api.put("/prevoz-limit/{item_id}")
    def update_prevoz_limit(item_id: int, body: PrevozLimitIn, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            _proveri_veze(conn, body)
            res = conn.execute(text("""
                UPDATE prevoz_limit
                SET naziv = :naziv, destinacija_id = :dest, mesto_id = :mesto,
                    grupa_datuma_id = :grupa, smer = :smer, limit_mesta = :limit,
                    dodatna_mesta = :dod, updated_at = NOW()
                WHERE id = :id
            """), {**_params(body), "id": item_id})
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
