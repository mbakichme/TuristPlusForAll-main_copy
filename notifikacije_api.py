"""Notifikacije: tekstualne poruke korisnika koje se prikazuju na naslovnoj strani.

Svaka poruka je zapis u tabeli `notifikacije`; autor se čuva kao snimak
(ime + korisničko ime) da zapis ostane čitljiv i kad se korisnik kasnije izmeni.
Na naslovnoj se prikazuje najnovija poruka.
"""
from fastapi import Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import text

PORUKA_MAX = 1000


class PorukaNova(BaseModel):
    poruka: str

    @field_validator("poruka")
    @classmethod
    def validna_poruka(cls, value):
        value = (value or "").strip()
        if not value:
            raise ValueError("Poruka ne sme biti prazna")
        if len(value) > PORUKA_MAX:
            raise ValueError(f"Poruka je predugačka (najviše {PORUKA_MAX} znakova)")
        return value


def init_notifikacije(engine):
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS notifikacije (
                id SERIAL PRIMARY KEY,
                poruka TEXT NOT NULL,
                autor_id INTEGER,
                autor_ime VARCHAR(200) NOT NULL DEFAULT '',
                autor_username VARCHAR(100) NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS notifikacije_created_idx ON notifikacije (created_at DESC)"
        ))


def _red(r):
    return {
        "id": r.id,
        "poruka": r.poruka,
        "autor_id": r.autor_id,
        "autor_ime": r.autor_ime,
        "autor_username": r.autor_username,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def register_notifikacije(api, engine, get_current_user):
    @api.get("/notifikacije")
    def lista(limit: int = 100, q: str = "", _: dict = Depends(get_current_user)):
        limit = max(1, min(limit, 1000))
        q = (q or "").strip()
        filter_sql = ""
        params: dict = {"limit": limit}
        if q:
            # LIKE specijalni znaci se escape-uju da se traže doslovno
            esc = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            filter_sql = """WHERE poruka ILIKE :q ESCAPE '\\'
                   OR autor_ime ILIKE :q ESCAPE '\\'
                   OR autor_username ILIKE :q ESCAPE '\\'"""
            params["q"] = f"%{esc}%"
        with engine.connect() as conn:
            rows = conn.execute(text(f"""
                SELECT id, poruka, autor_id, autor_ime, autor_username, created_at,
                       COUNT(*) OVER() AS ukupno
                FROM notifikacije
                {filter_sql}
                ORDER BY created_at DESC, id DESC
                LIMIT :limit
            """), params).fetchall()
        redovi = [_red(r) for r in rows]
        ukupno = rows[0].ukupno if rows else 0
        return {"najnovija": redovi[0] if redovi else None, "rows": redovi, "ukupno": ukupno}

    @api.post("/notifikacije", status_code=201)
    def dodaj(body: PorukaNova, current_user: dict = Depends(get_current_user)):
        uid = int(current_user["sub"])
        with engine.begin() as conn:
            autor = conn.execute(text("""
                SELECT first_name, last_name, username FROM users WHERE id = :id
            """), {"id": uid}).fetchone()
            if not autor:
                raise HTTPException(status_code=404, detail="Korisnik nije pronađen")
            ime = f"{autor.first_name} {autor.last_name}".strip()
            row = conn.execute(text("""
                INSERT INTO notifikacije (poruka, autor_id, autor_ime, autor_username)
                VALUES (:poruka, :autor_id, :ime, :username)
                RETURNING id, poruka, autor_id, autor_ime, autor_username, created_at
            """), {
                "poruka": body.poruka,
                "autor_id": uid,
                "ime": ime,
                "username": autor.username or "",
            }).fetchone()
        return _red(row)
