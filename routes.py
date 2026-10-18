import os
import io
import re
import json
import math
import base64
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional, List
from urllib.parse import quote

from fastapi import FastAPI, APIRouter, Request, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
import bcrypt
from jose import JWTError, jwt

from predracun_pdf import generate_predracun_pdf
from kurs_service import ensure_kurs_table, get_eur_rate
from grafik_boje import kategorija_grafika
from cenovnici_api import init_cenovnici, register_cenovnici
from koeficijenti_api import init_koeficijenti, register_koeficijenti, osiguraj_auto_red
from notifikacije_api import init_notifikacije, register_notifikacije
from profil_api import init_profil, register_profil
from dashboard_api import register_dashboard
from rezervacija_log import (
    OBLAST_OBRACUN, OBLAST_SAPUTNICI, OBLAST_UPLATA, OBLAST_REZERVACIJA,
    diff_saputnike, init_rezervacija_log, log_user, norm_vrednost,
    podeli_po_oblastima, register_rezervacija_log, zabelezi,
)

# ─── Auth config ────────────────────────────────────────────────────────────
SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "turisticka-agencija-super-secret-2024")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 8  # 8 hours


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


# ─── Uplate: dozvoljene vrednosti ───────────────────────────────────────────
NACINI_UPLATE = ("Gotovina", "Kartica", "Virman", "Knjiženje na račun")
SVRHE_UPLATE = ("Total aranžman", "Deo aranžmana", "Prevoz", "Osiguranje", "Odloženo - Ček")

# ─── Ugovor: promena smeštaja (soba + termin) ───────────────────────────────
# Advisory lock prostor za zauzeće soba (base + soba.id) — izdvojeno od drugih
# mogućih pg_advisory_xact_lock korisnika.
SMESTAJ_ADVISORY_LOCK_BASE = 7_500_000_000_000


def _parse_iso_date(v: str, field: str):
    try:
        return datetime.strptime((v or "").strip(), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=400, detail=f"{field} mora biti datum u formatu YYYY-MM-DD"
        )


def _eu_dst_active_utc(naive_utc: datetime) -> bool:
    """EU pravilo (važi i za Srbiju): DST od poslednje nedelje u martu 01:00 UTC
    do poslednje nedelje u oktobru 01:00 UTC."""
    import calendar
    year = naive_utc.year

    def last_sunday(month: int) -> int:
        last_day = calendar.monthrange(year, month)[1]
        wd = datetime(year, month, last_day).weekday()  # pon=0 … ned=6
        return last_day - ((wd + 1) % 7)

    start = datetime(year, 3, last_sunday(3), 1, 0, 0)
    end = datetime(year, 10, last_sunday(10), 1, 0, 0)
    return start <= naive_utc < end


def _belgrade_now() -> datetime:
    """Trenutni lokalni datum/vreme za Europe/Belgrade (naive — TIMESTAMP kolona).

    Preferira zoneinfo; ako tz baza nije dostupna, računa offset po EU pravilu
    (CET = UTC+1, CEST = UTC+2)."""
    now_utc = datetime.now(timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        return now_utc.astimezone(ZoneInfo("Europe/Belgrade")).replace(tzinfo=None)
    except Exception:
        naive_utc = now_utc.replace(tzinfo=None)
        offset = 2 if _eu_dst_active_utc(naive_utc) else 1
        return naive_utc + timedelta(hours=offset)


# ─── DB ─────────────────────────────────────────────────────────────────────
def get_engine():
    db_url = os.environ.get("EXTERNAL_NEON_DATABASE_URL")
    if not db_url:
        raise RuntimeError("EXTERNAL_NEON_DATABASE_URL nije podešen")
    return create_engine(db_url, pool_pre_ping=True)


def init_db(engine):
    with engine.begin() as conn:
        ensure_kurs_table(conn)
        # User types table
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS user_types (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL UNIQUE,
                slug VARCHAR(100) NOT NULL UNIQUE,
                description TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))

        # Users table
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                first_name VARCHAR(100) NOT NULL,
                last_name VARCHAR(100) NOT NULL,
                email VARCHAR(255) NOT NULL UNIQUE,
                phone VARCHAR(50),
                address TEXT,
                city VARCHAR(100),
                status VARCHAR(20) DEFAULT 'aktivan',
                username VARCHAR(100) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                user_type_id INTEGER REFERENCES user_types(id),
                is_superadmin BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """))

        # Seed default user types
        default_types = [
            ("Administrator", "administrator", "Puni pristup sistemu"),
            ("Analitičar", "analiticar", "Pristup analitičkim podacima i izveštajima"),
            ("Administrator podataka", "administrator-podataka", "Upravljanje podacima"),
            ("Računovodstvo", "racunovodstvo", "Pristup finansijskim podacima"),
            ("Prodaja", "prodaja", "Upravljanje prodajnim procesima"),
            ("Subagent", "subagent", "Ograničeni pristup za subagente"),
            ("Klijent", "klijent", "Pristup za krajnje korisnike"),
        ]
        for name, slug, desc in default_types:
            conn.execute(text("""
                INSERT INTO user_types (name, slug, description)
                VALUES (:name, :slug, :desc)
                ON CONFLICT (slug) DO NOTHING
            """), {"name": name, "slug": slug, "desc": desc})

        # Seed superadmin — always update password hash to ensure compatibility
        superadmin_pass = hash_password("admin123")
        conn.execute(text("""
            INSERT INTO users (first_name, last_name, email, username, password_hash, status, is_superadmin)
            VALUES ('Super', 'Admin', 'www@oktopod.rs', 'superadmin', :pw, 'aktivan', TRUE)
            ON CONFLICT (email) DO UPDATE SET password_hash = :pw
        """), {"pw": superadmin_pass})

        # ── New tables ──────────────────────────────────────────────────────
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tip_ponude (
                id SERIAL PRIMARY KEY,
                naziv VARCHAR(200) NOT NULL UNIQUE
            )
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS drzava (
                id SERIAL PRIMARY KEY,
                id_cis VARCHAR(50),
                naziv VARCHAR(200) NOT NULL,
                naziv_cis VARCHAR(200)
            )
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS destinacija (
                id SERIAL PRIMARY KEY,
                naziv VARCHAR(200) NOT NULL,
                drzava INTEGER REFERENCES drzava(id) ON DELETE SET NULL,
                status INTEGER DEFAULT 1,
                organizator INTEGER,
                predstavnik INTEGER,
                naziv_cis VARCHAR(200)
            )
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS mesto (
                id SERIAL PRIMARY KEY,
                naziv VARCHAR(200) NOT NULL,
                drzava INTEGER REFERENCES drzava(id) ON DELETE SET NULL,
                destinacija INTEGER REFERENCES destinacija(id) ON DELETE SET NULL,
                status INTEGER DEFAULT 1,
                organizator INTEGER,
                predstavnik INTEGER,
                grafik INTEGER DEFAULT 0,
                cis VARCHAR(100)
            )
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tip_smestaja (
                id SERIAL PRIMARY KEY,
                naziv VARCHAR(200) NOT NULL
            )
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS smestaj (
                id SERIAL PRIMARY KEY,
                naziv VARCHAR(200) NOT NULL,
                drzava INTEGER REFERENCES drzava(id) ON DELETE SET NULL,
                destinacija INTEGER REFERENCES destinacija(id) ON DELETE SET NULL,
                mesto INTEGER REFERENCES mesto(id) ON DELETE SET NULL,
                tip_smestaja INTEGER REFERENCES tip_smestaja(id) ON DELETE SET NULL,
                status INTEGER DEFAULT 1,
                organizator INTEGER,
                predstavnik INTEGER,
                grafik INTEGER DEFAULT 0
            )
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS agencija (
                id SERIAL PRIMARY KEY,
                naziv VARCHAR(300),
                poslovno_ime VARCHAR(300),
                email1 VARCHAR(255),
                email2 VARCHAR(255),
                telefon1 VARCHAR(50),
                telefon2 VARCHAR(50),
                ulica VARCHAR(300),
                broj VARCHAR(20),
                post_broj VARCHAR(20),
                mesto VARCHAR(200),
                drzava VARCHAR(200),
                opstina_rgz VARCHAR(100),
                opstina_naziv VARCHAR(200),
                mesto_rgz VARCHAR(100),
                mesto_naziv VARCHAR(200),
                ulica_rgz VARCHAR(100),
                ulica_naziv VARCHAR(300),
                api_kljuc_efakture VARCHAR(500),
                api_kljuc_cis VARCHAR(500),
                pib VARCHAR(20),
                mb VARCHAR(20),
                jbkjs VARCHAR(20),
                jmbg VARCHAR(20),
                tekuci_racun1 VARCHAR(50),
                banka1 VARCHAR(200),
                tekuci_racun2 VARCHAR(50),
                banka2 VARCHAR(200),
                tekuci_racun3 VARCHAR(50),
                banka3 VARCHAR(200),
                tekuci_racun4 VARCHAR(50),
                banka4 VARCHAR(200)
            )
        """))
        # Ensure at least one agencija row exists
        conn.execute(text("""
            INSERT INTO agencija (id) VALUES (1)
            ON CONFLICT (id) DO NOTHING
        """))
        # Periodi — grupe datuma putovanja
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS period_grupa (
                id SERIAL PRIMARY KEY,
                naziv VARCHAR(200) NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS period_datum (
                id SERIAL PRIMARY KEY,
                grupa_id INTEGER REFERENCES period_grupa(id) ON DELETE CASCADE,
                datum_od DATE NOT NULL,
                datum_do DATE NOT NULL
            )
        """))

        # Knjigovodstvo — aranzman (ugovori)
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS aranzman (
                id SERIAL PRIMARY KEY,
                danas TIMESTAMP DEFAULT NULL,
                putnik VARCHAR(200) DEFAULT '',
                rodjen DATE DEFAULT NULL,
                pasos VARCHAR(50) DEFAULT NULL,
                adresa VARCHAR(200) DEFAULT '',
                telefon VARCHAR(200) DEFAULT '',
                prevozow SMALLINT DEFAULT NULL,
                prevozrt SMALLINT DEFAULT NULL,
                viza SMALLINT DEFAULT NULL,
                smer VARCHAR(50) DEFAULT NULL,
                destinacija VARCHAR(100) DEFAULT '',
                subagent VARCHAR(200) DEFAULT '',
                procenatar DOUBLE PRECISION DEFAULT 0,
                procenatpr DOUBLE PRECISION DEFAULT 0,
                procenatpra DOUBLE PRECISION DEFAULT 0,
                procenatvi DOUBLE PRECISION DEFAULT 0,
                mesto VARCHAR(200) DEFAULT '',
                naziv VARCHAR(200) DEFAULT '',
                naziv1 VARCHAR(200) DEFAULT '',
                datumod TIMESTAMP DEFAULT NULL,
                datumdo TIMESTAMP DEFAULT NULL,
                datumoddo VARCHAR(200) DEFAULT NULL,
                apartman VARCHAR(10) DEFAULT '',
                opis VARCHAR(20) DEFAULT '',
                opis1 VARCHAR(20) DEFAULT '',
                soba VARCHAR(200) DEFAULT '',
                soba1 VARCHAR(200) DEFAULT '',
                cenaviza DOUBLE PRECISION DEFAULT 0,
                kolviza INTEGER DEFAULT 0,
                cenaow DOUBLE PRECISION DEFAULT 0,
                cenadow DOUBLE PRECISION DEFAULT 0,
                cenart DOUBLE PRECISION DEFAULT 0,
                cenadrt DOUBLE PRECISION DEFAULT 0,
                kolow INTEGER DEFAULT 0,
                kolrt INTEGER DEFAULT 0,
                cenachd DOUBLE PRECISION DEFAULT 0,
                cenaaranz DOUBLE PRECISION DEFAULT 0,
                cenaaranzd DOUBLE PRECISION DEFAULT 0,
                kolchd DOUBLE PRECISION DEFAULT 0,
                kolaranz DOUBLE PRECISION DEFAULT 0,
                cenadod DOUBLE PRECISION DEFAULT 0,
                koldod DOUBLE PRECISION DEFAULT 0,
                popustar DOUBLE PRECISION DEFAULT 0,
                popustpr DOUBLE PRECISION DEFAULT 0,
                popustvi DOUBLE PRECISION DEFAULT 0,
                spajanje1od TIMESTAMP DEFAULT NULL,
                spajanje1do TIMESTAMP DEFAULT NULL,
                spajanje2od TIMESTAMP DEFAULT NULL,
                spajanje2do TIMESTAMP DEFAULT NULL,
                obradio VARCHAR(200) DEFAULT '',
                uplaceno DOUBLE PRECISION DEFAULT 0,
                uplacenod DOUBLE PRECISION DEFAULT 0,
                gde VARCHAR(200) DEFAULT NULL,
                timelimit TIMESTAMP DEFAULT NULL,
                uplatasmestaj DOUBLE PRECISION DEFAULT 0,
                uplataprevoz DOUBLE PRECISION DEFAULT 0,
                uplataviza DOUBLE PRECISION DEFAULT 0,
                legal SMALLINT DEFAULT 0,
                napomena VARCHAR(1024) DEFAULT '',
                obrok VARCHAR(3) DEFAULT '',
                osiguranje DOUBLE PRECISION DEFAULT 0,
                osiguranje1 DOUBLE PRECISION DEFAULT 0,
                helas1 DOUBLE PRECISION DEFAULT 0,
                helas2 DOUBLE PRECISION DEFAULT 0,
                helas3 DOUBLE PRECISION DEFAULT 0,
                helas4 DOUBLE PRECISION DEFAULT 0,
                helas5 DOUBLE PRECISION DEFAULT 0,
                kljuc VARCHAR(200) NOT NULL,
                avioid INTEGER DEFAULT NULL,
                avioid1 INTEGER DEFAULT NULL,
                avioid2 VARCHAR(100) DEFAULT NULL,
                avioid3 VARCHAR(10) DEFAULT NULL,
                avioid4 INTEGER DEFAULT NULL,
                refno VARCHAR(200) DEFAULT '',
                napomena1 VARCHAR(255) DEFAULT NULL,
                organizator VARCHAR(200) DEFAULT NULL,
                poslovnica VARCHAR(200) DEFAULT NULL,
                keptp INTEGER DEFAULT NULL,
                datumkeptp TIMESTAMP DEFAULT NULL,
                fiskalni VARCHAR(200) DEFAULT NULL,
                datumfiskalni TIMESTAMP DEFAULT NULL,
                iznosfiskalni DOUBLE PRECISION DEFAULT 0,
                ulazak VARCHAR(200) DEFAULT NULL,
                tiprezervacije VARCHAR(200) DEFAULT NULL,
                anketa VARCHAR(200) DEFAULT NULL,
                loyalty VARCHAR(200) DEFAULT NULL,
                bod DOUBLE PRECISION DEFAULT NULL,
                busnapomena VARCHAR(1024) DEFAULT NULL,
                busnapomena1 VARCHAR(200) DEFAULT NULL,
                CONSTRAINT aranzman_kljuc_unique UNIQUE (kljuc)
            )
        """))
        # Dopuna aranžmana — saputnici po redu (podržava više od 4 saputnika)
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS aranzman_dopuna (
                id SERIAL PRIMARY KEY,
                aranzman_id INTEGER NOT NULL
                    REFERENCES aranzman(id) ON DELETE CASCADE,
                saputnik VARCHAR(200) DEFAULT '',
                rodjen DATE DEFAULT NULL,
                pasos VARCHAR(50) DEFAULT NULL,
                uzrast VARCHAR(20) DEFAULT '',
                prevozow SMALLINT DEFAULT NULL,
                prevozrt SMALLINT DEFAULT NULL,
                viza SMALLINT DEFAULT NULL,
                ulazak VARCHAR(200) DEFAULT NULL,
                smer VARCHAR(50) DEFAULT NULL,
                adresa VARCHAR(300) DEFAULT '',
                email VARCHAR(300) DEFAULT '',
                telefon VARCHAR(300) DEFAULT ''
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_aranzman_dopuna_aranzman_id "
            "ON aranzman_dopuna(aranzman_id)"
        ))
        # Starije baze: dodaj smer ako ne postoji
        conn.execute(text(
            "ALTER TABLE aranzman ADD COLUMN IF NOT EXISTS smer VARCHAR(50) DEFAULT NULL"
        ))
        # Datum rođenja i pasoš nosioca i saputnika (additive migracija).
        for tabela in ("aranzman", "aranzman_dopuna"):
            conn.execute(text(f"ALTER TABLE {tabela} ADD COLUMN IF NOT EXISTS rodjen DATE"))
            conn.execute(text(f"ALTER TABLE {tabela} ADD COLUMN IF NOT EXISTS pasos VARCHAR(50)"))
        # Starije baze: kontakt podaci saputnika u aranzman_dopuna
        conn.execute(text(
            "ALTER TABLE aranzman_dopuna ADD COLUMN IF NOT EXISTS adresa VARCHAR(300) DEFAULT ''"
        ))
        conn.execute(text(
            "ALTER TABLE aranzman_dopuna ADD COLUMN IF NOT EXISTS email VARCHAR(300) DEFAULT ''"
        ))
        conn.execute(text(
            "ALTER TABLE aranzman_dopuna ADD COLUMN IF NOT EXISTS telefon VARCHAR(300) DEFAULT ''"
        ))
        # Veza ugovora na konkretni smeštaj (instanca = mesto + grupa termina).
        # Naziv/soba u aranzman-u su nazivi pa se smeštaji istog naziva u različitim
        # grupama ne mogu razlučiti — smestaj_id čuva tačan izbor sa forme/grafika.
        conn.execute(text(
            "ALTER TABLE aranzman ADD COLUMN IF NOT EXISTS smestaj_id INTEGER"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_aranzman_smestaj_id ON aranzman(smestaj_id)"
        ))
        # Dodatne stavke — id je broj ugovora i nije jedinstven.
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS dodatne (
                usluga VARCHAR(150) DEFAULT NULL,
                eur DOUBLE PRECISION DEFAULT NULL,
                din DOUBLE PRECISION DEFAULT NULL,
                id INTEGER DEFAULT NULL
            )
        """))
        conn.execute(text("ALTER TABLE dodatne ADD COLUMN IF NOT EXISTS stavka_id SERIAL"))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_dodatne_stavka_id ON dodatne(stavka_id)"
        ))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_dodatne_id ON dodatne(id)"))
        # Knjigovodstvo — uplate (struktura po starom sistemu: kljuc = broj uplate PK,
        # broj = dokument broj kao string, id = veza na ugovor/fakturu NIJE jedinstven)
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS uplate (
                id INTEGER DEFAULT NULL,
                danas TIMESTAMP DEFAULT NULL,
                ime VARCHAR(300) DEFAULT '',
                adresa VARCHAR(300) DEFAULT '',
                nacin VARCHAR(300) DEFAULT '',
                din DOUBLE PRECISION DEFAULT 0,
                evro DOUBLE PRECISION DEFAULT 0,
                uevro DOUBLE PRECISION DEFAULT 0,
                svrha VARCHAR(300) DEFAULT '',
                obradio VARCHAR(300) DEFAULT '',
                vrsta VARCHAR(300) DEFAULT '',
                kljuc SERIAL PRIMARY KEY,
                broj VARCHAR(10) DEFAULT NULL,
                faktura VARCHAR(300) DEFAULT '',
                destinacija VARCHAR(300) DEFAULT '',
                mesto VARCHAR(300) DEFAULT '',
                subagent VARCHAR(300) DEFAULT '',
                organizator VARCHAR(300) DEFAULT '',
                poslovnica VARCHAR(300) DEFAULT ''
            )
        """))
        # Knjigovodstvo — subagenti
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS subagenti (
                id SERIAL PRIMARY KEY,
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
                kontakt VARCHAR(300) DEFAULT ''
            )
        """))

        # Knjigovodstvo — predracuni
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS predracun (
                id SERIAL PRIMARY KEY,
                broj_predracuna VARCHAR(50) NOT NULL,
                ugovor VARCHAR(50) DEFAULT '',
                datum DATE DEFAULT CURRENT_DATE,
                nosilac VARCHAR(300) DEFAULT '',
                saputnik TEXT DEFAULT '',
                destinacija VARCHAR(300) DEFAULT '',
                period VARCHAR(100) DEFAULT '',
                racun VARCHAR(200) DEFAULT '',
                nacin VARCHAR(100) DEFAULT '',
                napomena TEXT DEFAULT '',
                provizija DOUBLE PRECISION DEFAULT 0,
                zaduzenje DOUBLE PRECISION DEFAULT 0,
                subagent VARCHAR(300) DEFAULT '',
                adresa VARCHAR(300) DEFAULT '',
                mesto VARCHAR(300) DEFAULT '',
                organizator VARCHAR(300) DEFAULT '',
                poslovnica VARCHAR(300) DEFAULT '',
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))

        # Add columns for existing installations
        conn.execute(text("""
            ALTER TABLE agencija ADD COLUMN IF NOT EXISTS jmbg VARCHAR(20)
        """))

        # ── Izvodi (bankovni izvodi — XML upload) ───────────────────────────
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS izvodi (
                id SERIAL PRIMARY KEY,
                racun VARCHAR(50) NOT NULL DEFAULT '',
                broj_izvoda VARCHAR(50) NOT NULL DEFAULT '',
                datum_izvoda DATE,
                valuta VARCHAR(10) DEFAULT 'RSD',
                saldo DOUBLE PRECISION DEFAULT 0,
                raspolozivo DOUBLE PRECISION DEFAULT 0,
                rezervisano DOUBLE PRECISION DEFAULT 0,
                broj_transakcija INTEGER DEFAULT 0,
                podaci JSONB DEFAULT '{}'::jsonb,
                datum_unosa TIMESTAMP DEFAULT NOW(),
                korisnik VARCHAR(150) DEFAULT '',
                CONSTRAINT uq_izvodi_racun_broj UNIQUE (racun, broj_izvoda)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS izvodi_pregled (
                id SERIAL PRIMARY KEY,
                izvod_id INTEGER NOT NULL REFERENCES izvodi(id) ON DELETE CASCADE,
                racun VARCHAR(50) NOT NULL DEFAULT '',
                broj_izvoda VARCHAR(50) NOT NULL DEFAULT '',
                datum_izvoda DATE,
                datum_unosa TIMESTAMP DEFAULT NOW(),
                korisnik VARCHAR(150) DEFAULT ''
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_izvodi_pregled_unosa
            ON izvodi_pregled (datum_unosa DESC)
        """))
        conn.execute(text("""
            ALTER TABLE smestaj ADD COLUMN IF NOT EXISTS mesto INTEGER REFERENCES mesto(id) ON DELETE SET NULL
        """))
        conn.execute(text("""
            ALTER TABLE mesto ADD COLUMN IF NOT EXISTS grupa_datuma INTEGER REFERENCES period_grupa(id) ON DELETE SET NULL
        """))
        # Mesto ↔ grupe perioda (1:m): jedan mesto može imati više grupa perioda.
        # mesto.grupa_datuma ostaje kao "primarna" (prva) grupa — čitaju je stari delovi koda.
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS mesto_grupa (
                id SERIAL PRIMARY KEY,
                mesto_id INTEGER NOT NULL REFERENCES mesto(id) ON DELETE CASCADE,
                grupa_id INTEGER NOT NULL REFERENCES period_grupa(id) ON DELETE CASCADE,
                UNIQUE (mesto_id, grupa_id)
            )
        """))
        conn.execute(text("""
            INSERT INTO mesto_grupa (mesto_id, grupa_id)
            SELECT id, grupa_datuma FROM mesto
            WHERE grupa_datuma IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM mesto_grupa mg
                  WHERE mg.mesto_id = mesto.id AND mg.grupa_id = mesto.grupa_datuma
              )
        """))
        conn.execute(text("""
            ALTER TABLE smestaj ADD COLUMN IF NOT EXISTS grupa_datuma INTEGER REFERENCES period_grupa(id) ON DELETE SET NULL
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS sobe (
                id SERIAL PRIMARY KEY,
                veza_id_smestaj INTEGER NOT NULL REFERENCES smestaj(id) ON DELETE CASCADE,
                broj_sobe VARCHAR(50) DEFAULT '',
                opis TEXT DEFAULT '',
                tip VARCHAR(100) DEFAULT '',
                status INTEGER DEFAULT 1,
                opis_dodatno TEXT DEFAULT '',
                veliki_opis TEXT DEFAULT ''
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_sobe_smestaj ON sobe (veza_id_smestaj)
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS dokumenti (
                id SERIAL PRIMARY KEY,
                tip VARCHAR(50) NOT NULL UNIQUE,
                naziv VARCHAR(100) DEFAULT '',
                slika TEXT DEFAULT NULL,
                slika_mime VARCHAR(50) DEFAULT NULL,
                napomena TEXT DEFAULT NULL,
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """))

        # Boje grafik — globalne postavke boja za prikaz grafika
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS boje_grafik (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                isplacen VARCHAR(20) NOT NULL DEFAULT 'zelena',
                predrezervacija_aktivna VARCHAR(20) NOT NULL DEFAULT 'zelena',
                predrezervacija_istekla VARCHAR(20) NOT NULL DEFAULT 'zelena',
                blok VARCHAR(20) NOT NULL DEFAULT 'zelena',
                saldo_veci VARCHAR(20) NOT NULL DEFAULT 'zelena',
                predrezervacija_subagent VARCHAR(20) NOT NULL DEFAULT 'zelena',
                CONSTRAINT chk_isplacen CHECK (isplacen IN ('zelena', 'plava', 'crvena', 'zuta', 'ljubicasta', 'narandzasta', 'crna', 'roze')),
                CONSTRAINT chk_predrezervacija_aktivna CHECK (predrezervacija_aktivna IN ('zelena', 'plava', 'crvena', 'zuta', 'ljubicasta', 'narandzasta', 'crna', 'roze')),
                CONSTRAINT chk_predrezervacija_istekla CHECK (predrezervacija_istekla IN ('zelena', 'plava', 'crvena', 'zuta', 'ljubicasta', 'narandzasta', 'crna', 'roze')),
                CONSTRAINT chk_blok CHECK (blok IN ('zelena', 'plava', 'crvena', 'zuta', 'ljubicasta', 'narandzasta', 'crna', 'roze')),
                CONSTRAINT chk_saldo_veci CHECK (saldo_veci IN ('zelena', 'plava', 'crvena', 'zuta', 'ljubicasta', 'narandzasta', 'crna', 'roze')),
                CONSTRAINT chk_predrezervacija_subagent CHECK (predrezervacija_subagent IN ('zelena', 'plava', 'crvena', 'zuta', 'ljubicasta', 'narandzasta', 'crna', 'roze'))
            )
        """))
        conn.execute(text("""
            INSERT INTO boje_grafik (id, isplacen, predrezervacija_aktivna, predrezervacija_istekla, blok, saldo_veci, predrezervacija_subagent)
            VALUES (1, 'zelena', 'zelena', 'zelena', 'zelena', 'zelena', 'zelena')
            ON CONFLICT (id) DO NOTHING
        """))

        # Seed tip_ponude
        tip_ponude_values = [
            "Aranžmani sa fiksnim terminima",
            "Metropole",
            "Ekskurzije",
            "Na upit",
            "Kongresi",
        ]
        for naziv in tip_ponude_values:
            conn.execute(text("""
                INSERT INTO tip_ponude (naziv)
                VALUES (:naziv)
                ON CONFLICT (naziv) DO NOTHING
            """), {"naziv": naziv})


# ─── Pydantic schemas ────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    email: str
    password: str


class UserTypeCreate(BaseModel):
    name: str
    slug: str
    description: Optional[str] = None


class UserTypeUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = None


class UserCreate(BaseModel):
    first_name: str
    last_name: str
    email: str
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    status: str = "aktivan"
    username: str
    password: str
    user_type_id: Optional[int] = None


class UserUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    status: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    user_type_id: Optional[int] = None


# ─── New Pydantic schemas ────────────────────────────────────────────────────
class TipPonudeCreate(BaseModel):
    naziv: str


class TipPonudeUpdate(BaseModel):
    naziv: Optional[str] = None


class DrzavaCreate(BaseModel):
    naziv: str
    id_cis: Optional[str] = None
    naziv_cis: Optional[str] = None


class DrzavaUpdate(BaseModel):
    naziv: Optional[str] = None
    id_cis: Optional[str] = None
    naziv_cis: Optional[str] = None


class DestinacijaCreate(BaseModel):
    naziv: str
    drzava: Optional[int] = None
    status: Optional[int] = 1
    organizator: Optional[int] = None
    predstavnik: Optional[int] = None
    naziv_cis: Optional[str] = None


class DestinacijaUpdate(BaseModel):
    naziv: Optional[str] = None
    drzava: Optional[int] = None
    status: Optional[int] = None
    organizator: Optional[int] = None
    predstavnik: Optional[int] = None
    naziv_cis: Optional[str] = None


class MestoCreate(BaseModel):
    naziv: str
    drzava: Optional[int] = None
    destinacija: Optional[int] = None
    grupa_datuma: Optional[int] = None
    grupe: Optional[List[int]] = None  # sve grupe perioda mesta (prva = primarna)
    status: Optional[int] = 1
    organizator: Optional[int] = None
    predstavnik: Optional[int] = None
    grafik: Optional[int] = 0
    cis: Optional[str] = None


class MestoUpdate(BaseModel):
    naziv: Optional[str] = None
    drzava: Optional[int] = None
    destinacija: Optional[int] = None
    grupa_datuma: Optional[int] = None
    grupe: Optional[List[int]] = None  # None = ne diraj; [] = obriši sve grupe
    status: Optional[int] = None
    organizator: Optional[int] = None
    predstavnik: Optional[int] = None
    grafik: Optional[int] = None
    cis: Optional[str] = None


class TipSmestajaCreate(BaseModel):
    naziv: str


class TipSmestajaUpdate(BaseModel):
    naziv: Optional[str] = None


class SmestajCreate(BaseModel):
    naziv: str
    drzava: Optional[int] = None
    destinacija: Optional[int] = None
    mesto: Optional[int] = None
    tip_smestaja: Optional[int] = None
    grupa_datuma: Optional[int] = None
    status: Optional[int] = 1
    organizator: Optional[int] = None
    predstavnik: Optional[int] = None
    grafik: Optional[int] = 0


class SmestajUpdate(BaseModel):
    naziv: Optional[str] = None
    drzava: Optional[int] = None
    destinacija: Optional[int] = None
    mesto: Optional[int] = None
    tip_smestaja: Optional[int] = None
    grupa_datuma: Optional[int] = None
    status: Optional[int] = None
    organizator: Optional[int] = None
    predstavnik: Optional[int] = None
    grafik: Optional[int] = None


class PeriodGrupaCreate(BaseModel):
    naziv: str

class SobaCreate(BaseModel):
    veza_id_smestaj: int
    broj_sobe: Optional[str] = ""
    opis: Optional[str] = ""
    tip: Optional[str] = ""
    status: Optional[int] = 1
    opis_dodatno: Optional[str] = ""
    veliki_opis: Optional[str] = ""

class SobaUpdate(BaseModel):
    veza_id_smestaj: Optional[int] = None
    broj_sobe: Optional[str] = None
    opis: Optional[str] = None
    tip: Optional[str] = None
    status: Optional[int] = None
    opis_dodatno: Optional[str] = None
    veliki_opis: Optional[str] = None

class PolazakSave(BaseModel):
    destinacija: Optional[str] = ""
    polazak: Optional[str] = ""
    sat: Optional[str] = ""
    valuta: Optional[str] = ""
    adlrt: Optional[float] = None
    chdrt: Optional[float] = None
    infrt: Optional[float] = None
    adlow: Optional[float] = None
    chdow: Optional[float] = None
    infow: Optional[float] = None

# tip → prikazani naziv (logo je globalni, ostali su dokumenti sa headerom + napomenom)
DOKUMENTI_TIPOVI = {
    "logo": "Logo agencije",
    "predracun": "Predračun",
    "ugovor": "Ugovor",
    "faktura": "Faktura",
    "vaucer": "Vaučer",
    "karta": "Karta",
    "potvrda": "Potvrda",
    "administrativna_zabrana": "Administrativna zabrana",
    "najava": "Najava",
}

DOKUMENT_MAX_SLICA = 4 * 1024 * 1024  # 4 MB


class DokumentSlikaBody(BaseModel):
    data_url: str


class DokumentNapomenaBody(BaseModel):
    napomena: Optional[str] = ""

class PeriodGrupaUpdate(BaseModel):
    naziv: Optional[str] = None

class PeriodDatumCreate(BaseModel):
    grupa_id: int
    datum_od: str   # ISO yyyy-mm-dd
    datum_do: str   # ISO yyyy-mm-dd

class PeriodDatumUpdate(BaseModel):
    datum_od: Optional[str] = None
    datum_do: Optional[str] = None


class SubagentCreate(BaseModel):
    naziv: str
    adresa: Optional[str] = None
    mesto: Optional[str] = None
    osoba: Optional[str] = None
    tel: Optional[str] = None
    tel1: Optional[str] = None
    tel2: Optional[str] = None
    fax: Optional[str] = None
    racun: Optional[str] = None
    provizija: Optional[float] = 0
    provizija1: Optional[float] = 0
    provizija1a: Optional[float] = 0
    provizija2: Optional[float] = 0
    punnaziv: Optional[str] = None
    kontakt: Optional[str] = None


class SubagentUpdate(BaseModel):
    naziv: Optional[str] = None
    adresa: Optional[str] = None
    mesto: Optional[str] = None
    osoba: Optional[str] = None
    tel: Optional[str] = None
    tel1: Optional[str] = None
    tel2: Optional[str] = None
    fax: Optional[str] = None
    racun: Optional[str] = None
    provizija: Optional[float] = None
    provizija1: Optional[float] = None
    provizija1a: Optional[float] = None
    provizija2: Optional[float] = None
    punnaziv: Optional[str] = None
    kontakt: Optional[str] = None


class PredracunCreate(BaseModel):
    ugovor: str
    racun: Optional[str] = ""
    nacin: Optional[str] = ""
    napomena: Optional[str] = ""


class PredracunUpdate(BaseModel):
    racun: Optional[str] = None
    nacin: Optional[str] = None
    napomena: Optional[str] = None


class UplataCreate(BaseModel):
    ugovor: str
    ime: str
    adresa: Optional[str] = ""
    nacin: str
    din: float
    svrha: str


class DodatnaOriginal(BaseModel):
    usluga: Optional[str]
    eur: Optional[float]
    din: Optional[float]

    @field_validator("eur", "din", mode="before")
    @classmethod
    def reject_boolean(cls, value):
        if isinstance(value, bool):
            raise ValueError("Iznos mora biti broj, ne boolean")
        return value


class DodatnaCreate(DodatnaOriginal):
    usluga: str


class DodatnaUpdate(DodatnaCreate):
    original: DodatnaOriginal


class DodatnaDelete(BaseModel):
    original: DodatnaOriginal


def _dodatna_values(body: DodatnaCreate) -> dict:
    usluga = body.usluga.strip()
    if not usluga or len(usluga) > 150:
        raise HTTPException(status_code=400, detail="Usluga mora imati od 1 do 150 znakova")
    for value in (body.eur, body.din):
        if value is None:
            continue
        if not math.isfinite(value):
            raise HTTPException(status_code=400, detail="Iznos mora biti konačan broj")
        amount = Decimal(str(value))
        if amount * 100 != (amount * 100).to_integral_value():
            raise HTTPException(status_code=400, detail="Iznos može imati najviše 2 decimale")
    return {"usluga": usluga, "eur": body.eur, "din": body.din}


class UgovorSmestajUpdate(BaseModel):
    """Promena smeštaja na ugovoru — soba + termin (PATCH /ugovori/{kljuc}/smestaj)."""
    soba_id: int
    datum_od: str   # ISO yyyy-mm-dd
    datum_do: str   # ISO yyyy-mm-dd


# ─── Rezervacije: unos/izmena aranžmana iz forme (Sačuvaj/Izmeni) ───────────
# Advisory lock za dodelu novog broja ugovora (MAX+1 po godini iz Datuma od).
REZ_ADVISORY_LOCK = 9_250_000_000_001


class RezPutnikIn(BaseModel):
    ime: str = ""
    datumRodjenja: Optional[str] = None  # ISO yyyy-mm-dd
    pasos: str = ""
    ow: bool = False
    rt: bool = False
    sp: bool = False
    smer: str = ""
    adresa: str = ""
    telefon: str = ""
    email: str = ""
    ulazak: str = ""  # mesto ulaska (saputnici — aranzman_dopuna.ulazak)


class RezCenaRedIn(BaseModel):
    """Popust/provizija po redu: procenat direktno, ili iznos (EUR/RSD) koji se
    pri čuvanju prevodi u procenat — a kod provizije prevoza u iznos po osobi
    (legacy obračun: provizija = procenatpr × količina)."""
    pct: Optional[float] = None
    eur: Optional[float] = None
    rsd: Optional[float] = None


class RezCeneIn(BaseModel):
    cenaSmestajEUR: float = 0.0
    kolSmestajEUR: float = 1.0
    cenaSmestajRSD: float = 0.0
    kolSmestajRSD: float = 1.0
    popustSmestaj: RezCenaRedIn = RezCenaRedIn()
    cenaPrevozEUR: float = 0.0
    kolPrevozEUR: float = 1.0
    cenaPrevozRSD: float = 0.0
    kolPrevozRSD: float = 1.0
    popustPrevoz: RezCenaRedIn = RezCenaRedIn()
    osiguranjeEUR: float = 0.0
    osiguranjeRSD: float = 0.0
    provizijaSmestaj: RezCenaRedIn = RezCenaRedIn()
    provizijaPrevoz: RezCenaRedIn = RezCenaRedIn()


class RezBoravakIn(BaseModel):
    datumOd: Optional[str] = None  # ISO yyyy-mm-dd
    datumDo: Optional[str] = None
    smestajId: Optional[int] = None
    sobaId: Optional[int] = None
    mestoId: Optional[int] = None
    # fallback: sačuvani naziv van referentne liste (stari ugovori) — ne gubiti ga pri čuvanju
    smestajNaziv: Optional[str] = None
    sobaBroj: Optional[str] = None
    mestoNaziv: Optional[str] = None
    struktura: str = ""
    napomena: str = ""
    napomenaInterna: str = ""


class RezervacijaIn(BaseModel):
    tiprezervacije: str = ""
    subagent: Optional[str] = None  # naziv iz tabele subagenti (aranzman.subagent)
    timelimit: Optional[str] = None  # ISO "yyyy-mm-ddTHH:MM:00" ili null
    nosilac: RezPutnikIn
    saputnici: list[RezPutnikIn] = []
    boravak: RezBoravakIn
    destinacijaId: Optional[int] = None
    destinacijaNaziv: Optional[str] = None  # fallback van referentne liste
    ulazak: str = ""  # mesto ulaska nosioca
    cene: RezCeneIn


# ─── Boje grafik ───────────────────────────────────────────────────────────
DOZVOLJENE_BOJE = ("zelena", "plava", "crvena", "zuta", "ljubicasta", "narandzasta", "crna", "roze")


class BojeGrafik(BaseModel):
    model_config = {"extra": "forbid"}

    isplacen: str
    predrezervacija_aktivna: str
    predrezervacija_istekla: str
    blok: str
    saldo_veci: str
    predrezervacija_subagent: str

    @field_validator("isplacen", "predrezervacija_aktivna", "predrezervacija_istekla",
                     "blok", "saldo_veci", "predrezervacija_subagent")
    @classmethod
    def _validate_boja(cls, v: str) -> str:
        if v not in DOZVOLJENE_BOJE:
            raise ValueError(f"Boja mora biti jedna od: {', '.join(DOZVOLJENE_BOJE)}")
        return v


def _rez_str(v: Optional[str], limit: int) -> Optional[str]:
    """Trim + ograniči na dužinu kolone; prazno → None."""
    s = (v or "").strip()
    return s[:limit] if s else None


def _rez_datum(v: Optional[str], field: str):
    """ISO yyyy-mm-dd → date; prazno → None; neispravno → 400."""
    if v is None or not str(v).strip():
        return None
    try:
        return datetime.strptime(str(v).strip(), "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{field} mora biti datum u formatu YYYY-MM-DD")


def _rez_ts(v: Optional[str]) -> Optional[datetime]:
    if v is None or not str(v).strip():
        return None
    s = str(v).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise HTTPException(status_code=400, detail="Time limit mora biti datum i sat")


def _rez_pct_od_iznosa(iznos: float, osnova: float) -> float:
    """Iznos → procenat osnove (2 dec); osnova 0 → 0."""
    if not osnova or not math.isfinite(osnova) or osnova <= 0:
        return 0.0
    return round(iznos / osnova * 100.0, 2)


def _rez_red_ukupno(red: RezCenaRedIn, bruto_eur: float, bruto_rsd: float) -> Optional[float]:
    """Ukupan iznos redu: procenat × bruto EUR, ili direktno EUR/RSD; ništa → None."""
    if red.pct is not None:
        return round(red.pct / 100.0 * bruto_eur, 2)
    if red.eur is not None:
        return round(red.eur, 2)
    if red.rsd is not None:
        return round(red.rsd, 2)
    return None


def _rez_procenat_iz_reda(red: RezCenaRedIn, bruto_eur: float, bruto_rsd: float) -> float:
    """Procenat za popustar/popustpr/procenatar: pct direktno; iznos EUR → % bruto
    EUR; iznos RSD → % bruto RSD; ništa → 0."""
    if red.pct is not None:
        return round(red.pct, 2)
    ukupno = _rez_red_ukupno(red, bruto_eur, bruto_rsd)
    if ukupno is None:
        return 0.0
    osnova = bruto_eur if red.eur is not None else bruto_rsd
    return _rez_pct_od_iznosa(ukupno, osnova)


# ─── Izvodi XML parsing ──────────────────────────────────────────────────────
def _xml_txt(el, tag: str, default: str = "") -> str:
    node = el.find(tag)
    if node is None or node.text is None:
        return default
    return node.text.strip()


def _xml_num(el, tag: str) -> float:
    val = _xml_txt(el, tag)
    if not val:
        return 0.0
    try:
        return float(val.replace(",", "."))
    except ValueError:
        return 0.0


def _xml_date(el, tag: str):
    val = _xml_txt(el, tag)
    if not val:
        return None
    try:
        return datetime.fromisoformat(val).date()
    except ValueError:
        return None


def parse_izvodi_xml(raw: bytes) -> list:
    """Parse bank statement XML (stmtrslist/stmtrs) — returns list of statement dicts.

    Handles UTF-16 (BOM), UTF-8 and CP1250 encoded files. Nothing is written to disk.
    """
    root = None
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        # Fallback: manual decode + strip encoding declaration
        if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
            txt = raw.decode("utf-16")
        else:
            txt = None
            for enc in ("utf-8-sig", "utf-8", "cp1250", "latin-1"):
                try:
                    txt = raw.decode(enc)
                    break
                except (UnicodeDecodeError, LookupError):
                    continue
            if txt is None:
                raise ValueError("nepoznato kodiranje fajla")
        txt = re.sub(r"^<\?xml[^>]*\?>\s*", "", txt)
        try:
            root = ET.fromstring(txt)
        except ET.ParseError as e:
            raise ValueError(str(e))

    statements = []
    for stmtrs in root.iter("stmtrs"):
        ledger = stmtrs.find("ledgerbal")
        avail = stmtrs.find("availbal")
        transakcije = []
        trnlist = stmtrs.find("trnlist")
        if trnlist is None:
            trnlist = stmtrs
        for trn in trnlist.findall("stmttrn"):
            payee = trn.find("payeeinfo")
            payeeacc = trn.find("payeeaccountinfo")
            dt_posted = _xml_date(trn, "dtposted")
            transakcije.append({
                "fitid": _xml_txt(trn, "fitid"),
                "tip": _xml_txt(trn, "trntype"),
                "smer": _xml_txt(trn, "benefit"),
                "naziv_primaoca": _xml_txt(payee, "name") if payee is not None else "",
                "mesto_primaoca": _xml_txt(payee, "city") if payee is not None else "",
                "racun_primaoca": _xml_txt(payeeacc, "acctid") if payeeacc is not None else "",
                "datum_knjizenja": dt_posted.isoformat() if dt_posted else _xml_txt(trn, "dtposted")[:10],
                "iznos": _xml_num(trn, "trnamt"),
                "valuta": _xml_txt(trn, "curdef"),
                "svrha": _xml_txt(trn, "purpose"),
                "svrha_kod": _xml_txt(trn, "purposecode"),
                "poziv_na_broj": _xml_txt(trn, "payeerefnumber"),
                "model": _xml_txt(trn, "payeerefmodel") or _xml_txt(trn, "refmodel"),
                "mesto_izvrsenja": _xml_txt(trn, "trnplace"),
                "hitnost": _xml_txt(trn, "urgency"),
            })

        dtasof = _xml_date(ledger, "dtasof") if ledger is not None else None
        st = {
            "racun": _xml_txt(stmtrs, "acctid"),
            "broj_izvoda": _xml_txt(stmtrs, "stmtnumber"),
            "datum_izvoda": dtasof,
            "valuta": _xml_txt(stmtrs, "curdef", "RSD"),
            "saldo": _xml_num(ledger, "balamt") if ledger is not None else 0.0,
            "raspolozivo": _xml_num(avail, "balamt") if avail is not None else 0.0,
            "rezervisano": _xml_num(stmtrs, "reservedfunds"),
            "broj_transakcija": len(transakcije),
            "podaci": {
                "rstype": _xml_txt(stmtrs, "rstype"),
                "acctid": _xml_txt(stmtrs, "acctid"),
                "stmtnumber": _xml_txt(stmtrs, "stmtnumber"),
                "curdef": _xml_txt(stmtrs, "curdef"),
                "ledgerbal": {
                    "balamt": _xml_num(ledger, "balamt") if ledger is not None else 0.0,
                    "dtasof": _xml_txt(ledger, "dtasof"),
                } if ledger is not None else {},
                "availbal": {
                    "balamt": _xml_num(avail, "balamt") if avail is not None else 0.0,
                    "dtasof": _xml_txt(avail, "dtasof"),
                } if avail is not None else {},
                "reservedfunds": _xml_num(stmtrs, "reservedfunds"),
                "transakcije": transakcije,
            },
        }
        if st["racun"] or st["broj_izvoda"]:
            statements.append(st)
    return statements


# ─── Auth dependency ─────────────────────────────────────────────────────────
def get_current_user(request: Request):
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Neautorizovan pristup")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Neautorizovan pristup")
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Nevalidan token")


