"""Dobavljači — tabela `dobavljaci` (kopija strukture `subagenti`, redovi sa provizija = 0).

Lista sa pretragom, unos, izmena i brisanje. Provizione kolone se ne menjaju kroz ove
endpointe (ostaju kakve su bile u kopiji).
"""
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

DOBAVLJACI_SEARCH_COLS = ("naziv", "punnaziv", "mesto", "adresa", "osoba", "tel", "tel1", "tel2", "pib", "matbroj", "email")

# Polja koja forma šalje (provizija kolone se ne diraju)
POLJA = ("naziv", "punnaziv", "adresa", "mesto", "osoba", "tel", "tel1", "tel2", "fax",
         "racun", "kontakt", "pib", "matbroj", "email")


class DobavljacIn(BaseModel):
    naziv: str = Field(..., min_length=1, max_length=200)
    punnaziv: str = Field("", max_length=300)
    adresa: str = Field("", max_length=200)
    mesto: str = Field("", max_length=100)
    osoba: str = Field("", max_length=200)
    tel: str = Field("", max_length=100)
    tel1: str = Field("", max_length=100)
    tel2: str = Field("", max_length=200)
    fax: str = Field("", max_length=100)
    racun: str = Field("", max_length=200)
    kontakt: str = Field("", max_length=300)
    pib: str = Field("", max_length=30)
    matbroj: str = Field("", max_length=20)
    email: str = Field("", max_length=200)


def init_dobavljaci(engine) -> None:
    ddl = """
    CREATE TABLE IF NOT EXISTS dobavljaci (
      id INTEGER PRIMARY KEY,
      naziv VARCHAR(200) DEFAULT '',
      adresa VARCHAR(200) DEFAULT '',
      mesto VARCHAR(100) DEFAULT '',
      osoba VARCHAR(200) DEFAULT '',
      tel VARCHAR(100) DEFAULT '',
      tel1 VARCHAR(100) DEFAULT '',
      tel2 VARCHAR(200) DEFAULT '',
      fax VARCHAR(100) DEFAULT '',
      racun VARCHAR(200) DEFAULT '',
      provizija DOUBLE PRECISION DEFAULT 0,
      provizija1 DOUBLE PRECISION DEFAULT 0,
      provizija1a DOUBLE PRECISION DEFAULT 0,
      provizija2 DOUBLE PRECISION DEFAULT 0,
      punnaziv VARCHAR(300) DEFAULT '',
      kontakt VARCHAR(300) DEFAULT '',
      pib VARCHAR(30) DEFAULT '',
      matbroj VARCHAR(20) DEFAULT '',
      email VARCHAR(200) DEFAULT '',
      ta BOOLEAN DEFAULT TRUE
    )
    """
    with engine.begin() as conn:
        conn.execute(text(ddl))
        # id sekvenca za nove redove; start iznad postojećeg maksimuma
        conn.execute(text("CREATE SEQUENCE IF NOT EXISTS dobavljaci_id_seq"))
        conn.execute(text(
            "SELECT setval('dobavljaci_id_seq', GREATEST((SELECT COALESCE(MAX(id), 0) FROM dobavljaci), "
            "(SELECT last_value FROM dobavljaci_id_seq)))"
        ))
        conn.execute(text("ALTER TABLE dobavljaci ALTER COLUMN id SET DEFAULT nextval('dobavljaci_id_seq')"))


def register_dobavljaci(api, engine, get_current_user):
    @api.get("/dobavljaci")
    def list_dobavljaci(q: str = "", _: dict = Depends(get_current_user)):
        q = q.strip()
        where = ""
        bind = {}
        if q:
            ors = " OR ".join(f"COALESCE({c}, '') ILIKE :q" for c in DOBAVLJACI_SEARCH_COLS)
            where = f"WHERE {ors}"
            bind["q"] = f"%{q}%"
        with engine.connect() as conn:
            rows = conn.execute(text(f"""
                SELECT id, naziv, punnaziv, adresa, mesto, osoba, tel, tel1, tel2, fax,
                       racun, pib, matbroj, email, kontakt
                FROM dobavljaci
                {where}
                ORDER BY naziv ASC, id ASC
            """), bind).fetchall()
        return {"rows": [dict(r._mapping) for r in rows], "total": len(rows)}

    @api.post("/dobavljaci", status_code=201)
    def create_dobavljac(body: DobavljacIn, _: dict = Depends(get_current_user)):
        vals = {k: getattr(body, k).strip() for k in POLJA}
        cols = ", ".join(POLJA)
        params = ", ".join(f":{k}" for k in POLJA)
        with engine.begin() as conn:
            new_id = conn.execute(text(
                f"INSERT INTO dobavljaci ({cols}) VALUES ({params}) RETURNING id"
            ), vals).scalar()
        return {"status": "kreirano", "id": new_id}

    @api.put("/dobavljaci/{item_id}")
    def update_dobavljac(item_id: int, body: DobavljacIn, _: dict = Depends(get_current_user)):
        vals = {k: getattr(body, k).strip() for k in POLJA}
        vals["id"] = item_id
        sets = ", ".join(f"{k} = :{k}" for k in POLJA)
        with engine.begin() as conn:
            res = conn.execute(text(f"UPDATE dobavljaci SET {sets} WHERE id = :id"), vals)
        if res.rowcount == 0:
            raise HTTPException(status_code=404, detail="Dobavljač nije pronađen")
        return {"status": "sacuvano", "id": item_id}

    @api.delete("/dobavljaci/{item_id}")
    def delete_dobavljac(item_id: int, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            res = conn.execute(text("DELETE FROM dobavljaci WHERE id = :id"), {"id": item_id})
        if res.rowcount == 0:
            raise HTTPException(status_code=404, detail="Dobavljač nije pronađen")
        return {"status": "obrisano", "id": item_id}
