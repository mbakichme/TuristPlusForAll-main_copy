"""Profil ulogovanog korisnika: podaci (telefon, JMBG), promena lozinke i brojači ugovora.

Brojači: ugovor pripada korisniku preko `aranzman.obradio` (ime i prezime kreatora,
upisuje se pri kreiranju rezervacije). `danas` je vreme kreiranja ugovora.
"""
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import text

BELGRADE = ZoneInfo("Europe/Belgrade")
_TELEFON = re.compile(r"[0-9+()/.\- ]{5,50}")


def init_profil(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS jmbg VARCHAR(13)"))


class ProfilIzmena(BaseModel):
    phone: str | None = None
    jmbg: str | None = None

    @field_validator("phone")
    @classmethod
    def _telefon(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        if not _TELEFON.fullmatch(v):
            raise ValueError("Neispravan broj telefona")
        return v

    @field_validator("jmbg")
    @classmethod
    def _jmbg(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        if not re.fullmatch(r"\d{13}", v):
            raise ValueError("JMBG mora imati tačno 13 cifara")
        return v


class LozinkaIzmena(BaseModel):
    trenutna: str
    nova: str

    @field_validator("nova")
    @classmethod
    def _nova(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Nova lozinka mora imati najmanje 8 karaktera")
        return v


def register_profil(api, engine, get_current_user, hash_password, verify_password) -> None:

    def _uid(current_user: dict) -> int:
        try:
            return int(current_user["sub"])
        except (KeyError, TypeError, ValueError):
            raise HTTPException(status_code=401, detail="Neautorizovan pristup")

    @api.get("/profil")
    def profil(current_user: dict = Depends(get_current_user)):
        uid = _uid(current_user)
        danas = datetime.now(BELGRADE).date()
        with engine.connect() as conn:
            u = conn.execute(text("""
                SELECT u.id, u.first_name, u.last_name, u.email, u.username,
                       u.phone, u.jmbg, u.is_superadmin, ut.name AS user_type_name
                FROM users u
                LEFT JOIN user_types ut ON u.user_type_id = ut.id
                WHERE u.id = :id
            """), {"id": uid}).mappings().fetchone()
            if not u:
                raise HTTPException(status_code=404, detail="Korisnik nije pronađen")
            ime = f"{(u['first_name'] or '').strip()} {(u['last_name'] or '').strip()}".strip()
            ukupno = danas_n = 0
            if ime:
                s = conn.execute(text("""
                    SELECT COUNT(DISTINCT kljuc) AS ukupno,
                           COUNT(DISTINCT kljuc) FILTER (WHERE danas::date = :d) AS danas
                    FROM aranzman
                    WHERE TRIM(obradio) = :ime AND kljuc IS NOT NULL AND kljuc <> ''
                """), {"ime": ime, "d": danas}).mappings().one()
                ukupno, danas_n = s["ukupno"], s["danas"]
        return {
            "id": u["id"],
            "first_name": u["first_name"],
            "last_name": u["last_name"],
            "email": u["email"],
            "username": u["username"],
            "phone": u["phone"],
            "jmbg": u["jmbg"],
            "is_superadmin": u["is_superadmin"],
            "user_type_name": u["user_type_name"],
            "statistika": {"ukupno_ugovora": ukupno, "danas_ugovora": danas_n},
        }

    @api.put("/profil")
    def izmeni_profil(body: ProfilIzmena, current_user: dict = Depends(get_current_user)):
        uid = _uid(current_user)
        # exclude_unset: polje koje klijent nije poslao ostaje netaknuto
        data = body.model_dump(exclude_unset=True)
        if not data:
            raise HTTPException(status_code=400, detail="Nema podataka za izmenu")
        sets = ", ".join(f"{k} = :{k}" for k in data)  # ključevi su samo polja modela
        data["id"] = uid
        with engine.begin() as conn:
            r = conn.execute(text(f"""
                UPDATE users SET {sets}, updated_at = NOW()
                WHERE id = :id
                RETURNING phone, jmbg
            """), data).mappings().fetchone()
        if not r:
            raise HTTPException(status_code=404, detail="Korisnik nije pronađen")
        return {"phone": r["phone"], "jmbg": r["jmbg"]}

    @api.post("/profil/lozinka")
    def promeni_lozinku(body: LozinkaIzmena, current_user: dict = Depends(get_current_user)):
        uid = _uid(current_user)
        with engine.begin() as conn:
            r = conn.execute(text("SELECT password_hash FROM users WHERE id = :id"),
                             {"id": uid}).fetchone()
            if not r:
                raise HTTPException(status_code=404, detail="Korisnik nije pronađen")
            if not verify_password(body.trenutna, r.password_hash):
                raise HTTPException(status_code=400, detail="Trenutna lozinka nije ispravna")
            if verify_password(body.nova, r.password_hash):
                raise HTTPException(status_code=400, detail="Nova lozinka mora biti različita od trenutne")
            conn.execute(text("UPDATE users SET password_hash = :h, updated_at = NOW() WHERE id = :id"),
                         {"h": hash_password(body.nova), "id": uid})
        return {"status": "promenjeno"}
