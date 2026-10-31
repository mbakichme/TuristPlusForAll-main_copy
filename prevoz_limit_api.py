"""Limiti prevoz: broj mesta u autobusu po državi → destinaciji → mestu → grupi
termina → datumu i smeru (Odlazak / Povratak), uz dodatna mesta (+ ili −).

Hijerarhija veza (zavisna polja):
  drzava ← destinacija.drzava
  destinacija ← mesto.destinacija
  mesto ↔ grupa termina preko mesto_grupa (autoritativna veza)

Naziv se računa iz veza: Država-Destinacija-Mesto-Grupa Termina-dd.mm.yyyy
Veze su samo ID-jevi (bez FK, po konvenciji projekta).
"""
from datetime import date
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

SMEROVI = ("Odlazak", "Povratak")
DATUM_FMT = "%d.%m.%Y"

# Parovi (mesto_id, grupa_id) iz mesto_grupa — jedini izvor istine
MESTO_GRUPA_SQL = "SELECT mg.mesto_id, mg.grupa_id FROM mesto_grupa mg"


class PrevozLimitIn(BaseModel):
    drzava_id: int
    destinacija_id: int
    mesto_id: int
    grupa_datuma_id: int
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


def naziv_zapisa(drzava: str, destinacija: str, mesto: str, grupa: str, datum: date) -> str:
    return f"{drzava}-{destinacija}-{mesto}-{grupa}-{datum.strftime(DATUM_FMT)}"


def init_prevoz_limit(engine):
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS prevoz_limit (
                id SERIAL PRIMARY KEY,
                naziv VARCHAR(300) NOT NULL,
                drzava_id INTEGER,
                destinacija_id INTEGER,
                mesto_id INTEGER,
                grupa_datuma_id INTEGER,
                datum DATE,
                smer VARCHAR(20) NOT NULL,
                limit_mesta INTEGER NOT NULL DEFAULT 0 CHECK (limit_mesta >= 0),
                dodatna_mesta INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """))
        conn.execute(text("ALTER TABLE prevoz_limit ADD COLUMN IF NOT EXISTS drzava_id INTEGER"))
        conn.execute(text("ALTER TABLE prevoz_limit ADD COLUMN IF NOT EXISTS datum DATE"))
        conn.execute(text("ALTER TABLE prevoz_limit ALTER COLUMN naziv TYPE VARCHAR(300)"))
        # jedan zapis po (mesto, grupa, datum, smer) — generisanje je idempotentno
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS prevoz_limit_uniq
            ON prevoz_limit (mesto_id, grupa_datuma_id, datum, smer)
        """))


SELECT_SQL = """
    SELECT p.id, p.naziv, p.drzava_id, p.destinacija_id, p.mesto_id, p.grupa_datuma_id,
           p.datum, p.smer, p.limit_mesta, p.dodatna_mesta,
           dr.naziv AS drzava_naziv, de.naziv AS destinacija_naziv,
           m.naziv AS mesto_naziv, pg.naziv AS grupa_datuma_naziv
    FROM prevoz_limit p
    LEFT JOIN drzava dr ON dr.id = p.drzava_id
    LEFT JOIN destinacija de ON de.id = p.destinacija_id
    LEFT JOIN mesto m ON m.id = p.mesto_id
    LEFT JOIN period_grupa pg ON pg.id = p.grupa_datuma_id
"""


def _red(r):
    return {
        "id": r.id,
        "naziv": r.naziv,
        "drzava_id": r.drzava_id,
        "drzava_naziv": r.drzava_naziv,
        "destinacija_id": r.destinacija_id,
        "destinacija_naziv": r.destinacija_naziv,
        "mesto_id": r.mesto_id,
        "mesto_naziv": r.mesto_naziv,
        "grupa_datuma_id": r.grupa_datuma_id,
        "grupa_datuma_naziv": r.grupa_datuma_naziv,
        "datum": r.datum.isoformat() if r.datum else None,
        "smer": r.smer,
        "limit": r.limit_mesta,
        "dodatna_mesta": r.dodatna_mesta,
        "ukupno": r.limit_mesta + r.dodatna_mesta,
    }


def _naziv_iz_veza(conn, body: PrevozLimitIn) -> str:
    """Proverava zavisnost veza na serveru i vraća računati naziv."""
    drz = conn.execute(text("SELECT naziv FROM drzava WHERE id = :i"), {"i": body.drzava_id}).first()
    if not drz:
        raise HTTPException(status_code=400, detail="Nepoznata država")
    dest = conn.execute(
        text("SELECT naziv, drzava FROM destinacija WHERE id = :i"), {"i": body.destinacija_id}
    ).first()
    if not dest:
        raise HTTPException(status_code=400, detail="Nepoznata destinacija")
    if dest.drzava != body.drzava_id:
        raise HTTPException(status_code=400, detail="Destinacija ne pripada izabranoj državi")
    mesto = conn.execute(
        text("SELECT naziv, destinacija FROM mesto WHERE id = :i"), {"i": body.mesto_id}
    ).first()
    if not mesto:
        raise HTTPException(status_code=400, detail="Nepoznato mesto")
    if mesto.destinacija != body.destinacija_id:
        raise HTTPException(status_code=400, detail="Mesto ne pripada izabranoj destinaciji")
    grupa = conn.execute(text(f"""
        SELECT pg.naziv FROM period_grupa pg
        WHERE pg.id = :g AND EXISTS (
            SELECT 1 FROM ({MESTO_GRUPA_SQL}) x WHERE x.mesto_id = :m AND x.grupa_id = pg.id)
    """), {"g": body.grupa_datuma_id, "m": body.mesto_id}).first()
    if not grupa:
        raise HTTPException(status_code=400, detail="Grupa termina nije vezana za izabrano mesto")
    return naziv_zapisa(drz.naziv, dest.naziv, mesto.naziv, grupa.naziv, body.datum)


