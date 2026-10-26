"""Zaduženje partner + uslovi plaćanja po rezervaciji (aranzman).

Tabele:
- zaduzenje_po_aranzmanu: jedan red po rezervaciji (UNIQUE aranzman_id),
  partner iz tabele subagenti + iznosi EUR/RSD za Hotel, HF, Transfer, Prevoz.
- uslovi_placanja_po_aranzmanu: više redova po rezervaciji (naziv, iznosi,
  %, datum plaćanja, plaćeno).

Obavezna veza: aranzman_id -> aranzman(id), ON DELETE CASCADE.
Snimanje je replace-all u jednoj transakciji.
"""

from datetime import date
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text


def init_zaduzenje(engine):
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS zaduzenje_po_aranzmanu (
                id SERIAL PRIMARY KEY,
                aranzman_id INTEGER NOT NULL UNIQUE
                    REFERENCES aranzman(id) ON DELETE CASCADE,
                subagent_id INTEGER NULL,
                hotel_eur NUMERIC(14,2) NOT NULL DEFAULT 0,
                hotel_rsd NUMERIC(14,2) NOT NULL DEFAULT 0,
                hf_eur NUMERIC(14,2) NOT NULL DEFAULT 0,
                hf_rsd NUMERIC(14,2) NOT NULL DEFAULT 0,
                transfer_eur NUMERIC(14,2) NOT NULL DEFAULT 0,
                transfer_rsd NUMERIC(14,2) NOT NULL DEFAULT 0,
                prevoz_eur NUMERIC(14,2) NOT NULL DEFAULT 0,
                prevoz_rsd NUMERIC(14,2) NOT NULL DEFAULT 0,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS uslovi_placanja_po_aranzmanu (
                id SERIAL PRIMARY KEY,
                aranzman_id INTEGER NOT NULL
                    REFERENCES aranzman(id) ON DELETE CASCADE,
                redosled INTEGER NOT NULL DEFAULT 0,
                naziv VARCHAR(300) NOT NULL DEFAULT '',
                iznos_eur NUMERIC(14,2) NULL,
                iznos_rsd NUMERIC(14,2) NULL,
                iznos_procenat NUMERIC(6,2) NULL,
                datum_placanja DATE NULL,
                placeno BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS uslovi_placanja_aranzman_idx "
            "ON uslovi_placanja_po_aranzmanu (aranzman_id)"
        ))


class ZaduzenjeIn(BaseModel):
    subagent_id: Optional[int] = None
    hotel_eur: float = Field(0, ge=0, le=1e9)
    hotel_rsd: float = Field(0, ge=0, le=1e9)
    hf_eur: float = Field(0, ge=0, le=1e9)
    hf_rsd: float = Field(0, ge=0, le=1e9)
    transfer_eur: float = Field(0, ge=0, le=1e9)
    transfer_rsd: float = Field(0, ge=0, le=1e9)
    prevoz_eur: float = Field(0, ge=0, le=1e9)
    prevoz_rsd: float = Field(0, ge=0, le=1e9)


class UsloviRedIn(BaseModel):
    naziv: str = Field("", max_length=300)
    iznos_eur: Optional[float] = Field(None, ge=0, le=1e9)
    iznos_rsd: Optional[float] = Field(None, ge=0, le=1e9)
    iznos_procenat: Optional[float] = Field(None, ge=0, le=100)
    datum_placanja: Optional[date] = None
    placeno: bool = False


class UsloviIn(BaseModel):
    redovi: list[UsloviRedIn] = Field(default_factory=list, max_length=200)


def _aranzman_id(conn, kljuc: str) -> int:
    row = conn.execute(text("SELECT id FROM aranzman WHERE kljuc = :k"),
                       {"k": kljuc.strip().strip("/")}).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Ugovor nije pronađen")
    return row.id


def _f(v) -> float:
    return float(v) if v is not None else 0.0


