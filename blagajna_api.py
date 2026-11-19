"""Blagajna — tabela `blagajna` (datum blagajne, datum uplate, iznos, uplaceno da/ne).

Lista sa pretragom (q) po svim poljima, unos, izmena i brisanje.
"""
from datetime import date

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

BLAGAJNA_SEARCH_SQL = (
    "COALESCE(TO_CHAR(datum_blagajne, 'DD.MM.YYYY'), '') || ' ' || "
    "COALESCE(TO_CHAR(datum_uplate, 'DD.MM.YYYY'), '') || ' ' || "
    "COALESCE(CAST(iznos AS TEXT), '') || ' ' || "
    "CASE WHEN uplaceno THEN 'da uplaceno' ELSE 'ne nije uplaceno' END"
)


class BlagajnaIn(BaseModel):
    datum_blagajne: date
    datum_uplate: date
    iznos: float = Field(..., ge=0)
    uplaceno: bool = False


def init_blagajna(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS blagajna (
                id SERIAL PRIMARY KEY,
                datum_blagajne DATE NOT NULL,
                datum_uplate DATE NOT NULL,
                iznos NUMERIC(12,2) NOT NULL,
                uplaceno BOOLEAN NOT NULL DEFAULT FALSE
            )
        """))


def register_blagajna(api, engine, get_current_user):
    @api.get("/blagajna")
    def list_blagajna(q: str = "", _: dict = Depends(get_current_user)):
        q = q.strip()
        where = ""
        bind = {}
        if q:
            where = f"WHERE {BLAGAJNA_SEARCH_SQL} ILIKE :q"
            bind["q"] = f"%{q}%"
        with engine.connect() as conn:
            rows = conn.execute(text(f"""
                SELECT id, datum_blagajne, datum_uplate, iznos, uplaceno
                FROM blagajna
                {where}
                ORDER BY datum_blagajne DESC, id DESC
            """), bind).mappings().all()
        out = []
        for r in rows:
            d = dict(r)
            d["datum_blagajne"] = d["datum_blagajne"].isoformat()
            d["datum_uplate"] = d["datum_uplate"].isoformat()
            d["iznos"] = float(d["iznos"])
            out.append(d)
        return {"rows": out, "total": len(out)}

    @api.post("/blagajna", status_code=201)
    def create_blagajna(body: BlagajnaIn, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            new_id = conn.execute(text("""
                INSERT INTO blagajna (datum_blagajne, datum_uplate, iznos, uplaceno)
                VALUES (:datum_blagajne, :datum_uplate, :iznos, :uplaceno)
                RETURNING id
            """), body.model_dump()).scalar_one()
        return {"status": "kreirano", "id": new_id}

    @api.put("/blagajna/{item_id}")
    def update_blagajna(item_id: int, body: BlagajnaIn, _: dict = Depends(get_current_user)):
        vals = body.model_dump()
        vals["id"] = item_id
        with engine.begin() as conn:
            res = conn.execute(text("""
                UPDATE blagajna
                SET datum_blagajne = :datum_blagajne, datum_uplate = :datum_uplate,
                    iznos = :iznos, uplaceno = :uplaceno
                WHERE id = :id
            """), vals)
        if res.rowcount == 0:
            raise HTTPException(status_code=404, detail="Stavka blagajne nije pronađena")
        return {"status": "sacuvano", "id": item_id}

    @api.delete("/blagajna/{item_id}")
    def delete_blagajna(item_id: int, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            res = conn.execute(text("DELETE FROM blagajna WHERE id = :id"), {"id": item_id})
        if res.rowcount == 0:
            raise HTTPException(status_code=404, detail="Stavka blagajne nije pronađena")
        return {"status": "obrisano", "id": item_id}