def _params(body: PrevozLimitIn, naziv: str) -> dict:
    return {
        "naziv": naziv,
        "drz": body.drzava_id,
        "dest": body.destinacija_id,
        "mesto": body.mesto_id,
        "grupa": body.grupa_datuma_id,
        "datum": body.datum,
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
                   OR dr.naziv ILIKE :q OR de.naziv ILIKE :q
                   OR m.naziv ILIKE :q OR pg.naziv ILIKE :q
            """
            params["q"] = f"%{q}%"
        with engine.connect() as conn:
            rows = conn.execute(
                text(SELECT_SQL + uslov + " ORDER BY p.datum NULLS LAST, p.naziv, p.id"),
                params,
            ).fetchall()
        return [_red(r) for r in rows]

    @api.post("/prevoz-limit", status_code=201)
    def create_prevoz_limit(body: PrevozLimitIn, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            naziv = _naziv_iz_veza(conn, body)
            try:
                new_id = conn.execute(text("""
                    INSERT INTO prevoz_limit (naziv, drzava_id, destinacija_id, mesto_id, grupa_datuma_id,
                                              datum, smer, limit_mesta, dodatna_mesta)
                    VALUES (:naziv, :drz, :dest, :mesto, :grupa, :datum, :smer, :limit, :dod)
                    RETURNING id
                """), _params(body, naziv)).scalar_one()
            except IntegrityError:
                raise HTTPException(status_code=409, detail="Limit za ovo mesto, termin, datum i smer već postoji")
        return {"status": "kreirano", "id": new_id}

    @api.put("/prevoz-limit/{item_id}")
    def update_prevoz_limit(item_id: int, body: PrevozLimitIn, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            naziv = _naziv_iz_veza(conn, body)
            try:
                res = conn.execute(text("""
                    UPDATE prevoz_limit
                    SET naziv = :naziv, drzava_id = :drz, destinacija_id = :dest, mesto_id = :mesto,
                        grupa_datuma_id = :grupa, datum = :datum, smer = :smer,
                        limit_mesta = :limit, dodatna_mesta = :dod, updated_at = NOW()
                    WHERE id = :id
                """), {**_params(body, naziv), "id": item_id})
            except IntegrityError:
                raise HTTPException(status_code=409, detail="Limit za ovo mesto, termin, datum i smer već postoji")
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
        """Za svaku grupu termina → mesta vezana za nju → destinacija i država mesta;
        za svaki period (od, do) dva zapisa: Odlazak na datum od, Povratak na datum do.
        Postojeći zapisi (ista kombinacija mesto/grupa/datum/smer) se preskaču."""
        with engine.begin() as conn:
            drz_nazivi = {r.id: r.naziv for r in conn.execute(text("SELECT id, naziv FROM drzava")).fetchall()}
            dest = {r.id: (r.naziv, r.drzava) for r in conn.execute(
                text("SELECT id, naziv, drzava FROM destinacija")).fetchall()}
            mesta = {r.id: (r.naziv, r.destinacija) for r in conn.execute(
                text("SELECT id, naziv, destinacija FROM mesto")).fetchall()}
            grupe = {r.id: r.naziv for r in conn.execute(text("SELECT id, naziv FROM period_grupa")).fetchall()}
            veze = conn.execute(text(f"""
                SELECT x.mesto_id, x.grupa_id, pd.datum_od, pd.datum_do
                FROM ({MESTO_GRUPA_SQL}) x
                JOIN period_datum pd ON pd.grupa_id = x.grupa_id
                ORDER BY x.mesto_id, x.grupa_id, pd.datum_od
            """)).fetchall()

            dodato = postojeci = preskoceno = 0
            for v in veze:
                mesto_naziv, dest_id = mesta.get(v.mesto_id, (None, None))
                if dest_id is None or dest_id not in dest:
                    preskoceno += 1
                    continue
                dest_naziv, drz_id = dest[dest_id]
                if drz_id is None or drz_id not in drz_nazivi:
                    preskoceno += 1
                    continue
                for datum, smer in ((v.datum_od, "Odlazak"), (v.datum_do, "Povratak")):
                    naziv = naziv_zapisa(drz_nazivi[drz_id], dest_naziv, mesto_naziv,
                                         grupe[v.grupa_id], datum)
                    res = conn.execute(text("""
                        INSERT INTO prevoz_limit (naziv, drzava_id, destinacija_id, mesto_id,
                                                  grupa_datuma_id, datum, smer, limit_mesta, dodatna_mesta)
                        VALUES (:naziv, :drz, :dest, :mesto, :grupa, :datum, :smer, 0, 0)
                        ON CONFLICT (mesto_id, grupa_datuma_id, datum, smer) DO NOTHING
                        RETURNING id
                    """), {"naziv": naziv, "drz": drz_id, "dest": dest_id, "mesto": v.mesto_id,
                           "grupa": v.grupa_id, "datum": datum, "smer": smer})
                    if res.first() is None:
                        postojeci += 1
                    else:
                        dodato += 1
        return {"status": "generisano", "dodato": dodato, "postojeci": postojeci, "preskoceno": preskoceno}
