"""Cenovnici: trajni snimak soba/termina i cene za ceo termin."""
import json
from datetime import date
from decimal import Decimal
from uuid import uuid4

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import text


class CenaIn(BaseModel):
    soba_id: int
    period_id: int
    cena: Decimal

    @field_validator("cena")
    @classmethod
    def validna_cena(cls, value):
        if not value.is_finite() or value < 0 or value >= Decimal("1000000000000"):
            raise ValueError("Cena mora biti konačan, nenegativan iznos manji od 1000000000000")
        if value != value.quantize(Decimal("0.01")):
            raise ValueError("Cena može imati najviše dve decimale")
        return value


class CenovnikIzmena(BaseModel):
    datumod: date
    datumdo: date
    cene: list[CenaIn] = Field(default_factory=list, max_length=100000)

    @model_validator(mode="after")
    def validni_datumi(self):
        if self.datumod > self.datumdo:
            raise ValueError("Aktivan od mora biti pre ili isti kao Aktivan do")
        return self


class CenovnikNovi(CenovnikIzmena):
    mesto_id: int
    grupa_id: int
    smestaj_id: int


def init_cenovnici(engine):
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS cenovnici (
                id SERIAL PRIMARY KEY, uuid UUID NOT NULL UNIQUE,
                naziv TEXT NOT NULL, mesto_id INTEGER NOT NULL,
                grupa_id INTEGER NOT NULL, smestaj_id INTEGER NOT NULL,
                sobe JSONB NOT NULL, periodi JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS cenovnik_opcije (
                cenovnik_id INTEGER PRIMARY KEY REFERENCES cenovnici(id) ON DELETE CASCADE,
                datumod DATE NOT NULL, datumdo DATE NOT NULL,
                CHECK (datumod <= datumdo)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS cenovnik_cene (
                cenovnik_id INTEGER NOT NULL REFERENCES cenovnici(id) ON DELETE CASCADE,
                soba_id INTEGER NOT NULL, period_id INTEGER NOT NULL,
                cena NUMERIC(14,2) NOT NULL CHECK (cena >= 0),
                PRIMARY KEY (cenovnik_id, soba_id, period_id)
            )
        """))


def _sablon(conn, mesto_id, grupa_id, smestaj_id):
    ref = conn.execute(text("""
        SELECT m.naziv AS mesto_naziv, s.naziv AS smestaj_naziv, g.naziv AS grupa_naziv
        FROM smestaj s JOIN mesto m ON m.id = s.mesto
        JOIN period_grupa g ON g.id = s.grupa_datuma
        WHERE m.id = :m AND s.id = :s AND g.id = :g
        AND (m.grupa_datuma = :g OR EXISTS (
            SELECT 1 FROM mesto_grupa mg WHERE mg.mesto_id = m.id AND mg.grupa_id = :g
        ))
    """), {"m": mesto_id, "g": grupa_id, "s": smestaj_id}).mappings().first()
    if not ref:
        raise HTTPException(400, "Mesto, grupa termina i smeštaj nisu povezani")
    sobe = [dict(r) for r in conn.execute(text("""
        SELECT id, broj_sobe, tip, opis, opis_dodatno FROM sobe
        WHERE veza_id_smestaj = :s ORDER BY broj_sobe, id
    """), {"s": smestaj_id}).mappings()]
    periodi = []
    for r in conn.execute(text("""
        SELECT id, datum_od, datum_do FROM period_datum
        WHERE grupa_id = :g ORDER BY datum_od, datum_do, id
    """), {"g": grupa_id}).mappings():
        nocenja = (r["datum_do"] - r["datum_od"]).days
        if nocenja <= 0:
            raise HTTPException(400, "Grupa sadrži termin bez pozitivnog broja noćenja")
        periodi.append({"id": r["id"], "datum_od": r["datum_od"].isoformat(),
                        "datum_do": r["datum_do"].isoformat(), "nocenja": nocenja})
    if not sobe or not periodi:
        raise HTTPException(400, "Smeštaj mora imati sobe, a grupa definisane termine")
    # Virtuelne sobe: za svaku sobu sa dodatnim koeficijentima (soba_koeficijenti)
    # kreira se red odmah ispod nje — v{broj} (jedan dodatni koeficijent), odnosno
    # v{broj}-1, v{broj}-2… (više njih). Id je negativan i važi SAMO u okviru
    # ovog cenovnika; veza sa sobom od koje je nastala je izvor_soba_id.
    # Ne upisuju se u tabelu sobe — žive u JSONB snimku cenovnika.
    dodatni: dict[int, list[str]] = {}
    for r in conn.execute(text("""
        SELECT k.soba_id, k.struktura FROM soba_koeficijenti k
        JOIN sobe s ON s.id = k.soba_id
        WHERE s.veza_id_smestaj = :s ORDER BY k.soba_id, k.id
    """), {"s": smestaj_id}).fetchall():
        dodatni.setdefault(r.soba_id, []).append(r.struktura)
    sa_virtuelnim: list[dict] = []
    virtual_id = 0
    for sob in sobe:
        sa_virtuelnim.append(sob)
        strukture = dodatni.get(sob["id"], [])
        broj = sob["broj_sobe"] or str(sob["id"])
        for i, struktura in enumerate(strukture, start=1):
            virtual_id -= 1
            sa_virtuelnim.append({
                "id": virtual_id,
                "broj_sobe": f"v{broj}" if len(strukture) == 1 else f"v{broj}-{i}",
                "tip": struktura,
                "opis": sob["opis"] or "",
                "opis_dodatno": sob["opis_dodatno"] or "",
                "izvor_soba_id": sob["id"],
                "virtuelna": True,
            })
    sobe = sa_virtuelnim
    return {"naziv": f'{ref["mesto_naziv"]}-{ref["smestaj_naziv"]}-{ref["grupa_naziv"]}',
            "mesto_id": mesto_id, "grupa_id": grupa_id, "smestaj_id": smestaj_id,
            "sobe": sobe, "periodi": periodi, "cene": [], "datumod": None, "datumdo": None}


def _detail(conn, item_id, lock=False):
    r = conn.execute(text("""
        SELECT c.*, o.datumod, o.datumdo FROM cenovnici c
        JOIN cenovnik_opcije o ON o.cenovnik_id = c.id WHERE c.id = :id
    """ + (" FOR UPDATE OF c" if lock else "")), {"id": item_id}).mappings().first()
    if not r:
        raise HTTPException(404, "Cenovnik nije pronađen")
    result = dict(r)
    result["uuid"] = str(result["uuid"])
    result["cene"] = [{"soba_id": x.soba_id, "period_id": x.period_id, "cena": str(x.cena)}
                      for x in conn.execute(text("""
                          SELECT soba_id, period_id, cena FROM cenovnik_cene
                          WHERE cenovnik_id = :id ORDER BY soba_id, period_id
                      """), {"id": item_id})]
    return result


def _save_values(conn, item_id, body, snapshot):
    rooms = {x["id"] for x in snapshot["sobe"]}
    periods = {x["id"] for x in snapshot["periodi"]}
    seen = set()
    for cell in body.cene:
        key = (cell.soba_id, cell.period_id)
        if cell.soba_id not in rooms or cell.period_id not in periods:
            raise HTTPException(400, "Cena ne pripada sobi/terminu ovog cenovnika")
        if key in seen:
            raise HTTPException(400, "Duplirana cena za istu sobu i termin")
        seen.add(key)
    conn.execute(text("""
        INSERT INTO cenovnik_opcije (cenovnik_id, datumod, datumdo) VALUES (:id, :od, :do)
        ON CONFLICT (cenovnik_id) DO UPDATE SET datumod = EXCLUDED.datumod, datumdo = EXCLUDED.datumdo
    """), {"id": item_id, "od": body.datumod, "do": body.datumdo})
    conn.execute(text("DELETE FROM cenovnik_cene WHERE cenovnik_id = :id"), {"id": item_id})
    if body.cene:
        conn.execute(text("""
            INSERT INTO cenovnik_cene (cenovnik_id, soba_id, period_id, cena)
            VALUES (:id, :soba_id, :period_id, :cena)
        """), [{"id": item_id, **x.model_dump()} for x in body.cene])
    conn.execute(text("UPDATE cenovnici SET updated_at = NOW() WHERE id = :id"), {"id": item_id})


def register_cenovnici(api, engine, get_current_user):
    @api.get("/cenovnici/sablon")
    def sablon(mesto_id: int, grupa_id: int, smestaj_id: int, _: dict = Depends(get_current_user)):
        with engine.connect() as conn:
            return _sablon(conn, mesto_id, grupa_id, smestaj_id)

    @api.get("/cenovnici")
    def lista(q: str = "", _: dict = Depends(get_current_user)):
        with engine.connect() as conn:
            return [dict(r) for r in conn.execute(text("""
                SELECT c.id, c.uuid::text AS uuid, c.naziv, c.mesto_id, c.grupa_id, c.smestaj_id,
                       o.datumod, o.datumdo FROM cenovnici c
                JOIN cenovnik_opcije o ON o.cenovnik_id = c.id
                WHERE (:q = '' OR c.naziv ILIKE :like OR c.uuid::text ILIKE :like OR c.id::text ILIKE :like)
                ORDER BY c.id DESC
            """), {"q": q.strip(), "like": f"%{q.strip()}%"}).mappings()]

    @api.get("/cenovnici/{item_id}")
    def detalj(item_id: int, _: dict = Depends(get_current_user)):
        with engine.connect() as conn:
            return _detail(conn, item_id)

    @api.post("/cenovnici", status_code=201)
    def kreiraj(body: CenovnikNovi, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            snap = _sablon(conn, body.mesto_id, body.grupa_id, body.smestaj_id)
            item_id = conn.execute(text("""
                INSERT INTO cenovnici (uuid, naziv, mesto_id, grupa_id, smestaj_id, sobe, periodi)
                VALUES (:uuid, :naziv, :mesto_id, :grupa_id, :smestaj_id, CAST(:sobe AS JSONB), CAST(:periodi AS JSONB))
                RETURNING id
            """), {"uuid": str(uuid4()), "naziv": snap["naziv"], "mesto_id": body.mesto_id,
                   "grupa_id": body.grupa_id, "smestaj_id": body.smestaj_id,
                   "sobe": json.dumps(snap["sobe"]), "periodi": json.dumps(snap["periodi"])}).scalar_one()
            _save_values(conn, item_id, body, snap)
            return _detail(conn, item_id)

    @api.put("/cenovnici/{item_id}")
    def izmeni(item_id: int, body: CenovnikIzmena, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            snap = _detail(conn, item_id, lock=True)
            _save_values(conn, item_id, body, snap)
            return _detail(conn, item_id)

    @api.delete("/cenovnici/{item_id}")
    def obrisi(item_id: int, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            row = conn.execute(text("SELECT id FROM cenovnici WHERE id = :i"), {"i": item_id}).first()
            if not row:
                raise HTTPException(status_code=404, detail="Cenovnik nije pronađen")
            # cenovnik_cene / cenovnik_opcije idu preko ON DELETE CASCADE
            conn.execute(text("DELETE FROM cenovnici WHERE id = :i"), {"i": item_id})
            return {"status": "obrisan", "id": item_id}
