"""Dodatne usluge (katalog): naziv + iznos u EUR i u RSD (din).

Tabela `dodatne_usluge` je namerno drugačijeg imena od `dodatne` (stavke ugovora).
"""
from decimal import Decimal, ROUND_HALF_UP

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text

MAX_IZNOS = Decimal("9999999999.99")


def _zaokruzi(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class DodatnaUslugaIn(BaseModel):
    naziv: str = Field(..., max_length=200)
    iznos_eur: Decimal = Decimal("0")
    iznos_din: Decimal = Decimal("0")

    @field_validator("naziv")
    @classmethod
    def naziv_validan(cls, value):
        value = (value or "").strip()
        if not value:
            raise ValueError("Naziv je obavezan")
        return value

    @field_validator("iznos_eur", "iznos_din")
    @classmethod
    def iznos_validan(cls, value):
        if value < 0:
            raise ValueError("Iznos ne sme biti negativan")
        if value > MAX_IZNOS:
            raise ValueError("Iznos je prevelik")
        return _zaokruzi(value)


def init_dodatne_usluge(engine):
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS dodatne_usluge (
                id SERIAL PRIMARY KEY,
                naziv VARCHAR(200) NOT NULL,
                iznos_eur NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (iznos_eur >= 0),
                iznos_din NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (iznos_din >= 0),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        # opciona veza stavke ugovora sa katalogom (ON DELETE SET NULL — stavka ostaje sa svojim iznosima)
        conn.execute(text("ALTER TABLE dodatne ADD COLUMN IF NOT EXISTS dodatna_usluga_id INTEGER"))
        conn.execute(text("""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'dodatne_dodatna_usluga_fk') THEN
                    ALTER TABLE dodatne ADD CONSTRAINT dodatne_dodatna_usluga_fk
                        FOREIGN KEY (dodatna_usluga_id) REFERENCES dodatne_usluge(id) ON DELETE SET NULL;
                END IF;
            END $$
        """))


def _red(row):
    return {
        "id": row["id"],
        "naziv": row["naziv"],
        "iznos_eur": float(row["iznos_eur"]),
        "iznos_din": float(row["iznos_din"]),
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


def register_dodatne_usluge(api, engine, get_current_user):
    @api.get("/dodatne-usluge")
    def lista(_: dict = Depends(get_current_user)):
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT id, naziv, iznos_eur, iznos_din, created_at, updated_at
                FROM dodatne_usluge
                ORDER BY naziv, id
            """)).mappings().all()
        return [_red(r) for r in rows]

    @api.post("/dodatne-usluge", status_code=201)
    def kreiraj(body: DodatnaUslugaIn, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            row = conn.execute(text("""
                INSERT INTO dodatne_usluge (naziv, iznos_eur, iznos_din)
                VALUES (:naziv, :eur, :din)
                RETURNING id, naziv, iznos_eur, iznos_din, created_at, updated_at
            """), {"naziv": body.naziv, "eur": body.iznos_eur, "din": body.iznos_din}).mappings().one()
        return _red(row)

    @api.put("/dodatne-usluge/{item_id}")
    def izmeni(item_id: int, body: DodatnaUslugaIn, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            row = conn.execute(text("""
                UPDATE dodatne_usluge
                SET naziv = :naziv, iznos_eur = :eur, iznos_din = :din, updated_at = NOW()
                WHERE id = :id
                RETURNING id, naziv, iznos_eur, iznos_din, created_at, updated_at
            """), {"id": item_id, "naziv": body.naziv, "eur": body.iznos_eur, "din": body.iznos_din}).mappings().first()
        if row is None:
            raise HTTPException(status_code=404, detail="Dodatna usluga nije pronađena")
        return _red(row)

    @api.delete("/dodatne-usluge/{item_id}")
    def obrisi(item_id: int, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            res = conn.execute(text("DELETE FROM dodatne_usluge WHERE id = :id"), {"id": item_id})
        if res.rowcount == 0:
            raise HTTPException(status_code=404, detail="Dodatna usluga nije pronađena")
        return {"status": "obrisano"}
