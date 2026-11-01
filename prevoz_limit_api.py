"""Limiti prevoz i destinacije prevoza.

  destinacija_prevoz:       više redova može imati istu destinaciju (id_destinacije); naziv = naziv destinacije.
  destinacija_prevoz_grupa: veza destinacija prevoza ↔ grupa termina. Grupa termina može biti
                            vezana samo za JEDNU destinaciju prevoza (UNIQUE na id_grupe_termina).
                            Grupe se biraju među grupama povezanim sa destinacijom (preko mesta).
  prevoz_limit:             jedan red po (destinacija prevoza, datum, smer).
                            Odlazak = datum_od, Povratak = datum_do perioda grupa termina.

Veze su samo ID-jevi (bez FK, po konvenciji projekta).
"""
from datetime import date
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

SMEROVI = ("Odlazak", "Povratak")


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


class DestinacijaPrevozIn(BaseModel):
    id_destinacije: int
    grupe: list[int] = Field(..., min_length=1)


class DestinacijaPrevozBrzoIn(BaseModel):
    id_destinacije_prevoza: int


class DestinacijaPrevozGrupeIn(BaseModel):
    grupe: list[int] = Field(..., min_length=1)

    @field_validator("grupe")
    @classmethod
    def bez_duplikata(cls, value):
        return sorted(set(value))


def init_prevoz_limit(engine):
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS destinacija_prevoz (
                id SERIAL PRIMARY KEY,
                id_destinacije INTEGER NOT NULL,
                naziv VARCHAR(300) NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """))
        conn.execute(text("ALTER TABLE destinacija_prevoz DROP CONSTRAINT IF EXISTS destinacija_prevoz_destinacija_uniq"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS destinacija_prevoz_grupa (
                id SERIAL PRIMARY KEY,
                destinacija_prevoz_id INTEGER NOT NULL,
                id_grupe_termina INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                CONSTRAINT destinacija_prevoz_grupa_uniq UNIQUE (id_grupe_termina)
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
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS prevoz_limit_uniq
            ON prevoz_limit (id_destinacije_prevoza, datum, smer)
        """))


SELECT_SQL = """
    SELECT pl.id, pl.id_destinacije_prevoza, pl.datum, pl.smer, pl.limit_mesta, pl.dodatna_mesta,
           pl.created_at, pl.updated_at,
           dp.naziv AS destinacija_prevoz_naziv, dp.id_destinacije
    FROM prevoz_limit pl
    LEFT JOIN destinacija_prevoz dp ON dp.id = pl.id_destinacije_prevoza
"""


