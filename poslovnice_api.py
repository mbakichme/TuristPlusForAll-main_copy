"""Poslovnice agencije: naziv, adresa, grad + RGZ podaci (opština / mesto / ulica).

Tabela `poslovnice` — CRUD preko /poslovnice (lista, dodaj, izmeni, obriši).
"""
from fastapi import Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import text

RGZ_POLJA = ("opstina_rgz", "opstina_naziv", "mesto_rgz", "mesto_naziv", "ulica_rgz", "ulica_naziv")
POLJA = ("naziv", "adresa", "grad") + RGZ_POLJA
MAX_LEN = {
    "naziv": 200, "adresa": 300, "grad": 200,
    "opstina_rgz": 100, "opstina_naziv": 200, "mesto_rgz": 100,
    "mesto_naziv": 200, "ulica_rgz": 100, "ulica_naziv": 300,
}


class PoslovnicaIn(BaseModel):
    naziv: str
    adresa: str = ""
    grad: str = ""
    opstina_rgz: str = ""
    opstina_naziv: str = ""
    mesto_rgz: str = ""
    mesto_naziv: str = ""
    ulica_rgz: str = ""
    ulica_naziv: str = ""

    @field_validator(*POLJA, mode="before")
    @classmethod
    def ocisti(cls, value):
        return "" if value is None else str(value).strip()

    @field_validator(*POLJA)
    @classmethod
    def duzina(cls, value, info):
        limit = MAX_LEN.get(info.field_name)
        if limit and len(value) > limit:
            raise ValueError(f"Polje je predugačko (najviše {limit} znakova)")
        return value

    @field_validator("naziv")
    @classmethod
    def naziv_obavezan(cls, value):
        if not value:
            raise ValueError("Naziv poslovnice je obavezan")
        return value


def init_poslovnice(engine):
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS poslovnice (
                id SERIAL PRIMARY KEY,
                naziv VARCHAR(200) NOT NULL,
                adresa VARCHAR(300) NOT NULL DEFAULT '',
                grad VARCHAR(200) NOT NULL DEFAULT '',
                opstina_rgz VARCHAR(100) NOT NULL DEFAULT '',
                opstina_naziv VARCHAR(200) NOT NULL DEFAULT '',
                mesto_rgz VARCHAR(100) NOT NULL DEFAULT '',
                mesto_naziv VARCHAR(200) NOT NULL DEFAULT '',
                ulica_rgz VARCHAR(100) NOT NULL DEFAULT '',
                ulica_naziv VARCHAR(300) NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))


def register_poslovnice(api, engine, get_current_user):
    cols = ", ".join(("id",) + POLJA)

    @api.get("/poslovnice")
    def lista(_: dict = Depends(get_current_user)):
        with engine.connect() as conn:
            rows = conn.execute(text(f"SELECT {cols} FROM poslovnice ORDER BY naziv, id")).mappings().all()
        return {"poslovnice": [dict(r) for r in rows]}

    @api.post("/poslovnice", status_code=201)
    def dodaj(body: PoslovnicaIn, _: dict = Depends(get_current_user)):
        params = body.model_dump()
        with engine.begin() as conn:
            new_id = conn.execute(text(f"""
                INSERT INTO poslovnice ({", ".join(POLJA)})
                VALUES ({", ".join(f":{p}" for p in POLJA)})
                RETURNING id
            """), params).scalar()
        return {"id": new_id, "status": "dodato"}

    @api.put("/poslovnice/{pid}")
    def izmeni(pid: int, body: PoslovnicaIn, _: dict = Depends(get_current_user)):
        params = body.model_dump()
        params["id"] = pid
        with engine.begin() as conn:
            res = conn.execute(text(f"""
                UPDATE poslovnice SET {", ".join(f"{p} = :{p}" for p in POLJA)}, updated_at = NOW()
                WHERE id = :id
            """), params)
            if res.rowcount == 0:
                raise HTTPException(status_code=404, detail="Poslovnica nije pronađena")
        return {"id": pid, "status": "sacuvano"}

    @api.delete("/poslovnice/{pid}")
    def obrisi(pid: int, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            res = conn.execute(text("DELETE FROM poslovnice WHERE id = :id"), {"id": pid})
            if res.rowcount == 0:
                raise HTTPException(status_code=404, detail="Poslovnica nije pronađena")
            # korisnici ostaju, samo gube vezu sa obrisanom poslovnicom
            conn.execute(text("UPDATE users SET poslovnica_id = NULL WHERE poslovnica_id = :id"), {"id": pid})
        return {"id": pid, "status": "obrisano"}
