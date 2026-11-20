"""Banke — tabela `banke` (šifra, naziv, broj računa, mesto).

Lista sa pretragom (q), unos, izmena i brisanje. Čekovi čuvaju naziv i broj računa
banke kao snimak (bez FK), pa brisanje banke ne menja postojeće čekove.
"""
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

BANKE_SEARCH_COLS = ("sifra", "naziv", "racun", "mesto")


class BankaIn(BaseModel):
    sifra: str = Field(..., min_length=1, max_length=20)
    naziv: str = Field(..., min_length=1, max_length=200)
    racun: str = Field(..., min_length=1, max_length=50)
    mesto: str = Field(..., min_length=1, max_length=100)


def _cisto(body: BankaIn) -> dict:
    vals = {k: (getattr(body, k) or "").strip() for k in ("sifra", "naziv", "racun", "mesto")}
    for k, v in vals.items():
        if not v:
            raise HTTPException(status_code=400, detail=f"Polje '{k}' je obavezno")
    return vals


def init_banke(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS banke (
                id SERIAL PRIMARY KEY,
                sifra VARCHAR(20) NOT NULL UNIQUE,
                naziv VARCHAR(200) NOT NULL,
                racun VARCHAR(50) NOT NULL,
                mesto VARCHAR(100) NOT NULL
            )
        """))


def register_banke(api, engine, get_current_user):
    @api.get("/banke")
    def list_banke(q: str = "", _: dict = Depends(get_current_user)):
        q = q.strip()
        where = ""
        bind = {}
        if q:
            ors = " OR ".join(f"COALESCE({c}, '') ILIKE :q" for c in BANKE_SEARCH_COLS)
            where = f"WHERE {ors}"
            bind["q"] = f"%{q}%"
        with engine.connect() as conn:
            rows = conn.execute(text(f"""
                SELECT id, sifra, naziv, racun, mesto
                FROM banke
                {where}
                ORDER BY naziv ASC, id ASC
            """), bind).fetchall()
        return {"rows": [dict(r._mapping) for r in rows], "total": len(rows)}

    @api.post("/banke", status_code=201)
    def create_banka(body: BankaIn, _: dict = Depends(get_current_user)):
        vals = _cisto(body)
        with engine.begin() as conn:
            zauzeta = conn.execute(text("SELECT 1 FROM banke WHERE sifra = :s"), {"s": vals["sifra"]}).fetchone()
            if zauzeta:
                raise HTTPException(status_code=409, detail="Banka sa tom šifrom već postoji")
            new_id = conn.execute(text("""
                INSERT INTO banke (sifra, naziv, racun, mesto)
                VALUES (:sifra, :naziv, :racun, :mesto)
                RETURNING id
            """), vals).scalar_one()
        return {"status": "kreirano", "id": new_id}

    @api.put("/banke/{item_id}")
    def update_banka(item_id: int, body: BankaIn, _: dict = Depends(get_current_user)):
        vals = _cisto(body)
        vals["id"] = item_id
        with engine.begin() as conn:
            zauzeta = conn.execute(text(
                "SELECT 1 FROM banke WHERE sifra = :s AND id <> :id"
            ), {"s": vals["sifra"], "id": item_id}).fetchone()
            if zauzeta:
                raise HTTPException(status_code=409, detail="Banka sa tom šifrom već postoji")
            res = conn.execute(text("""
                UPDATE banke SET sifra = :sifra, naziv = :naziv, racun = :racun, mesto = :mesto
                WHERE id = :id
            """), vals)
        if res.rowcount == 0:
            raise HTTPException(status_code=404, detail="Banka nije pronađena")
        return {"status": "sacuvano", "id": item_id}

    @api.delete("/banke/{item_id}")
    def delete_banka(item_id: int, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            res = conn.execute(text("DELETE FROM banke WHERE id = :id"), {"id": item_id})
        if res.rowcount == 0:
            raise HTTPException(status_code=404, detail="Banka nije pronađena")
        return {"status": "obrisano", "id": item_id}