def register_zaduzenje(api, engine, get_current_user):

    @api.get("/subagenti-izbor")
    def subagenti_izbor(_: dict = Depends(get_current_user)):
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT id, naziv FROM subagenti WHERE naziv <> '' ORDER BY naziv"
            )).fetchall()
        return [{"id": r.id, "naziv": r.naziv} for r in rows]

    @api.get("/zaduzenje/{kljuc:path}")
    def zaduzenje_get(kljuc: str, _: dict = Depends(get_current_user)):
        with engine.connect() as conn:
            aid = _aranzman_id(conn, kljuc)
            z = conn.execute(text("""
                SELECT z.subagent_id, s.naziv AS subagent_naziv,
                       z.hotel_eur, z.hotel_rsd, z.hf_eur, z.hf_rsd,
                       z.transfer_eur, z.transfer_rsd, z.prevoz_eur, z.prevoz_rsd
                FROM zaduzenje_po_aranzmanu z
                LEFT JOIN subagenti s ON s.id = z.subagent_id
                WHERE z.aranzman_id = :a
            """), {"a": aid}).mappings().first()
        if not z:
            return {"postoji": False, "subagent_id": None, "subagent_naziv": None,
                    "hotel_eur": 0, "hotel_rsd": 0, "hf_eur": 0, "hf_rsd": 0,
                    "transfer_eur": 0, "transfer_rsd": 0, "prevoz_eur": 0, "prevoz_rsd": 0}
        out = {"postoji": True, "subagent_id": z["subagent_id"],
               "subagent_naziv": z["subagent_naziv"]}
        for k in ("hotel_eur", "hotel_rsd", "hf_eur", "hf_rsd",
                  "transfer_eur", "transfer_rsd", "prevoz_eur", "prevoz_rsd"):
            out[k] = _f(z[k])
        return out

    @api.put("/zaduzenje/{kljuc:path}")
    def zaduzenje_put(kljuc: str, body: ZaduzenjeIn, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            aid = _aranzman_id(conn, kljuc)
            if body.subagent_id is not None:
                ok = conn.execute(text("SELECT 1 FROM subagenti WHERE id = :s"),
                                  {"s": body.subagent_id}).fetchone()
                if not ok:
                    raise HTTPException(status_code=400, detail="Nepoznat subagent")
            conn.execute(text("""
                INSERT INTO zaduzenje_po_aranzmanu
                  (aranzman_id, subagent_id, hotel_eur, hotel_rsd, hf_eur, hf_rsd,
                   transfer_eur, transfer_rsd, prevoz_eur, prevoz_rsd, updated_at)
                VALUES (:a, :s, :he, :hr, :fe, :fr, :te, :tr, :pe, :pr, NOW())
                ON CONFLICT (aranzman_id) DO UPDATE SET
                  subagent_id = EXCLUDED.subagent_id,
                  hotel_eur = EXCLUDED.hotel_eur, hotel_rsd = EXCLUDED.hotel_rsd,
                  hf_eur = EXCLUDED.hf_eur, hf_rsd = EXCLUDED.hf_rsd,
                  transfer_eur = EXCLUDED.transfer_eur, transfer_rsd = EXCLUDED.transfer_rsd,
                  prevoz_eur = EXCLUDED.prevoz_eur, prevoz_rsd = EXCLUDED.prevoz_rsd,
                  updated_at = NOW()
            """), {"a": aid, "s": body.subagent_id,
                   "he": body.hotel_eur, "hr": body.hotel_rsd,
                   "fe": body.hf_eur, "fr": body.hf_rsd,
                   "te": body.transfer_eur, "tr": body.transfer_rsd,
                   "pe": body.prevoz_eur, "pr": body.prevoz_rsd})
        return {"status": "sacuvano"}

    @api.get("/uslovi-placanja/{kljuc:path}")
    def uslovi_get(kljuc: str, _: dict = Depends(get_current_user)):
        with engine.connect() as conn:
            aid = _aranzman_id(conn, kljuc)
            rows = conn.execute(text("""
                SELECT id, naziv, iznos_eur, iznos_rsd, iznos_procenat,
                       datum_placanja, placeno
                FROM uslovi_placanja_po_aranzmanu
                WHERE aranzman_id = :a
                ORDER BY redosled, id
            """), {"a": aid}).mappings().all()
        return {"redovi": [{
            "id": r["id"], "naziv": r["naziv"],
            "iznos_eur": _f(r["iznos_eur"]) if r["iznos_eur"] is not None else None,
            "iznos_rsd": _f(r["iznos_rsd"]) if r["iznos_rsd"] is not None else None,
            "iznos_procenat": _f(r["iznos_procenat"]) if r["iznos_procenat"] is not None else None,
            "datum_placanja": r["datum_placanja"].isoformat() if r["datum_placanja"] else None,
            "placeno": bool(r["placeno"]),
        } for r in rows]}

    @api.put("/uslovi-placanja/{kljuc:path}")
    def uslovi_put(kljuc: str, body: UsloviIn, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            aid = _aranzman_id(conn, kljuc)
            conn.execute(text("DELETE FROM uslovi_placanja_po_aranzmanu WHERE aranzman_id = :a"),
                         {"a": aid})
            for i, r in enumerate(body.redovi):
                conn.execute(text("""
                    INSERT INTO uslovi_placanja_po_aranzmanu
                      (aranzman_id, redosled, naziv, iznos_eur, iznos_rsd,
                       iznos_procenat, datum_placanja, placeno)
                    VALUES (:a, :o, :n, :e, :r, :p, :d, :pl)
                """), {"a": aid, "o": i, "n": r.naziv.strip(),
                       "e": r.iznos_eur, "r": r.iznos_rsd, "p": r.iznos_procenat,
                       "d": r.datum_placanja, "pl": r.placeno})
        return {"status": "sacuvano", "broj": len(body.redovi)}