def create_app(static_dir: str) -> FastAPI:
    engine = get_engine()
    init_db(engine)
    init_cenovnici(engine)
    init_koeficijenti(engine)
    init_notifikacije(engine)
    init_rezervacija_log(engine)
    init_profil(engine)

    api = APIRouter()
    register_cenovnici(api, engine, get_current_user)
    register_koeficijenti(api, engine, get_current_user)
    register_notifikacije(api, engine, get_current_user)
    register_rezervacija_log(api, engine, get_current_user)
    register_profil(api, engine, get_current_user, hash_password, verify_password)
    register_dashboard(api, engine, get_current_user)

    # ── Health ──────────────────────────────────────────────────────────────
    @api.get("/health")
    def health():
        return {"ok": True}

    # ── Auth ────────────────────────────────────────────────────────────────
    @api.post("/auth/login")
    def login(body: LoginRequest):
        with engine.connect() as conn:
            row = conn.execute(text("""
                SELECT u.id, u.first_name, u.last_name, u.email, u.username,
                       u.password_hash, u.status, u.is_superadmin,
                       ut.slug as user_type_slug, ut.name as user_type_name
                FROM users u
                LEFT JOIN user_types ut ON u.user_type_id = ut.id
                WHERE u.email = :email
            """), {"email": body.email}).fetchone()

        if not row:
            raise HTTPException(status_code=401, detail="Pogrešan email ili lozinka")
        if not verify_password(body.password, row.password_hash):
            raise HTTPException(status_code=401, detail="Pogrešan email ili lozinka")
        if row.status != "aktivan":
            raise HTTPException(status_code=403, detail="Nalog je neaktivan")

        token = create_access_token({
            "sub": str(row.id),
            "email": row.email,
            "username": row.username,
            "is_superadmin": row.is_superadmin,
            "user_type_slug": row.user_type_slug,
        })
        return {
            "access_token": token,
            "token_type": "bearer",
            "user": {
                "id": row.id,
                "first_name": row.first_name,
                "last_name": row.last_name,
                "email": row.email,
                "username": row.username,
                "is_superadmin": row.is_superadmin,
                "user_type_slug": row.user_type_slug,
                "user_type_name": row.user_type_name,
            }
        }

    @api.get("/auth/me")
    def me(current_user: dict = Depends(get_current_user)):
        with engine.connect() as conn:
            row = conn.execute(text("""
                SELECT u.id, u.first_name, u.last_name, u.email, u.username,
                       u.status, u.is_superadmin,
                       ut.slug as user_type_slug, ut.name as user_type_name
                FROM users u
                LEFT JOIN user_types ut ON u.user_type_id = ut.id
                WHERE u.id = :id
            """), {"id": int(current_user["sub"])}).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Korisnik nije pronađen")
        return {
            "id": row.id,
            "first_name": row.first_name,
            "last_name": row.last_name,
            "email": row.email,
            "username": row.username,
            "is_superadmin": row.is_superadmin,
            "user_type_slug": row.user_type_slug,
            "user_type_name": row.user_type_name,
        }

    # ── User Types ──────────────────────────────────────────────────────────
    @api.get("/user-types")
    def list_user_types(_: dict = Depends(get_current_user)):
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT id, name, slug, description, created_at FROM user_types ORDER BY id"
            )).fetchall()
        return [{"id": r.id, "name": r.name, "slug": r.slug,
                 "description": r.description,
                 "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]

    @api.post("/user-types")
    def create_user_type(body: UserTypeCreate, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            row = conn.execute(text("""
                INSERT INTO user_types (name, slug, description)
                VALUES (:name, :slug, :desc)
                RETURNING id, name, slug, description, created_at
            """), {"name": body.name, "slug": body.slug, "desc": body.description}).fetchone()
        return {"id": row.id, "name": row.name, "slug": row.slug,
                "description": row.description,
                "created_at": row.created_at.isoformat() if row.created_at else None}

    @api.put("/user-types/{type_id}")
    def update_user_type(type_id: int, body: UserTypeUpdate, _: dict = Depends(get_current_user)):
        fields = {k: v for k, v in body.model_dump().items() if v is not None}
        if not fields:
            raise HTTPException(status_code=400, detail="Nema podataka za ažuriranje")
        set_clause = ", ".join(f"{k} = :{k}" for k in fields)
        fields["id"] = type_id
        with engine.begin() as conn:
            row = conn.execute(text(f"""
                UPDATE user_types SET {set_clause}
                WHERE id = :id
                RETURNING id, name, slug, description, created_at
            """), fields).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Tip korisnika nije pronađen")
        return {"id": row.id, "name": row.name, "slug": row.slug,
                "description": row.description,
                "created_at": row.created_at.isoformat() if row.created_at else None}

    @api.delete("/user-types/{type_id}")
    def delete_user_type(type_id: int, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            result = conn.execute(text(
                "DELETE FROM user_types WHERE id = :id RETURNING id"
            ), {"id": type_id}).fetchone()
        if not result:
            raise HTTPException(status_code=404, detail="Tip korisnika nije pronađen")
        return {"ok": True}

    # ── Users ───────────────────────────────────────────────────────────────
    @api.get("/users")
    def list_users(_: dict = Depends(get_current_user)):
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT u.id, u.first_name, u.last_name, u.email, u.phone,
                       u.address, u.city, u.status, u.username,
                       u.is_superadmin, u.created_at,
                       ut.id as user_type_id, ut.name as user_type_name, ut.slug as user_type_slug
                FROM users u
                LEFT JOIN user_types ut ON u.user_type_id = ut.id
                ORDER BY u.id
            """)).fetchall()
        return [{
            "id": r.id, "first_name": r.first_name, "last_name": r.last_name,
            "email": r.email, "phone": r.phone, "address": r.address,
            "city": r.city, "status": r.status, "username": r.username,
            "is_superadmin": r.is_superadmin,
            "user_type_id": r.user_type_id,
            "user_type_name": r.user_type_name,
            "user_type_slug": r.user_type_slug,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        } for r in rows]

    @api.post("/users")
    def create_user(body: UserCreate, _: dict = Depends(get_current_user)):
        pw_hash = hash_password(body.password)
        with engine.begin() as conn:
            try:
                row = conn.execute(text("""
                    INSERT INTO users
                        (first_name, last_name, email, phone, address, city,
                         status, username, password_hash, user_type_id)
                    VALUES
                        (:first_name, :last_name, :email, :phone, :address, :city,
                         :status, :username, :pw, :user_type_id)
                    RETURNING id, first_name, last_name, email, phone, address,
                              city, status, username, user_type_id, created_at
                """), {
                    "first_name": body.first_name, "last_name": body.last_name,
                    "email": body.email, "phone": body.phone,
                    "address": body.address, "city": body.city,
                    "status": body.status, "username": body.username,
                    "pw": pw_hash, "user_type_id": body.user_type_id,
                }).fetchone()
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Greška: {str(e)}")
        return {
            "id": row.id, "first_name": row.first_name, "last_name": row.last_name,
            "email": row.email, "phone": row.phone, "address": row.address,
            "city": row.city, "status": row.status, "username": row.username,
            "user_type_id": row.user_type_id,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    @api.put("/users/{user_id}")
    def update_user(user_id: int, body: UserUpdate, _: dict = Depends(get_current_user)):
        data = body.model_dump(exclude_none=True)
        if "password" in data:
            data["password_hash"] = hash_password(data.pop("password"))
        data["updated_at"] = datetime.now(timezone.utc)
        if not data:
            raise HTTPException(status_code=400, detail="Nema podataka za ažuriranje")
        set_clause = ", ".join(f"{k} = :{k}" for k in data)
        data["id"] = user_id
        with engine.begin() as conn:
            row = conn.execute(text(f"""
                UPDATE users SET {set_clause}
                WHERE id = :id
                RETURNING id, first_name, last_name, email, phone, address,
                          city, status, username, user_type_id, updated_at
            """), data).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Korisnik nije pronađen")
        return {"id": row.id, "first_name": row.first_name, "last_name": row.last_name,
                "email": row.email, "phone": row.phone, "address": row.address,
                "city": row.city, "status": row.status, "username": row.username,
                "user_type_id": row.user_type_id}

    @api.delete("/users/{user_id}")
    def delete_user(user_id: int, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            result = conn.execute(text(
                "DELETE FROM users WHERE id = :id AND is_superadmin = FALSE RETURNING id"
            ), {"id": user_id}).fetchone()
        if not result:
            raise HTTPException(status_code=404, detail="Korisnik nije pronađen ili ne može biti obrisan")
        return {"ok": True}

    # ── Tip Ponude ──────────────────────────────────────────────────────────
    @api.get("/tip-ponude")
    def list_tip_ponude(_: dict = Depends(get_current_user)):
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT id, naziv FROM tip_ponude ORDER BY id"
            )).fetchall()
        return [{"id": r.id, "naziv": r.naziv} for r in rows]

    @api.post("/tip-ponude")
    def create_tip_ponude(body: TipPonudeCreate, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            row = conn.execute(text("""
                INSERT INTO tip_ponude (naziv)
                VALUES (:naziv)
                RETURNING id, naziv
            """), {"naziv": body.naziv}).fetchone()
        return {"id": row.id, "naziv": row.naziv}

    @api.put("/tip-ponude/{item_id}")
    def update_tip_ponude(item_id: int, body: TipPonudeUpdate, _: dict = Depends(get_current_user)):
        fields = {k: v for k, v in body.model_dump().items() if v is not None}
        if not fields:
            raise HTTPException(status_code=400, detail="Nema podataka za ažuriranje")
        set_clause = ", ".join(f"{k} = :{k}" for k in fields)
        fields["id"] = item_id
        with engine.begin() as conn:
            row = conn.execute(text(f"""
                UPDATE tip_ponude SET {set_clause}
                WHERE id = :id
                RETURNING id, naziv
            """), fields).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Tip ponude nije pronađen")
        return {"id": row.id, "naziv": row.naziv}

    @api.delete("/tip-ponude/{item_id}")
    def delete_tip_ponude(item_id: int, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            result = conn.execute(text(
                "DELETE FROM tip_ponude WHERE id = :id RETURNING id"
            ), {"id": item_id}).fetchone()
        if not result:
            raise HTTPException(status_code=404, detail="Tip ponude nije pronađen")
        return {"ok": True}

    # ── Drzava ──────────────────────────────────────────────────────────────
    @api.get("/drzava")
    def list_drzava(_: dict = Depends(get_current_user)):
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT id, id_cis, naziv, naziv_cis FROM drzava ORDER BY id"
            )).fetchall()
        return [{"id": r.id, "id_cis": r.id_cis, "naziv": r.naziv, "naziv_cis": r.naziv_cis} for r in rows]

    @api.post("/drzava")
    def create_drzava(body: DrzavaCreate, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            row = conn.execute(text("""
                INSERT INTO drzava (id_cis, naziv, naziv_cis)
                VALUES (:id_cis, :naziv, :naziv_cis)
                RETURNING id, id_cis, naziv, naziv_cis
            """), {"id_cis": body.id_cis, "naziv": body.naziv, "naziv_cis": body.naziv_cis}).fetchone()
        return {"id": row.id, "id_cis": row.id_cis, "naziv": row.naziv, "naziv_cis": row.naziv_cis}

    @api.put("/drzava/{item_id}")
    def update_drzava(item_id: int, body: DrzavaUpdate, _: dict = Depends(get_current_user)):
        fields = {k: v for k, v in body.model_dump().items() if v is not None}
        if not fields:
            raise HTTPException(status_code=400, detail="Nema podataka za ažuriranje")
        set_clause = ", ".join(f"{k} = :{k}" for k in fields)
        fields["id"] = item_id
        with engine.begin() as conn:
            row = conn.execute(text(f"""
                UPDATE drzava SET {set_clause}
                WHERE id = :id
                RETURNING id, id_cis, naziv, naziv_cis
            """), fields).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Država nije pronađena")
        return {"id": row.id, "id_cis": row.id_cis, "naziv": row.naziv, "naziv_cis": row.naziv_cis}

    @api.delete("/drzava/{item_id}")
    def delete_drzava(item_id: int, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            result = conn.execute(text(
                "DELETE FROM drzava WHERE id = :id RETURNING id"
            ), {"id": item_id}).fetchone()
        if not result:
            raise HTTPException(status_code=404, detail="Država nije pronađena")
        return {"ok": True}

    # ── Destinacija ─────────────────────────────────────────────────────────
    @api.get("/destinacija")
    def list_destinacija(_: dict = Depends(get_current_user)):
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT d.id, d.naziv, d.drzava, d.status, d.organizator,
                       d.predstavnik, d.naziv_cis, dr.naziv as drzava_naziv
                FROM destinacija d
                LEFT JOIN drzava dr ON d.drzava = dr.id
                ORDER BY d.id
            """)).fetchall()
        return [{
            "id": r.id, "naziv": r.naziv, "drzava": r.drzava,
            "status": r.status, "organizator": r.organizator,
            "predstavnik": r.predstavnik, "naziv_cis": r.naziv_cis,
            "drzava_naziv": r.drzava_naziv,
        } for r in rows]

    @api.post("/destinacija")
    def create_destinacija(body: DestinacijaCreate, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            row = conn.execute(text("""
                INSERT INTO destinacija (naziv, drzava, status, organizator, predstavnik, naziv_cis)
                VALUES (:naziv, :drzava, :status, :organizator, :predstavnik, :naziv_cis)
                RETURNING id, naziv, drzava, status, organizator, predstavnik, naziv_cis
            """), {
                "naziv": body.naziv, "drzava": body.drzava, "status": body.status,
                "organizator": body.organizator, "predstavnik": body.predstavnik,
                "naziv_cis": body.naziv_cis,
            }).fetchone()
        return {
            "id": row.id, "naziv": row.naziv, "drzava": row.drzava,
            "status": row.status, "organizator": row.organizator,
            "predstavnik": row.predstavnik, "naziv_cis": row.naziv_cis,
        }

    @api.put("/destinacija/{item_id}")
    def update_destinacija(item_id: int, body: DestinacijaUpdate, _: dict = Depends(get_current_user)):
        fields = {k: v for k, v in body.model_dump().items() if v is not None}
        if not fields:
            raise HTTPException(status_code=400, detail="Nema podataka za ažuriranje")
        set_clause = ", ".join(f"{k} = :{k}" for k in fields)
        fields["id"] = item_id
        with engine.begin() as conn:
            row = conn.execute(text(f"""
                UPDATE destinacija SET {set_clause}
                WHERE id = :id
                RETURNING id, naziv, drzava, status, organizator, predstavnik, naziv_cis
            """), fields).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Destinacija nije pronađena")
        return {
            "id": row.id, "naziv": row.naziv, "drzava": row.drzava,
            "status": row.status, "organizator": row.organizator,
            "predstavnik": row.predstavnik, "naziv_cis": row.naziv_cis,
        }

    @api.delete("/destinacija/{item_id}")
    def delete_destinacija(item_id: int, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            result = conn.execute(text(
                "DELETE FROM destinacija WHERE id = :id RETURNING id"
            ), {"id": item_id}).fetchone()
        if not result:
            raise HTTPException(status_code=404, detail="Destinacija nije pronađena")
        return {"ok": True}

    # ── Mesto ───────────────────────────────────────────────────────────────
    def _mesto_snimi_grupe(conn, mesto_id: int, grupe: List[int]) -> None:
        """Zapisuje veze mesto ↔ grupe perioda (duple se ignorišu, redosled se čuva)."""
        ids: list = []
        for g in grupe or []:
            if isinstance(g, int) and g > 0 and g not in ids:
                ids.append(g)
        for g in ids:
            conn.execute(text("""
                INSERT INTO mesto_grupa (mesto_id, grupa_id)
                VALUES (:m, :g)
                ON CONFLICT (mesto_id, grupa_id) DO NOTHING
            """), {"m": mesto_id, "g": g})

    @api.get("/mesto")
    def list_mesto(_: dict = Depends(get_current_user)):
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT m.id, m.naziv, m.drzava, m.destinacija, m.grupa_datuma, m.status,
                       m.organizator, m.predstavnik, m.grafik, m.cis,
                       dr.naziv as drzava_naziv, de.naziv as destinacija_naziv,
                       pg.naziv as grupa_datuma_naziv,
                       COALESCE((SELECT array_agg(mg.grupa_id ORDER BY CASE WHEN mg.grupa_id = m.grupa_datuma THEN 0 ELSE 1 END, mg.grupa_id)
                                 FROM mesto_grupa mg WHERE mg.mesto_id = m.id),
                                ARRAY[]::INTEGER[]) AS grupe,
                       COALESCE((SELECT array_agg(pg2.naziv ORDER BY CASE WHEN mg2.grupa_id = m.grupa_datuma THEN 0 ELSE 1 END, mg2.grupa_id)
                                 FROM mesto_grupa mg2
                                 JOIN period_grupa pg2 ON pg2.id = mg2.grupa_id
                                 WHERE mg2.mesto_id = m.id),
                                ARRAY[]::VARCHAR[]) AS grupe_nazivi
                FROM mesto m
                LEFT JOIN drzava dr ON m.drzava = dr.id
                LEFT JOIN destinacija de ON m.destinacija = de.id
                LEFT JOIN period_grupa pg ON m.grupa_datuma = pg.id
                ORDER BY m.id
            """)).fetchall()
        return [{
            "id": r.id, "naziv": r.naziv, "drzava": r.drzava,
            "destinacija": r.destinacija, "grupa_datuma": r.grupa_datuma,
            "grupe": list(r.grupe or []), "grupe_nazivi": list(r.grupe_nazivi or []),
            "status": r.status,
            "organizator": r.organizator, "predstavnik": r.predstavnik,
            "grafik": r.grafik, "cis": r.cis,
            "drzava_naziv": r.drzava_naziv, "destinacija_naziv": r.destinacija_naziv,
            "grupa_datuma_naziv": r.grupa_datuma_naziv,
        } for r in rows]

    @api.post("/mesto")
    def create_mesto(body: MestoCreate, _: dict = Depends(get_current_user)):
        # grupe: nova polja (lista ID-jeva); fallback na staro grupa_datuma ako nije poslato
        grupe = body.grupe if body.grupe is not None else ([body.grupa_datuma] if body.grupa_datuma else [])
        primarna = grupe[0] if grupe else body.grupa_datuma
        with engine.begin() as conn:
            row = conn.execute(text("""
                INSERT INTO mesto (naziv, drzava, destinacija, grupa_datuma, status, organizator, predstavnik, grafik, cis)
                VALUES (:naziv, :drzava, :destinacija, :grupa_datuma, :status, :organizator, :predstavnik, :grafik, :cis)
                RETURNING id, naziv, drzava, destinacija, grupa_datuma, status, organizator, predstavnik, grafik, cis
            """), {
                "naziv": body.naziv, "drzava": body.drzava, "destinacija": body.destinacija,
                "grupa_datuma": primarna,
                "status": body.status, "organizator": body.organizator,
                "predstavnik": body.predstavnik, "grafik": body.grafik, "cis": body.cis,
            }).fetchone()
            _mesto_snimi_grupe(conn, row.id, grupe)
        return {
            "id": row.id, "naziv": row.naziv, "drzava": row.drzava,
            "destinacija": row.destinacija, "grupa_datuma": row.grupa_datuma,
            "grupe": grupe,
            "status": row.status,
            "organizator": row.organizator, "predstavnik": row.predstavnik,
            "grafik": row.grafik, "cis": row.cis,
        }

    @api.put("/mesto/{item_id}")
    def update_mesto(item_id: int, body: MestoUpdate, _: dict = Depends(get_current_user)):
        fields = {k: v for k, v in body.model_dump().items() if v is not None}
        # grupe se ne upisuju direktno u mesto — idu u mesto_grupa; primarna (prva) ide u grupa_datuma
        grupe = fields.pop("grupe", None)
        if grupe is not None:
            fields["grupa_datuma"] = grupe[0] if grupe else None
        if not fields:
            raise HTTPException(status_code=400, detail="Nema podataka za ažuriranje")
        set_clause = ", ".join(f"{k} = :{k}" for k in fields)
        fields["id"] = item_id
        with engine.begin() as conn:
            row = conn.execute(text(f"""
                UPDATE mesto SET {set_clause}
                WHERE id = :id
                RETURNING id, naziv, drzava, destinacija, grupa_datuma, status, organizator, predstavnik, grafik, cis
            """), fields).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Mesto nije pronađeno")
            if grupe is not None:
                conn.execute(text("DELETE FROM mesto_grupa WHERE mesto_id = :id"),
                             {"id": item_id})
                _mesto_snimi_grupe(conn, item_id, grupe)
        return {
            "id": row.id, "naziv": row.naziv, "drzava": row.drzava,
            "destinacija": row.destinacija, "grupa_datuma": row.grupa_datuma,
            "grupe": grupe,
            "status": row.status,
            "organizator": row.organizator, "predstavnik": row.predstavnik,
            "grafik": row.grafik, "cis": row.cis,
        }

    @api.delete("/mesto/{item_id}")
    def delete_mesto(item_id: int, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            result = conn.execute(text(
                "DELETE FROM mesto WHERE id = :id RETURNING id"
            ), {"id": item_id}).fetchone()
        if not result:
            raise HTTPException(status_code=404, detail="Mesto nije pronađeno")
        return {"ok": True}

    # ── Tip Smestaja ────────────────────────────────────────────────────────
    @api.get("/tip-smestaja")
    def list_tip_smestaja(_: dict = Depends(get_current_user)):
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT id, naziv FROM tip_smestaja ORDER BY id"
            )).fetchall()
        return [{"id": r.id, "naziv": r.naziv} for r in rows]

    @api.post("/tip-smestaja")
    def create_tip_smestaja(body: TipSmestajaCreate, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            row = conn.execute(text("""
                INSERT INTO tip_smestaja (naziv)
                VALUES (:naziv)
                RETURNING id, naziv
            """), {"naziv": body.naziv}).fetchone()
        return {"id": row.id, "naziv": row.naziv}

    @api.put("/tip-smestaja/{item_id}")
    def update_tip_smestaja(item_id: int, body: TipSmestajaUpdate, _: dict = Depends(get_current_user)):
        fields = {k: v for k, v in body.model_dump().items() if v is not None}
        if not fields:
            raise HTTPException(status_code=400, detail="Nema podataka za ažuriranje")
        set_clause = ", ".join(f"{k} = :{k}" for k in fields)
        fields["id"] = item_id
        with engine.begin() as conn:
            row = conn.execute(text(f"""
                UPDATE tip_smestaja SET {set_clause}
                WHERE id = :id
                RETURNING id, naziv
            """), fields).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Tip smeštaja nije pronađen")
        return {"id": row.id, "naziv": row.naziv}

    @api.delete("/tip-smestaja/{item_id}")
    def delete_tip_smestaja(item_id: int, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            result = conn.execute(text(
                "DELETE FROM tip_smestaja WHERE id = :id RETURNING id"
            ), {"id": item_id}).fetchone()
        if not result:
            raise HTTPException(status_code=404, detail="Tip smeštaja nije pronađen")
        return {"ok": True}

    # ── Smestaj ─────────────────────────────────────────────────────────────
    @api.get("/smestaj")
    def list_smestaj(_: dict = Depends(get_current_user)):
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT s.id, s.naziv, s.drzava, s.destinacija, s.mesto, s.tip_smestaja,
                       s.grupa_datuma, s.status, s.organizator, s.predstavnik, s.grafik,
                       dr.naziv as drzava_naziv, de.naziv as destinacija_naziv,
                       me.naziv as mesto_naziv, ts.naziv as tip_smestaja_naziv,
                       pg.naziv as grupa_datuma_naziv
                FROM smestaj s
                LEFT JOIN drzava dr ON s.drzava = dr.id
                LEFT JOIN destinacija de ON s.destinacija = de.id
                LEFT JOIN mesto me ON s.mesto = me.id
                LEFT JOIN tip_smestaja ts ON s.tip_smestaja = ts.id
                LEFT JOIN period_grupa pg ON s.grupa_datuma = pg.id
                ORDER BY s.id
            """)).fetchall()
        return [{
            "id": r.id, "naziv": r.naziv, "drzava": r.drzava,
            "destinacija": r.destinacija, "mesto": r.mesto, "tip_smestaja": r.tip_smestaja,
            "grupa_datuma": r.grupa_datuma,
            "status": r.status, "organizator": r.organizator,
            "predstavnik": r.predstavnik, "grafik": r.grafik,
            "drzava_naziv": r.drzava_naziv,
            "destinacija_naziv": r.destinacija_naziv,
            "mesto_naziv": r.mesto_naziv,
            "tip_smestaja_naziv": r.tip_smestaja_naziv,
            "grupa_datuma_naziv": r.grupa_datuma_naziv,
        } for r in rows]

    @api.post("/smestaj")
    def create_smestaj(body: SmestajCreate, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            row = conn.execute(text("""
                INSERT INTO smestaj (naziv, drzava, destinacija, mesto, tip_smestaja, grupa_datuma, status, organizator, predstavnik, grafik)
                VALUES (:naziv, :drzava, :destinacija, :mesto, :tip_smestaja, :grupa_datuma, :status, :organizator, :predstavnik, :grafik)
                RETURNING id, naziv, drzava, destinacija, mesto, tip_smestaja, grupa_datuma, status, organizator, predstavnik, grafik
            """), {
                "naziv": body.naziv, "drzava": body.drzava, "destinacija": body.destinacija,
                "mesto": body.mesto, "tip_smestaja": body.tip_smestaja,
                "grupa_datuma": body.grupa_datuma, "status": body.status,
                "organizator": body.organizator, "predstavnik": body.predstavnik, "grafik": body.grafik,
            }).fetchone()
        return {
            "id": row.id, "naziv": row.naziv, "drzava": row.drzava,
            "destinacija": row.destinacija, "mesto": row.mesto, "tip_smestaja": row.tip_smestaja,
            "grupa_datuma": row.grupa_datuma,
            "status": row.status, "organizator": row.organizator,
            "predstavnik": row.predstavnik, "grafik": row.grafik,
        }

    @api.put("/smestaj/{item_id}")
    def update_smestaj(item_id: int, body: SmestajUpdate, _: dict = Depends(get_current_user)):
        fields = {k: v for k, v in body.model_dump().items() if v is not None}
        if not fields:
            raise HTTPException(status_code=400, detail="Nema podataka za ažuriranje")
        set_clause = ", ".join(f"{k} = :{k}" for k in fields)
        fields["id"] = item_id
        with engine.begin() as conn:
            row = conn.execute(text(f"""
                UPDATE smestaj SET {set_clause}
                WHERE id = :id
                RETURNING id, naziv, drzava, destinacija, mesto, tip_smestaja, grupa_datuma, status, organizator, predstavnik, grafik
            """), fields).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Smeštaj nije pronađen")
        return {
            "id": row.id, "naziv": row.naziv, "drzava": row.drzava,
            "destinacija": row.destinacija, "mesto": row.mesto, "tip_smestaja": row.tip_smestaja,
            "grupa_datuma": row.grupa_datuma,
            "status": row.status, "organizator": row.organizator,
            "predstavnik": row.predstavnik, "grafik": row.grafik,
        }

    @api.delete("/smestaj/{item_id}")
    def delete_smestaj(item_id: int, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            result = conn.execute(text(
                "DELETE FROM smestaj WHERE id = :id RETURNING id"
            ), {"id": item_id}).fetchone()
        if not result:
            raise HTTPException(status_code=404, detail="Smeštaj nije pronađen")
        return {"ok": True}

    # ── Sobe (veza na smestaj: više soba → jedan smeštaj) ──────────────────
    @api.get("/sobe")
    def list_sobe(request: Request, _: dict = Depends(get_current_user)):
        q = (request.query_params.get("q") or "").strip()
        where = ""
        bind = {}
        if q:
            like = f"%{q}%"
            conds = " OR ".join(
                f"COALESCE({c}::text, '') ILIKE :q"
                for c in ("b.broj_sobe", "b.opis", "b.tip", "b.opis_dodatno", "b.veliki_opis", "s.naziv", "m.naziv")
            )
            where = f"WHERE {conds}"
            bind["q"] = like
        with engine.connect() as conn:
            rows = conn.execute(text(f"""
                SELECT b.id, b.veza_id_smestaj, b.broj_sobe, b.opis, b.tip,
                       b.status, b.opis_dodatno, b.veliki_opis,
                       s.naziv AS smestaj_naziv, m.naziv AS mesto_naziv
                FROM sobe b
                LEFT JOIN smestaj s ON b.veza_id_smestaj = s.id
                LEFT JOIN mesto m ON m.id = s.mesto
                {where}
                ORDER BY s.naziv, b.broj_sobe
                LIMIT 2000
            """), bind).fetchall()
            dodati_po_sobi: dict[int, list[str]] = {}
            for dk in conn.execute(text(
                "SELECT soba_id, struktura FROM soba_koeficijenti ORDER BY id"
            )).fetchall():
                dodati_po_sobi.setdefault(dk[0], []).append(dk[1])
        return [{
            "id": r.id, "veza_id_smestaj": r.veza_id_smestaj,
            "broj_sobe": r.broj_sobe, "opis": r.opis, "tip": r.tip,
            "status": r.status, "opis_dodatno": r.opis_dodatno,
            "veliki_opis": r.veliki_opis, "smestaj_naziv": r.smestaj_naziv,
            "mesto_naziv": r.mesto_naziv,
            # nazivi koeficijenata: osnovni (po tipu sobe) + dodatni definisani
            "koeficijenti": ([(r.tip or "").strip()] if (r.tip or "").strip() else [])
                + dodati_po_sobi.get(r.id, []),
        } for r in rows]

    @api.post("/sobe")
    def create_soba(body: SobaCreate, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            exists = conn.execute(text(
                "SELECT 1 FROM smestaj WHERE id = :id"
            ), {"id": body.veza_id_smestaj}).fetchone()
            if not exists:
                raise HTTPException(status_code=404, detail="Smeštaj nije pronađen")
            row = conn.execute(text("""
                INSERT INTO sobe (veza_id_smestaj, broj_sobe, opis, tip, status, opis_dodatno, veliki_opis)
                VALUES (:smestaj, :broj_sobe, :opis, :tip, :status, :opis_dodatno, :veliki_opis)
                RETURNING id, veza_id_smestaj, broj_sobe, opis, tip, status, opis_dodatno, veliki_opis
            """), {
                "smestaj": body.veza_id_smestaj, "broj_sobe": body.broj_sobe or "",
                "opis": body.opis or "", "tip": body.tip or "", "status": body.status if body.status is not None else 1,
                "opis_dodatno": body.opis_dodatno or "", "veliki_opis": body.veliki_opis or "",
            }).fetchone()
            # početni koeficijent: soba 1/2 dobija koeficijent 1/2, 1/3 → 1/3 ... (nule ako ne postoji)
            osiguraj_auto_red(conn, row.tip)
        return {
            "id": row.id, "veza_id_smestaj": row.veza_id_smestaj,
            "broj_sobe": row.broj_sobe, "opis": row.opis, "tip": row.tip,
            "status": row.status, "opis_dodatno": row.opis_dodatno,
            "veliki_opis": row.veliki_opis,
        }

    @api.put("/sobe/{item_id}")
    def update_soba(item_id: int, body: SobaUpdate, _: dict = Depends(get_current_user)):
        fields = {k: v for k, v in body.model_dump().items() if v is not None}
        if not fields:
            raise HTTPException(status_code=400, detail="Nema podataka za ažuriranje")
        if "veza_id_smestaj" in fields:
            with engine.begin() as conn:
                exists = conn.execute(text(
                    "SELECT 1 FROM smestaj WHERE id = :id"
                ), {"id": fields["veza_id_smestaj"]}).fetchone()
            if not exists:
                raise HTTPException(status_code=404, detail="Smeštaj nije pronađen")
        set_clause = ", ".join(f"{k} = :{k}" for k in fields)
        fields["id"] = item_id
        with engine.begin() as conn:
            row = conn.execute(text(f"""
                UPDATE sobe SET {set_clause}
                WHERE id = :id
                RETURNING id, veza_id_smestaj, broj_sobe, opis, tip, status, opis_dodatno, veliki_opis
            """), fields).fetchone()
            if "tip" in fields:
                osiguraj_auto_red(conn, row.tip)
        if not row:
            raise HTTPException(status_code=404, detail="Soba nije pronađena")
        return {
            "id": row.id, "veza_id_smestaj": row.veza_id_smestaj,
            "broj_sobe": row.broj_sobe, "opis": row.opis, "tip": row.tip,
            "status": row.status, "opis_dodatno": row.opis_dodatno,
            "veliki_opis": row.veliki_opis,
        }

    @api.delete("/sobe/{item_id}")
    def delete_soba(item_id: int, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            result = conn.execute(text(
                "DELETE FROM sobe WHERE id = :id RETURNING id"
            ), {"id": item_id}).fetchone()
        if not result:
            raise HTTPException(status_code=404, detail="Soba nije pronađena")
        return {"ok": True}

    # ── Polazak (cena i mesto polaska agencijskog prevoza) ─────────────────
    POLAZAK_COLS = ("id, destinacija, polazak, sat, valuta, "
                    "adlrt, chdrt, infrt, adlow, chdow, infow")

    @api.get("/polazak")
    def list_polazak(_: dict = Depends(get_current_user)):
        with engine.connect() as conn:
            rows = conn.execute(text(f"""
                SELECT {POLAZAK_COLS} FROM polazak
                ORDER BY destinacija, polazak, sat, id
            """)).fetchall()
        return [dict(r._mapping) for r in rows]

    @api.post("/polazak")
    def create_polazak(body: PolazakSave, _: dict = Depends(get_current_user)):
        vals = body.model_dump()
        with engine.begin() as conn:
            row = conn.execute(text(f"""
                INSERT INTO polazak (destinacija, polazak, sat, valuta,
                                     adlrt, chdrt, infrt, adlow, chdow, infow)
                VALUES (:destinacija, :polazak, :sat, :valuta,
                        :adlrt, :chdrt, :infrt, :adlow, :chdow, :infow)
                RETURNING {POLAZAK_COLS}
            """), vals).fetchone()
        return dict(row._mapping)

    @api.put("/polazak/{item_id}")
    def update_polazak(item_id: int, body: PolazakSave, _: dict = Depends(get_current_user)):
        vals = body.model_dump()
        vals["id"] = item_id
        with engine.begin() as conn:
            row = conn.execute(text(f"""
                UPDATE polazak SET
                    destinacija = :destinacija, polazak = :polazak,
                    sat = :sat, valuta = :valuta,
                    adlrt = :adlrt, chdrt = :chdrt, infrt = :infrt,
                    adlow = :adlow, chdow = :chdow, infow = :infow
                WHERE id = :id
                RETURNING {POLAZAK_COLS}
            """), vals).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Polazak nije pronađen")
        return dict(row._mapping)

    @api.delete("/polazak/{item_id}")
    def delete_polazak(item_id: int, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            result = conn.execute(text(
                "DELETE FROM polazak WHERE id = :id RETURNING id"
            ), {"id": item_id}).fetchone()
        if not result:
            raise HTTPException(status_code=404, detail="Polazak nije pronađen")
        return {"ok": True}

    # ── Dokumenti (logo + headeri i napomene za štampane dokumente) ────────
    def _dokument_out(r) -> dict:
        slika = None
        if r.slika:
            mime = r.slika_mime or "image/png"
            slika = f"data:{mime};base64,{r.slika}"
        return {"tip": r.tip, "naziv": r.naziv, "napomena": r.napomena,
                "slika": slika, "updated_at": r.updated_at.isoformat() if r.updated_at else None}

    @api.get("/dokumenti")
    def list_dokumenti(_: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            for tip, naziv in DOKUMENTI_TIPOVI.items():
                conn.execute(text("""
                    INSERT INTO dokumenti (tip, naziv)
                    VALUES (:tip, :naziv)
                    ON CONFLICT (tip) DO NOTHING
                """), {"tip": tip, "naziv": naziv})
            rows = conn.execute(text(
                "SELECT * FROM dokumenti ORDER BY id"
            )).fetchall()
        return [_dokument_out(r) for r in rows]

    @api.post("/dokumenti/{tip}/slika")
    def upload_dokument_slika(tip: str, body: DokumentSlikaBody, _: dict = Depends(get_current_user)):
        if tip not in DOKUMENTI_TIPOVI:
            raise HTTPException(status_code=404, detail="Nepoznat tip dokumenta")
        m = re.match(r"^data:(image/[a-zA-Z0-9.+-]+);base64,(.*)$", body.data_url.strip(), re.S)
        if not m:
            raise HTTPException(status_code=400, detail="Slika mora biti data URL (image/*)")
        mime, b64 = m.group(1), m.group(2)
        try:
            data = base64.b64decode(b64)
        except Exception:
            raise HTTPException(status_code=400, detail="Neispravan base64 sadržaj")
        if not data:
            raise HTTPException(status_code=400, detail="Prazna slika")
        if len(data) > DOKUMENT_MAX_SLICA:
            raise HTTPException(status_code=400, detail="Slika je veća od 4 MB")
        b64_clean = base64.b64encode(data).decode("ascii")
        with engine.begin() as conn:
            row = conn.execute(text("""
                UPDATE dokumenti
                SET slika = :slika, slika_mime = :mime, updated_at = NOW()
                WHERE tip = :tip
                RETURNING *
            """), {"slika": b64_clean, "mime": mime, "tip": tip}).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Nepoznat tip dokumenta")
        return _dokument_out(row)

    @api.delete("/dokumenti/{tip}/slika")
    def delete_dokument_slika(tip: str, _: dict = Depends(get_current_user)):
        if tip not in DOKUMENTI_TIPOVI:
            raise HTTPException(status_code=404, detail="Nepoznat tip dokumenta")
        with engine.begin() as conn:
            row = conn.execute(text("""
                UPDATE dokumenti
                SET slika = NULL, slika_mime = NULL, updated_at = NOW()
                WHERE tip = :tip
                RETURNING *
            """), {"tip": tip}).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Nepoznat tip dokumenta")
        return _dokument_out(row)

    @api.put("/dokumenti/{tip}/napomena")
    def update_dokument_napomena(tip: str, body: DokumentNapomenaBody, _: dict = Depends(get_current_user)):
        if tip not in DOKUMENTI_TIPOVI:
            raise HTTPException(status_code=404, detail="Nepoznat tip dokumenta")
        with engine.begin() as conn:
            row = conn.execute(text("""
                UPDATE dokumenti
                SET napomena = :napomena, updated_at = NOW()
                WHERE tip = :tip
                RETURNING *
            """), {"napomena": body.napomena or "", "tip": tip}).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Nepoznat tip dokumenta")
        return _dokument_out(row)

    # ── Grafik (gant po sobama: periodi grupe + ugovori smeštaja) ──────────
    # ── Pretraga slobodnih kapaciteta ──────────────────────────────────────
    # Maksimalan broj noćenja koji se NUDI u listi trajanja (krajevi lanaca
    # preko tog broja se ne prikazuju); pretraga konkretnog boravka (od+do)
    # nije ograničena — granica važi samo za ponuđene opcije
    MAX_NOCENJA_OPCIJE = 30

    # Privremene fiksne cene karata (EUR) dok se tabela polazak ne doradi
    KARTA_ADL = Decimal("80")
    KARTA_CHD = Decimal("70")
    # Dete mlađe od ove granice (godine) računa se kao INF, ostala deca kao CHD
    INF_GRANICA = 2

    def _q2(x) -> float:
        return float(Decimal(x).quantize(Decimal("0.01")))

    def _fmt(x) -> str:
        d = Decimal(x).quantize(Decimal("0.01"))
        s = f"{d:.2f}"
        return s[:-3] if s.endswith(".00") else s

    def _obracun_cena(conn, smestaji: list, d_od, d_do, adl: int, chd: int, inf: int, sopstveni: bool):
        """Pravila 2 i 3 pretrage: koeficijenti po sobi + obračun cene iz cenovnika.

        Pravilo 2: soba ostaje SAMO ako neka od njenih struktura (sobe.tip +
        soba_koeficijenti) ima red u koeficijenti_prodaje sa TAČNO (adl, chd, inf)
        i koeficijentom > 0. Sobe bez takvog reda se izbacuju (brojač
        `iskljuceno_putnici` na smeštaju).

        Pravilo 3: cena iz AKTIVNOG cenovnika smeštaja (cenovnik_opcije.datumod ≤
        danas ≤ datumdo, najnoviji id) — red snimka = sama soba (struktura == tip)
        ili virtuelna soba nastala iz nje (izvor_soba_id + tip == struktura);
        boravak = lanac perioda snimka od d_od do d_do, osnova = ZBIR cena po
        terminu. Po osobi: osnova × koeficijent, sopstveni prevoz → minus
        umanjenje × (adl+chd) JEDNOM. Po sobi: osnova + karte (80·ADL + 70·CHD)
        za autobuski, bez karata i bez umanjenja za sopstveni. Popust (opcije
        prvog termina lanca, važi danas) se primenjuje na dobijenu cenu.
        """
        danas = _belgrade_now().date()
        broj_osoba = adl + chd
        koef_rows = conn.execute(text("""
            SELECT struktura, koeficijent FROM koeficijenti_prodaje
            WHERE adl = :adl AND chd = :chd AND inf = :inf
            ORDER BY (koeficijent > 0) DESC, rucno, id
        """), {"adl": adl, "chd": chd, "inf": inf}).fetchall()
        # Pravilo 2: dovoljno je da POSTOJI red sa tačnom strukturom putnika;
        # koeficijent sme biti 0 (koristi se samo kod cene PO OSOBI — tada je
        # 0 signal „nije unet" i soba dobija nema_cene sa razlogom).
        koef_map: dict = {}
        for r in koef_rows:
            koef_map.setdefault((r.struktura or "").strip(), Decimal(str(r.koeficijent or 0)))

        soba_ids = [s["id"] for g in smestaji for s in g["sobe"]]
        dodatni: dict = {}
        if soba_ids:
            for r in conn.execute(text(
                "SELECT soba_id, struktura FROM soba_koeficijenti WHERE soba_id = ANY(:ids)"
            ), {"ids": soba_ids}):
                dodatni.setdefault(r.soba_id, []).append((r.struktura or "").strip())

        def _cenovnik(sid):
            c = conn.execute(text("""
                SELECT c.id, c.sobe, c.periodi
                FROM cenovnici c
                JOIN cenovnik_opcije o ON o.cenovnik_id = c.id
                WHERE c.smestaj_id = :sid AND o.datumod <= :d AND o.datumdo >= :d
                ORDER BY c.id DESC LIMIT 1
            """), {"sid": sid, "d": danas}).fetchone()
            if not c:
                return None
            cene = {(r.soba_id, r.period_id): Decimal(str(r.cena)) for r in conn.execute(text(
                "SELECT soba_id, period_id, cena FROM cenovnik_cene WHERE cenovnik_id = :c"
            ), {"c": c.id})}
            opcije = {(r.soba_id, r.period_id): r for r in conn.execute(text(
                "SELECT * FROM opcije_soba WHERE cenovnik_id = :c"
            ), {"c": c.id}).mappings()}
            popusti = {(r.soba_id, r.period_id): r for r in conn.execute(text(
                "SELECT * FROM popust_soba WHERE cenovnik_id = :c"
            ), {"c": c.id}).mappings()}
            # lanac perioda snimka od d_od do d_do (BFS — najmanje termina)
            poceci: dict = {}
            for p in c.periodi:
                poceci.setdefault(str(p["datum_od"]), []).append(p)
            cilj = d_do.isoformat()
            front = [(d_od.isoformat(), [])]
            videno = set()
            lanac = None
            while front and lanac is None:
                sledeci = []
                for cur, put in front:
                    if cur in videno:
                        continue
                    videno.add(cur)
                    for p in poceci.get(cur, []):
                        np_ = put + [p]
                        if str(p["datum_do"]) == cilj:
                            lanac = np_
                            break
                        if str(p["datum_do"]) < cilj:
                            sledeci.append((str(p["datum_do"]), np_))
                    if lanac is not None:
                        break
                front = sledeci
            return {"id": c.id, "sobe": c.sobe, "cene": cene, "opcije": opcije,
                    "popusti": popusti, "lanac": lanac or []}

        def _po_opsegu(mapa, soba_row_id, pid):
            return mapa.get((soba_row_id, pid)) or mapa.get((soba_row_id, 0))

        def _obracun_sobe(cen, soba, struktura, koef):
            """Vrati dict obračuna ili None ako nema cene za tu strukturu."""
            obr = []
            if struktura == (soba["tip"] or "").strip():
                red = next((r for r in cen["sobe"] if r["id"] == soba["id"] and not r.get("virtuelna")), None)
            else:
                red = next((r for r in cen["sobe"] if r.get("virtuelna") and r.get("izvor_soba_id") == soba["id"]
                            and (r.get("tip") or "").strip() == struktura), None)
            if not red:
                return None
            obr.append(f"Cenovnik #{cen['id']}, red {red['broj_sobe']} ({struktura}), koeficijent {koef} "
                       f"za {adl} ADL / {chd} CHD / {inf} INF")
            osnova = Decimal("0")
            delovi = []
            for p in cen["lanac"]:
                cena_p = cen["cene"].get((red["id"], p["id"]))
                if cena_p is None or cena_p <= 0:
                    return {"nema_cene": True, "obracun": obr + [
                        f"Nema unete cene za termin {p['datum_od']} – {p['datum_do']}"]}
                osnova += cena_p
                delovi.append(f"{_fmt(cena_p)}")
            if len(delovi) > 1:
                obr.append(f"Osnova iz cenovnika: {' + '.join(delovi)} = {_fmt(osnova)} € "
                           f"(lanac od {len(delovi)} termina)")
            else:
                obr.append(f"Osnova iz cenovnika: {_fmt(osnova)} €")
            prvi_pid = cen["lanac"][0]["id"]
            opc = _po_opsegu(cen["opcije"], red["id"], prvi_pid)
            tip_cene = (opc["tip_cene"] if opc and opc["tip_cene"] else "po_osobi")
            umanj_sp = Decimal(str(opc["popust_sopstveni_prevoz"])) if opc and opc["popust_sopstveni_prevoz"] else Decimal("0")
            napomene = []
            if opc:
                if opc["blokirano"]:
                    napomene.append("Soba je BLOKIRANA u opcijama cenovnika")
                if opc["prevoz"] == "obavezan" and sopstveni:
                    napomene.append("Opcije: prevoz je OBAVEZAN (traženo: sopstveni)")
                if opc["prevoz"] == "nemoguc" and not sopstveni:
                    napomene.append("Opcije: prevoz NIJE MOGUĆ (traženo: autobuski)")
            if tip_cene == "po_sobi":
                cena = osnova
                obr.append("Tip cene: PO SOBI")
                if sopstveni:
                    obr.append("Sopstveni prevoz: bez karata, bez umanjenja")
                else:
                    karte = KARTA_ADL * adl + KARTA_CHD * chd
                    cena += karte
                    obr.append(f"Autobuski prevoz: karte {_fmt(KARTA_ADL)}×{adl} ADL + "
                               f"{_fmt(KARTA_CHD)}×{chd} CHD = {_fmt(karte)} € → {_fmt(cena)} €")
            else:
                if koef <= 0:
                    return {"nema_cene": True, "obracun": obr + [
                        f"Tip cene: PO OSOBI, ali koeficijent za {adl} ADL / {chd} CHD / {inf} INF "
                        f"(struktura {struktura}) je 0 — unesite ga na Koeficijentima prodaje"]}
                cena = osnova * koef
                obr.append(f"Tip cene: PO OSOBI → {_fmt(osnova)} × {koef} = {_fmt(cena)} €")
                if sopstveni:
                    if umanj_sp > 0:
                        um = umanj_sp * broj_osoba
                        cena -= um
                        obr.append(f"Sopstveni prevoz: umanjenje {_fmt(umanj_sp)} × {broj_osoba} osoba = "
                                   f"−{_fmt(um)} € → {_fmt(cena)} €")
                    else:
                        obr.append("Sopstveni prevoz: umanjenje nije definisano u opcijama (0 €)")
                else:
                    obr.append("Autobuski prevoz: konačna cena (prevoz uključen)")
            if cena < 0:
                cena = Decimal("0")
            osnovna = cena.quantize(Decimal("0.01"))
            snizena = None
            pop = _po_opsegu(cen["popusti"], red["id"], prvi_pid)
            if pop:
                vazi = ((pop["vazi_od"] is None or pop["vazi_od"] <= danas)
                        and (pop["vazi_do"] is None or pop["vazi_do"] >= danas))
                um = Decimal(str(pop["umanjenje"]))
                if vazi:
                    if pop["umanjenje_vrsta"] == "procenat":
                        snizena = (osnovna * (Decimal("100") - um) / Decimal("100")).quantize(Decimal("0.01"))
                        obr.append(f"Popust ({pop['tip_popusta']}): −{_fmt(um)}% → {_fmt(snizena)} €")
                    else:
                        snizena = max(Decimal("0"), osnovna - um).quantize(Decimal("0.01"))
                        obr.append(f"Popust ({pop['tip_popusta']}): −{_fmt(um)} € → {_fmt(snizena)} €")
                else:
                    obr.append(f"Popust ({pop['tip_popusta']}) postoji ali ne važi danas "
                               f"({pop['vazi_od']} – {pop['vazi_do']})")
            else:
                obr.append("Popust: nema")
            return {"nema_cene": False, "cena_osnovna": _q2(osnovna),
                    "cena_snizena": _q2(snizena) if snizena is not None else None,
                    "struktura": struktura, "koeficijent": float(koef),
                    "tip_cene": tip_cene, "obracun": obr, "napomene": napomene}

        out = []
        for g in smestaji:
            cen = _cenovnik(g["smestaj_id"])
            sobe_out = []
            iskljuceno = 0
            for s in g["sobe"]:
                tip = (s["tip"] or "").strip()
                strukture = [tip] + [d for d in dodatni.get(s["id"], []) if d != tip]
                kandidati = [(st, koef_map[st]) for st in strukture if st in koef_map]
                if not kandidati:
                    iskljuceno += 1
                    continue
                najbolji = None
                if cen and cen["lanac"]:
                    for st, koef in kandidati:
                        r = _obracun_sobe(cen, s, st, koef)
                        if r is None or r["nema_cene"]:
                            if najbolji is None:
                                najbolji = r
                            continue
                        if najbolji is None or najbolji.get("nema_cene") or \
                           (r["cena_snizena"] or r["cena_osnovna"]) < (najbolji["cena_snizena"] or najbolji["cena_osnovna"]):
                            najbolji = r
                if najbolji is None:
                    razlog = ("Nema aktivnog cenovnika za ovaj smeštaj" if not cen else
                              "Cenovnik ne pokriva traženi boravak lancem termina" if not cen["lanac"] else
                              "U cenovniku ne postoji red za strukturu " + ", ".join(st for st, _ in kandidati))
                    najbolji = {"nema_cene": True, "obracun": [razlog]}
                najbolji.setdefault("struktura", kandidati[0][0])
                najbolji.setdefault("koeficijent", float(kandidati[0][1]))
                najbolji.setdefault("cena_osnovna", None)
                najbolji.setdefault("cena_snizena", None)
                najbolji.setdefault("tip_cene", None)
                najbolji.setdefault("napomene", [])
                sobe_out.append({**s, **najbolji})
            if not sobe_out:
                continue
            out.append({**g, "sobe": sobe_out, "iskljuceno_putnici": iskljuceno,
                        "cenovnik_id": cen["id"] if cen else None})
        return out

    @api.get("/slobodne-sobe")
    def slobodne_sobe(request: Request, _: dict = Depends(get_current_user)):
        q = dict(request.query_params)
        od = (q.get("datum_od") or "").strip()
        do = (q.get("datum_do") or "").strip()
        grupa_raw = (q.get("grupa_id") or "").strip()
        mesto_raw = (q.get("mesto_id") or "").strip()
        # putnici + prevoz (koriste se samo u modu konkretnog boravka od+do)
        odrasli_raw = (q.get("odrasli") or "").strip()
        deca_raw = (q.get("deca") or "").strip()  # godine dece, npr. "5,12"
        prevoz_raw = (q.get("prevoz") or "").strip().lower()
        obracun = odrasli_raw != ""
        adl = int(odrasli_raw) if odrasli_raw.isdigit() else 2
        godine = [int(x) for x in deca_raw.split(",") if x.strip().isdigit()] if deca_raw else []
        chd = sum(1 for gd in godine if gd >= INF_GRANICA)
        inf = sum(1 for gd in godine if gd < INF_GRANICA)
        sopstveni = prevoz_raw.startswith("sopstveni")
        if not od:
            raise HTTPException(status_code=400, detail="datum_od je obavezan")
        try:
            d_od = datetime.strptime(od, "%d.%m.%Y").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Datumi moraju biti u formatu DD.MM.YYYY")
        grupa_id = int(grupa_raw) if grupa_raw.isdigit() else None
        mesto_id = int(mesto_raw) if mesto_raw.isdigit() else None

        def _smestaji_za_termin(conn, d_od, d_do):
            """Slobodni smeštaji (sa sobama) za boravak od d_od do d_do.

            Smeštaj prolazi SAMO ako njegova grupa termina (smestaj.grupa_datuma)
            pokriva boravak LANCOM uzastopnih perioda: prvi period počinje na
            d_od, a svaki sledeći počinje tačno na kraju prethodnog — boravak
            mora da se završi na kraju nekog perioda grupe (npr. 25.05→14.06 =
            25.05–04.06 + 04.06–14.06 u grupi 6). Soba prolazi ako nema aranzman
            koji preklapa ceo boravak (po nazivu vile).
            """
            rows = conn.execute(text("""
                WITH RECURSIVE lanac_krajevi(grupa_id, kraj) AS (
                    -- početak lanca: bilo koji period koji počinje na datum_od
                    SELECT pd.grupa_id, pd.datum_do
                    FROM period_datum pd
                    WHERE pd.datum_od = :dod
                    UNION
                    -- produžetak: period koji počinje tačno na kraju lanca
                    SELECT l.grupa_id, pd2.datum_do
                    FROM lanac_krajevi l
                    JOIN period_datum pd2
                      ON pd2.grupa_id = l.grupa_id AND pd2.datum_od = l.kraj
                    WHERE l.kraj < :ddo
                )
                SELECT s.id AS smestaj_id, s.naziv AS smestaj_naziv,
                       b.id, TRIM(b.broj_sobe) AS broj_sobe, b.tip, b.opis, b.opis_dodatno
                FROM sobe b
                JOIN smestaj s ON s.id = b.veza_id_smestaj
                WHERE (CAST(:g AS INTEGER) IS NULL OR s.grupa_datuma = CAST(:g AS INTEGER))
                  AND (CAST(:m AS INTEGER) IS NULL OR s.mesto = CAST(:m AS INTEGER))
                  -- vezuje Grupu termina za vilu: traženi boravak (od→do) mora
                  -- biti pokriven lancom perioda u grupi termina tog smeštaja
                  AND EXISTS (
                      SELECT 1 FROM lanac_krajevi lk
                      WHERE lk.grupa_id = s.grupa_datuma
                        AND lk.kraj = :ddo
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM aranzman a
                      WHERE a.naziv = s.naziv
                        AND TRIM(COALESCE(a.soba, '')) = TRIM(b.broj_sobe)
                        AND a.datumod IS NOT NULL AND a.datumdo IS NOT NULL
                        AND a.datumod < :ddo
                        AND a.datumdo > :dod
                  )
                ORDER BY s.naziv, b.broj_sobe
            """), {"g": grupa_id, "m": mesto_id, "dod": d_od, "ddo": d_do}).fetchall()
            grouped: dict = {}
            for r in rows:
                g = grouped.setdefault(r.smestaj_id, {
                    "smestaj_id": r.smestaj_id, "smestaj_naziv": r.smestaj_naziv, "sobe": [],
                })
                g["sobe"].append({
                    "id": r.id, "broj_sobe": r.broj_sobe, "tip": r.tip or "",
                    "opis": r.opis or "", "opis_dodatno": r.opis_dodatno or "",
                })
            return list(grouped.values())

        with engine.connect() as conn:
            if do:
                # ── STARI MOD: konkretan boravak (od+do) ──
                try:
                    d_do = datetime.strptime(do, "%d.%m.%Y").date()
                except ValueError:
                    raise HTTPException(status_code=400, detail="Datumi moraju biti u formatu DD.MM.YYYY")
                if d_do <= d_od:
                    raise HTTPException(status_code=400, detail="Datum do mora biti posle datuma od")
                smestaji = _smestaji_za_termin(conn, d_od, d_do)
                if not obracun:
                    return smestaji  # stari klijenti bez putnika: samo raspoloživost
                return _obracun_cena(conn, smestaji, d_od, d_do, adl, chd, inf, sopstveni)

            # ── NOVI MOD: pretraga po SVIM lancima perioda koji počinju na datum_od ──
            # (grupa_id filter ili obavezno mesto_id — opcije su krajevi LANACA
            # uzastopnih perioda grupa mesta: osnovni termin + produženi boravci,
            # npr. 25.05–04.06 + 04.06–14.06 = opcija 25.05–14.06); ograničeno na
            # najviše MAX_NOCENJA_OPCIJE noćenja (duži lanci se ne nude); vraća
            # samo opcije SA slobodnim smeštajem, hronološki po datumu povratka
            if grupa_id is None and mesto_id is None:
                raise HTTPException(status_code=400,
                                    detail="datum_do ili mesto_id su obavezni")
            _grupa_filter = ("pd.grupa_id = :g" if grupa_id is not None else
                             "pd.grupa_id IN (SELECT grupa_id FROM mesto_grupa WHERE mesto_id = :m)")
            _params = ({"g": grupa_id, "od": d_od} if grupa_id is not None
                       else {"m": mesto_id, "od": d_od})
            krajevi = conn.execute(text(f"""
                WITH RECURSIVE krajevi(grupa_id, kraj) AS (
                    SELECT pd.grupa_id, pd.datum_do
                    FROM period_datum pd
                    WHERE {_grupa_filter} AND pd.datum_od = :od
                    UNION
                    SELECT k.grupa_id, pd2.datum_do
                    FROM krajevi k
                    JOIN period_datum pd2
                      ON pd2.grupa_id = k.grupa_id AND pd2.datum_od = k.kraj
                )
                SELECT DISTINCT kraj FROM krajevi
                WHERE kraj - :od <= :max_noci
                ORDER BY kraj
            """), {**_params, "max_noci": MAX_NOCENJA_OPCIJE}).fetchall()
            out = []
            for t in krajevi:
                smestaji = _smestaji_za_termin(conn, d_od, t.kraj)
                if not smestaji:
                    continue  # ponudi samo opcije sa raspoloživim smeštajem
                out.append({
                    "datum_od": d_od.strftime("%d.%m.%Y"),
                    "datum_do": t.kraj.strftime("%d.%m.%Y"),
                    "nocenja": (t.kraj - d_od).days,
                    "smestaji": smestaji,
                })
            return out

    @api.get("/grafik")
    def grafik_data(request: Request, _: dict = Depends(get_current_user)):
        q = dict(request.query_params)
        raw_smestaj = (q.get("smestaj_id", "") or "").strip()
        sve = raw_smestaj.lower() == "sve"
        try:
            grupa_id = int(q.get("grupa_id", ""))
            if not sve:
                smestaj_id = int(raw_smestaj)
        except ValueError:
            raise HTTPException(status_code=400, detail="smestaj_id i grupa_id su obavezni")
        kurs = get_eur_middle()
        sada = _belgrade_now()
        with engine.connect() as conn:
            boje_row = conn.execute(text("SELECT * FROM boje_grafik WHERE id = 1")).mappings().first()
            boje = dict(boje_row) if boje_row else {}
            periodi_rows = conn.execute(text("""
                SELECT to_char(datum_od, 'DD.MM.YYYY') AS od, to_char(datum_do, 'DD.MM.YYYY') AS doo
                FROM period_datum WHERE grupa_id = :g ORDER BY datum_od
            """), {"g": grupa_id}).fetchall()
            periodi = [{"datum_od": r.od, "datum_do": r.doo} for r in periodi_rows]

            def sekcija(srow):
                """Grafik-podaci za jedan smeštaj (sobe + ugovori + saldo)."""
                sobe = conn.execute(text("""
                    SELECT id, broj_sobe, tip, opis, opis_dodatno
                    FROM sobe WHERE veza_id_smestaj = :s
                    ORDER BY broj_sobe
                """), {"s": srow.id}).fetchall()
                # mesto-termin prefiks za opseg ugovora ('HANIOTI 7', 'SARTI 7'...)
                mrow = conn.execute(text("SELECT naziv FROM mesto WHERE id = :m"),
                                    {"m": srow.mesto}).fetchone() if srow.mesto else None
                mpref = (mrow.naziv or "").strip() if mrow else ""
                # Ugovori smeštaja — RAZDVOJENI po grupi termina:
                # 1) novi ugovori imaju smestaj_id (tačna instanca smeštaja);
                # 2) legacy (bez smestaj_id): isti naziv + mesto-termin ovog mesta
                #    + datumi se poklapaju sa gridom OVE grupe (datumod = početak
                #    nekog perioda grupe, datumdo = kraj nekog perioda grupe) —
                #    smeštaji istog naziva u drugim grupama imaju druge gridove pa
                #    ne prolaze; neporavnati datumi (storno sa proizvoljnim datumom)
                #    prikazuju se u svim grupama koje preklapaju, da ne nestanu.
                ugovori = conn.execute(text("""
                    SELECT kljuc, putnik, COALESCE(subagent, '') AS subagent,
                           tiprezervacije, timelimit,
                           COALESCE(soba, '') AS soba,
                           kolaranz, cenaaranz, kolchd, cenachd, cenaow, kolow,
                           cenart, kolrt, cenaviza, kolviza, popustar, popustpr,
                           popustvi, procenatar, procenatpr, procenatvi,
                           cenadod, osiguranje1, uplaceno,
                           to_char(datumod, 'DD.MM.YYYY') AS od,
                           to_char(datumdo, 'DD.MM.YYYY') AS doo
                    FROM aranzman a
                    WHERE TRIM(a.naziv) = TRIM(:naziv)
                      AND a.datumod IS NOT NULL AND a.datumdo IS NOT NULL
                      AND (
                            a.smestaj_id = :sid
                            OR (
                                a.smestaj_id IS NULL
                                AND (CAST(:mpref AS TEXT) = ''
                                     OR LOWER(TRIM(COALESCE(a.mesto, ''))) LIKE LOWER(:mpref) || '%')
                                AND EXISTS (
                                    SELECT 1 FROM period_datum pd
                                    WHERE pd.grupa_id = :g
                                      AND a.datumod < pd.datum_do AND a.datumdo > pd.datum_od
                                )
                                AND (
                                    EXISTS (
                                        SELECT 1
                                        FROM period_datum p1
                                        JOIN period_datum p2
                                          ON p2.grupa_id = p1.grupa_id AND p2.datum_od >= p1.datum_od
                                        WHERE p1.grupa_id = :g
                                          AND p1.datum_od = a.datumod AND p2.datum_do = a.datumdo
                                    )
                                    OR NOT EXISTS (
                                        SELECT 1
                                        FROM period_datum p1
                                        JOIN period_datum p2
                                          ON p2.grupa_id = p1.grupa_id AND p2.datum_od >= p1.datum_od
                                        WHERE p1.datum_od = a.datumod AND p2.datum_do = a.datumdo
                                          AND p1.grupa_id IN (
                                                SELECT grupa_id FROM mesto_grupa WHERE mesto_id = :m
                                                UNION
                                                SELECT grupa_datuma FROM smestaj
                                                WHERE TRIM(naziv) = TRIM(:naziv) AND grupa_datuma IS NOT NULL
                                          )
                                    )
                                )
                            )
                      )
                    ORDER BY a.kljuc
                """), {"naziv": srow.naziv, "sid": srow.id, "mpref": mpref,
                       "g": grupa_id, "m": srow.mesto}).fetchall()
                # Saldo po ugovoru (EUR) — ista logika obračuna kao detalj ugovora
                ugovori_out = []
                for r in ugovori:
                    calc = calc_ugovor_values(dict(r._mapping))
                    saldo_rsd = round(calc["saldo"] * kurs, 2)
                    kategorija = kategorija_grafika(
                        r.tiprezervacije, r.subagent, r.timelimit, saldo_rsd, sada
                    )
                    ugovori_out.append({
                        "kljuc": r.kljuc, "soba": r.soba,
                        "datum_od": r.od, "datum_do": r.doo,
                        "putnik": r.putnik, "subagent": r.subagent,
                        "saldo": calc["saldo"],
                        "saldo_rsd": saldo_rsd,
                        "boja_kategorija": kategorija,
                        "boja": boje.get(kategorija, "zelena"),
                    })
                return {
                    "smestaj": {"id": srow.id, "naziv": srow.naziv},
                    "periodi": periodi,
                    "sobe": [{
                        "id": r.id, "broj_sobe": r.broj_sobe, "tip": r.tip,
                        "opis": r.opis, "opis_dodatno": r.opis_dodatno,
                    } for r in sobe],
                    "ugovori": ugovori_out,
                }

            if sve:
                # "Prikaži sve" — svi smeštaji grupe perioda, po sekciji za svaki smeštaj
                srows = conn.execute(text(
                    "SELECT id, naziv, mesto FROM smestaj WHERE grupa_datuma = :g ORDER BY naziv"
                ), {"g": grupa_id}).fetchall()
                return {"sve": True, "sekcije": [sekcija(s) for s in srows]}
            srow = conn.execute(text(
                "SELECT id, naziv, mesto FROM smestaj WHERE id = :id"
            ), {"id": smestaj_id}).fetchone()
            if not srow:
                raise HTTPException(status_code=404, detail="Smeštaj nije pronađen")
            return sekcija(srow)

    # ── Periodi ─────────────────────────────────────────────────────────────
    @api.get("/period-grupa")
    def list_period_grupa(_: dict = Depends(get_current_user)):
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT g.id, g.naziv, g.created_at,
                       COALESCE(
                           json_agg(
                               json_build_object(
                                   'id', d.id,
                                   'datum_od', to_char(d.datum_od, 'DD.MM.YYYY'),
                                   'datum_do', to_char(d.datum_do, 'DD.MM.YYYY')
                               ) ORDER BY d.datum_od
                           ) FILTER (WHERE d.id IS NOT NULL), '[]'
                       ) AS datumi
                FROM period_grupa g
                LEFT JOIN period_datum d ON d.grupa_id = g.id
                GROUP BY g.id, g.naziv, g.created_at
                ORDER BY g.created_at DESC
            """)).fetchall()
        return [{
            "id": r.id, "naziv": r.naziv,
            "created_at": str(r.created_at) if r.created_at else None,
            "datumi": r.datumi,
        } for r in rows]

    @api.post("/period-grupa")
    def create_period_grupa(body: PeriodGrupaCreate, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            row = conn.execute(text(
                "INSERT INTO period_grupa (naziv) VALUES (:naziv) RETURNING id, naziv"
            ), {"naziv": body.naziv}).fetchone()
        return {"id": row.id, "naziv": row.naziv, "datumi": []}

    @api.put("/period-grupa/{item_id}")
    def update_period_grupa(item_id: int, body: PeriodGrupaUpdate, _: dict = Depends(get_current_user)):
        if not body.naziv:
            raise HTTPException(status_code=400, detail="Naziv je obavezan")
        with engine.begin() as conn:
            row = conn.execute(text(
                "UPDATE period_grupa SET naziv = :naziv WHERE id = :id RETURNING id, naziv"
            ), {"naziv": body.naziv, "id": item_id}).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Grupa nije pronađena")
        return {"id": row.id, "naziv": row.naziv}

    @api.delete("/period-grupa/{item_id}")
    def delete_period_grupa(item_id: int, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            result = conn.execute(text(
                "DELETE FROM period_grupa WHERE id = :id RETURNING id"
            ), {"id": item_id}).fetchone()
        if not result:
            raise HTTPException(status_code=404, detail="Grupa nije pronađena")
        return {"ok": True}

    @api.post("/period-datum")
    def create_period_datum(body: PeriodDatumCreate, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            row = conn.execute(text("""
                INSERT INTO period_datum (grupa_id, datum_od, datum_do)
                VALUES (:grupa_id, :datum_od, :datum_do)
                RETURNING id, grupa_id,
                    to_char(datum_od, 'DD.MM.YYYY') as datum_od,
                    to_char(datum_do, 'DD.MM.YYYY') as datum_do
            """), {
                "grupa_id": body.grupa_id,
                "datum_od": body.datum_od,
                "datum_do": body.datum_do,
            }).fetchone()
        return {
            "id": row.id, "grupa_id": row.grupa_id,
            "datum_od": row.datum_od, "datum_do": row.datum_do,
        }

    @api.put("/period-datum/{item_id}")
    def update_period_datum(item_id: int, body: PeriodDatumUpdate, _: dict = Depends(get_current_user)):
        fields = {}
        if body.datum_od is not None:
            fields["datum_od"] = body.datum_od
        if body.datum_do is not None:
            fields["datum_do"] = body.datum_do
        if not fields:
            raise HTTPException(status_code=400, detail="Nema podataka za ažuriranje")
        set_clause = ", ".join(f"{k} = :{k}" for k in fields)
        fields["id"] = item_id
        with engine.begin() as conn:
            row = conn.execute(text(f"""
                UPDATE period_datum SET {set_clause}
                WHERE id = :id
                RETURNING id, grupa_id,
                    to_char(datum_od, 'DD.MM.YYYY') as datum_od,
                    to_char(datum_do, 'DD.MM.YYYY') as datum_do
            """), fields).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Datum nije pronađen")
        return {
            "id": row.id, "grupa_id": row.grupa_id,
            "datum_od": row.datum_od, "datum_do": row.datum_do,
        }

    @api.delete("/period-datum/{item_id}")
    def delete_period_datum(item_id: int, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            result = conn.execute(text(
                "DELETE FROM period_datum WHERE id = :id RETURNING id"
            ), {"id": item_id}).fetchone()
        if not result:
            raise HTTPException(status_code=404, detail="Datum nije pronađen")
        return {"ok": True}

    # ── Knjigovodstvo: preuzimanje ugovora ──────────────────────────────────
    ARANZMAN_INT = {
        "prevozow", "prevozrt", "viza", "kolviza", "kolow", "kolrt",
        "legal", "avioid", "avioid1", "avioid4", "keptp",
    }
    # Kolone prebačene u aranzman_dopuna (saputnik po redu)
    ARANZMAN_DOPUNA_STR = {"saputnik", "uzrast", "ulazak", "smer"}
    ARANZMAN_DOPUNA_INT = {"prevozow", "prevozrt", "viza"}
    MOVED_COLS_RE = re.compile(
        r"^(saputnik\d+|uzrast\d+|ulazak\d+|prevoz\d+(ow|rt)|viza\d+)$"
    )
    ARANZMAN_FLOAT = {
        "procenatar", "procenatpr", "procenatpra", "procenatvi",
        "cenaviza", "cenaow", "cenadow", "cenart", "cenadrt",
        "cenachd", "cenaaranz", "cenaaranzd", "kolchd", "kolaranz",
        "cenadod", "koldod", "popustar", "popustpr", "popustvi",
        "uplaceno", "uplacenod", "uplatasmestaj", "uplataprevoz",
        "uplataviza", "osiguranje", "osiguranje1",
        "helas1", "helas2", "helas3", "helas4", "helas5",
        "iznosfiskalni", "bod",
    }
    ARANZMAN_TS = {
        "danas", "datumod", "datumdo", "spajanje1od", "spajanje1do",
        "spajanje2od", "spajanje2do", "timelimit", "datumkeptp", "datumfiskalni",
    }
    ARANZMAN_INT_NULLABLE = {"avioid", "avioid1", "avioid4", "keptp"}
    ARANZMAN_FLOAT_NULLABLE = {"bod"}

    @api.get("/preuzimanje_podataka/{broj:path}")
    def preuzmi_ugovor(broj: str, _: dict = Depends(get_current_user)):
        broj = broj.strip().strip("/")
        if not broj:
            raise HTTPException(status_code=400, detail="Broj ugovora je obavezan")
        import httpx
        from urllib.parse import quote
        url = f"http://188.255.223.36/api/uplatejson.php?ugovor={quote(broj.split('/')[0], safe='')}"
        try:
            resp = httpx.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Greška pri preuzimanju podataka: {e}")
        if not data.get("success"):
            raise HTTPException(status_code=404, detail=data.get("message") or "Ugovor nije pronađen")

        def conv_int(col, v):
            if v in (None, ""):
                return None if col in ARANZMAN_INT_NULLABLE else 0
            try:
                return int(float(v))
            except (TypeError, ValueError):
                return None if col in ARANZMAN_INT_NULLABLE else 0

        def conv_float(col, v):
            if v in (None, ""):
                return None if col in ARANZMAN_FLOAT_NULLABLE else 0.0
            try:
                return float(v)
            except (TypeError, ValueError):
                return None if col in ARANZMAN_FLOAT_NULLABLE else 0.0

        def conv_ts(v):
            if v in (None, ""):
                return None
            return str(v).strip() or None

        def conv_str(v):
            if v is None:
                return None
            return str(v)

        def dopuna_iz_rec(rec: dict) -> list[dict]:
            """Izvuči saputnike (saputnik1..N) iz zapisa eksternog API-ja u redove."""
            redovi = []
            for i in range(1, 21):
                if not any(
                    k in rec for k in
                    (f"saputnik{i}", f"uzrast{i}", f"prevoz{i}ow",
                     f"prevoz{i}rt", f"viza{i}", f"ulazak{i}")
                ):
                    break
                def s(k):
                    v = rec.get(k)
                    return str(v).strip() if v is not None else ""
                def n(k):
                    v = rec.get(k)
                    if v in (None, ""):
                        return None
                    try:
                        return int(float(v))
                    except (TypeError, ValueError):
                        return None
                saputnik = s(f"saputnik{i}")
                uzrast = s(f"uzrast{i}")
                prevozow, prevozrt, viza = n(f"prevoz{i}ow"), n(f"prevoz{i}rt"), n(f"viza{i}")
                ulazak = s(f"ulazak{i}")
                # preskoči potpuno prazne saputnike (samo nule/prazno)
                if not saputnik and not uzrast and not ulazak \
                        and not prevozow and not prevozrt and not viza:
                    continue
                redovi.append({
                    "saputnik": saputnik, "uzrast": uzrast,
                    "prevozow": prevozow, "prevozrt": prevozrt,
                    "viza": viza, "ulazak": ulazak or None,
                })
            return redovi

        with engine.begin() as conn:
            aranzmani = data.get("aranzman") or []
            for rec in aranzmani:
                dopuna = dopuna_iz_rec(rec)
                # polja saputnika (saputnik1, uzrast1, prevoz1ow, viza1, ulazak1...)
                # prebačena su u aranzman_dopuna — ne idu više u aranzman
                cols = [k for k in rec.keys()
                        if k != "id" and not MOVED_COLS_RE.match(k)]
                if not cols:
                    continue
                vals = {}
                for c in cols:
                    v = rec[c]
                    if c in ARANZMAN_INT:
                        vals[c] = conv_int(c, v)
                    elif c in ARANZMAN_FLOAT:
                        vals[c] = conv_float(c, v)
                    elif c in ARANZMAN_TS:
                        vals[c] = conv_ts(v)
                    else:
                        vals[c] = conv_str(v)
                if not vals.get("kljuc"):
                    vals["kljuc"] = broj.split("/")[0]
                # uvek upiši kljuc u formatu <broj>/<godina> (npr. 33333/26)
                if "/" in broj:
                    vals["kljuc"] = broj
                else:
                    vals["kljuc"] = f"{broj}/26"
                if "kljuc" not in cols:
                    cols.append("kljuc")
                col_sql = ", ".join(cols)
                ph_sql = ", ".join(f":{c}" for c in cols)
                upd_sql = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != "kljuc")
                aid = conn.execute(text(
                    f"INSERT INTO aranzman ({col_sql}) VALUES ({ph_sql}) "
                    f"ON CONFLICT (kljuc) DO UPDATE SET {upd_sql} "
                    f"RETURNING id"
                ), vals).scalar_one()
                # saputnici: osveži redove u aranzman_dopuna
                if dopuna or rec.get("saputnik1") is not None:
                    conn.execute(text(
                        "DELETE FROM aranzman_dopuna WHERE aranzman_id = :i"
                    ), {"i": aid})
                    for red in dopuna:
                        conn.execute(text("""
                            INSERT INTO aranzman_dopuna
                                (aranzman_id, saputnik, uzrast, prevozow, prevozrt, viza, ulazak)
                            VALUES (:i, :saputnik, :uzrast, :prevozow, :prevozrt, :viza, :ulazak)
                        """), {"i": aid, **red})

            uplate = data.get("uplate") or []
            for rec in uplate:
                if rec.get("id") in (None, "") or rec.get("kljuc") in (None, ""):
                    continue
                cols = []
                vals = {}
                for k, v in rec.items():
                    if k in ("id", "kljuc"):
                        try:
                            vals[k] = int(float(v))
                            cols.append(k)
                        except (TypeError, ValueError):
                            continue
                    elif k in ("din", "evro", "uevro"):
                        try:
                            vals[k] = None if v in (None, "") else float(v)
                            cols.append(k)
                        except (TypeError, ValueError):
                            vals[k] = None
                            cols.append(k)
                    else:
                        vals[k] = conv_str(v)
                        cols.append(k)
                if not cols or "kljuc" not in cols or "id" not in cols:
                    continue
                col_sql = ", ".join(cols)
                ph_sql = ", ".join(f":{c}" for c in cols)
                upd_sql = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != "kljuc")
                conn.execute(text(
                    f"INSERT INTO uplate ({col_sql}) VALUES ({ph_sql}) "
                    f"ON CONFLICT (kljuc) DO UPDATE SET {upd_sql}"
                ), vals)

        return {"ok": True, "aranzman": len(aranzmani), "uplate": len(uplate)}

    # ── Knjigovodstvo: lista ugovora (server-side search/sort/pagination) ───
    UGOVORI_SORT = {"kljuc", "danas", "putnik", "mesto", "naziv", "datumod", "datumdo", "subagent"}
    UGOVORI_SEARCH_COLS = [
        "kljuc", "putnik", "mesto", "naziv", "destinacija", "datumoddo",
        "obradio", "refno", "napomena", "napomena1", "soba", "tiprezervacije",
        "organizator", "poslovnica", "naziv1", "telefon", "adresa",
    ]
    # Filter-red u tabeli: f_<kolona> → SQL izraz za ILIKE (min 3 karaktera)
    UGOVORI_FILTER_COLS = {
        "kljuc": "COALESCE(kljuc::text, '')",
        "danas": "to_char(danas, 'DD.MM.YYYY')",
        "putnik": "COALESCE(putnik::text, '')",
        "mesto": "COALESCE(mesto::text, '')",
        "naziv": "COALESCE(naziv::text, '')",
        "datumod": "to_char(datumod, 'DD.MM.YYYY')",
        "datumdo": "to_char(datumdo, 'DD.MM.YYYY')",
        "subagent": "COALESCE(subagent::text, '')",
    }

    # Svi obračuni koriste trajnu tabelu kurs; API se poziva samo za nedostajući datum.
    def get_eur_middle():
        return get_eur_rate(engine, _belgrade_now().date().isoformat())[0]

    def get_eur_middle_za_datum(iso_datum: str):
        return get_eur_rate(engine, iso_datum)

    @api.get("/kurs")
    def get_kurs(_: dict = Depends(get_current_user)):
        kurs, datum = get_eur_rate(engine, _belgrade_now().date().isoformat())
        return {
            "kurs": kurs,
            "datum": datetime.strptime(datum, "%Y-%m-%d").strftime("%d.%m.%Y") if datum else None,
        }

    @api.get("/kurs/pregled")
    def pregled_kurseva(datum: Optional[str] = None, page: int = 1,
                        page_size: int = 100, _: dict = Depends(get_current_user)):
        # Pregled je isključivo čitanje baze; ne popunjava nedostajuće datume.
        if page < 1 or not 1 <= page_size <= 100:
            raise HTTPException(status_code=422, detail="Neispravna stranica ili veličina stranice")
        params = {"limit": page_size, "offset": (page - 1) * page_size}
        condition = ""
        if datum:
            parsed = _parse_iso_date(datum, "Datum")
            if parsed.isoformat() != datum:
                raise HTTPException(status_code=400, detail="Datum mora biti YYYY-MM-DD")
            params["datum"] = parsed
            condition = " WHERE datum = :datum"
        with engine.connect() as conn:
            total = conn.execute(text("SELECT count(*) FROM kurs" + condition), params).scalar_one()
            rows = conn.execute(text(
                "SELECT id, iznos, datum, datum_kursa FROM kurs" + condition +
                " ORDER BY datum DESC, id DESC LIMIT :limit OFFSET :offset"
            ), params).mappings().all()
        return {"rows": [{"id": r["id"], "iznos": float(r["iznos"]),
                          "datum": r["datum"].isoformat(), "datum_kursa": r["datum_kursa"].isoformat()}
                         for r in rows], "total": total, "page": page, "page_size": page_size}

    @api.get("/pregledi/prodaja-aranzmana")
    def pregled_prodaja_aranzmana(
        datum: Optional[str] = None,
        _: dict = Depends(get_current_user),
    ):
        """Dnevni izveštaj prodaje aranžmana — ugovori kreirani na izabrani dan."""
        import datetime
        d = None
        if datum:
            for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
                try:
                    d = datetime.datetime.strptime(datum.strip(), fmt).date()
                    break
                except ValueError:
                    continue
        if d is None:
            d = datetime.date.today()

        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT a.kljuc,
                       to_char(a.danas, 'DD.MM.YYYY') AS danas_fmt,
                       to_char(a.danas, 'HH24:MI') AS vreme,
                       a.putnik, a.mesto, a.naziv, a.soba,
                       to_char(a.datumod, 'DD.MM.YYYY') AS datumod_fmt,
                       to_char(a.datumdo, 'DD.MM.YYYY') AS datumdo_fmt,
                       a.tiprezervacije, a.subagent, a.obradio, a.apartman,
                       CASE WHEN COALESCE(TRIM(a.putnik), '') <> '' THEN 1 ELSE 0 END
                         + (SELECT COUNT(*) FROM aranzman_dopuna ad
                            WHERE ad.aranzman_id = a.id
                              AND COALESCE(TRIM(ad.saputnik), '') <> '') AS broj_putnika,
                       a.kolaranz, a.cenaaranz, a.kolchd, a.cenachd,
                       a.cenaow, a.kolow, a.cenart, a.kolrt,
                       a.cenaviza, a.kolviza, a.popustar, a.popustpr,
                       a.popustvi, a.procenatar, a.procenatpr, a.procenatvi,
                       a.cenadod, a.osiguranje1, a.uplaceno
                FROM aranzman a
                WHERE a.danas::date = :d
                ORDER BY a.danas NULLS LAST, a.id
            """), {"d": d}).fetchall()

        kurs = get_eur_middle()
        out = []
        sum_naplata = 0.0
        sum_provizija = 0.0
        sum_putnika = 0
        for r in rows:
            row = dict(r._mapping)
            calc = calc_ugovor_values(row)
            naplata = calc["naplata"]
            provizija = calc["provizija"]
            sum_naplata += naplata
            sum_provizija += provizija
            bp = int(row.get("broj_putnika") or 0)
            sum_putnika += bp
            out.append({
                "kljuc": row["kljuc"],
                "danas": row["danas_fmt"],
                "vreme": row["vreme"],
                "putnik": row["putnik"],
                "broj_putnika": bp,
                "mesto": row["mesto"],
                "smestaj": row["naziv"],
                "soba": row["soba"],
                "datum_od": row["datumod_fmt"],
                "datum_do": row["datumdo_fmt"],
                "tiprezervacije": row["tiprezervacije"],
                "struktura": row["apartman"],
                "subagent": row["subagent"],
                "obradio": row["obradio"],
                "naplata": naplata,
                "provizija": provizija,
                "ukupno": round(naplata + provizija, 2),
                "uplaceno": calc["uplaceno"],
            })

        ukupno_eur = round(sum_naplata + sum_provizija, 2)
        return {
            "datum": d.strftime("%d.%m.%Y"),
            "kurs": kurs,
            "rows": out,
            "totals": {
                "broj": len(out),
                "putnika": sum_putnika,
                "naplata": round(sum_naplata, 2),
                "provizija": round(sum_provizija, 2),
                "ukupno_eur": ukupno_eur,
                "ukupno_din": round(ukupno_eur * kurs, 2) if kurs else None,
            },
        }

    @api.get("/pregledi/prodaja-aranzmana/pdf")
    def pregled_prodaja_aranzmana_pdf(
        datum: Optional[str] = None,
        _: dict = Depends(get_current_user),
    ):
        """PDF dnevnog izveštaja prodaje — grupisano po poslovnici."""
        from dnevni_izvestaj_pdf import build_dnevni_izvestaj_pdf

        import datetime
        d = None
        if datum:
            for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
                try:
                    d = datetime.datetime.strptime(datum.strip(), fmt).date()
                    break
                except ValueError:
                    continue
        if d is None:
            d = datetime.date.today()
        datum_display = d.strftime("%d.%m.%Y")

        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT a.kljuc,
                       to_char(a.danas, 'DD.MM.YYYY') AS danas_fmt,
                       a.putnik,
                       (CASE WHEN COALESCE(TRIM(a.putnik), '') <> '' THEN 1 ELSE 0 END
                         + (SELECT COUNT(*) FROM aranzman_dopuna ad
                            WHERE ad.aranzman_id = a.id
                              AND COALESCE(TRIM(ad.saputnik), '') <> '')) AS broj_putnika,
                       a.subagent, a.mesto, a.destinacija, a.naziv, a.soba,
                       a.apartman, a.datumoddo, a.poslovnica, a.obradio,
                       to_char(a.datumod, 'DD.MM.YYYY') AS od_fmt,
                       to_char(a.datumdo, 'DD.MM.YYYY') AS do_fmt
                FROM aranzman a
                WHERE a.danas::date = :d
                ORDER BY a.danas NULLS LAST, a.id
            """), {"d": d}).fetchall()
            logo_row = conn.execute(text(
                "SELECT slika, slika_mime FROM dokumenti WHERE tip = 'logo'"
            )).fetchone()

        logo_data_url = None
        if logo_row and logo_row.slika:
            mime = logo_row.slika_mime or "image/png"
            logo_data_url = f"data:{mime};base64,{logo_row.slika}"

        pdf_rows = []
        for r in rows:
            m = dict(r._mapping)
            broj_raw = str(m.get("kljuc") or "").split("/")[0].strip()
            try:
                broj_fmt = f"{int(broj_raw):,}"
            except ValueError:
                broj_fmt = broj_raw
            pdf_rows.append({
                "kljuc": m.get("kljuc"),
                "danas": m.get("danas_fmt"),
                "poslovnica": m.get("poslovnica"),
                "putnik": m.get("putnik"),
                "broj_putnika": m.get("broj_putnika"),
                "subagent": m.get("subagent"),
                "mesto": m.get("mesto"),
                "destinacija": m.get("destinacija"),
                "smestaj": m.get("naziv"),
                "soba": m.get("soba"),
                "tip": m.get("apartman"),
                "datum_smene": m.get("datumoddo"),
                "datum_od": m.get("od_fmt"),
                "datum_do": m.get("do_fmt"),
                "operater": m.get("obradio"),
                "broj_fmt": broj_fmt,
            })

        pdf_bytes = build_dnevni_izvestaj_pdf(datum_display, pdf_rows, logo_data_url)
        fname = f"Dnevna_prodaja_{d.strftime('%d-%m-%Y')}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )

    def calc_ugovor_values(row: dict) -> dict:
        """Port PHP obračuna iz uplate.php — ulaz: kolone aranzman reda."""
        def n(k):
            v = row.get(k)
            try:
                return float(v) if v not in (None, "") else 0.0
            except (TypeError, ValueError):
                return 0.0

        cenaaranz_c = n("kolaranz") * n("cenaaranz") + n("kolchd") * n("cenachd")
        cenaprevoz_c = n("cenaow") * n("kolow") + n("cenart") * n("kolrt")
        cenaviza_c = n("kolviza") * n("cenaviza")
        popustsmestaj = n("popustar") * cenaaranz_c / 100
        popustprevoz = n("popustpr") * cenaprevoz_c / 100
        popustviza = n("popustvi") * cenaviza_c
        provizijaar = (cenaaranz_c - popustsmestaj) * n("procenatar") / 100
        provizijapr = 0.0 if n("cenart") == 0 else n("procenatpr") * n("kolrt")
        provizijapr1 = 0.0 if n("cenaow") == 0 else n("procenatpr") * n("kolow")
        provizijaviza = n("kolviza") * n("procenatvi")
        provizija = provizijaar + provizijapr + provizijapr1 + provizijaviza
        naplata = (cenaaranz_c + cenaprevoz_c + cenaviza_c
                   - popustsmestaj - popustprevoz - popustviza
                   - provizijaar - provizijapr - provizijapr1 - provizijaviza
                   + n("cenadod") + n("osiguranje1"))
        uplaceno = n("uplaceno")
        saldo = naplata - uplaceno
        return {
            "smestaj": round(cenaaranz_c, 2),
            "prevoz": round(cenaprevoz_c, 2),
            "viza": round(cenaviza_c, 2),
            "popust": round(popustsmestaj + popustprevoz + popustviza, 2),
            "provizija": round(provizija, 2),
            "naplata": round(naplata, 2),
            "uplaceno": round(uplaceno, 2),
            "saldo": round(saldo, 2),
        }

    UGOVORI_LIST_COLS = [
        "kolaranz", "cenaaranz", "kolchd", "cenachd", "cenaow", "kolow",
        "cenart", "kolrt", "cenaviza", "kolviza", "popustar", "popustpr",
        "popustvi", "procenatar", "procenatpr", "procenatvi",
        "cenadod", "osiguranje1", "uplaceno",
    ]

    def _uplate_za_ugovor(kljuc: str) -> list[dict]:
        """Uplate povezane sa ugovorom: uplate.id = aranzman.kljuc bez "/26"
        (radi i preko faktura). Svaki red dobija kurs NBS na dan uplate i
        suma_eur = din / kurs (deljenje — 1 € = kurs dinara)."""
        broj = kljuc.strip().strip("/").split("/")[0]
        try:
            brojnum = int(broj)
        except ValueError:
            brojnum = None
        sql = "SELECT * FROM uplate WHERE COALESCE(faktura, '') = :broj"
        bind = {"broj": broj}
        if brojnum is not None:
            sql += " OR id = :brojnum"
            bind["brojnum"] = brojnum
        sql += " ORDER BY danas NULLS LAST"
        with engine.connect() as conn:
            rows = conn.execute(text(sql), bind).fetchall()
        out = []
        for r in rows:
            d = dict(r._mapping)
            danas_dt = d.get("danas")
            d["danas"] = danas_dt.strftime("%d.%m.%Y") if danas_dt else None
            din = d.get("din")
            kurs = kurs_datum = suma_eur = None
            if din is not None and danas_dt is not None:
                # Isključivo datum ove uplate: bez zamene današnjim kursom.
                kurs, kurs_datum = get_eur_middle_za_datum(danas_dt.date().isoformat())
                if kurs and math.isfinite(kurs) and kurs > 0:
                    suma_eur = round(float(din) / kurs, 2)
            d["kurs"] = kurs
            if kurs_datum:
                try:
                    import datetime as _dt
                    d["kurs_datum"] = _dt.date.fromisoformat(kurs_datum).strftime("%d.%m.%Y")
                except (TypeError, ValueError):
                    d["kurs_datum"] = kurs_datum
            else:
                d["kurs_datum"] = None
            d["suma_eur"] = suma_eur
            out.append(d)
        return out

    @api.get("/ugovori/{kljuc:path}/uplate")
    def ugovor_uplate(kljuc: str, _: dict = Depends(get_current_user)):
        out = _uplate_za_ugovor(kljuc)
        return {"rows": out, "total": len(out)}

    @api.get("/ugovori/{kljuc:path}/uplate/pdf")
    def ugovor_uplate_pdf(kljuc: str, _: dict = Depends(get_current_user)):
        """PDF 'Pregled uplata' — po šablonu starog sistema, logo gore levo."""
        from uplate_pdf import build_uplate_pdf

        kljuc_clean = kljuc.strip().strip("/")
        rows = _uplate_za_ugovor(kljuc)
        with engine.connect() as conn:
            arow = conn.execute(text(
                "SELECT putnik, adresa FROM aranzman WHERE kljuc = :k"
            ), {"k": kljuc_clean}).fetchone()
            logo_row = conn.execute(text(
                "SELECT slika, slika_mime FROM dokumenti WHERE tip = 'logo'"
            )).fetchone()
        logo_data_url = None
        if logo_row and logo_row.slika:
            mime = logo_row.slika_mime or "image/png"
            logo_data_url = f"data:{mime};base64,{logo_row.slika}"
        pdf_bytes = build_uplate_pdf(
            putnik=arow.putnik if arow else None,
            adresa=arow.adresa if arow else None,
            ugovor=kljuc_clean,
            rows=rows,
            logo_data_url=logo_data_url,
        )
        fname = f"Pregled_uplata_{kljuc_clean.replace('/', '-')}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )

    # ── Knjigovodstvo: unos nove uplate ─────────────────────────────────────
    @api.post("/uplate", status_code=201)
    def create_uplata(body: UplataCreate, current_user: dict = Depends(get_current_user)):
        ugovor = (body.ugovor or "").strip().strip("/")
        ime = (body.ime or "").strip()
        adresa = (body.adresa or "").strip()
        nacin = (body.nacin or "").strip()
        svrha = (body.svrha or "").strip()

        if not ugovor:
            raise HTTPException(status_code=400, detail="Broj ugovora je obavezan")
        if not ime:
            raise HTTPException(status_code=400, detail="Ime platioca je obavezno")
        if len(ime) > 300 or len(adresa) > 300:
            raise HTTPException(status_code=400, detail="Ime i adresa mogu imati najviše 300 znakova")
        if nacin not in NACINI_UPLATE:
            raise HTTPException(status_code=400, detail="Neispravan način plaćanja")
        if svrha not in SVRHE_UPLATE:
            raise HTTPException(status_code=400, detail="Neispravna svrha uplate")

        try:
            din = float(body.din)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Iznos mora biti broj")
        if not math.isfinite(din) or din <= 0:
            raise HTTPException(status_code=400, detail="Iznos mora biti pozitivan broj")
        if abs(din - round(din, 2)) > 1e-9:
            raise HTTPException(status_code=400, detail="Iznos može imati najviše 2 decimale")

        # kurs mora postojati PRE samog unosa uplate
        kurs = get_eur_middle()
        if not kurs or not math.isfinite(float(kurs)) or float(kurs) <= 0:
            raise HTTPException(status_code=503, detail="Kurs EUR nije dostupan — uplata nije uneta")

        try:
            user_id = int(current_user["sub"])
        except (KeyError, TypeError, ValueError):
            raise HTTPException(status_code=401, detail="Neautorizovan pristup")

        with engine.begin() as conn:
            urow = conn.execute(text(
                "SELECT u.id, u.first_name, u.last_name, u.status "
                "FROM users u WHERE u.id = :id"
            ), {"id": user_id}).fetchone()
            if not urow:
                raise HTTPException(status_code=401, detail="Neautorizovan pristup")
            if (urow.status or "") != "aktivan":
                raise HTTPException(status_code=403, detail="Nalog je neaktivan")

            # ugovor: tačan ključ (33333/26) ili broj pre kose crte (33333)
            if "/" in ugovor:
                arow = conn.execute(text(
                    "SELECT kljuc, destinacija, mesto, subagent, organizator, poslovnica "
                    "FROM aranzman WHERE kljuc = :k"
                ), {"k": ugovor}).fetchone()
            else:
                arow = conn.execute(text(
                    "SELECT kljuc, destinacija, mesto, subagent, organizator, poslovnica "
                    "FROM aranzman WHERE split_part(kljuc, '/', 1) = :b "
                    "ORDER BY id DESC LIMIT 1"
                ), {"b": ugovor}).fetchone()
            if not arow:
                raise HTTPException(status_code=404, detail="Ugovor nije pronađen")

            broj_ugovora = (arow.kljuc or "").split("/")[0].strip()
            try:
                ugovor_id = int(broj_ugovora)
            except ValueError:
                raise HTTPException(status_code=400, detail="Neispravan broj ugovora")

            obradio = f"{(urow.first_name or '').strip()} {(urow.last_name or '').strip()}".strip()
            uevro = round(din / float(kurs), 2)

            new_kljuc = conn.execute(text("""
                INSERT INTO uplate
                    (id, danas, ime, adresa, nacin, din, evro, uevro, svrha,
                     obradio, vrsta, faktura, destinacija, mesto, subagent,
                     organizator, poslovnica)
                VALUES
                    (:id, :danas, :ime, :adresa, :nacin, :din, :evro, :uevro, :svrha,
                     :obradio, :vrsta, :faktura, :destinacija, :mesto, :subagent,
                     :organizator, :poslovnica)
                RETURNING kljuc
            """), {
                "id": ugovor_id,
                "danas": _belgrade_now(),
                "ime": ime,
                "adresa": adresa,
                "nacin": nacin,
                "din": din,
                "evro": 0,
                "uevro": uevro,
                "svrha": svrha,
                "obradio": obradio,
                "vrsta": "UPLATA",
                "faktura": broj_ugovora,
                "destinacija": arow.destinacija,
                "mesto": arow.mesto,
                "subagent": arow.subagent,
                "organizator": arow.organizator,
                "poslovnica": arow.poslovnica,
            }).scalar_one()

            # broj dokumenta = ključ nove uplate kao string (VARCHAR(10) ograničenje)
            broj_dokumenta = str(new_kljuc)
            if len(broj_dokumenta) > 10:
                raise HTTPException(
                    status_code=500,
                    detail="Broj uplate premašuje dozvoljenih 10 znakova",
                )
            conn.execute(text("UPDATE uplate SET broj = :b WHERE kljuc = :k"),
                         {"b": broj_dokumenta, "k": new_kljuc})
            zabelezi(conn, arow.kljuc, OBLAST_UPLATA, "uplata_dodata", user_id, obradio, [
                {"polje": "Uplata (broj)", "stara": None, "nova": broj_dokumenta},
                {"polje": "Platilac", "stara": None, "nova": ime},
                {"polje": "Iznos (DIN)", "stara": None, "nova": norm_vrednost(din)},
                {"polje": "Način plaćanja", "stara": None, "nova": nacin},
                {"polje": "Svrha", "stara": None, "nova": svrha},
            ])

        return {"kljuc": int(new_kljuc), "message": "Uplata je uspešno uneta"}

    @api.get("/uplate/{kljuc}/priznanica")
    def uplata_priznanica(kljuc: int, _: dict = Depends(get_current_user)):
        """PDF priznanica o uplati — dva primerka na A4, isprekidana linija + makaze."""
        from priznanica_pdf import build_priznanica_pdf

        with engine.connect() as conn:
            u = conn.execute(text("SELECT * FROM uplate WHERE kljuc = :k"), {"k": kljuc}).fetchone()
            if not u:
                raise HTTPException(status_code=404, detail="Uplata nije pronađena")
            ag = conn.execute(text("SELECT * FROM agencija ORDER BY id LIMIT 1")).fetchone()
            logo_row = conn.execute(text(
                "SELECT slika, slika_mime FROM dokumenti WHERE tip = 'logo'"
            )).fetchone()
            # uplate.id = aranzman.kljuc bez "/26" → podaci o terminu i smeštaju
            ar = conn.execute(text("""
                SELECT kljuc, putnik, adresa, naziv, mesto,
                       to_char(datumod, 'DD.MM.YYYY') AS od,
                       to_char(datumdo, 'DD.MM.YYYY') AS do
                FROM aranzman
                WHERE split_part(kljuc, '/', 1) = :broj
                ORDER BY id DESC LIMIT 1
            """), {"broj": str(u.id)}).fetchone()

        logo_data_url = None
        if logo_row and logo_row.slika:
            mime = logo_row.slika_mime or "image/png"
            logo_data_url = f"data:{mime};base64,{logo_row.slika}"
        uplata = dict(u._mapping)
        aranzman = dict(ar._mapping) if ar else None
        if not (uplata.get("ime") or "").strip() and aranzman:
            uplata["ime"] = aranzman.get("putnik")
        if not (uplata.get("adresa") or "").strip() and aranzman:
            uplata["adresa"] = aranzman.get("adresa")
        pdf_bytes = build_priznanica_pdf(
            uplata=uplata,
            aranzman=aranzman,
            agencija=dict(ag._mapping) if ag else None,
            logo_data_url=logo_data_url,
        )
        fname = f"Priznanica_{kljuc}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )

    # ── Ugovor: promena smeštaja (soba + termin) ────────────────────────────
    @api.patch("/ugovori/{kljuc:path}/smestaj")
    def ugovor_smestaj_update(
        kljuc: str, body: UgovorSmestajUpdate,
        current_user: dict = Depends(get_current_user),
    ):
        """Promena sobe i termina smeštaja na ugovoru (aranzman).

        Sve vrednosti se izvode iz baze: sobe → smestaj (naziv) → mesto →
        destinacija; apartman = sobe.tip. Zauzeće = svaki drugi aranzman sa
        istim nazivom smeštaja i sobom (TRIM poređenje) čiji se period
        preklapa — ista konvencija kao /slobodne-sobe, bez trenutnog ugovora.
        Atomarno u jednoj transakciji: transakcioni advisory lock na sobu pa
        SELECT ... FOR UPDATE na ugovor (dosledan redosled — bez deadlocka).
        Finansije i dopune se NE menjaju."""
        kljuc = kljuc.strip().strip("/")
        if not kljuc:
            raise HTTPException(status_code=400, detail="Broj ugovora je obavezan")
        datum_od = _parse_iso_date(body.datum_od, "datum_od")
        datum_do = _parse_iso_date(body.datum_do, "datum_do")
        if datum_do <= datum_od:
            raise HTTPException(status_code=400, detail="Datum do mora biti posle datuma od")

        try:
            user_id = int(current_user["sub"])
        except (KeyError, TypeError, ValueError):
            raise HTTPException(status_code=401, detail="Neautorizovan pristup")

        # datumoddo u formatu postojećih podataka: 'DD.MM.YYYY-DD.MM.YYYY'
        datumoddo = f"{datum_od.strftime('%d.%m.%Y')}-{datum_do.strftime('%d.%m.%Y')}"

        with engine.begin() as conn:
            # token sam ne garantuje status naloga — proveri u bazi
            urow = conn.execute(text(
                "SELECT u.id, u.status FROM users u WHERE u.id = :id"
            ), {"id": user_id}).fetchone()
            if not urow:
                raise HTTPException(status_code=401, detail="Neautorizovan pristup")
            if (urow.status or "") != "aktivan":
                raise HTTPException(status_code=403, detail="Nalog je neaktivan")

            # soba + izvedeni podaci (sobe → smestaj → mesto → destinacija)
            brow = conn.execute(text("""
                SELECT b.id,
                       COALESCE(TRIM(b.broj_sobe), '') AS broj_sobe,
                       COALESCE(TRIM(b.tip), '') AS tip,
                       s.id AS smestaj_id, s.naziv AS smestaj_naziv,
                       m.id AS mesto_id, m.naziv AS mesto_naziv,
                       d.naziv AS destinacija_naziv
                FROM sobe b
                JOIN smestaj s ON s.id = b.veza_id_smestaj
                LEFT JOIN mesto m ON m.id = s.mesto
                LEFT JOIN destinacija d
                    ON d.id = COALESCE(m.destinacija, s.destinacija)
                WHERE b.id = :id
            """), {"id": body.soba_id}).fetchone()
            if not brow:
                raise HTTPException(status_code=404, detail="Soba nije pronađena")
            if brow.mesto_id is None:
                raise HTTPException(status_code=404, detail="Mesto smeštaja nije pronađeno")
            if len(brow.tip or "") > 10:
                raise HTTPException(status_code=400, detail="Tip sobe može imati najviše 10 znakova na ugovoru")

            # redosled zaključavanja: (1) advisory lock na sobu — serijalizuje
            # sve promene iste sobe do kraja transakcije, pa (2) red ugovora.
            conn.execute(text("SELECT pg_advisory_xact_lock(:key)"),
                         {"key": SMESTAJ_ADVISORY_LOCK_BASE + body.soba_id})

            # ugovor — zaključaj red do kraja transakcije
            arow = conn.execute(text(
                "SELECT id, naziv, mesto, destinacija, soba, apartman, datumod, datumdo, datumoddo "
                "FROM aranzman WHERE kljuc = :k FOR UPDATE"
            ), {"k": kljuc}).fetchone()
            if not arow:
                raise HTTPException(status_code=404, detail="Ugovor nije pronađen")

            # zauzeće — ista konvencija kao /slobodne-sobe, bez trenutnog ugovora
            conflict = conn.execute(text("""
                SELECT a.kljuc FROM aranzman a
                WHERE a.id <> :cur_id
                  AND a.naziv = :naziv
                  AND TRIM(COALESCE(a.soba, '')) = :soba
                  AND a.datumod IS NOT NULL AND a.datumdo IS NOT NULL
                  AND a.datumod < :d_do
                  AND a.datumdo > :d_od
                LIMIT 1
            """), {
                "cur_id": arow.id,
                "naziv": brow.smestaj_naziv,
                "soba": brow.broj_sobe,
                "d_od": datum_od,
                "d_do": datum_do,
            }).fetchone()
            if conflict:
                raise HTTPException(
                    status_code=409,
                    detail=f"Soba je zauzeta u izabranom periodu (ugovor {conflict.kljuc})",
                )

            novi_smestaj = {
                "naziv": brow.smestaj_naziv,
                "mesto": brow.mesto_naziv,
                "destinacija": brow.destinacija_naziv or "",
                "soba": brow.broj_sobe,
                "apartman": brow.tip or "",
                "datumod": datum_od,
                "datumdo": datum_do,
                "datumoddo": datumoddo,
            }
            conn.execute(text("""
                UPDATE aranzman SET
                    naziv = :naziv,
                    mesto = :mesto,
                    destinacija = :destinacija,
                    soba = :soba,
                    apartman = :apartman,
                    datumod = :datumod,
                    datumdo = :datumdo,
                    datumoddo = :datumoddo
                WHERE id = :id
            """), {"id": arow.id, **novi_smestaj})
            uid, uime = log_user(conn, current_user)
            zabelezi(conn, kljuc, OBLAST_REZERVACIJA, "smestaj_promenjen", uid, uime,
                     podeli_po_oblastima(dict(arow._mapping), novi_smestaj).get(OBLAST_REZERVACIJA, []))

        return {"message": "Smeštaj je uspešno promenjen"}

    # ── Rezervacije: Sačuvaj / Izmeni (unos i izmena aranžmana iz forme) ────
    def _rez_user_row(current_user: dict):
        try:
            user_id = int(current_user["sub"])
        except (KeyError, TypeError, ValueError):
            raise HTTPException(status_code=401, detail="Neautorizovan pristup")
        with engine.connect() as conn:
            urow = conn.execute(text(
                "SELECT u.id, u.first_name, u.last_name, u.status "
                "FROM users u WHERE u.id = :id"
            ), {"id": user_id}).fetchone()
        if not urow:
            raise HTTPException(status_code=401, detail="Neautorizovan pristup")
        if (urow.status or "") != "aktivan":
            raise HTTPException(status_code=403, detail="Nalog je neaktivan")
        return urow

    def sledeci_broj_ugovora(conn, godina: int) -> str:
        """Novi broj = MAX(broj) unutar godine iz Datuma od + 1 (brojač se resetuje
        svake godine: 1/27, 2/27, ...). Pozivati SAMO pod REZ_ADVISORY_LOCK."""
        suf = f"{godina % 100:02d}"
        max_broj = conn.execute(text("""
            SELECT COALESCE(MAX(split_part(kljuc, '/', 1)::bigint), 0)
            FROM aranzman
            WHERE split_part(kljuc, '/', 1) ~ '^[0-9]+$'
              AND split_part(kljuc, '/', 2) = :suf
        """), {"suf": suf}).scalar_one()
        return f"{int(max_broj) + 1}/{suf}"

    def rez_saputnici_snimak(saputnici: list[RezPutnikIn]) -> list[dict]:
        """Saputnici iz forme u obliku aranzman_dopuna kolona — za diff u logu."""
        out = []
        for s in saputnici:
            if not s.ime.strip():
                continue
            out.append({
                "saputnik": s.ime.strip()[:200],
                "rodjen": _rez_datum(s.datumRodjenja, "Datum rođenja saputnika"),
                "pasos": _rez_str(s.pasos, 50),
                "prevozow": 1 if s.ow else 0,
                "prevozrt": 1 if s.rt else 0,
                "smer": _rez_str(s.smer, 50) if s.ow else None,
                "adresa": (s.adresa or "").strip()[:300],
                "email": (s.email or "").strip()[:300],
                "telefon": (s.telefon or "").strip()[:300],
                "ulazak": _rez_str(s.ulazak, 200),
            })
        return out

    def rez_saputnici_upisi(conn, aranzman_id: int, saputnici: list[RezPutnikIn]):
        """Saputnici iz forme → aranzman_dopuna (red po redu). uzrast/viza se ne
        unose u formi — nasleđuju se po imenu sa postojećih redova (import)."""
        stari = conn.execute(text(
            "SELECT saputnik, uzrast, viza FROM aranzman_dopuna WHERE aranzman_id = :i"
        ), {"i": aranzman_id}).fetchall()
        nasledjeno = {}
        for s in stari:
            ime = (s.saputnik or "").strip().upper()
            if ime:
                nasledjeno[ime] = s
        conn.execute(text("DELETE FROM aranzman_dopuna WHERE aranzman_id = :i"),
                     {"i": aranzman_id})
        for s in saputnici:
            if not s.ime.strip():
                continue
            st = nasledjeno.get(s.ime.strip().upper())
            conn.execute(text("""
                INSERT INTO aranzman_dopuna
                    (aranzman_id, saputnik, rodjen, pasos, prevozow, prevozrt, smer,
                     adresa, email, telefon, ulazak, uzrast, viza)
                VALUES (:aid, :ime, :rodjen, :pasos, :ow, :rt, :smer,
                        :adresa, :email, :telefon, :ulazak, :uzrast, :viza)
            """), {
                "aid": aranzman_id,
                "ime": s.ime.strip()[:200],
                "rodjen": _rez_datum(s.datumRodjenja, "Datum rođenja saputnika"),
                "pasos": _rez_str(s.pasos, 50),
                "ow": 1 if s.ow else 0,
                "rt": 1 if s.rt else 0,
                "smer": _rez_str(s.smer, 50) if s.ow else None,
                "adresa": (s.adresa or "").strip()[:300],
                "email": (s.email or "").strip()[:300],
                "telefon": (s.telefon or "").strip()[:300],
                "ulazak": _rez_str(s.ulazak, 200),
                "uzrast": st.uzrast if st else None,
                "viza": st.viza if st else None,
            })

    def _rez_proveri_konflikt(conn, smestaj_naziv, soba_broj, datum_od, datum_do,
                              exclude_kljuc=None) -> None:
        """Sudar termina: isti smeštaj + ista soba sa preklapajućim periodom.
        Ista konvencija kao /slobodne-sobe i grafik (datumod < :do AND datumdo > :od,
        tako da se mogu nasloniti dva uzastopna boravka na isti dan). Baca 409 ako
        već postoji drugi zapis u tom periodu — rezervacija se NE upisuje."""
        if not smestaj_naziv or not soba_broj:
            return  # bez izabranog smeštaja/sobe se zauzeće ne može odrediti
        sql = """
            SELECT kljuc, putnik, to_char(datumod, 'DD.MM.YYYY') AS od,
                   to_char(datumdo, 'DD.MM.YYYY') AS doo
            FROM aranzman
            WHERE naziv = :naziv
              AND TRIM(COALESCE(soba, '')) = TRIM(:soba)
              AND datumod IS NOT NULL AND datumdo IS NOT NULL
              AND datumod < :do AND datumdo > :od
        """
        params: dict = {"naziv": smestaj_naziv, "soba": soba_broj,
                        "od": datum_od, "do": datum_do}
        if exclude_kljuc:
            sql += " AND kljuc <> :ek"
            params["ek"] = exclude_kljuc
        sql += " ORDER BY datumod LIMIT 1"
        row = conn.execute(text(sql), params).fetchone()
        if row:
            raise HTTPException(
                status_code=409,
                detail=(f"Termin je zauzet — soba {soba_broj} ({smestaj_naziv}) već ima zapis "
                        f"u periodu {row.od}–{row.doo}: ugovor {row.kljuc}"
                        + (f" ({row.putnik})" if row.putnik else "")
                        + ". Rezervacija nije upisana."),
            )

    def rezervacija_vrednosti(conn, body: RezervacijaIn, urow,
                              exclude_kljuc: str | None = None) -> dict:
        """Mapira formu rezervacije na kolone aranzman-a (POST i PUT)."""
        n, b, c = body.nosilac, body.boravak, body.cene

        datum_od = _rez_datum(b.datumOd, "Datum od")
        datum_do = _rez_datum(b.datumDo, "Datum do")
        if datum_od is None:
            raise HTTPException(status_code=400, detail="Datum od je obavezan")
        if datum_do is None:
            raise HTTPException(status_code=400, detail="Datum do je obavezan")
        if datum_do <= datum_od:
            raise HTTPException(status_code=400, detail="Datum do mora biti posle Datuma od")
        if not n.ime.strip():
            raise HTTPException(status_code=400, detail="Ime nosioca aranžmana je obavezno")

        def naziv_po_id(tabela: str, idv, kolona: str = "naziv"):
            if idv is None:
                return None
            r = conn.execute(text(f"SELECT {kolona} FROM {tabela} WHERE id = :i"),
                             {"i": idv}).fetchone()
            return (getattr(r, kolona) or "").strip() or None if r else None

        # baza čuva NAZIVE (ne ID-jeve): ID pobeđuje, fallback je sačuvani naziv
        # van referentne liste (stari ugovori) — da se ne izgubi pri čuvanju.
        smestaj_naziv = naziv_po_id("smestaj", b.smestajId) or _rez_str(b.smestajNaziv, 200)
        # ID konkretne instance smeštaja (mesto + grupa termina) — smeštaji istog
        # naziva postoje u više grupa, pa grafik po ovom ID-ju razdvaja ugovore
        smestaj_id_val = None
        if b.smestajId is not None:
            r = conn.execute(text("SELECT id FROM smestaj WHERE id = :i"),
                             {"i": b.smestajId}).fetchone()
            if r:
                smestaj_id_val = r.id
        mesto_naziv = naziv_po_id("mesto", b.mestoId) or _rez_str(b.mestoNaziv, 200)
        destinacija_naziv = naziv_po_id("destinacija", body.destinacijaId) or _rez_str(body.destinacijaNaziv, 100)
        soba_broj = None
        if b.sobaId is not None:
            r = conn.execute(text("SELECT broj_sobe FROM sobe WHERE id = :i"), {"i": b.sobaId}).fetchone()
            if r:
                soba_broj = (r.broj_sobe or "").strip() or None
        if soba_broj is None:
            soba_broj = _rez_str(b.sobaBroj, 200)

        # obavezna provera zauzeća pre upisa (POST i PUT; PUT izuzima sebe)
        _rez_proveri_konflikt(conn, smestaj_naziv, soba_broj, datum_od, datum_do, exclude_kljuc)

        # bruto osnove za konverziju iznosa u procente
        bruto_sm_eur = round(c.cenaSmestajEUR * c.kolSmestajEUR, 2)
        bruto_sm_rsd = round(c.cenaSmestajRSD * c.kolSmestajRSD, 2)
        bruto_pr_eur = round(c.cenaPrevozEUR * c.kolPrevozEUR, 2)
        bruto_pr_rsd = round(c.cenaPrevozRSD * c.kolPrevozRSD, 2)

        popustar = _rez_procenat_iz_reda(c.popustSmestaj, bruto_sm_eur, bruto_sm_rsd)
        popustpr = _rez_procenat_iz_reda(c.popustPrevoz, bruto_pr_eur, bruto_pr_rsd)
        procenatar = _rez_procenat_iz_reda(c.provizijaSmestaj, bruto_sm_eur, bruto_sm_rsd)
        # provizija prevoza: legacy obračun = procenatpr × količina (iznos po osobi)
        prv_ukupno = _rez_red_ukupno(c.provizijaPrevoz, bruto_pr_eur, bruto_pr_rsd)
        kol_pr = c.kolPrevozRSD if (c.provizijaPrevoz.eur is None and c.provizijaPrevoz.rsd is not None) \
            else c.kolPrevozEUR
        procenatpr = round(prv_ukupno / kol_pr, 2) if prv_ukupno is not None and kol_pr > 0 else 0.0

        ow, rt = bool(n.ow), bool(n.rt)
        kol_pr_int = int(round(c.kolPrevozEUR))
        return {
            "putnik": n.ime.strip()[:200],
            "rodjen": _rez_datum(n.datumRodjenja, "Datum rođenja"),
            "pasos": _rez_str(n.pasos, 50),
            "adresa": (n.adresa or "").strip()[:200],
            "telefon": (n.telefon or "").strip()[:200],
            "refno": _rez_str(n.email, 200),  # refno = email (isti maping kao pri učitavanju)
            "prevozow": 1 if ow else 0,
            "prevozrt": 1 if rt else 0,
            "smer": _rez_str(n.smer, 50) if ow else None,
            "tiprezervacije": _rez_str(body.tiprezervacije, 200),
            "subagent": (body.subagent or "").strip()[:300],
            "timelimit": _rez_ts(body.timelimit),
            "mesto": mesto_naziv,
            "naziv": smestaj_naziv,
            "smestaj_id": smestaj_id_val,
            "soba": soba_broj,
            "destinacija": destinacija_naziv,
            "apartman": _rez_str(b.struktura, 10),
            "datumod": datetime(datum_od.year, datum_od.month, datum_od.day),
            "datumdo": datetime(datum_do.year, datum_do.month, datum_do.day),
            "datumoddo": f"{datum_od:%d.%m.%Y}-{datum_do:%d.%m.%Y}",
            "napomena": (b.napomena or "")[:1024],
            "napomena1": _rez_str(b.napomenaInterna, 255),
            "ulazak": _rez_str(body.ulazak, 200),
            "cenaaranz": round(c.cenaSmestajEUR, 2),
            "kolaranz": c.kolSmestajEUR,
            "cenaaranzd": round(c.cenaSmestajRSD, 2),
            # prevoz po nosiocu (RT → cenart/cenadrt, inače cenaow/cenadow);
            # nekorišćena strana ostaje sa količinom 1 i cenom 0 (kao u starom sistemu)
            "cenaow": 0.0 if rt else round(c.cenaPrevozEUR, 2),
            "kolow": 1 if rt else max(0, kol_pr_int),
            "cenart": round(c.cenaPrevozEUR, 2) if rt else 0.0,
            "kolrt": max(0, kol_pr_int) if rt else 1,
            "cenadow": 0.0 if rt else round(c.cenaPrevozRSD, 2),
            "cenadrt": round(c.cenaPrevozRSD, 2) if rt else 0.0,
            "osiguranje": round(c.osiguranjeRSD, 2),
            "osiguranje1": round(c.osiguranjeEUR, 2),
            "popustar": popustar,
            "popustpr": popustpr,
            "procenatar": procenatar,
            "procenatpr": procenatpr,
            "obradio": f"{(urow.first_name or '').strip()} {(urow.last_name or '').strip()}".strip(),
        }

    @api.post("/rezervacije", status_code=201)
    def kreiraj_rezervaciju(body: RezervacijaIn, current_user: dict = Depends(get_current_user)):
        """Sačuvaj — novi ugovor. Broj = MAX(broj) unutar godine iz Datuma od + 1,
        pod advisory lock-om + UNIQUE(kljuc) kao poslednjom odbranom od duplikata."""
        urow = _rez_user_row(current_user)
        datum_od_d = _rez_datum(body.boravak.datumOd, "Datum od")
        if datum_od_d is None:
            raise HTTPException(status_code=400, detail="Datum od je obavezan")
        godina = datum_od_d.year
        for _ in range(6):
            try:
                with engine.begin() as conn:
                    # kritična sekcija dodele broja — sve instance aplikacije se
                    # izvršavaju redno, pa dve rezervacije ne mogu dobiti isti broj
                    conn.execute(text("SELECT pg_advisory_xact_lock(:k)"),
                                 {"k": REZ_ADVISORY_LOCK})
                    kljuc = sledeci_broj_ugovora(conn, godina)
                    vals = rezervacija_vrednosti(conn, body, urow)
                    vals["kljuc"] = kljuc
                    vals["danas"] = _belgrade_now()
                    cols = list(vals.keys())
                    ph = ", ".join(f":{k}" for k in cols)
                    aid = conn.execute(text(
                        f"INSERT INTO aranzman ({', '.join(cols)}) VALUES ({ph}) RETURNING id"
                    ), vals).scalar_one()
                    rez_saputnici_upisi(conn, aid, body.saputnici)
                    uid, uime = log_user(conn, current_user)
                    for oblast, promene in podeli_po_oblastima({}, vals).items():
                        zabelezi(conn, kljuc, oblast, "kreirana", uid, uime, promene)
                    zabelezi(conn, kljuc, OBLAST_SAPUTNICI, "kreirana", uid, uime,
                             diff_saputnike([], rez_saputnici_snimak(body.saputnici)))
                return {"kljuc": kljuc, "message": "Rezervacija je sačuvana"}
            except IntegrityError:
                # UNIQUE(kljuc) — import je ubacio isti broj u međuvremenu;
                # preskoči na sledeći slobodan broj
                continue
        raise HTTPException(status_code=500, detail="Dodela broja ugovora nije uspela — pokušajte ponovo")

    @api.put("/rezervacije/{kljuc:path}")
    def izmeni_rezervaciju(kljuc: str, body: RezervacijaIn,
                           current_user: dict = Depends(get_current_user)):
        """Izmeni — snimanje izmena postojećeg ugovora (broj se ne menja)."""
        kljuc = kljuc.strip().strip("/")
        urow = _rez_user_row(current_user)
        with engine.begin() as conn:
            arow = conn.execute(text("SELECT id FROM aranzman WHERE kljuc = :k"),
                                {"k": kljuc}).fetchone()
            if not arow:
                raise HTTPException(status_code=404, detail="Ugovor nije pronađen")
            vals = rezervacija_vrednosti(conn, body, urow, exclude_kljuc=kljuc)
            # stare vrednosti za diff (samo kolone koje forma šalje)
            cols_sql = ", ".join(vals.keys())
            stari = dict(conn.execute(text(
                f"SELECT {cols_sql} FROM aranzman WHERE id = :id"
            ), {"id": arow.id}).mappings().one())
            stari_sap = [dict(r) for r in conn.execute(text(
                "SELECT saputnik, rodjen, pasos, prevozow, prevozrt, smer, adresa, "
                "email, telefon, ulazak FROM aranzman_dopuna WHERE aranzman_id = :i"
            ), {"i": arow.id}).mappings().all()]
            sets = ", ".join(f"{k} = :{k}" for k in vals)
            conn.execute(text(f"UPDATE aranzman SET {sets} WHERE kljuc = :wk"),
                         {**vals, "wk": kljuc})
            rez_saputnici_upisi(conn, arow.id, body.saputnici)
            uid, uime = log_user(conn, current_user)
            for oblast, promene in podeli_po_oblastima(stari, vals).items():
                zabelezi(conn, kljuc, oblast, "izmena", uid, uime, promene)
            zabelezi(conn, kljuc, OBLAST_SAPUTNICI, "izmena", uid, uime,
                     diff_saputnike(stari_sap, rez_saputnici_snimak(body.saputnici)))
        return {"ok": True, "kljuc": kljuc, "message": "Izmene su sačuvane"}

    @api.post("/rezervacije/{kljuc:path}/storno")
    def storniraj_rezervaciju(kljuc: str, current_user: dict = Depends(get_current_user)):
        kljuc = kljuc.strip().strip("/")
        _rez_user_row(current_user)
        with engine.begin() as conn:
            redovi = conn.execute(text(
                "SELECT id, tiprezervacije, naziv, soba, smestaj_id, napomena, putnik "
                "FROM aranzman WHERE kljuc = :k ORDER BY id FOR UPDATE"
            ), {"k": kljuc}).mappings().all()
            if not redovi:
                raise HTTPException(status_code=404, detail="Ugovor nije pronađen")
            uid, uime = log_user(conn, current_user)
            for red in redovi:
                if (red["tiprezervacije"] or "").strip().upper() == "STORNO":
                    continue
                napomena = red["napomena"] or ""
                dodatak = f"STORNO — prethodni smeštaj: {red['naziv'] or '—'}; soba: {red['soba'] or '—'}."
                napomena = f"{napomena}\n{dodatak}" if napomena else dodatak
                if len(napomena) > 1024:
                    raise HTTPException(status_code=400, detail="Napomena je preduga za dopisivanje podataka storniranja. Skratite je i pokušajte ponovo.")
                putnik = (red["putnik"] or "").rstrip()
                if not putnik.upper().endswith("(STORNO)"):
                    putnik = f"{putnik} - (STORNO)" if putnik else "(STORNO)"
                novo = {"tiprezervacije": "STORNO", "naziv": "STORNO", "soba": "", "smestaj_id": None, "napomena": napomena, "putnik": putnik}
                conn.execute(text(
                    "UPDATE aranzman SET tiprezervacije = :tiprezervacije, naziv = :naziv, "
                    "soba = :soba, smestaj_id = :smestaj_id, napomena = :napomena, putnik = :putnik WHERE id = :id"
                ), {**novo, "id": red["id"]})
                for oblast, promene in podeli_po_oblastima(dict(red), novo).items():
                    zabelezi(conn, kljuc, oblast, "izmena", uid, uime, promene)
        return {"ok": True, "kljuc": kljuc, "message": f"Rezervacija {kljuc} je stornirana"}

    def dodatne_contract(conn, kljuc: str, current_user: dict) -> int:
        try:
            user_id = int(current_user["sub"])
        except (KeyError, TypeError, ValueError):
            raise HTTPException(status_code=401, detail="Neautorizovan pristup")
        urow = conn.execute(text(
            "SELECT u.id, u.status FROM users u WHERE u.id = :id"
        ), {"id": user_id}).fetchone()
        if not urow:
            raise HTTPException(status_code=401, detail="Neautorizovan pristup")
        if (urow.status or "") != "aktivan":
            raise HTTPException(status_code=403, detail="Nalog je neaktivan")
        arow = conn.execute(text(
            "SELECT kljuc FROM aranzman WHERE kljuc = :k"
        ), {"k": kljuc}).fetchone()
        if not arow:
            raise HTTPException(status_code=404, detail="Ugovor nije pronađen")
        prefix = (arow.kljuc or "").split("/", 1)[0]
        if not re.fullmatch(r"[+-]?[0-9]+", prefix):
            raise HTTPException(status_code=400, detail="Neispravan broj ugovora")
        broj = int(prefix)
        if not -(2**31) <= broj <= 2**31 - 1:
            raise HTTPException(status_code=400, detail="Neispravan broj ugovora")
        return broj

    @api.post("/ugovori/{kljuc:path}/dodatne", status_code=201)
    def create_dodatna(kljuc: str, body: DodatnaCreate,
                       current_user: dict = Depends(get_current_user)):
        values = _dodatna_values(body)
        with engine.begin() as conn:
            broj = dodatne_contract(conn, kljuc, current_user)
            row = conn.execute(text("""
                INSERT INTO dodatne (id, usluga, eur, din)
                VALUES (:id, :usluga, :eur, :din)
                RETURNING stavka_id, usluga, eur, din
            """), {"id": broj, **values}).mappings().one()
            result = dict(row)
            uid, uime = log_user(conn, current_user)
            zabelezi(conn, kljuc, OBLAST_OBRACUN, "usluga_dodata", uid, uime, [
                {"polje": "Usluga", "stara": None, "nova": norm_vrednost(values["usluga"])},
                {"polje": "EUR", "stara": None, "nova": norm_vrednost(values["eur"])},
                {"polje": "DIN", "stara": None, "nova": norm_vrednost(values["din"])},
            ])
        return result

    @api.patch("/ugovori/{kljuc:path}/dodatne/{stavka_id}")
    def update_dodatna(kljuc: str, stavka_id: int, body: DodatnaUpdate,
                       current_user: dict = Depends(get_current_user)):
        values = _dodatna_values(body)
        for value in (body.original.eur, body.original.din):
            if value is not None and not math.isfinite(value):
                raise HTTPException(status_code=400, detail="Originalni iznos mora biti konačan broj")
        with engine.begin() as conn:
            broj = dodatne_contract(conn, kljuc, current_user)
            row = conn.execute(text("""
                UPDATE dodatne SET usluga = :usluga, eur = :eur, din = :din
                WHERE stavka_id = :stavka_id AND id = :id
                  AND usluga IS NOT DISTINCT FROM :original_usluga
                  AND eur IS NOT DISTINCT FROM :original_eur
                  AND din IS NOT DISTINCT FROM :original_din
                RETURNING stavka_id, usluga, eur, din
            """), {
                "id": broj, "stavka_id": stavka_id, **values,
                "original_usluga": body.original.usluga,
                "original_eur": body.original.eur,
                "original_din": body.original.din,
            }).mappings().first()
            if row is None:
                exists = conn.execute(text(
                    "SELECT stavka_id FROM dodatne WHERE stavka_id = :stavka_id AND id = :id"
                ), {"stavka_id": stavka_id, "id": broj}).fetchone()
                if exists:
                    raise HTTPException(status_code=409, detail="Stavka je u međuvremenu izmenjena")
                raise HTTPException(status_code=404, detail="Stavka nije pronađena")
            result = dict(row)
            uid, uime = log_user(conn, current_user)
            zabelezi(conn, kljuc, OBLAST_OBRACUN, "usluga_izmenjena", uid, uime, [
                {"polje": lbl, "stara": norm_vrednost(getattr(body.original, p)),
                 "nova": norm_vrednost(values[p])}
                for p, lbl in (("usluga", "Usluga"), ("eur", "EUR"), ("din", "DIN"))
                if norm_vrednost(getattr(body.original, p)) != norm_vrednost(values[p])
            ])
        return result

    @api.delete("/ugovori/{kljuc:path}/dodatne/{stavka_id}")
    def delete_dodatna(kljuc: str, stavka_id: int, body: DodatnaDelete,
                       current_user: dict = Depends(get_current_user)):
        body = body.original
        for value in (body.eur, body.din):
            if value is not None and not math.isfinite(value):
                raise HTTPException(status_code=400, detail="Originalni iznos mora biti konačan broj")
        with engine.begin() as conn:
            broj = dodatne_contract(conn, kljuc, current_user)
            row = conn.execute(text("""
                DELETE FROM dodatne WHERE stavka_id = :stavka_id AND id = :id
                  AND usluga IS NOT DISTINCT FROM :usluga
                  AND eur IS NOT DISTINCT FROM :eur
                  AND din IS NOT DISTINCT FROM :din
                RETURNING stavka_id
            """), {"stavka_id": stavka_id, "id": broj,
                    "usluga": body.usluga, "eur": body.eur, "din": body.din}).first()
            if row is None:
                exists = conn.execute(text(
                    "SELECT stavka_id FROM dodatne WHERE stavka_id = :s AND id = :i"
                ), {"s": stavka_id, "i": broj}).first()
                raise HTTPException(status_code=409 if exists else 404,
                    detail="Stavka je u međuvremenu izmenjena" if exists else "Stavka nije pronađena")
            uid, uime = log_user(conn, current_user)
            zabelezi(conn, kljuc, OBLAST_OBRACUN, "usluga_obrisana", uid, uime, [
                {"polje": "Usluga", "stara": norm_vrednost(body.usluga), "nova": None},
                {"polje": "EUR", "stara": norm_vrednost(body.eur), "nova": None},
                {"polje": "DIN", "stara": norm_vrednost(body.din), "nova": None},
            ])
        return {"message": "Dodatna stavka je obrisana"}

    @api.get("/ugovori/{kljuc:path}/pdf")
    def download_ugovor_pdf(kljuc: str, current_user: dict = Depends(get_current_user)):
        from decimal import Decimal, ROUND_HALF_UP
        from ugovor_pdf import generate_ugovor_pdf
        with engine.connect() as conn:
            broj = dodatne_contract(conn, kljuc, current_user)
            row = conn.execute(text("SELECT * FROM aranzman WHERE kljuc = :k"),
                               {"k": kljuc}).mappings().one()
            data = dict(row)
            data["email"] = data.get("refno") or ""
            data["putnici_detalji"] = [dict(p) for p in conn.execute(text(
                "SELECT * FROM aranzman_dopuna WHERE aranzman_id = :i ORDER BY id"
            ), {"i": data["id"]}).mappings()]
            data["dodatne"] = [dict(p) for p in conn.execute(text(
                "SELECT stavka_id, usluga, eur, din FROM dodatne WHERE id = :i ORDER BY stavka_id"
            ), {"i": broj}).mappings()]
            agency = conn.execute(text("SELECT * FROM agencija WHERE id = 1")).mappings().first()
        if not data.get("danas"):
            raise HTTPException(status_code=422, detail="Ugovor nema datum izdavanja")
        datum = data["danas"].date() if hasattr(data["danas"], "date") else data["danas"]
        kurs, kurs_datum = get_eur_middle_za_datum(datum.isoformat())
        if not kurs or not math.isfinite(kurs) or kurs <= 0:
            raise HTTPException(status_code=503, detail="Kurs NBS za datum ugovora nije dostupan. Pokušajte ponovo.")
        calc = calc_ugovor_values(data)
        ukupno = Decimal(str(calc["naplata"])) + Decimal(str(calc["provizija"]))
        data.update(obracun=calc, ukupno_eur=ukupno,
                    ukupno_rsd=(ukupno * Decimal(str(kurs))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                    kurs=kurs, kurs_datum=kurs_datum, datum_izdavanja=datum)
        izdavalac = dict(agency) if agency else {}
        izdavalac["racun"] = next((izdavalac.get(f"tekuci_racun{i}") for i in range(1, 5)
                                  if izdavalac.get(f"tekuci_racun{i}")), "")
        izdavalac["banka"] = next((izdavalac.get(f"banka{i}") for i in range(1, 5)
                                  if izdavalac.get(f"tekuci_racun{i}")), "")
        pdf = generate_ugovor_pdf(data, izdavalac)
        safe_key = re.sub(r"[^0-9A-Za-z_-]", "-", kljuc)
        return Response(content=pdf, media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="Ugovor_{safe_key}.pdf"'})

    @api.get("/ugovori/{kljuc:path}")
    def ugovor_detail(kljuc: str, _: dict = Depends(get_current_user)):
        kljuc = kljuc.strip().strip("/")
        with engine.connect() as conn:
            row = conn.execute(text("""
                SELECT a.*, s.naziv AS subagent_naziv, s.provizija AS subagent_provizija,
                       s.racun AS subagent_racun, s.tel AS subagent_tel,
                       s.kontakt AS subagent_kontakt
                FROM aranzman a
                LEFT JOIN subagenti s ON s.naziv = a.subagent AND s.naziv <> ''
                WHERE a.kljuc = :kljuc
            """), {"kljuc": kljuc}).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Ugovor nije pronađen")
            # saputnici iz aranzman_dopuna (red po red)
            dopuni = conn.execute(text("""
                SELECT saputnik, uzrast, prevozow, prevozrt, viza, ulazak, smer,
                       adresa, email, telefon, rodjen, pasos
                FROM aranzman_dopuna WHERE aranzman_id = :i ORDER BY id
            """), {"i": row.id}).fetchall()
            # dodatne.id je broj ugovora, ne interni aranzman.id.
            broj_ugovora = kljuc.split("/", 1)[0]
            dodatne = conn.execute(text("""
                SELECT stavka_id, usluga, eur, din FROM dodatne WHERE id = :broj
                ORDER BY usluga NULLS LAST, eur NULLS LAST, din NULLS LAST
            """), {"broj": int(broj_ugovora)}).mappings().all() if broj_ugovora.isdigit() else []
        d = dict(row._mapping)
        subagent = None
        if d.get("subagent_naziv"):
            subagent = {
                "naziv": d.get("subagent_naziv"),
                "provizija": d.get("subagent_provizija"),
                "racun": d.get("subagent_racun"),
                "tel": d.get("subagent_tel"),
                "kontakt": d.get("subagent_kontakt"),
            }
        kurs = get_eur_middle()
        calc = calc_ugovor_values(d)
        ukupna = round((calc["naplata"] + calc["provizija"]) * kurs, 2) if kurs else None
        fmt_date = lambda v: v.strftime("%d.%m.%Y") if v else None
        putnici_detalji = [{
            "saputnik": (p.saputnik or "").strip(),
            "rodjen": fmt_date(p.rodjen),
            "pasos": p.pasos,
            "uzrast": (p.uzrast or "").strip() or None,
            "prevozow": p.prevozow,
            "prevozrt": p.prevozrt,
            "viza": p.viza,
            "ulazak": p.ulazak,
            "smer": p.smer,
            "adresa": (p.adresa or "").strip() or None,
            "email": (p.email or "").strip() or None,
            "telefon": (p.telefon or "").strip() or None,
        } for p in dopuni]
        putnici = [str(d.get("putnik") or "").strip()]
        putnici += [p["saputnik"] for p in putnici_detalji if p["saputnik"]]
        putnici = [p for p in putnici if p]
        return {
            "kljuc": d.get("kljuc"),
            "danas": fmt_date(d.get("danas")),
            "putnik": d.get("putnik"),
            "rodjen": fmt_date(d.get("rodjen")),
            "pasos": d.get("pasos"),
            "putnici": putnici,
            "putnici_detalji": putnici_detalji,
            "dodatne": [dict(stavka) for stavka in dodatne],
            "smer": d.get("smer"),
            "tiprezervacije": d.get("tiprezervacije"),
            "subagent": d.get("subagent") or "",
            "timelimit": d["timelimit"].strftime("%d.%m.%Y %H:%M") if d.get("timelimit") else None,
            "adresa": d.get("adresa"),
            "telefon": d.get("telefon"),
            "refno": d.get("refno"),
            "prevozow": d.get("prevozow"),
            "prevozrt": d.get("prevozrt"),
            "osiguranje": d.get("osiguranje"),
            "osiguranje1": d.get("osiguranje1"),
            "soba": d.get("soba"),
            "apartman": d.get("apartman"),
            "napomena": d.get("napomena"),
            "napomena1": d.get("napomena1"),
            "ulazak": d.get("ulazak"),
            "cenaaranz": d.get("cenaaranz"),
            "kolaranz": d.get("kolaranz"),
            "popustar": d.get("popustar"),
            "cenaow": d.get("cenaow"),
            "kolow": d.get("kolow"),
            "cenart": d.get("cenart"),
            "kolrt": d.get("kolrt"),
            "popustpr": d.get("popustpr"),
            "cenadod": d.get("cenadod"),
            "uplacenod": d.get("uplacenod"),
            "procenatar": d.get("procenatar"),
            "mesto": d.get("mesto"),
            "naziv": d.get("naziv"),
            "datumod": fmt_date(d.get("datumod")),
            "datumdo": fmt_date(d.get("datumdo")),
            "destinacija": d.get("destinacija"),
            "subagent": d.get("subagent"),
            "subagent_info": subagent,
            "kurs": kurs,
            "ukupna_vrednost": ukupna,
            **calc,
        }

    @api.get("/ugovori")
    def list_ugovori(request: Request, _: dict = Depends(get_current_user)):
        q = dict(request.query_params)
        search = q.get("search", "").strip()
        sort = q.get("sort", "danas")
        direction = q.get("dir", "desc")
        try:
            page = max(int(q.get("page", "1")), 1)
        except ValueError:
            page = 1
        try:
            page_size = min(max(int(q.get("page_size", "50")), 1), 200)
        except ValueError:
            page_size = 50
        if sort not in UGOVORI_SORT:
            sort = "kljuc"
        if direction not in ("asc", "desc"):
            direction = "asc"

        conds = []
        bind = {}
        if search:
            like = f"%{search}%"
            # search_in ograničava kolone pretrage (npr. "putnik,kljuc" za dashboard)
            cols = UGOVORI_SEARCH_COLS
            search_in = (q.get("search_in") or "").strip()
            if search_in:
                req = [c.strip() for c in search_in.split(",") if c.strip() in UGOVORI_SEARCH_COLS]
                if req:
                    cols = req
            ors = " OR ".join(f"COALESCE({c}::text, '') ILIKE :search" for c in cols)
            conds.append(f"({ors})")
            bind["search"] = like
        # Filter-red tabele: svako polje sa ≥3 karaktera dodaje svoj uslov (AND)
        for fkey, fexpr in UGOVORI_FILTER_COLS.items():
            fval = (q.get(f"f_{fkey}") or "").strip()
            if len(fval) >= 3:
                conds.append(f"{fexpr} ILIKE :f_{fkey}")
                bind[f"f_{fkey}"] = f"%{fval}%"
        where = ("WHERE " + " AND ".join(conds)) if conds else ""

        with engine.connect() as conn:
            total = conn.execute(text(f"SELECT COUNT(*) FROM aranzman {where}"), bind).scalar() or 0
            rows = conn.execute(text(f"""
                SELECT kljuc,
                       to_char(danas, 'DD.MM.YYYY') AS danas_fmt,
                       putnik, mesto, naziv, subagent, apartman, soba,
                       (SELECT COALESCE(json_agg(saputnici.sk), '[]'::json) FROM (
                           SELECT saputnik AS sk FROM aranzman_dopuna ad
                           WHERE ad.aranzman_id = a.id
                             AND COALESCE(TRIM(ad.saputnik), '') <> ''
                           ORDER BY ad.id
                       ) saputnici) AS saputnici_list,
                       to_char(datumod, 'DD.MM.YYYY') AS datumod_fmt,
                       to_char(datumdo, 'DD.MM.YYYY') AS datumdo_fmt,
                       {', '.join(UGOVORI_LIST_COLS)}
                FROM aranzman a {where}
                ORDER BY {sort} {direction} NULLS LAST, a.id {direction}
            """), {**bind, "limit": page_size, "offset": (page - 1) * page_size}).fetchall()

        kurs = get_eur_middle()

        def row_putnici(r) -> list:
            ps = [str(r.putnik or "").strip()]
            ps += [str(s or "").strip() for s in (r.saputnici_list or [])]
            return [p for p in ps if p]

        def row_ukupna(r) -> float | None:
            calc = calc_ugovor_values(dict(r._mapping))
            return round((calc["naplata"] + calc["provizija"]) * kurs, 2) if kurs else None

        return {
            "rows": [{
                "kljuc": r.kljuc,
                "danas": r.danas_fmt,
                "putnik": r.putnik,
                "putnici": row_putnici(r),
                "mesto": r.mesto,
                "naziv": r.naziv,
                "struktura": r.apartman,
                "soba": r.soba,
                "subagent": r.subagent,
                "datumdo": r.datumdo_fmt,
                "ukupna_vrednost": row_ukupna(r),
            } for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    # ── Subagenti (povezani sa aranzman.subagent = subagenti.naziv) ─────────
    SUBAGENTI_SORT = {
        "naziv": "s.naziv", "mesto": "s.mesto",
        "provizija": "s.provizija", "broj_ugovora": "COALESCE(cnt.c, 0)",
    }
    SUBAGENTI_SEARCH_COLS = [
        "s.naziv", "s.adresa", "s.mesto", "s.osoba", "s.tel", "s.tel1",
        "s.tel2", "s.racun", "s.punnaziv", "s.kontakt", "s.fax",
    ]

    @api.get("/subagenti")
    def list_subagenti(request: Request, _: dict = Depends(get_current_user)):
        q = dict(request.query_params)
        search = q.get("search", "").strip()
        sort = q.get("sort", "naziv")
        direction = q.get("dir", "asc")
        try:
            page = max(int(q.get("page", "1")), 1)
        except ValueError:
            page = 1
        try:
            page_size = min(max(int(q.get("page_size", "100")), 1), 200)
        except ValueError:
            page_size = 100
        sort_expr = SUBAGENTI_SORT.get(sort, "s.naziv")
        if direction not in ("asc", "desc"):
            direction = "asc"

        where = ""
        bind = {}
        if search:
            like = f"%{search}%"
            ors = " OR ".join(f"COALESCE({c}, '') ILIKE :search" for c in SUBAGENTI_SEARCH_COLS)
            where = f"WHERE {ors}"
            bind["search"] = like

        with engine.connect() as conn:
            total = conn.execute(text(
                f"SELECT COUNT(*) FROM subagenti s {where}"
            ), bind).scalar() or 0
            rows = conn.execute(text(f"""
                WITH cnt AS (
                    SELECT subagent, COUNT(*) AS c FROM aranzman GROUP BY subagent
                )
                SELECT s.id, s.naziv, s.adresa, s.mesto, s.osoba, s.tel, s.tel1,
                       s.tel2, s.fax, s.racun, s.provizija, s.punnaziv, s.kontakt,
                       COALESCE(cnt.c, 0) AS broj_ugovora
                FROM subagenti s
                LEFT JOIN cnt ON cnt.subagent = s.naziv AND s.naziv <> ''
                {where}
                ORDER BY {sort_expr} {direction} NULLS LAST, s.naziv ASC
                LIMIT :limit OFFSET :offset
            """), {**bind, "limit": page_size, "offset": (page - 1) * page_size}).fetchall()

        return {
            "rows": [dict(r._mapping) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    @api.get("/subagenti/{item_id}")
    def get_subagent(item_id: int, _: dict = Depends(get_current_user)):
        with engine.connect() as conn:
            row = conn.execute(text("SELECT * FROM subagenti WHERE id = :id"),
                               {"id": item_id}).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Subagent nije pronađen")
        return dict(row._mapping)

    @api.post("/subagenti")
    def create_subagent(body: SubagentCreate, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            row = conn.execute(text("""
                INSERT INTO subagenti (naziv, adresa, mesto, osoba, tel, tel1, tel2,
                                       fax, racun, provizija, provizija1, provizija1a,
                                       provizija2, punnaziv, kontakt)
                VALUES (:naziv, :adresa, :mesto, :osoba, :tel, :tel1, :tel2,
                        :fax, :racun, :provizija, :provizija1, :provizija1a,
                        :provizija2, :punnaziv, :kontakt)
                RETURNING id
            """), body.model_dump()).fetchone()
        return {"id": row.id}

    @api.put("/subagenti/{item_id}")
    def update_subagent(item_id: int, body: SubagentUpdate, _: dict = Depends(get_current_user)):
        fields = {k: v for k, v in body.model_dump().items() if v is not None or k in ("naziv",)}
        fields = {k: v for k, v in fields.items() if v is not None}
        if not fields:
            raise HTTPException(status_code=400, detail="Nema podataka za ažuriranje")
        set_clause = ", ".join(f"{k} = :{k}" for k in fields)
        fields["id"] = item_id
        with engine.begin() as conn:
            row = conn.execute(text(
                f"UPDATE subagenti SET {set_clause} WHERE id = :id RETURNING id"
            ), fields).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Subagent nije pronađen")
        return {"id": row.id}

    @api.delete("/subagenti/{item_id}")
    def delete_subagent(item_id: int, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            row = conn.execute(text(
                "DELETE FROM subagenti WHERE id = :id RETURNING id"
            ), {"id": item_id}).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Subagent nije pronađen")
        return {"ok": True}

    def calc_ugovor_d_values(row: dict) -> dict:
        """Obračun 'd' varijanti (dinarske kolone) — za predracun.provizija."""
        def n(k):
            v = row.get(k)
            try:
                return float(v) if v not in (None, "") else 0.0
            except (TypeError, ValueError):
                return 0.0

        cenaaranzd_c = n("kolaranz") * n("cenaaranzd") + n("kolchd") * n("uplatasmestaj")
        cenaprevozd_c = n("cenadow") * n("kolow") + n("cenadrt") * n("kolrt")
        popustsmestajd = n("popustar") * cenaaranzd_c / 100
        popustprevozd = n("popustpr") * cenaprevozd_c / 100
        provizijaard = (cenaaranzd_c - popustsmestajd) * n("procenatar") / 100
        provizijaprd = 0.0 if n("cenadrt") == 0 else n("procenatpr") * n("koldrt")
        provizijapr1d = 0.0 if n("cenadow") == 0 else n("procenatpr") * n("koldow")
        provizijavizad = 0.0
        provizijad = provizijaard + provizijaprd + provizijapr1d + provizijavizad
        naplatad = (cenaaranzd_c + cenaprevozd_c
                    - popustsmestajd - popustprevozd
                    - provizijaard - provizijaprd - provizijapr1d - provizijavizad
                    + n("koldod") + n("osiguranje"))
        return {
            "provizijaard": round(provizijaard, 2),
            "provizijapr1d": round(provizijapr1d, 2),
            "provizija_d": round(provizijaard + provizijapr1d, 2),
            "naplatad": round(naplatad, 2),
            "saldo_d": round(naplatad - n("uplacenod"), 2),
        }

    def napravi_saputnik(conn, aranzman_id: int) -> str:
        redovi = conn.execute(text(
            "SELECT saputnik FROM aranzman_dopuna "
            "WHERE aranzman_id = :i AND COALESCE(TRIM(saputnik), '') <> '' "
            "ORDER BY id"
        ), {"i": aranzman_id}).fetchall()
        return ", ".join((r.saputnik or "").strip() for r in redovi)

    def sledeci_broj_predracuna(conn, ugovor: str) -> str:
        """Prvi predracun = broj ugovora (npr. 34094/26); dalji: 34094-1/26, 34094-2/26..."""
        count = conn.execute(text(
            "SELECT COUNT(*) FROM predracun WHERE ugovor = :u"
        ), {"u": ugovor}).scalar() or 0
        if count == 0:
            return ugovor
        if "/" in ugovor:
            base, god = ugovor.rsplit("/", 1)
            return f"{base}-{count}/{god}"
        return f"{ugovor}-{count}"

    @api.get("/predracuni")
    def list_predracuni(request: Request, _: dict = Depends(get_current_user)):
        q = dict(request.query_params)
        search = q.get("search", "").strip()
        sort = q.get("sort", "id")
        direction = q.get("dir", "desc")
        try:
            page = max(int(q.get("page", "1")), 1)
        except ValueError:
            page = 1
        try:
            page_size = min(max(int(q.get("page_size", "100")), 1), 200)
        except ValueError:
            page_size = 100
        PRED_SORT = {
            "broj_predracuna": "broj_predracuna", "datum": "datum",
            "nosilac": "nosilac", "ugovor": "ugovor", "zaduzenje": "zaduzenje",
        }
        sort_col = PRED_SORT.get(sort, "id")
        if direction not in ("asc", "desc"):
            direction = "desc"
        where = ""
        bind = {}
        if search:
            like = f"%{search}%"
            cols = ["broj_predracuna", "ugovor", "nosilac", "saputnik",
                    "destinacija", "subagent", "nacin", "racun", "napomena"]
            ors = " OR ".join(f"COALESCE({c}, '') ILIKE :search" for c in cols)
            where = f"WHERE {ors}"
            bind["search"] = like

        with engine.connect() as conn:
            total = conn.execute(text(
                f"SELECT COUNT(*) FROM predracun {where}"), bind).scalar() or 0
            rows = conn.execute(text(f"""
                SELECT id, broj_predracuna, ugovor,
                       to_char(datum, 'DD.MM.YYYY') AS datum_fmt,
                       nosilac, saputnik, destinacija, period, racun, nacin,
                       napomena, provizija, zaduzenje, subagent, adresa, mesto,
                       organizator, poslovnica
                FROM predracun {where}
                ORDER BY {sort_col} {direction} NULLS LAST, id DESC
                LIMIT :limit OFFSET :offset
            """), {**bind, "limit": page_size, "offset": (page - 1) * page_size}).fetchall()

        return {
            "rows": [dict(r._mapping) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    @api.get("/predracuni/pripremi/{ugovor:path}")
    def predracun_pripremi(ugovor: str, _: dict = Depends(get_current_user)):
        ugovor = ugovor.strip().strip("/")
        with engine.connect() as conn:
            row = conn.execute(text("""
                SELECT a.*, s.naziv AS subagent_naziv, s.adresa AS subagent_adresa,
                       s.mesto AS subagent_mesto
                FROM aranzman a
                LEFT JOIN subagenti s ON s.naziv = a.subagent AND s.naziv <> ''
                WHERE a.kljuc = :kljuc
            """), {"kljuc": ugovor}).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Ugovor nije pronađen")
            d = dict(row._mapping)
            broj = sledeci_broj_predracuna(conn, ugovor)
            saputnici_str = napravi_saputnik(conn, row.id)
            agencija_row = conn.execute(text(
                "SELECT tekuci_racun1, banka1, tekuci_racun2, banka2, "
                "tekuci_racun3, banka3, tekuci_racun4, banka4 FROM agencija WHERE id = 1"
            )).fetchone()
            racuni = []
            if agencija_row:
                a = dict(agencija_row._mapping)
                for i in range(1, 5):
                    val = a.get(f"tekuci_racun{i}")
                    if val:
                        racuni.append({
                            "label": f"Tekući račun {i}",
                            "racun": val,
                            "banka": a.get(f"banka{i}") or "",
                        })
        kurs = get_eur_middle()
        calc = calc_ugovor_values(d)
        calc_d = calc_ugovor_d_values(d)
        zaduzenje = round((calc["naplata"] + calc["provizija"]) * kurs, 2) if kurs else None
        fmt_date = lambda v: v.strftime("%d.%m.%Y") if v else None
        period = None
        if d.get("datumod") or d.get("datumdo"):
            period = f"{fmt_date(d.get('datumod')) or ''} - {fmt_date(d.get('datumdo')) or ''}"
        import datetime
        return {
            "broj_predracuna": broj,
            "datum": datetime.date.today().strftime("%d.%m.%Y"),
            "nosilac": d.get("putnik"),
            "saputnik": saputnici_str,
            "destinacija": d.get("destinacija"),
            "period": period,
            "provizija": calc_d["provizija_d"],
            "zaduzenje": zaduzenje,
            "kurs": kurs,
            "subagent": d.get("subagent"),
            "adresa": d.get("subagent_adresa") or "",
            "mesto": d.get("subagent_mesto") or "",
            "ugovor": d.get("kljuc"),
            "organizator": d.get("organizator"),
            "poslovnica": d.get("poslovnica"),
            "racuni": racuni,
            "nacini": ["Avans 100%", "Periodično"],
        }

    @api.post("/predracuni")
    def create_predracun(body: PredracunCreate, _: dict = Depends(get_current_user)):
        ugovor = (body.ugovor or "").strip().strip("/")
        with engine.begin() as conn:
            arow = conn.execute(text(
                "SELECT * FROM aranzman WHERE kljuc = :kljuc"), {"kljuc": ugovor}).fetchone()
            if not arow:
                raise HTTPException(status_code=404, detail="Ugovor nije pronađen")
            d = dict(arow._mapping)
            srow = conn.execute(text(
                "SELECT adresa, mesto FROM subagenti WHERE naziv = :naziv AND naziv <> ''"
            ), {"naziv": d.get("subagent") or ""}).fetchone()
            broj = sledeci_broj_predracuna(conn, ugovor)
            kurs = get_eur_middle()
            calc = calc_ugovor_values(d)
            calc_d = calc_ugovor_d_values(d)
            zaduzenje = round((calc["naplata"] + calc["provizija"]) * kurs, 2) if kurs else 0
            fmt_date = lambda v: v.strftime("%d.%m.%Y") if v else None
            period = None
            if d.get("datumod") or d.get("datumdo"):
                period = f"{fmt_date(d.get('datumod')) or ''} - {fmt_date(d.get('datumdo')) or ''}"
            prow = conn.execute(text("""
                INSERT INTO predracun (broj_predracuna, ugovor, datum, nosilac, saputnik,
                    destinacija, period, racun, nacin, napomena, provizija, zaduzenje,
                    subagent, adresa, mesto, organizator, poslovnica)
                VALUES (:broj, :ugovor, CURRENT_DATE, :nosilac, :saputnik,
                    :destinacija, :period, :racun, :nacin, :napomena, :provizija, :zaduzenje,
                    :subagent, :adresa, :mesto, :organizator, :poslovnica)
                RETURNING id
            """), {
                "broj": broj, "ugovor": ugovor,
                "nosilac": d.get("putnik") or "",
                "saputnik": napravi_saputnik(conn, arow.id),
                "destinacija": d.get("destinacija") or "",
                "period": period or "",
                "racun": body.racun or "", "nacin": body.nacin or "",
                "napomena": body.napomena or "",
                "provizija": calc_d["provizija_d"],
                "zaduzenje": zaduzenje,
                "subagent": d.get("subagent") or "",
                "adresa": (srow.adresa if srow else "") or "",
                "mesto": (srow.mesto if srow else "") or "",
                "organizator": d.get("organizator") or "",
                "poslovnica": d.get("poslovnica") or "",
            }).fetchone()
        return {"id": prow.id, "broj_predracuna": broj}

    @api.get("/predracuni/{item_id}")
    def get_predracun(item_id: int, _: dict = Depends(get_current_user)):
        with engine.connect() as conn:
            row = conn.execute(text("""
                SELECT id, broj_predracuna, ugovor,
                       to_char(datum, 'DD.MM.YYYY') AS datum_fmt,
                       nosilac, saputnik, destinacija, period, racun, nacin,
                       napomena, provizija, zaduzenje, subagent, adresa, mesto,
                       organizator, poslovnica
                FROM predracun WHERE id = :id
            """), {"id": item_id}).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Predračun nije pronađen")
        return dict(row._mapping)

    @api.get("/predracuni/{item_id}/pdf")
    def download_predracun_pdf(item_id: int, _: dict = Depends(get_current_user)):
        with engine.connect() as conn:
            row = conn.execute(text("""
                SELECT id, broj_predracuna, ugovor,
                       to_char(datum, 'DD.MM.YYYY') AS datum_fmt,
                       nosilac, saputnik, destinacija, period, racun, nacin,
                       napomena, provizija, zaduzenje, subagent, adresa, mesto,
                       organizator, poslovnica
                FROM predracun WHERE id = :id
            """), {"id": item_id}).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Predračun nije pronađen")
            pred = dict(row._mapping)
            agrow = conn.execute(text("SELECT * FROM agencija WHERE id = 1")).fetchone()
            # podaci aranžmana za opis usluge (mesto, datumi putovanja)
            arow = conn.execute(text("""
                SELECT mesto,
                       to_char(datumod, 'DD.MM.YYYY') AS datumod_fmt,
                       to_char(datumdo, 'DD.MM.YYYY') AS datumdo_fmt
                FROM aranzman WHERE kljuc = :ugovor
            """), {"ugovor": pred.get("ugovor") or ""}).fetchone()
        a = dict(agrow._mapping) if agrow else {}
        pred["a_mesto"] = arow.mesto if arow else ""
        pred["a_datumod"] = arow.datumod_fmt if arow else ""
        pred["a_datumdo"] = arow.datumdo_fmt if arow else ""
        racun_val = (pred.get("racun") or "").strip()
        banka_val = ""
        if racun_val:
            for i in range(1, 5):
                if (a.get(f"tekuci_racun{i}") or "").strip() == racun_val:
                    banka_val = a.get(f"banka{i}") or ""
                    break
        # Podaci izdavaoca predracuna iz "Osnovni podaci" (tabela agencija)
        izdavalac = {
            "naziv": a.get("naziv") or a.get("poslovno_ime") or "",
            "poslovno_ime": a.get("poslovno_ime") or "",
            "ulica": a.get("ulica") or "",
            "broj": a.get("broj") or "",
            "post_broj": a.get("post_broj") or "",
            "mesto": a.get("mesto") or "",
            "drzava": a.get("drzava") or "",
            "pib": a.get("pib") or "",
            "mb": a.get("mb") or "",
            "telefon1": a.get("telefon1") or "",
            "email1": a.get("email1") or "",
            "racun": racun_val,
            "banka": banka_val,
        }
        pdf_bytes = generate_predracun_pdf(pred, izdavalac)
        safe_broj = re.sub(r"[^0-9A-Za-z-]", "-", str(pred.get("broj_predracuna") or item_id))
        filename = f"Predracun_{safe_broj}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"; '
                                       f"filename*=UTF-8''{quote(filename)}",
            },
        )

    @api.put("/predracuni/{item_id}")
    def update_predracun(item_id: int, body: PredracunUpdate, _: dict = Depends(get_current_user)):
        fields = {k: v for k, v in body.model_dump().items() if v is not None}
        if not fields:
            raise HTTPException(status_code=400, detail="Nema podataka za ažuriranje")
        set_clause = ", ".join(f"{k} = :{k}" for k in fields)
        fields["id"] = item_id
        with engine.begin() as conn:
            row = conn.execute(text(
                f"UPDATE predracun SET {set_clause} WHERE id = :id RETURNING id"
            ), fields).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Predračun nije pronađen")
        return {"id": row.id}

    @api.delete("/predracuni/{item_id}")
    def delete_predracun(item_id: int, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            row = conn.execute(text(
                "DELETE FROM predracun WHERE id = :id RETURNING id"
            ), {"id": item_id}).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Predračun nije pronađen")
        return {"ok": True}

    # ─── Izvodi (bankovni izvodi — XML) ─────────────────────────────────────
    @api.post("/izvodi/upload")
    async def upload_izvod(
        file: UploadFile = File(...),
        current_user: dict = Depends(get_current_user),
    ):
        raw = await file.read()
        try:
            file.file.close()
        except Exception:
            pass
        if not raw:
            raise HTTPException(status_code=400, detail="Prazan fajl")

        try:
            statements = parse_izvodi_xml(raw)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Neispravan XML fajl: {e}")

        if not statements:
            raise HTTPException(status_code=400, detail="XML ne sadrži izvode (stmtrs)")

        korisnik = (current_user.get("username") or current_user.get("email") or "").strip()
        inserted, skipped = [], []
        with engine.begin() as conn:
            for st in statements:
                dup = conn.execute(text(
                    "SELECT 1 FROM izvodi WHERE racun = :r AND broj_izvoda = :b"
                ), {"r": st["racun"], "b": st["broj_izvoda"]}).fetchone()
                if dup:
                    skipped.append(f"{st['broj_izvoda']} ({st['racun']})")
                    continue
                row = conn.execute(text("""
                    INSERT INTO izvodi (racun, broj_izvoda, datum_izvoda, valuta,
                                        saldo, raspolozivo, rezervisano,
                                        broj_transakcija, podaci, korisnik)
                    VALUES (:racun, :broj, :datum, :valuta,
                            :saldo, :raspolozivo, :rezervisano,
                            :brt, CAST(:podaci AS JSONB), :korisnik)
                    RETURNING id
                """), {
                    "racun": st["racun"], "broj": st["broj_izvoda"],
                    "datum": st["datum_izvoda"], "valuta": st["valuta"],
                    "saldo": st["saldo"], "raspolozivo": st["raspolozivo"],
                    "rezervisano": st["rezervisano"], "brt": st["broj_transakcija"],
                    "podaci": json.dumps(st["podaci"], ensure_ascii=False),
                    "korisnik": korisnik,
                }).fetchone()
                izvod_id = row.id
                conn.execute(text("""
                    INSERT INTO izvodi_pregled (izvod_id, racun, broj_izvoda,
                                                datum_izvoda, datum_unosa, korisnik)
                    VALUES (:izvod_id, :racun, :broj, :datum, NOW(), :korisnik)
                """), {
                    "izvod_id": izvod_id, "racun": st["racun"],
                    "broj": st["broj_izvoda"], "datum": st["datum_izvoda"],
                    "korisnik": korisnik,
                })
                inserted.append({
                    "id": izvod_id, "racun": st["racun"],
                    "broj_izvoda": st["broj_izvoda"],
                    "datum_izvoda": st["datum_izvoda"].isoformat() if st["datum_izvoda"] else None,
                    "broj_transakcija": st["broj_transakcija"],
                })

        return {
            "ok": True,
            "uneseno": len(inserted),
            "preskoceno": skipped,
            "izvodi": inserted,
        }

    @api.get("/izvodi")
    def list_izvodi(
        q: Optional[str] = None,
        _: dict = Depends(get_current_user),
    ):
        cond = ""
        params: dict = {}
        if q and q.strip():
            cond = "WHERE (p.racun ILIKE :q OR p.broj_izvoda ILIKE :q OR p.korisnik ILIKE :q \
                    OR TO_CHAR(p.datum_izvoda, 'DD.MM.YYYY') ILIKE :q \
                    OR TO_CHAR(p.datum_unosa, 'DD.MM.YYYY') ILIKE :q)"
            params["q"] = f"%{q.strip()}%"
        with engine.connect() as conn:
            rows = conn.execute(text(f"""
                SELECT p.id, p.izvod_id, p.racun, p.broj_izvoda,
                       p.datum_izvoda, p.datum_unosa, p.korisnik,
                       i.broj_transakcija, i.valuta, i.saldo
                FROM izvodi_pregled p
                LEFT JOIN izvodi i ON i.id = p.izvod_id
                {cond}
                ORDER BY p.datum_unosa DESC, p.id DESC
                LIMIT 1000
            """), params).fetchall()
        return [{
            "id": r.id,
            "izvod_id": r.izvod_id,
            "racun": r.racun,
            "broj_izvoda": r.broj_izvoda,
            "datum_izvoda": r.datum_izvoda.isoformat() if r.datum_izvoda else None,
            "datum_unosa": r.datum_unosa.isoformat() if r.datum_unosa else None,
            "korisnik": r.korisnik,
            "broj_transakcija": r.broj_transakcija,
            "valuta": r.valuta,
            "saldo": r.saldo,
        } for r in rows]

    @api.delete("/izvodi/{item_id}")
    def delete_izvod(item_id: int, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            row = conn.execute(text(
                "DELETE FROM izvodi WHERE id = :id RETURNING id"
            ), {"id": item_id}).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Izvod nije pronađen")
        return {"ok": True}

    @api.get("/izvodi/banke")
    def izvodi_banke(_: dict = Depends(get_current_user)):
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT p.racun, COUNT(*) AS izvoda
                FROM izvodi_pregled p
                GROUP BY p.racun
                ORDER BY p.racun
            """)).fetchall()
        return [{"racun": r.racun, "izvoda": r.izvoda} for r in rows]

    @api.get("/izvodi/stavke")
    def izvodi_stavke(
        racun: str,
        broj_izvoda: Optional[str] = None,
        datum_unosa: Optional[str] = None,
        _: dict = Depends(get_current_user),
    ):
        if not racun.strip():
            raise HTTPException(status_code=400, detail="Izaberi banku (račun)")
        if not (broj_izvoda and broj_izvoda.strip()) and not (datum_unosa and datum_unosa.strip()):
            raise HTTPException(status_code=400, detail="Izaberi broj izvoda ili datum unosa")

        or_conds, params = [], {"racun": racun.strip()}
        if broj_izvoda and broj_izvoda.strip():
            or_conds.append("i.broj_izvoda = :broj")
            params["broj"] = broj_izvoda.strip()
        if datum_unosa and datum_unosa.strip():
            or_conds.append("i.datum_unosa::date = :dun")
            params["dun"] = datum_unosa.strip()

        with engine.connect() as conn:
            stmts = conn.execute(text(f"""
                SELECT i.id, i.racun, i.broj_izvoda, i.datum_izvoda, i.podaci
                FROM izvodi i
                WHERE i.racun = :racun AND ({ " OR ".join(or_conds) })
                ORDER BY i.datum_unosa DESC
            """), params).fetchall()
            if not stmts:
                return {"izvodi": [], "stavke": []}

            stavke = []
            for s in stmts:
                for trn in (s.podaci or {}).get("transakcije", []):
                    if (trn.get("smer") or "") == "debit":
                        continue  # prikaz samo uplata (credit)
                    poziv = (trn.get("poziv_na_broj") or "").strip()
                    stavke.append({
                        "fitid": trn.get("fitid") or "",
                        "racun": s.racun,
                        "broj_izvoda": s.broj_izvoda,
                        "datum_izvoda": s.datum_izvoda.isoformat() if s.datum_izvoda else None,
                        "poziv_na_broj": poziv,
                        "naziv_primaoca": trn.get("naziv_primaoca") or "",
                        "mesto_primaoca": trn.get("mesto_primaoca") or "",
                        "svrha_kod": trn.get("svrha_kod") or "",
                        "svrha": trn.get("svrha") or "",
                        "iznos": trn.get("iznos") or 0.0,
                        "datum_knjizenja": trn.get("datum_knjizenja"),
                        "smer": trn.get("smer") or "",
                    })

            # ── Veza: poziv_na_broj → aranzman.kljuc (npr. 32258 → 32258/26) ──
            pozivi = sorted({s["poziv_na_broj"] for s in stavke if s["poziv_na_broj"]})
            godine = sorted({str(s.datum_izvoda or "")[2:4]} - {""})
            veza_map: dict = {}
            if pozivi:
                cands, cand_map = set(), {}
                for poz in pozivi:
                    if "/" in poz:
                        cs = [poz]
                    else:
                        cs = [f"{poz}/26"] + [f"{poz}/{g}" for g in godine if g]
                    cand_map[poz] = cs
                    cands.update(cs)
                urows = conn.execute(text(
                    "SELECT kljuc FROM aranzman WHERE kljuc = ANY(:c)"
                ), {"c": sorted(cands)}).fetchall()
                existing = {u.kljuc for u in urows}
                for poz, cs in cand_map.items():
                    hit = next((c for c in cs if c in existing), None)
                    if hit:
                        veza_map[poz] = hit

            # ── Predračun: ugovor (Veza) → predracun.broj_predracuna ──────────
            pred_map: dict = {}
            kljucevi = sorted(set(veza_map.values()))
            if kljucevi:
                prows = conn.execute(text("""
                    SELECT ugovor, broj_predracuna FROM predracun
                    WHERE ugovor = ANY(:u) ORDER BY id
                """), {"u": kljucevi}).fetchall()
                for pr in prows:
                    pred_map.setdefault(pr.ugovor, [])
                    pred_map[pr.ugovor].append(pr.broj_predracuna)

            for s in stavke:
                v = veza_map.get(s["poziv_na_broj"]) if s["poziv_na_broj"] else None
                s["veza"] = v
                s["predracun"] = ", ".join(pred_map[v]) if v and v in pred_map else None

        return {
            "izvodi": [{
                "racun": s.racun,
                "broj_izvoda": s.broj_izvoda,
                "datum_izvoda": s.datum_izvoda.isoformat() if s.datum_izvoda else None,
            } for s in stmts],
            "stavke": stavke,
        }

    # ─── Agencija ────────────────────────────────────────────────────────────
    @api.get("/agencija")
    def get_agencija(_: dict = Depends(get_current_user)):
        with engine.connect() as conn:
            row = conn.execute(text("SELECT * FROM agencija WHERE id = 1")).fetchone()
        if not row:
            return {}
        return dict(row._mapping)

    @api.put("/agencija")
    async def update_agencija(request: Request, _: dict = Depends(get_current_user)):
        data = await request.json()
        allowed = [
            "naziv", "poslovno_ime", "email1", "email2", "telefon1", "telefon2",
            "ulica", "broj", "post_broj", "mesto", "drzava",
            "opstina_rgz", "opstina_naziv", "mesto_rgz", "mesto_naziv",
            "ulica_rgz", "ulica_naziv", "api_kljuc_efakture", "api_kljuc_cis",
            "pib", "mb", "jbkjs", "jmbg",
            "tekuci_racun1", "banka1", "tekuci_racun2", "banka2",
            "tekuci_racun3", "banka3", "tekuci_racun4", "banka4",
        ]
        fields = {k: v for k, v in data.items() if k in allowed}
        if not fields:
            return {"ok": True}
        set_clause = ", ".join(f"{k} = :{k}" for k in fields)
        fields["id"] = 1
        with engine.begin() as conn:
            conn.execute(text(f"UPDATE agencija SET {set_clause} WHERE id = :id"), fields)
        return {"ok": True}

    # ─── Boje grafik ─────────────────────────────────────────────────────────
    @api.get("/boje-grafik")
    def get_boje_grafik(_: dict = Depends(get_current_user)):
        with engine.connect() as conn:
            row = conn.execute(text("SELECT * FROM boje_grafik WHERE id = 1")).fetchone()
        if not row:
            return {
                "isplacen": "zelena",
                "predrezervacija_aktivna": "zelena",
                "predrezervacija_istekla": "zelena",
                "blok": "zelena",
                "saldo_veci": "zelena",
                "predrezervacija_subagent": "zelena",
            }
        return {
            "isplacen": row.isplacen,
            "predrezervacija_aktivna": row.predrezervacija_aktivna,
            "predrezervacija_istekla": row.predrezervacija_istekla,
            "blok": row.blok,
            "saldo_veci": row.saldo_veci,
            "predrezervacija_subagent": row.predrezervacija_subagent,
        }

    @api.put("/boje-grafik")
    def update_boje_grafik(body: BojeGrafik, _: dict = Depends(get_current_user)):
        data = body.model_dump()
        set_clause = ", ".join(f"{k} = :{k}" for k in data)
        data["id"] = 1
        with engine.begin() as conn:
            conn.execute(text(f"UPDATE boje_grafik SET {set_clause} WHERE id = :id"), data)
        return data

    # ─── App setup ───────────────────────────────────────────────────────────
    app = FastAPI()
    app.include_router(api, prefix="/api")

    if os.path.isdir(static_dir):
        assets_dir = os.path.join(static_dir, "assets")
        if os.path.isdir(assets_dir):
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        @app.get("/{path:path}")
        async def spa_fallback(request: Request, path: str):
            file_path = os.path.join(static_dir, path)
            if path and os.path.isfile(file_path):
                return FileResponse(file_path)
            return FileResponse(
                os.path.join(static_dir, "index.html"),
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                },
            )

    return app