def _red_limita(r):
    return {
        "id": r.id,
        "id_destinacije_prevoza": r.id_destinacije_prevoza,
        "destinacija_prevoz_naziv": r.destinacija_prevoz_naziv,
        "id_destinacije": r.id_destinacije,
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


def _grupe_destinacije(conn, id_destinacije: int, dp_id: Optional[int]) -> set[int]:
    """Grupe termina povezane sa destinacijom (preko mesta); proverava da li su slobodne."""
    rows = conn.execute(text("""
        SELECT DISTINCT pg.id, dpg.destinacija_prevoz_id
        FROM mesto_grupa mg
        JOIN mesto m ON m.id = mg.mesto_id
        JOIN period_grupa pg ON pg.id = mg.grupa_id
        LEFT JOIN destinacija_prevoz_grupa dpg ON dpg.id_grupe_termina = pg.id
        WHERE m.destinacija = :d
    """), {"d": id_destinacije}).fetchall()
    return {r.id for r in rows}


def _proveri_grupe(conn, id_destinacije: int, grupe: list[int], dp_id: Optional[int]) -> None:
    dozvoljene = _grupe_destinacije(conn, id_destinacije, dp_id)
    if not set(grupe) <= dozvoljene:
        raise HTTPException(status_code=400, detail="Grupa termina nije povezana sa izabranom destinacijom")
    zauzete = conn.execute(text("""
        SELECT id_grupe_termina, destinacija_prevoz_id FROM destinacija_prevoz_grupa
        WHERE id_grupe_termina = ANY(:g) AND (:dp IS NULL OR destinacija_prevoz_id <> :dp)
    """), {"g": grupe, "dp": dp_id}).fetchall()
    if zauzete:
        raise HTTPException(status_code=409, detail="Neka grupa termina je već vezana za drugu destinaciju prevoza")


def _upisi_grupe(conn, dp_id: int, grupe: list[int]) -> None:
    conn.execute(text("DELETE FROM destinacija_prevoz_grupa WHERE destinacija_prevoz_id = :dp"), {"dp": dp_id})
    for g in grupe:
        conn.execute(text("""
            INSERT INTO destinacija_prevoz_grupa (destinacija_prevoz_id, id_grupe_termina)
            VALUES (:dp, :g)
        """), {"dp": dp_id, "g": g})


def register_prevoz_limit(api, engine, get_current_user):
    @api.get("/destinacija-prevoz")
    def list_destinacija_prevoz(_: dict = Depends(get_current_user)):
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT dp.id, dp.id_destinacije, dp.naziv, dp.created_at, dp.updated_at,
                       COALESCE(json_agg(json_build_object('id', pg.id, 'naziv', pg.naziv)
                                ORDER BY pg.naziv) FILTER (WHERE pg.id IS NOT NULL), '[]') AS grupe
                FROM destinacija_prevoz dp
                LEFT JOIN destinacija_prevoz_grupa dpg ON dpg.destinacija_prevoz_id = dp.id
                LEFT JOIN period_grupa pg ON pg.id = dpg.id_grupe_termina
                GROUP BY dp.id
                ORDER BY dp.naziv
            """)).fetchall()
        return [
            {"id": r.id, "id_destinacije": r.id_destinacije, "naziv": r.naziv,
             "grupe": r.grupe,
             "created_at": r.created_at.isoformat() if r.created_at else None,
             "updated_at": r.updated_at.isoformat() if r.updated_at else None}
            for r in rows
        ]

    @api.get("/destinacija-prevoz/grupe")
    def grupe_za_destinaciju(id_destinacije: int, dp_id: Optional[int] = None,
                             _: dict = Depends(get_current_user)):
        """Grupe termina povezane sa destinacijom; zauzeta = vezana za drugu destinaciju prevoza."""
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT DISTINCT pg.id, pg.naziv, dpg.destinacija_prevoz_id
                FROM mesto_grupa mg
                JOIN mesto m ON m.id = mg.mesto_id
                JOIN period_grupa pg ON pg.id = mg.grupa_id
                LEFT JOIN destinacija_prevoz_grupa dpg ON dpg.id_grupe_termina = pg.id
                WHERE m.destinacija = :d
                ORDER BY pg.naziv
            """), {"d": id_destinacije}).fetchall()
        return [
            {"id": r.id, "naziv": r.naziv,
             "zauzeta": r.destinacija_prevoz_id is not None and r.destinacija_prevoz_id != dp_id}
            for r in rows
        ]

    @api.post("/destinacija-prevoz", status_code=201)
    def create_destinacija_prevoz(body: DestinacijaPrevozIn, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            dest = conn.execute(text("SELECT naziv FROM destinacija WHERE id = :i"),
                                {"i": body.id_destinacije}).first()
            if not dest:
                raise HTTPException(status_code=400, detail="Nepoznata destinacija")
            grupe = sorted(set(body.grupe))
            _proveri_grupe(conn, body.id_destinacije, grupe, None)
            new_id = conn.execute(text("""
                INSERT INTO destinacija_prevoz (id_destinacije, naziv)
                VALUES (:d, :n) RETURNING id
            """), {"d": body.id_destinacije, "n": dest.naziv}).scalar_one()
            _upisi_grupe(conn, new_id, grupe)
        return {"status": "kreirano", "id": new_id}

    @api.put("/destinacija-prevoz/{item_id}")
    def update_destinacija_prevoz(item_id: int, body: DestinacijaPrevozGrupeIn,
                                  _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            dp = conn.execute(text("SELECT id_destinacije FROM destinacija_prevoz WHERE id = :i"),
                              {"i": item_id}).first()
            if not dp:
                raise HTTPException(status_code=404, detail="Destinacija prevoza nije pronađena")
            _proveri_grupe(conn, dp.id_destinacije, body.grupe, item_id)
            _upisi_grupe(conn, item_id, body.grupe)
            conn.execute(text("UPDATE destinacija_prevoz SET updated_at = NOW() WHERE id = :i"), {"i": item_id})
        return {"status": "sacuvano", "id": item_id}

    @api.delete("/destinacija-prevoz/{item_id}")
    def delete_destinacija_prevoz(item_id: int, _: dict = Depends(get_current_user)):
        """Briše destinaciju prevoza, njene veze sa grupama i sve njene limite."""
        with engine.begin() as conn:
            if not conn.execute(text("SELECT 1 FROM destinacija_prevoz WHERE id = :i"), {"i": item_id}).first():
                raise HTTPException(status_code=404, detail="Destinacija prevoza nije pronađena")
            broj_limita = conn.execute(text(
                "DELETE FROM prevoz_limit WHERE id_destinacije_prevoza = :i"), {"i": item_id}).rowcount
            conn.execute(text("DELETE FROM destinacija_prevoz_grupa WHERE destinacija_prevoz_id = :i"), {"i": item_id})
            conn.execute(text("DELETE FROM destinacija_prevoz WHERE id = :i"), {"i": item_id})
        return {"status": "obrisano", "id": item_id, "broj_limita": broj_limita}

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
        return [_red_limita(r) for r in rows]

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

    @api.post("/prevoz-limit/kreiraj")
    def kreiraj_limite_za_destinaciju(body: DestinacijaPrevozBrzoIn, _: dict = Depends(get_current_user)):
        """Za izabranu destinaciju prevoza i sve njene grupe termina pravi red za svaki Odlazak
        (datum_od) i Povratak (datum_do). Limit i dodatna mesta kreću od 0.
        Postojeći red (destinacija, datum, smer) se ne menja i ne duplira."""
        with engine.begin() as conn:
            _proveri_destinaciju_prevoza(conn, body.id_destinacije_prevoza)
            ukupno = conn.execute(text("""
                SELECT count(*) FROM (
                    SELECT pd.datum_od AS datum, 'Odlazak' AS smer
                    FROM destinacija_prevoz_grupa dpg
                    JOIN period_datum pd ON pd.grupa_id = dpg.id_grupe_termina
                    WHERE dpg.destinacija_prevoz_id = :dp
                    UNION
                    SELECT pd.datum_do, 'Povratak'
                    FROM destinacija_prevoz_grupa dpg
                    JOIN period_datum pd ON pd.grupa_id = dpg.id_grupe_termina
                    WHERE dpg.destinacija_prevoz_id = :dp
                ) t
            """), {"dp": body.id_destinacije_prevoza}).scalar_one()
            dodato = 0
            for smer, kolona in (("Odlazak", "datum_od"), ("Povratak", "datum_do")):
                res = conn.execute(text(f"""
                    INSERT INTO prevoz_limit (id_destinacije_prevoza, datum, smer, limit_mesta, dodatna_mesta)
                    SELECT DISTINCT dpg.destinacija_prevoz_id, pd.{kolona}, :smer, 0, 0
                    FROM destinacija_prevoz_grupa dpg
                    JOIN period_datum pd ON pd.grupa_id = dpg.id_grupe_termina
                    WHERE dpg.destinacija_prevoz_id = :dp
                    ON CONFLICT (id_destinacije_prevoza, datum, smer) DO NOTHING
                """), {"smer": smer, "dp": body.id_destinacije_prevoza})
                dodato += res.rowcount
        return {"status": "kreirano", "dodato": dodato, "postojalo": ukupno - dodato}
