import os
import io
import re
import json
import math
import base64
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from datetime import date as SubDate
from decimal import Decimal
from typing import Optional, List
from urllib.parse import quote

from fastapi import FastAPI, APIRouter, Request, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
import bcrypt
from jose import JWTError, jwt

from predracun_pdf import generate_predracun_pdf
import db_config
from kurs_service import ensure_kurs_table, get_eur_rate
from grafik_boje import kategorija_grafika
from cenovnici_api import init_cenovnici, register_cenovnici
from koeficijenti_api import init_koeficijenti, register_koeficijenti, osiguraj_auto_red
from poslovnice_api import init_poslovnice, register_poslovnice
from prevoz_limit_api import init_prevoz_limit, register_prevoz_limit
from dodatne_usluge_api import init_dodatne_usluge, register_dodatne_usluge
from zaduzenje_api import init_zaduzenje, register_zaduzenje
from zabrana_api import init_zabrana, register_zabrana
from saglasnost_pdf import init_saglasnost
from dobavljaci_api import init_dobavljaci, register_dobavljaci
from banke_api import init_banke, register_banke
from notifikacije_api import init_notifikacije, register_notifikacije
from profil_api import init_profil, register_profil
from dashboard_api import register_dashboard
from obracun_po_aranzmanu import init_obracun_po_aranzmanu, obracun_iz_rezervacije, varijante_cene
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
NACINI_UPLATE = ("Gotovina", "Kartica", "Ček", "Virman", "IPC", "Vaučer", "Ostalo")
TIPOVI_KARTICA_SEED = ("Visa", "Mastercard", "Dina", "Maestro", "American Express", "Diners Club")
SVRHE_UPLATE = ("Total aranžman", "Deo aranžmana", "Prevoz", "Osiguranje", "Odloženo - Ček", "Povraćaj")

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
# Doplate za mesta za sedenje (EUR) — kolone parametri_obracuna
MESTA_SEDENJA_POLJA = ("donja_platforma_eur", "gornja_platforma_eur", "dole_za_stolom_eur",
                       "dole_zadnji_red_eur", "gore_izlog_eur", "gore_sto_eur", "sarage_eur")
# Prefiksi izračunatih dodatnih usluga (frontend ih računa i šalje pri snimanju; backend ih zamenjuje)
IZRACUNATE_PREFIKS = ("TRANSFER - ", "PLAĆENO MESTO - ")


def get_engine():
    return db_config.get_engine()


def _logo_data_url_iz_baze():
    """Logo agencije iz tabele dokumenti (tip='logo') kao data URL; None ako nema."""
    with get_engine().connect() as conn:
        row = conn.execute(text(
            "SELECT slika, slika_mime FROM dokumenti WHERE tip = 'logo'"
        )).fetchone()
    if not row or not row.slika:
        return None
    return f"data:{row.slika_mime or 'image/png'};base64,{row.slika}"


def _banke_izdavaoca(a):
    """Lista 'tekući račun (banka)' za sve popunjene račune iz Osnovnih podešavanja."""
    out = []
    for i in range(1, 5):
        racun = (a.get(f"tekuci_racun{i}") or "").strip()
        if racun:
            banka = (a.get(f"banka{i}") or "").strip()
            out.append(f"{racun} ({banka})" if banka else racun)
    return out


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
        conn.execute(text(
            "ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS poslovnica_id INTEGER NULL"
        ))

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
        conn.execute(text(
            "ALTER TABLE smestaj ADD COLUMN IF NOT EXISTS granica_chd DOUBLE PRECISION NOT NULL DEFAULT 6.99"
        ))
        conn.execute(text(
            "ALTER TABLE smestaj ADD COLUMN IF NOT EXISTS prima_decu BOOLEAN NOT NULL DEFAULT TRUE"
        ))
        conn.execute(text(
            "ALTER TABLE smestaj ADD COLUMN IF NOT EXISTS ne_prima_ispod_godina INTEGER NULL"
        ))
        conn.execute(text(
            "ALTER TABLE smestaj ADD COLUMN IF NOT EXISTS popular BOOLEAN NOT NULL DEFAULT FALSE"
        ))
        conn.execute(text(
            "ALTER TABLE smestaj ADD COLUMN IF NOT EXISTS napomena TEXT NULL"
        ))
        conn.execute(text(
            "ALTER TABLE smestaj ADD COLUMN IF NOT EXISTS provizija INTEGER NOT NULL DEFAULT 10"
        ))
        conn.execute(text(
            "ALTER TABLE IF EXISTS polazak ADD COLUMN IF NOT EXISTS cena_transfera DOUBLE PRECISION NULL"
        ))
        conn.execute(text(
            "ALTER TABLE IF EXISTS polazak ADD COLUMN IF NOT EXISTS mesto_id INTEGER NULL"
        ))
        conn.execute(text(
            "ALTER TABLE IF EXISTS polazak ADD COLUMN IF NOT EXISTS grupa_id INTEGER NULL"
        ))
        conn.execute(text(
            "ALTER TABLE IF EXISTS polazak ADD COLUMN IF NOT EXISTS destinacija_id INTEGER NULL"
        ))

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
                fiskal_zahtev_link VARCHAR(500),
                fiskal_odgovor_link VARCHAR(500),
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
        conn.execute(text(
            "ALTER TABLE IF EXISTS agencija ADD COLUMN IF NOT EXISTS lice_reklamacije TEXT NULL"
        ))
        # Ensure at least one agencija row exists
        conn.execute(text("""
            INSERT INTO agencija (id) VALUES (1)
            ON CONFLICT (id) DO NOTHING
        """))
        conn.execute(text(
            "UPDATE agencija SET lice_reklamacije = :t WHERE id = 1 AND lice_reklamacije IS NULL"
        ), {"t": "Lice zaduženo za reklamacije je Radomir Kratovac, adresa Svetozara Markovića 4, Beograd, email astratravel@astratravel.rs, telefon 011/2622104."})
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
        # Knjiga evidencije prodatih aranžmana (KEPTP) — numeracija odvojena od aranzman.keptp;
        # jedan broj po ugovoru, dodeljuje ga korisnik kroz UI (ne svaki ugovor)
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS keptp (
                id SERIAL PRIMARY KEY,
                datum DATE NOT NULL,
                broj_keptp INTEGER NOT NULL UNIQUE,
                broj_ugovora VARCHAR(50) NOT NULL UNIQUE
            )
        """))
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
        # Tab Prevoz: mesto za sedenje, plaćeno, želja i datumi/destinacije po smeru
        # (OW / polazak+povratak RT). Destinacije se čuvaju kao NAZIV (kao aranzman.destinacija).
        # aranzman: polja nosioca + napomena prevoz (uz izbor destinacije);
        # aranzman_dopuna: ista polja po saputniku.
        for tabela in ("aranzman", "aranzman_dopuna"):
            for kolona, tip in (
                ("mesto_sedenja", "VARCHAR(50)"),
                ("placeno_prevoz", "SMALLINT"),
                ("zelja_prevoz", "SMALLINT"),
                ("datum_ow", "DATE"),
                ("destinacija_ow", "VARCHAR(200)"),
                ("datum_polaska", "DATE"),
                ("destinacija_polaska", "VARCHAR(200)"),
                ("datum_povratka", "DATE"),
                ("destinacija_povratka", "VARCHAR(200)"),
                ("destinacija_ow_id", "INTEGER"),
                ("destinacija_polaska_id", "INTEGER"),
                ("destinacija_povratka_id", "INTEGER"),
            ):
                conn.execute(text(f"ALTER TABLE {tabela} ADD COLUMN IF NOT EXISTS {kolona} {tip}"))
        conn.execute(text(
            "ALTER TABLE aranzman ADD COLUMN IF NOT EXISTS napomena_prevoz VARCHAR(500)"
        ))
        # Izbor destinacije (tab Prevoz) = destinacija_prevoz.id; ID bez FK (konvencija projekta)
        conn.execute(text(
            "ALTER TABLE aranzman ADD COLUMN IF NOT EXISTS destinacija_prevoz_id INTEGER"
        ))
        # Sopstveni prevoz (SP) po putniku — 1 = SP (bez autobusa); nosilac u aranzman, saputnici u aranzman_dopuna
        conn.execute(text("ALTER TABLE aranzman ADD COLUMN IF NOT EXISTS prevozsp SMALLINT DEFAULT NULL"))
        conn.execute(text("ALTER TABLE aranzman_dopuna ADD COLUMN IF NOT EXISTS prevozsp SMALLINT DEFAULT NULL"))
        # Uzrast nosioca (ADL / CHD / INF); saputnici imaju aranzman_dopuna.uzrast
        conn.execute(text(
            "ALTER TABLE aranzman ADD COLUMN IF NOT EXISTS uzrast VARCHAR(20) DEFAULT ''"
        ))
        # Mesto izlaska (tab Prevoz): podrazumevano = mesto ulaska; nosilac u aranzman,
        # saputnici u aranzman_dopuna.
        for tabela in ("aranzman", "aranzman_dopuna"):
            conn.execute(text(
                f"ALTER TABLE {tabela} ADD COLUMN IF NOT EXISTS mesto_izlaska VARCHAR(200)"
            ))
        # Grad (uz adresu): nosilac u aranzman, saputnici u aranzman_dopuna
        for tabela in ("aranzman", "aranzman_dopuna"):
            conn.execute(text(
                f"ALTER TABLE {tabela} ADD COLUMN IF NOT EXISTS grad VARCHAR(100)"
            ))
        # Dodatno sedište (saputnik): true = red je dodatno sedište (ime DODATNO SEDIŠTE, ADL)
        conn.execute(text(
            "ALTER TABLE aranzman_dopuna ADD COLUMN IF NOT EXISTS dodatno_sediste BOOLEAN NOT NULL DEFAULT FALSE"
        ))
        # Uplata karticom: podaci sa popupa (Način plaćanja = Kartica).
        for kolona, tip in (
            ("broj_potvrde", "VARCHAR(100)"),
            ("tip_kartice", "VARCHAR(50)"),
            ("broj_kartice", "TEXT"),
            ("broj_odobrenja", "VARCHAR(100)"),
        ):
            conn.execute(text(f"ALTER TABLE uplate ADD COLUMN IF NOT EXISTS {kolona} {tip}"))
        # broj kartice bez ograničenja dužine (ranije VARCHAR(30))
        conn.execute(text("ALTER TABLE uplate ALTER COLUMN broj_kartice TYPE TEXT"))
        # Povraćaj (prebacivanje uplate sa ugovora na ugovor): trag prebacivanja
        conn.execute(text("ALTER TABLE uplate ADD COLUMN IF NOT EXISTS prebaceno_sa VARCHAR(20)"))
        conn.execute(text("ALTER TABLE uplate ADD COLUMN IF NOT EXISTS datum_prebacivanja TIMESTAMP"))
        # Fiskalizacija uplate: jednom uspešno poslato, ne šalje se ponovo
        conn.execute(text("ALTER TABLE uplate ADD COLUMN IF NOT EXISTS fiskal_poslato BOOLEAN NOT NULL DEFAULT FALSE"))
        conn.execute(text("ALTER TABLE uplate ADD COLUMN IF NOT EXISTS fiskal_odgovor TEXT"))
        conn.execute(text("ALTER TABLE uplate ADD COLUMN IF NOT EXISTS fiskal_invoice TEXT"))
        conn.execute(text("ALTER TABLE uplate ADD COLUMN IF NOT EXISTS fiskal_link TEXT"))
        conn.execute(text("ALTER TABLE agencija ADD COLUMN IF NOT EXISTS fiskal_zahtev_link VARCHAR(500)"))
        conn.execute(text("ALTER TABLE agencija ADD COLUMN IF NOT EXISTS fiskal_odgovor_link VARCHAR(500)"))
        # Evidencija prebacivanja uplata (Povraćaj): jedan red po prebacivanju
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS prebacivanje (
                id SERIAL PRIMARY KEY,
                datum TIMESTAMP NOT NULL,
                uplata_kljuc INTEGER NOT NULL,
                iznos DOUBLE PRECISION NOT NULL DEFAULT 0,
                stari_ugovor VARCHAR(20) NOT NULL,
                novi_ugovor VARCHAR(20) NOT NULL,
                operater_id INTEGER,
                operater VARCHAR(300) NOT NULL DEFAULT ''
            )
        """))
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS tipovi_kartica ("
            " id SERIAL PRIMARY KEY, naziv VARCHAR(50) NOT NULL UNIQUE)"
        ))
        for naziv in TIPOVI_KARTICA_SEED:
            conn.execute(text(
                "INSERT INTO tipovi_kartica (naziv) VALUES (:n) ON CONFLICT (naziv) DO NOTHING"
            ), {"n": naziv})
        # Čekovi uplate: jedna uplata (način Ček) = više čekova; faktura = broj ugovora (kao uplate.faktura)
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS cekovi ("
            " id SERIAL PRIMARY KEY,"
            " uplata_kljuc INTEGER NOT NULL REFERENCES uplate(kljuc) ON DELETE CASCADE,"
            " faktura VARCHAR(300) DEFAULT '',"
            " redni INTEGER NOT NULL,"
            " datum DATE NOT NULL,"
            " iznos NUMERIC(14,2) NOT NULL,"
            " banka VARCHAR(200) DEFAULT '',"
            " broj_racuna_banke VARCHAR(50) DEFAULT '',"
            " broj_racuna_klijenta VARCHAR(50) DEFAULT '',"
            " serijski_broj VARCHAR(50) DEFAULT '')"
        ))
        # Banka klijenta = id iz tabele banke (kolona banka = naziv banke Agencije, kao do sada)
        conn.execute(text("""
            DO $$ BEGIN
                IF EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name = 'cekovi' AND column_name = 'banka_klijenta_id')
                   AND NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name = 'cekovi' AND column_name = 'banka_klijenta') THEN
                    ALTER TABLE cekovi RENAME COLUMN banka_klijenta_id TO banka_klijenta;
                END IF;
            END $$
        """))
        conn.execute(text("ALTER TABLE cekovi ADD COLUMN IF NOT EXISTS banka_klijenta INTEGER"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS cekovi_uplata_idx ON cekovi (uplata_kljuc)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS cekovi_faktura_idx ON cekovi (faktura)"))
        # Veza ugovora na konkretni smeštaj (instanca = mesto + grupa termina).
        # Naziv/soba u aranzman-u su nazivi pa se smeštaji istog naziva u različitim
        # grupama ne mogu razlučiti — smestaj_id čuva tačan izbor sa forme/grafika.
        conn.execute(text(
            "ALTER TABLE aranzman ADD COLUMN IF NOT EXISTS smestaj_id INTEGER"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_aranzman_smestaj_id ON aranzman(smestaj_id)"
        ))
        # Način plaćanja rezervacije (delimicno | u_celosti | NULL = nije izabran) — bira popust sobe
        conn.execute(text(
            "ALTER TABLE aranzman ADD COLUMN IF NOT EXISTS nacin_placanja VARCHAR(20)"
        ))
        # Dodatne stavke — ugovor = ceo ključ ugovora (npr. 213/26); id (broj) je zamenjen
        # jer dva ugovora iste brojke iz različitih godina dele stavke.
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS dodatne (
                ugovor VARCHAR(30) DEFAULT NULL,
                usluga VARCHAR(150) DEFAULT NULL,
                eur DOUBLE PRECISION DEFAULT NULL,
                din DOUBLE PRECISION DEFAULT NULL
            )
        """))
        conn.execute(text("ALTER TABLE dodatne ADD COLUMN IF NOT EXISTS ugovor VARCHAR(30) DEFAULT NULL"))
        conn.execute(text("ALTER TABLE dodatne ADD COLUMN IF NOT EXISTS stavka_id SERIAL"))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_dodatne_stavka_id ON dodatne(stavka_id)"
        ))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_dodatne_ugovor ON dodatne(ugovor)"))
        # Dodatni popusti — vezani za aranzman (aranzman.id); obračunavaju se na smeštaj
        # u istom koraku kao osnovni popust, posle njega (bez FK, po konvenciji projekta)
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS dodatni_popusti (
                id SERIAL PRIMARY KEY,
                aranzman_id INTEGER NOT NULL,
                naziv VARCHAR(150) NOT NULL,
                eur DOUBLE PRECISION DEFAULT NULL,
                rsd DOUBLE PRECISION DEFAULT NULL
            )
        """))
        conn.execute(text(
            "ALTER TABLE dodatni_popusti ADD COLUMN IF NOT EXISTS procenat DOUBLE PRECISION DEFAULT NULL"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_dodatni_popusti_aranzman ON dodatni_popusti(aranzman_id)"
        ))
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
        conn.execute(text("ALTER TABLE subagenti ADD COLUMN IF NOT EXISTS pib VARCHAR(30) DEFAULT ''"))
        conn.execute(text("ALTER TABLE subagenti ADD COLUMN IF NOT EXISTS matbroj VARCHAR(20) DEFAULT ''"))
        conn.execute(text("ALTER TABLE subagenti ADD COLUMN IF NOT EXISTS email VARCHAR(200) DEFAULT ''"))
        conn.execute(text("ALTER TABLE subagenti ADD COLUMN IF NOT EXISTS ugovor_broj VARCHAR(50) DEFAULT ''"))
        conn.execute(text("ALTER TABLE subagenti ADD COLUMN IF NOT EXISTS ugovor_datumod DATE"))
        conn.execute(text("ALTER TABLE subagenti ADD COLUMN IF NOT EXISTS ugovor_datumdo DATE"))

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
            ALTER TABLE sobe ADD COLUMN IF NOT EXISTS opis_ugovor VARCHAR(60) DEFAULT ''
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

        # Parametri obračuna — singleton (id=1), globalni parametri cene
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS parametri_obracuna (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                visina_popusta INTEGER NOT NULL DEFAULT 0 CHECK (visina_popusta BETWEEN 0 AND 100),
                datumod1 DATE NULL,
                datumdo1 DATE NULL,
                koeficijent1 DOUBLE PRECISION NULL,
                datumod2 DATE NULL,
                datumdo2 DATE NULL,
                koeficijent2 DOUBLE PRECISION NULL
            )
        """))
        conn.execute(text("""
            INSERT INTO parametri_obracuna (id, visina_popusta)
            VALUES (1, 0)
            ON CONFLICT (id) DO NOTHING
        """))
        conn.execute(text(
            "ALTER TABLE parametri_obracuna ADD COLUMN IF NOT EXISTS visina_provizije INTEGER NOT NULL DEFAULT 10 CHECK (visina_provizije BETWEEN 0 AND 100)"
        ))
        conn.execute(text(
            "ALTER TABLE parametri_obracuna ADD COLUMN IF NOT EXISTS donja_platforma_eur NUMERIC(10,2) NOT NULL DEFAULT 0 CHECK (donja_platforma_eur >= 0)"
        ))
        for _kol in MESTA_SEDENJA_POLJA:
            conn.execute(text(
                f"ALTER TABLE parametri_obracuna ADD COLUMN IF NOT EXISTS {_kol} NUMERIC(10,2) NOT NULL DEFAULT 0 CHECK ({_kol} >= 0)"
            ))

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
    poslovnica_id: Optional[int] = None


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
    poslovnica_id: Optional[int] = None


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
    granica_chd: Optional[float] = 6.99
    prima_decu: Optional[bool] = True
    ne_prima_ispod_godina: Optional[int] = None
    popular: Optional[bool] = False
    provizija: Optional[int] = 10
    napomena: Optional[str] = None

    @field_validator("provizija")
    @classmethod
    def _provizija_0_100(cls, v):
        if v is not None and not (0 <= v <= 100):
            raise ValueError("Provizija mora biti između 0 i 100")
        return v

    @field_validator("ne_prima_ispod_godina")
    @classmethod
    def _godine_0_18(cls, v):
        if v is not None and not (0 <= v <= 18):
            raise ValueError("Godine moraju biti između 0 i 18")
        return v


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
    granica_chd: Optional[float] = None
    prima_decu: Optional[bool] = None
    ne_prima_ispod_godina: Optional[int] = None
    popular: Optional[bool] = None
    provizija: Optional[int] = None
    napomena: Optional[str] = None

    @field_validator("provizija")
    @classmethod
    def _provizija_0_100_upd(cls, v):
        if v is not None and not (0 <= v <= 100):
            raise ValueError("Provizija mora biti između 0 i 100")
        return v

    @field_validator("ne_prima_ispod_godina")
    @classmethod
    def _godine_0_18(cls, v):
        if v is not None and not (0 <= v <= 18):
            raise ValueError("Godine moraju biti između 0 i 18")
        return v


class PeriodGrupaCreate(BaseModel):
    naziv: str

SOBA_OPIS_UGOVOR = ("Direktan pogled more", "Bočni pogled more", "Economy", "Economy UT", "Economy IT",
                    "Economy ZT", "Economy PT", "Economy PZ", "Economy MTPZ", "Economy VTPZ", "Graden")

def _proveri_opis_ugovor(v):
    if v and v not in SOBA_OPIS_UGOVOR:
        raise HTTPException(status_code=400, detail="Nepoznat opis za ugovor")
    return v or ""

class SobaCreate(BaseModel):
    veza_id_smestaj: int
    broj_sobe: Optional[str] = ""
    opis: Optional[str] = ""
    tip: Optional[str] = ""
    status: Optional[int] = 1
    opis_dodatno: Optional[str] = ""
    veliki_opis: Optional[str] = ""
    opis_ugovor: Optional[str] = ""

class SobaUpdate(BaseModel):
    veza_id_smestaj: Optional[int] = None
    broj_sobe: Optional[str] = None
    opis: Optional[str] = None
    tip: Optional[str] = None
    status: Optional[int] = None
    opis_dodatno: Optional[str] = None
    veliki_opis: Optional[str] = None
    opis_ugovor: Optional[str] = None

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
    cena_transfera: Optional[float] = None  # EUR, uvek; NULL = nije uneta (logo je globalni, ostali su dokumenti sa headerom + napomenom)
    mesto_id: Optional[int] = None  # šifarnik mesto; opciono
    grupa_id: Optional[int] = None  # period_grupa; opciono
    destinacija_id: Optional[int] = None  # šifarnik destinacija; obavezno; destinacija (tekst) se popunjava iz naziva
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
    pib: Optional[str] = ""
    matbroj: Optional[str] = ""
    email: Optional[str] = ""
    ugovor_broj: Optional[str] = ""
    ugovor_datumod: Optional[SubDate] = None
    ugovor_datumdo: Optional[SubDate] = None
    ta: bool = True


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
    pib: Optional[str] = None
    matbroj: Optional[str] = None
    email: Optional[str] = None
    ugovor_broj: Optional[str] = None
    ugovor_datumod: Optional[SubDate] = None
    ugovor_datumdo: Optional[SubDate] = None
    ta: Optional[bool] = None


class PredracunCreate(BaseModel):
    ugovor: str
    racun: Optional[str] = ""
    nacin: Optional[str] = ""
    napomena: Optional[str] = ""


class PredracunUpdate(BaseModel):
    racun: Optional[str] = None
    nacin: Optional[str] = None
    napomena: Optional[str] = None


class KarticaPodaci(BaseModel):
    brojPotvrde: Optional[str] = ""
    tipKartice: Optional[str] = ""
    brojKartice: Optional[str] = ""
    brojOdobrenja: Optional[str] = ""


class CekStavka(BaseModel):
    redni: int
    datum: str  # YYYY-MM-DD
    iznos: float
    banka: str = ""
    bankaKlijentaId: Optional[int] = None  # banke.id — banka klijenta
    brojRacunaBanke: str = ""
    brojRacunaKlijenta: str = ""
    serijskiBroj: Optional[str] = ""


class CekoviPodaci(BaseModel):
    cekovi: list[CekStavka] = []


MAX_CEKOVA = 60


def _cekovi_cisto(lista: "list[CekStavka] | None", din: float) -> list[dict]:
    """Validira čekove uplate: 1..60 stavki, pozitivni iznosi (max 2 decimale),
    zbir TAČNO jednak iznosu uplate (u centima). Vraća listu sortiranu i renumerisanu 1..n."""
    if not lista:
        raise HTTPException(status_code=400, detail="Unesite čekove")
    if len(lista) > MAX_CEKOVA:
        raise HTTPException(status_code=400, detail=f"Najviše {MAX_CEKOVA} čekova po uplati")
    from datetime import date as _date

    cisto = []
    for c in sorted(lista, key=lambda x: x.redni):
        try:
            _date.fromisoformat(c.datum)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Neispravan datum čeka")
        cents = round(c.iznos * 100)
        if cents <= 0 or abs(c.iznos * 100 - cents) > 1e-6:
            raise HTTPException(status_code=400, detail="Iznos čeka mora biti pozitivan (najviše 2 decimale)")
        banka = (c.banka or "").strip()
        racun_b = (c.brojRacunaBanke or "").strip()
        racun_k = (c.brojRacunaKlijenta or "").strip()
        serijski = (c.serijskiBroj or "").strip()
        if not banka or len(banka) > 200:
            raise HTTPException(status_code=400, detail="Banka je obavezna (najviše 200 znakova)")
        if not c.bankaKlijentaId or c.bankaKlijentaId <= 0:
            raise HTTPException(status_code=400, detail="Banka klijenta je obavezna (izaberite iz tabele banke)")
        if not racun_b or len(racun_b) > 50 or len(racun_k) > 50 or len(serijski) > 50:
            raise HTTPException(status_code=400, detail="Broj računa i serijski broj mogu imati najviše 50 znakova")
        cisto.append({
            "datum": _date.fromisoformat(c.datum), "iznos": cents,
            "banka": banka, "banka_klijenta": c.bankaKlijentaId,
            "broj_racuna_banke": racun_b,
            "broj_racuna_klijenta": racun_k, "serijski_broj": serijski,
        })
    zbir = sum(c["iznos"] for c in cisto)
    if zbir != round(din * 100):
        raise HTTPException(
            status_code=400,
            detail=f"Zbir čekova ({zbir / 100:,.2f}) se ne slaže sa iznosom uplate ({din:,.2f})",
        )
    for i, c in enumerate(cisto, start=1):
        c["redni"] = i
        c["iznos"] = c["iznos"] / 100
    return cisto


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
    dodatna_usluga_id: Optional[int] = None


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


class DodatniPopustIn(BaseModel):
    """Dodatni popust na smeštaj: ili procenat (od bruto smeštaja) ili iznos EUR i/ili RSD."""
    naziv: str
    eur: Optional[float] = None
    rsd: Optional[float] = None
    procenat: Optional[float] = None

    @field_validator("eur", "rsd", "procenat", mode="before")
    @classmethod
    def reject_boolean(cls, value):
        if isinstance(value, bool):
            raise ValueError("Iznos mora biti broj, ne boolean")
        return value


def _dodatni_popust_values(body: DodatniPopustIn) -> dict:
    naziv = body.naziv.strip()
    if not naziv or len(naziv) > 150:
        raise HTTPException(status_code=400, detail="Naziv mora imati od 1 do 150 znakova")
    for value in (body.eur, body.rsd):
        if value is None:
            continue
        if not math.isfinite(value) or value < 0:
            raise HTTPException(status_code=400, detail="Iznos mora biti nenegativan konačan broj")
        amount = Decimal(str(value))
        if amount * 100 != (amount * 100).to_integral_value():
            raise HTTPException(status_code=400, detail="Iznos može imati najviše 2 decimale")
    if body.procenat is not None:
        if not math.isfinite(body.procenat) or not (0 < body.procenat <= 100):
            raise HTTPException(status_code=400, detail="Procenat mora biti broj između 0 i 100")
        if (body.eur or 0) > 0 or (body.rsd or 0) > 0:
            raise HTTPException(status_code=400, detail="Unesite ili procenat ili iznos, ne oba")
        return {"naziv": naziv, "eur": None, "rsd": None, "procenat": body.procenat}
    if not ((body.eur or 0) > 0 or (body.rsd or 0) > 0):
        raise HTTPException(status_code=400, detail="Unesite procenat ili iznos u EUR ili RSD")
    return {"naziv": naziv, "eur": body.eur or None, "rsd": body.rsd or None, "procenat": None}


class UgovorSmestajUpdate(BaseModel):
    """Promena smeštaja na ugovoru — soba + termin (PATCH /ugovori/{kljuc}/smestaj)."""
    soba_id: int
    datum_od: str   # ISO yyyy-mm-dd
    datum_do: str   # ISO yyyy-mm-dd


# ─── Rezervacije: unos/izmena aranžmana iz forme (Sačuvaj/Izmeni) ───────────
# Advisory lock za dodelu novog broja ugovora (MAX+1 po godini iz Datuma od).
REZ_ADVISORY_LOCK = 9_250_000_000_001
KEPTP_ADVISORY_LOCK = 9_250_000_000_002


class KeptpDodeliIn(BaseModel):
    kljuc: str


class RezPutnikIn(BaseModel):
    ime: str = ""
    datumRodjenja: Optional[str] = None  # ISO yyyy-mm-dd
    pasos: str = ""
    uzrast: str = ""  # ADL / CHD / INF (prazno = nije izabrano)
    dodatnoSediste: bool = False  # aranzman_dopuna.dodatno_sediste
    ow: bool = False
    rt: bool = False
    sp: bool = False
    smer: str = ""
    adresa: str = ""
    grad: str = ""
    telefon: str = ""
    email: str = ""
    ulazak: str = ""  # mesto ulaska (saputnici — aranzman_dopuna.ulazak)
    mestoIzlaska: str = ""  # mesto izlaska (prazno → mesto ulaska)
    # tab Prevoz
    mestoSedenja: str = ""
    placeno: bool = False
    zelja: bool = False
    datumOw: Optional[str] = None  # ISO yyyy-mm-dd (važi ako ow)
    # destinacija prevoza = destinacija_prevoz.id (važi ako smer uključen); naziv se
    # upisuje u tekstualnu kolonu iz tabele. Bez ID-ja pada na tekst (legacy).
    destinacijaOwId: Optional[int] = None
    destinacijaOw: str = ""
    datumPolaska: Optional[str] = None  # RT
    destinacijaPolaskaId: Optional[int] = None
    destinacijaPolaska: str = ""
    datumPovratka: Optional[str] = None
    destinacijaPovratkaId: Optional[int] = None
    destinacijaPovratka: str = ""


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
    viza: bool = False


class RezTransferStavka(BaseModel):
    usluga: str  # npr. "TRANSFER - SUBOTICA" (računa frontend iz tabele Prevoz)
    eur: float


class RezObracunIzbor(BaseModel):
    # varijanta sobe izabrana u „PROVERI OBRAČUN“ — upisuje se samo u obracun_po_aranzmanu
    # (soba_cenovnik, struktura za koeficijent); iznos ide kroz polje Cena smeštaja
    broj_sobe: str
    struktura: str = ""
    # prevoz izabrane opcije (True = sa prevozom/autobuski); None = prema ow/rt iz forme
    prevoz: Optional[bool] = None


class RezervacijaIn(BaseModel):
    tiprezervacije: str = ""
    subagent: Optional[str] = None  # naziv iz tabele subagenti (aranzman.subagent)
    timelimit: Optional[str] = None  # ISO "yyyy-mm-ddTHH:MM:00" ili null
    nosilac: RezPutnikIn
    saputnici: list[RezPutnikIn] = []
    boravak: RezBoravakIn
    destinacijaId: Optional[int] = None  # destinacija (naziv ugovora) — ID iz tabele destinacija
    destinacijaNaziv: Optional[str] = None  # fallback van referentne liste
    destinacijaPrevozId: Optional[int] = None  # Izbor destinacije (tab Prevoz) — ID iz destinacija_prevoz
    ulazak: str = ""  # mesto ulaska nosioca
    izlazak: str = ""  # mesto izlaska nosioca (prazno → mesto ulaska)
    napomenaPrevoz: str = ""  # polje pored "Izbor destinacije" (tab Prevoz)
    cene: RezCeneIn
    # način plaćanja: "delimicno" | "u_celosti" | "" (nije izabran) — bira koji popust sobe važi
    nacinPlacanja: str = ""
    # TRANSFER stavke dodatnih usluga (po mestu ulaska). None = ne diraj; lista = zameni sve TRANSFER redove.
    transferi: Optional[list[RezTransferStavka]] = None
    # varijanta izabrana u PROVERI OBRAČUN (None = obračun po formi)
    obracunIzbor: Optional[RezObracunIzbor] = None

# ─── Boje grafik ───────────────────────────────────────────────────────────
DOZVOLJENE_BOJE = ("zelena", "plava", "crvena", "zuta", "ljubicasta", "narandzasta", "crna", "roze")


class ParametriObracuna(BaseModel):
    visina_popusta: int
    visina_provizije: int = 10
    donja_platforma_eur: float = Field(0, ge=0, lt=1e6)
    gornja_platforma_eur: float = Field(0, ge=0, lt=1e6)
    dole_za_stolom_eur: float = Field(0, ge=0, lt=1e6)
    dole_zadnji_red_eur: float = Field(0, ge=0, lt=1e6)
    gore_izlog_eur: float = Field(0, ge=0, lt=1e6)
    gore_sto_eur: float = Field(0, ge=0, lt=1e6)
    sarage_eur: float = Field(0, ge=0, lt=1e6)
    datumod1: Optional[SubDate] = None
    datumdo1: Optional[SubDate] = None
    koeficijent1: Optional[float] = None
    datumod2: Optional[SubDate] = None
    datumdo2: Optional[SubDate] = None
    koeficijent2: Optional[float] = None


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


def _rez_dp_naziv(conn, dp_id: Optional[int]) -> Optional[str]:
    """destinacija_prevoz.id → naziv (za tekstualnu kolonu); nepostojeći → 400."""
    if dp_id is None:
        return None
    r = conn.execute(text("SELECT naziv FROM destinacija_prevoz WHERE id = :i"),
                     {"i": dp_id}).fetchone()
    if not r:
        raise HTTPException(status_code=400, detail="Destinacija prevoza ne postoji")
    return (r.naziv or "").strip()[:200] or None


def _rez_prevoz_polja(s: "RezPutnikIn", conn) -> dict:
    """Polja taba Prevoz po putniku → kolone (aranzman za nosioca, aranzman_dopuna
    za saputnike). Datumi/destinacije se čuvaju samo kad je odgovarajući smer
    (OW / RT) uključen, inače NULL. Destinacija = *_id (destinacija_prevoz.id) +
    naziv u tekstualnoj koloni."""
    ow, rt = bool(s.ow), bool(s.rt)
    ow_id = s.destinacijaOwId if ow else None
    pol_id = s.destinacijaPolaskaId if rt else None
    pov_id = s.destinacijaPovratkaId if rt else None
    return {
        "mesto_sedenja": _rez_str(s.mestoSedenja, 50),
        "placeno_prevoz": 1 if s.placeno else 0,
        "zelja_prevoz": 1 if s.zelja else 0,
        "datum_ow": _rez_datum(s.datumOw, "Datum OW") if ow else None,
        "destinacija_ow_id": ow_id,
        "destinacija_ow": _rez_dp_naziv(conn, ow_id) if ow_id is not None else (_rez_str(s.destinacijaOw, 200) if ow else None),
        "datum_polaska": _rez_datum(s.datumPolaska, "Datum polaska RT") if rt else None,
        "destinacija_polaska_id": pol_id,
        "destinacija_polaska": _rez_dp_naziv(conn, pol_id) if pol_id is not None else (_rez_str(s.destinacijaPolaska, 200) if rt else None),
        "datum_povratka": _rez_datum(s.datumPovratka, "Datum povratka RT") if rt else None,
        "destinacija_povratka_id": pov_id,
        "destinacija_povratka": _rez_dp_naziv(conn, pov_id) if pov_id is not None else (_rez_str(s.destinacijaPovratka, 200) if rt else None),
    }


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


def _obracun_argumenti(body, vals: dict) -> dict:
    """Argumenti za obracun_iz_rezervacije iz forme i vrednosti koje idu u aranzman."""
    uzrasti = [body.nosilac.uzrast] + [s.uzrast for s in body.saputnici if (s.ime or "").strip()]
    # prefill iz Grafika/Pretrage postavlja samo količinu (broj osoba), ne i listu saputnika:
    # ako je količina veća od unetih putnika, višak se broji kao ADL
    kol = int(round(float(vals.get("kolaranz") or 0)))
    if kol > len(uzrasti):
        uzrasti += ["ADL"] * (kol - len(uzrasti))
    iznos = None
    if vals.get("cenaaranz") is not None and vals.get("kolaranz") is not None:
        iznos = round(float(vals["cenaaranz"]) * float(vals["kolaranz"]), 2)
    soba_broj = vals.get("soba")
    struktura = vals.get("gde") or vals.get("apartman")
    # varijanta izabrana u PROVERI OBRAČUN: obračun (soba_cenovnik, koeficijent) ide po njoj,
    # a Rezervacija (soba, apartman, gde) ostaje kakva jeste
    prevoz = bool(body.nosilac.ow or body.nosilac.rt)
    if body.obracunIzbor is not None:
        soba_broj = body.obracunIzbor.broj_sobe
        struktura = body.obracunIzbor.struktura or struktura
        if body.obracunIzbor.prevoz is not None:
            prevoz = body.obracunIzbor.prevoz
    return {
        "smestaj_id": body.boravak.smestajId,
        "soba_broj": soba_broj,
        # koeficijent se traži za strukturu virtuelne sobe (gde), inače za sobe.tip (apartman)
        "struktura": struktura,
        "uzrasti": uzrasti,
        "prevoz": prevoz,
        "iznos_eur": iznos,
        "datumod": vals.get("datumod"),
        "datumdo": vals.get("datumdo"),
    }


def create_app(static_dir: str) -> FastAPI:
    engine = get_engine()
    init_db(engine)
    init_cenovnici(engine)
    init_koeficijenti(engine)
    init_poslovnice(engine)
    init_prevoz_limit(engine)
    init_dodatne_usluge(engine)
    init_zaduzenje(engine)
    init_zabrana(engine)
    init_saglasnost(engine)
    init_dobavljaci(engine)
    init_banke(engine)
    init_notifikacije(engine)
    init_rezervacija_log(engine)
    init_obracun_po_aranzmanu(engine)

    api = APIRouter()
    register_cenovnici(api, engine, get_current_user)
    register_koeficijenti(api, engine, get_current_user)
    register_poslovnice(api, engine, get_current_user)
    register_prevoz_limit(api, engine, get_current_user)
    register_dodatne_usluge(api, engine, get_current_user)
    register_zaduzenje(api, engine, get_current_user)
    register_dobavljaci(api, engine, get_current_user)
    register_banke(api, engine, get_current_user)
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
                       u.is_superadmin, u.created_at, u.poslovnica_id,
                       p.naziv as poslovnica_naziv,
                       ut.id as user_type_id, ut.name as user_type_name, ut.slug as user_type_slug
                FROM users u
                LEFT JOIN user_types ut ON u.user_type_id = ut.id
                LEFT JOIN poslovnice p ON p.id = u.poslovnica_id
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
            "poslovnica_id": r.poslovnica_id,
            "poslovnica_naziv": r.poslovnica_naziv,
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
                         status, username, password_hash, user_type_id, poslovnica_id)
                    VALUES
                        (:first_name, :last_name, :email, :phone, :address, :city,
                         :status, :username, :pw, :user_type_id, :poslovnica_id)
                    RETURNING id, first_name, last_name, email, phone, address,
                              city, status, username, user_type_id, poslovnica_id, created_at
                """), {
                    "first_name": body.first_name, "last_name": body.last_name,
                    "email": body.email, "phone": body.phone,
                    "address": body.address, "city": body.city,
                    "status": body.status, "username": body.username,
                    "pw": pw_hash, "user_type_id": body.user_type_id,
                    "poslovnica_id": body.poslovnica_id,
                }).fetchone()
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Greška: {str(e)}")
        return {
            "id": row.id, "first_name": row.first_name, "last_name": row.last_name,
            "email": row.email, "phone": row.phone, "address": row.address,
            "city": row.city, "status": row.status, "username": row.username,
            "user_type_id": row.user_type_id,
            "poslovnica_id": row.poslovnica_id,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    @api.put("/users/{user_id}")
    def update_user(user_id: int, body: UserUpdate, _: dict = Depends(get_current_user)):
        data = body.model_dump(exclude_none=True)
        # poslovnica_id: null je validna vrednost (skidanje poslovnice)
        if "poslovnica_id" in body.model_fields_set:
            data["poslovnica_id"] = body.poslovnica_id
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
                          city, status, username, user_type_id, poslovnica_id, updated_at
            """), data).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Korisnik nije pronađen")
        return {"id": row.id, "first_name": row.first_name, "last_name": row.last_name,
                "email": row.email, "phone": row.phone, "address": row.address,
                "city": row.city, "status": row.status, "username": row.username,
                "user_type_id": row.user_type_id, "poslovnica_id": row.poslovnica_id}

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
                       s.granica_chd, s.prima_decu, s.ne_prima_ispod_godina, s.popular, s.provizija, s.napomena,
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
            "granica_chd": r.granica_chd,
            "prima_decu": r.prima_decu, "ne_prima_ispod_godina": r.ne_prima_ispod_godina,
            "popular": r.popular, "provizija": r.provizija, "napomena": r.napomena,
            "drzava_naziv": r.drzava_naziv,
            "destinacija_naziv": r.destinacija_naziv,
            "mesto_naziv": r.mesto_naziv,
            "tip_smestaja_naziv": r.tip_smestaja_naziv,
            "grupa_datuma_naziv": r.grupa_datuma_naziv,
        } for r in rows]

    @api.post("/smestaj")
    def create_smestaj(body: SmestajCreate, _: dict = Depends(get_current_user)):
        prima = True if body.prima_decu is None else body.prima_decu
        if not prima and body.ne_prima_ispod_godina is None:
            raise HTTPException(status_code=400, detail="Za „ne prima decu“ unesite godine ispod kojih se deca ne primaju")
        with engine.begin() as conn:
            row = conn.execute(text("""
                INSERT INTO smestaj (naziv, drzava, destinacija, mesto, tip_smestaja, grupa_datuma, status, organizator, predstavnik, grafik, granica_chd, prima_decu, ne_prima_ispod_godina, popular, provizija, napomena)
                VALUES (:naziv, :drzava, :destinacija, :mesto, :tip_smestaja, :grupa_datuma, :status, :organizator, :predstavnik, :grafik, COALESCE(:granica_chd, 6.99), :prima, :ispod, COALESCE(:popular, FALSE), COALESCE(:provizija, 10), :napomena)
                RETURNING id, naziv, drzava, destinacija, mesto, tip_smestaja, grupa_datuma, status, organizator, predstavnik, grafik, granica_chd, prima_decu, ne_prima_ispod_godina, popular, provizija, napomena
            """), {
                "naziv": body.naziv, "drzava": body.drzava, "destinacija": body.destinacija,
                "mesto": body.mesto, "tip_smestaja": body.tip_smestaja,
                "grupa_datuma": body.grupa_datuma, "status": body.status,
                "organizator": body.organizator, "predstavnik": body.predstavnik, "grafik": body.grafik,
                "granica_chd": body.granica_chd,
                "prima": prima,
                "ispod": None if prima else body.ne_prima_ispod_godina,
                "popular": body.popular,
                "provizija": body.provizija,
                "napomena": body.napomena,
            }).fetchone()
        return {
            "id": row.id, "naziv": row.naziv, "drzava": row.drzava,
            "destinacija": row.destinacija, "mesto": row.mesto, "tip_smestaja": row.tip_smestaja,
            "grupa_datuma": row.grupa_datuma,
            "status": row.status, "organizator": row.organizator,
            "predstavnik": row.predstavnik, "grafik": row.grafik,
            "granica_chd": row.granica_chd,
            "prima_decu": row.prima_decu, "ne_prima_ispod_godina": row.ne_prima_ispod_godina,
            "popular": row.popular, "provizija": row.provizija, "napomena": row.napomena,
        }

    @api.put("/smestaj/{item_id}")
    def update_smestaj(item_id: int, body: SmestajUpdate, _: dict = Depends(get_current_user)):
        fields = {k: v for k, v in body.model_dump().items() if v is not None}
        # godine može da se obriše (null u zahtevu) — samo ako je eksplicitno poslato
        if "ne_prima_ispod_godina" in body.model_fields_set:
            fields["ne_prima_ispod_godina"] = body.ne_prima_ispod_godina
        # napomena može da se obriše (null u zahtevu)
        if "napomena" in body.model_fields_set:
            fields["napomena"] = body.napomena
        if not fields:
            raise HTTPException(status_code=400, detail="Nema podataka za ažuriranje")
        with engine.begin() as conn:
            cur = conn.execute(text(
                "SELECT prima_decu, ne_prima_ispod_godina FROM smestaj WHERE id = :id FOR UPDATE"
            ), {"id": item_id}).fetchone()
            if not cur:
                raise HTTPException(status_code=404, detail="Smeštaj nije pronađen")
            prima = fields.get("prima_decu", cur.prima_decu)
            ispod = fields.get("ne_prima_ispod_godina", cur.ne_prima_ispod_godina)
            if not prima:
                if ispod is None:
                    raise HTTPException(status_code=400, detail="Za „ne prima decu“ unesite godine ispod kojih se deca ne primaju")
            else:
                fields["ne_prima_ispod_godina"] = None  # DA: godine nisu definisane
            set_clause = ", ".join(f"{k} = :{k}" for k in fields)
            fields["id"] = item_id
            row = conn.execute(text(f"""
                UPDATE smestaj SET {set_clause}
                WHERE id = :id
                RETURNING id, naziv, drzava, destinacija, mesto, tip_smestaja, grupa_datuma, status, organizator, predstavnik, grafik, granica_chd, prima_decu, ne_prima_ispod_godina, popular, provizija, napomena
            """), fields).fetchone()
        return {
            "id": row.id, "naziv": row.naziv, "drzava": row.drzava,
            "destinacija": row.destinacija, "mesto": row.mesto, "tip_smestaja": row.tip_smestaja,
            "grupa_datuma": row.grupa_datuma,
            "status": row.status, "organizator": row.organizator,
            "predstavnik": row.predstavnik, "grafik": row.grafik,
            "granica_chd": row.granica_chd,
            "prima_decu": row.prima_decu, "ne_prima_ispod_godina": row.ne_prima_ispod_godina,
            "popular": row.popular, "provizija": row.provizija, "napomena": row.napomena,
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
                       b.status, b.opis_dodatno, b.veliki_opis, b.opis_ugovor,
                       s.naziv AS smestaj_naziv, m.naziv AS mesto_naziv,
                       pg.naziv AS grupa_datuma_naziv
                FROM sobe b
                LEFT JOIN smestaj s ON b.veza_id_smestaj = s.id
                LEFT JOIN mesto m ON m.id = s.mesto
                LEFT JOIN period_grupa pg ON pg.id = s.grupa_datuma
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
            "veliki_opis": r.veliki_opis, "opis_ugovor": r.opis_ugovor or "",
            "smestaj_naziv": r.smestaj_naziv,
            "mesto_naziv": r.mesto_naziv,
            "grupa_datuma_naziv": r.grupa_datuma_naziv,
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
                INSERT INTO sobe (veza_id_smestaj, broj_sobe, opis, tip, status, opis_dodatno, veliki_opis, opis_ugovor)
                VALUES (:smestaj, :broj_sobe, :opis, :tip, :status, :opis_dodatno, :veliki_opis, :opis_ugovor)
                RETURNING id, veza_id_smestaj, broj_sobe, opis, tip, status, opis_dodatno, veliki_opis, opis_ugovor
            """), {
                "smestaj": body.veza_id_smestaj, "broj_sobe": body.broj_sobe or "",
                "opis": body.opis or "", "tip": body.tip or "", "status": body.status if body.status is not None else 1,
                "opis_dodatno": body.opis_dodatno or "", "veliki_opis": body.veliki_opis or "",
                "opis_ugovor": _proveri_opis_ugovor(body.opis_ugovor),
            }).fetchone()
            # početni koeficijent: soba 1/2 dobija koeficijent 1/2, 1/3 → 1/3 ... (nule ako ne postoji)
            osiguraj_auto_red(conn, row.tip)
        return {
            "id": row.id, "veza_id_smestaj": row.veza_id_smestaj,
            "broj_sobe": row.broj_sobe, "opis": row.opis, "tip": row.tip,
            "status": row.status, "opis_dodatno": row.opis_dodatno,
            "veliki_opis": row.veliki_opis, "opis_ugovor": row.opis_ugovor or "",
        }

    @api.put("/sobe/{item_id}")
    def update_soba(item_id: int, body: SobaUpdate, _: dict = Depends(get_current_user)):
        fields = {k: v for k, v in body.model_dump().items() if v is not None}
        if not fields:
            raise HTTPException(status_code=400, detail="Nema podataka za ažuriranje")
        if "opis_ugovor" in fields:
            fields["opis_ugovor"] = _proveri_opis_ugovor(fields["opis_ugovor"])
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
                RETURNING id, veza_id_smestaj, broj_sobe, opis, tip, status, opis_dodatno, veliki_opis, opis_ugovor
            """), fields).fetchone()
            if "tip" in fields:
                osiguraj_auto_red(conn, row.tip)
        if not row:
            raise HTTPException(status_code=404, detail="Soba nije pronađena")
        return {
            "id": row.id, "veza_id_smestaj": row.veza_id_smestaj,
            "broj_sobe": row.broj_sobe, "opis": row.opis, "tip": row.tip,
            "status": row.status, "opis_dodatno": row.opis_dodatno,
            "veliki_opis": row.veliki_opis, "opis_ugovor": row.opis_ugovor or "",
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
    def _polazak_sa_nazivima(conn, item_id: int | None = None):
        where = "WHERE p.id = :id" if item_id is not None else ""
        rows = conn.execute(text(f"""
            SELECT p.id, COALESCE(ds.naziv, p.destinacija) AS destinacija,
                   p.destinacija_id, ds.naziv AS destinacija_naziv,
                   p.polazak, p.sat, p.valuta,
                   p.adlrt, p.chdrt, p.infrt, p.adlow, p.chdow, p.infow,
                   p.cena_transfera, p.mesto_id, p.grupa_id,
                   m.naziv AS mesto_naziv, g.naziv AS grupa_naziv
            FROM polazak p
            LEFT JOIN destinacija ds ON ds.id = p.destinacija_id
            LEFT JOIN mesto m ON m.id = p.mesto_id
            LEFT JOIN period_grupa g ON g.id = p.grupa_id
            {where}
            ORDER BY destinacija, p.polazak, p.sat, p.id
        """), {"id": item_id} if item_id is not None else {}).fetchall()
        return [dict(r._mapping) for r in rows]

    def _polazak_validiraj(conn, body: "PolazakSave") -> dict:
        if body.destinacija_id is None:
            raise HTTPException(status_code=400, detail="Destinacija je obavezna")
        naziv = conn.execute(text("SELECT naziv FROM destinacija WHERE id = :id"),
                             {"id": body.destinacija_id}).scalar()
        if naziv is None:
            raise HTTPException(status_code=400, detail="Destinacija nije u šifarniku")
        vals = body.model_dump()
        vals["destinacija"] = naziv
        return vals

    @api.get("/polazak")
    def list_polazak(_: dict = Depends(get_current_user)):
        with engine.connect() as conn:
            return _polazak_sa_nazivima(conn)

    @api.post("/polazak")
    def create_polazak(body: PolazakSave, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            vals = _polazak_validiraj(conn, body)
            row = conn.execute(text("""
                INSERT INTO polazak (destinacija, destinacija_id, polazak, sat, valuta,
                                     adlrt, chdrt, infrt, adlow, chdow, infow, cena_transfera,
                                     mesto_id, grupa_id)
                VALUES (:destinacija, :destinacija_id, :polazak, :sat, :valuta,
                        :adlrt, :chdrt, :infrt, :adlow, :chdow, :infow, :cena_transfera,
                        :mesto_id, :grupa_id)
                RETURNING id
            """), vals).fetchone()
            return _polazak_sa_nazivima(conn, row.id)[0]

    @api.put("/polazak/{item_id}")
    def update_polazak(item_id: int, body: PolazakSave, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            vals = _polazak_validiraj(conn, body)
            vals["id"] = item_id
            row = conn.execute(text("""
                UPDATE polazak SET
                    destinacija = :destinacija, destinacija_id = :destinacija_id,
                    polazak = :polazak,
                    sat = :sat, valuta = :valuta,
                    adlrt = :adlrt, chdrt = :chdrt, infrt = :infrt,
                    adlow = :adlow, chdow = :chdow, infow = :infow,
                    cena_transfera = :cena_transfera,
                    mesto_id = :mesto_id, grupa_id = :grupa_id
                WHERE id = :id
                RETURNING id
            """), vals).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Polazak nije pronađen")
            return _polazak_sa_nazivima(conn, row.id)[0]


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
    # Dete do granica_chd (smeštaj.granica_chd, godine na datum početka boravka)
    # računa se kao CHD, starije kao ADL. INF se ne razlikuje.

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

        # Izuzetak za JEDNU osobu (1 ADL): ako početak boravka pada u period 1 ili 2
        # iz parametri_obracuna, koeficijent tog perioda množi OSNOVU iz cenovnika
        # i zamenjuje pravilo 2 (soba prolazi bez reda u koeficijenti_prodaje).
        izuzetak_koef = None
        if adl == 1 and chd == 0 and inf == 0:
            par = conn.execute(text("""
                SELECT datumod1, datumdo1, koeficijent1, datumod2, datumdo2, koeficijent2
                FROM parametri_obracuna WHERE id = 1
            """)).mappings().first()
            if par:
                for n in ("1", "2"):
                    od_, do_, k_ = par[f"datumod{n}"], par[f"datumdo{n}"], par[f"koeficijent{n}"]
                    if od_ and do_ and k_ is not None and od_ <= d_od <= do_:
                        izuzetak_koef = Decimal(str(k_))
                        break

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
            popusti: dict = {}
            for r in conn.execute(text(
                "SELECT * FROM popust_soba WHERE cenovnik_id = :c ORDER BY redni"
            ), {"c": c.id}).mappings():
                popusti.setdefault((r["soba_id"], r["period_id"]), []).append(r)
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

        def _obracun_sobe(cen, soba, struktura, koef, izuz=False):
            """Vrati dict obračuna ili None ako nema cene za tu strukturu.

            izuz=True: izuzetak za jednu osobu — koef je koeficijent perioda iz
            parametri_obracuna; množi se OSNOVA iz cenovnika (pre umanjenja i popusta).
            """
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
                opc_p = _po_opsegu(cen["opcije"], red["id"], p["id"])
                if opc_p and opc_p["blokirano"]:
                    # blokirana smena u lancu → soba se NE prikazuje
                    return {"blokirano_u_lancu": True}
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
            # koeficijent koji se množi: izuzetak (1 osoba) → osnova × koef perioda,
            # inače koef iz koeficijenti_prodaje (po osobi, u grani ispod)
            koef_mnozi = koef
            if izuz:
                if koef <= 0:
                    return {"nema_cene": True, "obracun": obr + [
                        "Izuzetak za 1 osobu: koeficijent perioda u parametrima obračuna je 0"]}
                osnova = osnova * koef
                obr.append(f"Izuzetak za 1 osobu (početak boravka u periodu parametara): "
                           f"osnova × {koef} = {_fmt(osnova)} €")
                koef_mnozi = Decimal("1")
            prvi_pid = cen["lanac"][0]["id"]
            opc = _po_opsegu(cen["opcije"], red["id"], prvi_pid)
            tip_cene = (opc["tip_cene"] if opc and opc["tip_cene"] else "po_osobi")
            umanj_sp = Decimal(str(opc["popust_sopstveni_prevoz"])) if opc and opc["popust_sopstveni_prevoz"] else Decimal("0")
            napomene = []
            if opc:
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
                if koef_mnozi <= 0:
                    return {"nema_cene": True, "obracun": obr + [
                        f"Tip cene: PO OSOBI, ali koeficijent za {adl} ADL / {chd} CHD / {inf} INF "
                        f"(struktura {struktura}) je 0 — unesite ga na Koeficijentima prodaje"]}
                cena = osnova * koef_mnozi
                if not izuz:
                    obr.append(f"Tip cene: PO OSOBI → {_fmt(osnova)} × {koef} = {_fmt(cena)} €")
                else:
                    obr.append(f"Tip cene: PO OSOBI → {_fmt(cena)} €")
                # Umanjenje za sopstveni prevoz: sopstveni → × broj smena,
                # autobuski → × (broj smena − 1); uvek × broj osoba.
                n_smena = len(cen["lanac"])
                puta = n_smena if sopstveni else n_smena - 1
                if umanj_sp > 0 and puta > 0:
                    um = umanj_sp * broj_osoba * puta
                    cena -= um
                    if sopstveni:
                        obr.append(f"Sopstveni prevoz: umanjenje {_fmt(umanj_sp)} × {broj_osoba} osoba × "
                                   f"{puta} smena = −{_fmt(um)} € → {_fmt(cena)} €")
                    else:
                        obr.append(f"Autobuski prevoz: umanjenje {_fmt(umanj_sp)} × {broj_osoba} osoba × "
                                   f"{puta} (smena − 1) = −{_fmt(um)} € → {_fmt(cena)} €")
                elif sopstveni:
                    obr.append("Sopstveni prevoz: umanjenje nije definisano u opcijama (0 €)")
                else:
                    obr.append("Autobuski prevoz: konačna cena (prevoz uključen)")
            if cena < 0:
                cena = Decimal("0")
            osnovna = cena.quantize(Decimal("0.01"))
            # Popusti se NIKAD ne sabiraju: svaki važeći popust = zasebna varijanta (kartica u pretrazi)
            varijante = []
            for pop in (_po_opsegu(cen["popusti"], red["id"], prvi_pid) or []):
                obr_p = list(obr)
                vazi = ((pop["vazi_od"] is None or pop["vazi_od"] <= danas)
                        and (pop["vazi_do"] is None or pop["vazi_do"] >= danas))
                um = Decimal(str(pop["umanjenje"]))
                snizena = None
                if vazi:
                    if pop["umanjenje_vrsta"] == "procenat":
                        snizena = (osnovna * (Decimal("100") - um) / Decimal("100")).quantize(Decimal("0.01"))
                        obr_p.append(f"Popust #{pop['redni']} ({pop['tip_popusta']}): −{_fmt(um)}% → {_fmt(snizena)} €")
                    else:
                        snizena = max(Decimal("0"), osnovna - um).quantize(Decimal("0.01"))
                        obr_p.append(f"Popust #{pop['redni']} ({pop['tip_popusta']}): −{_fmt(um)} € → {_fmt(snizena)} €")
                else:
                    obr_p.append(f"Popust #{pop['redni']} ({pop['tip_popusta']}) postoji ali ne važi danas "
                                 f"({pop['vazi_od']} – {pop['vazi_do']})")
                varijante.append({"popust_redni": pop["redni"], "tip_popusta": pop["tip_popusta"],
                                  "tip_placanja": pop["tip_placanja"], "vazi": vazi,
                                  "cena_snizena": _q2(snizena) if snizena is not None else None,
                                  "obracun": obr_p})
            if not varijante:
                varijante.append({"popust_redni": None, "tip_popusta": None, "tip_placanja": None,
                                  "vazi": False, "cena_snizena": None, "obracun": obr + ["Popust: nema"]})
            prva_vazeca = next((v for v in varijante if v["cena_snizena"] is not None), None)
            return {"nema_cene": False, "cena_osnovna": _q2(osnovna),
                    "cena_snizena": prva_vazeca["cena_snizena"] if prva_vazeca else None,
                    "varijante": varijante,
                    "struktura": struktura, "koeficijent": float(koef),
                    "tip_cene": tip_cene, "obracun": varijante[0]["obracun"], "napomene": napomene,
                    # umanjenje važi samo za po_osobi (kao u obračunu); po_sobi sopstveni nema umanjenja
                    "umanjenje_sopstveni": float(_q2(umanj_sp)) if umanj_sp > 0 and tip_cene != "po_sobi" else None,
                    "umanjenje_smene": len(cen["lanac"])}

        out = []
        for g in smestaji:
            cen = _cenovnik(g["smestaj_id"])
            sobe_out = []
            iskljuceno = 0
            for s in g["sobe"]:
                tip = (s["tip"] or "").strip()
                strukture = [tip] + [d for d in dodatni.get(s["id"], []) if d != tip]
                if izuzetak_koef is not None:
                    # izuzetak za 1 osobu: strukture 1/2 (uklj. 1/2 ECO, 1/2+1, 1/2 · STD); pravilo 2 se ne primenjuje
                    kandidati = [(st, izuzetak_koef) for st in strukture if re.match(r"^1/2(?:[\s+]|$)", st)]
                else:
                    kandidati = [(st, koef_map[st]) for st in strukture if st in koef_map]
                if not kandidati:
                    iskljuceno += 1
                    continue
                najbolji = None
                blokirana = False
                if cen and cen["lanac"]:
                    for st, koef in kandidati:
                        r = _obracun_sobe(cen, s, st, koef, izuz=izuzetak_koef is not None)
                        if r and r.get("blokirano_u_lancu"):
                            blokirana = True
                            break
                        if r is None or r["nema_cene"]:
                            if najbolji is None:
                                najbolji = r
                            continue
                        if najbolji is None or najbolji.get("nema_cene") or \
                           (r["cena_snizena"] or r["cena_osnovna"]) < (najbolji["cena_snizena"] or najbolji["cena_osnovna"]):
                            najbolji = r
                if blokirana:
                    # blokirana smena u lancu (spajanje termina) → soba se ne prikazuje
                    iskljuceno += 1
                    continue
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

    @api.get("/obracun/varijante-cene")
    def obracun_varijante_cene(smestaj_id: int, soba_id: int, datumod: SubDate, datumdo: SubDate,
                               adl: int = 0, chd: int = 0, inf: int = 0,
                               _: dict = Depends(get_current_user)):
        if datumdo <= datumod:
            raise HTTPException(status_code=400, detail="datumdo mora biti posle datumod")
        if min(adl, chd, inf) < 0 or adl + chd + inf == 0:
            raise HTTPException(status_code=400, detail="Unesite bar jednog putnika")
        with engine.connect() as conn:
            return varijante_cene(conn, smestaj_id, soba_id, datumod, datumdo, adl, chd, inf)

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
        sopstveni = prevoz_raw.startswith("sopstveni")
        # postojeći ugovor (obračun/promena plaćanja u Rezervaciji): njegova soba se ne broji kao zauzeta
        iskl = (q.get("iskluci_kljuc") or "").strip() or None
        # opcioni filter na jedan smeštaj (Grafik popup): obračun se računa samo za njega
        smestaj_raw = (q.get("smestaj_id") or "").strip()
        smestaj_filter = int(smestaj_raw) if smestaj_raw.isdigit() else None
        if not od:
            raise HTTPException(status_code=400, detail="datum_od je obavezan")
        try:
            d_od = datetime.strptime(od, "%d.%m.%Y").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Datumi moraju biti u formatu DD.MM.YYYY")
        grupa_id = int(grupa_raw) if grupa_raw.isdigit() else None
        mesto_id = int(mesto_raw) if mesto_raw.isdigit() else None

        def _smestaji_za_termin(conn, d_od, d_do, iskluci_kljuc=None):
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
                SELECT s.id AS smestaj_id, s.naziv AS smestaj_naziv, s.granica_chd,
                       s.prima_decu, s.ne_prima_ispod_godina,
                       b.id, TRIM(b.broj_sobe) AS broj_sobe, b.tip, b.opis, b.opis_dodatno
                FROM sobe b
                JOIN smestaj s ON s.id = b.veza_id_smestaj
                WHERE s.status = 1  -- neaktivni smeštaji se ne nude u pretrazi
                  AND (CAST(:g AS INTEGER) IS NULL OR s.grupa_datuma = CAST(:g AS INTEGER))
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
                        -- postojeći ugovor koji se obračunava ne zauzima sobu sam sebi
                        AND a.kljuc IS DISTINCT FROM CAST(:iskl AS TEXT)
                  )
                ORDER BY s.naziv, b.broj_sobe
            """), {"g": grupa_id, "m": mesto_id, "dod": d_od, "ddo": d_do, "iskl": iskluci_kljuc}).fetchall()
            grouped: dict = {}
            for r in rows:
                g = grouped.setdefault(r.smestaj_id, {
                    "smestaj_id": r.smestaj_id, "smestaj_naziv": r.smestaj_naziv,
                    "granica_chd": float(r.granica_chd),
                    "prima_decu": bool(r.prima_decu),
                    "ne_prima_ispod_godina": r.ne_prima_ispod_godina,
                    "sobe": [],
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
                smestaji = _smestaji_za_termin(conn, d_od, d_do, iskl)
                if smestaj_filter is not None:
                    smestaji = [g for g in smestaji if g["smestaj_id"] == smestaj_filter]
                # smeštaj koji ne prima decu ispod N godina: ako neko od dece
                # putnika ima manje od N, smeštaj se ne nudi (DA ili nedefinisane
                # godine ne utiču na pretragu)
                if godine:
                    smestaji = [
                        g for g in smestaji
                        if g["prima_decu"] or g["ne_prima_ispod_godina"] is None
                        or not any(gd < g["ne_prima_ispod_godina"] for gd in godine)
                    ]
                if not obracun:
                    return smestaji  # stari klijenti bez putnika: samo raspoloživost
                # CHD/ADL po smeštaju: dete do granica_chd = CHD, starije = ADL
                rezultat = []
                for g in smestaji:
                    granica = g["granica_chd"]
                    chd_g = sum(1 for gd in godine if gd <= granica)
                    adl_g = adl + len(godine) - chd_g
                    rezultat.extend(_obracun_cena(conn, [g], d_od, d_do, adl_g, chd_g, 0, sopstveni))
                return rezultat

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
            mesto_id = int(q.get("mesto_id", ""))
            if not sve:
                smestaj_id = int(raw_smestaj)
        except ValueError:
            raise HTTPException(status_code=400, detail="smestaj_id, grupa_id i mesto_id su obavezni")
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
                # Saldo po ugovoru (EUR) — ista logika obračuna kao detalj ugovora.
                # Dodatni popusti jednim batch upitom (ne po ugovoru — N+1 je usporavao grafik).
                popusti_po_kljucu = dodatni_za_ugovori([r.kljuc for r in ugovori])
                ugovori_out = []
                for r in ugovori:
                    popusti = popusti_po_kljucu.get(str(r.kljuc or "").strip().strip("/"), [])
                    calc = calc_ugovor_values(dict(r._mapping), popusti)
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
                # Aktivan cenovnik smeštaja (ista pravila kao pretraga) — osnovne cene po
                # sobi i virtuelnoj sobi za tooltip praznih polja. Datumi perioda DD.MM.YYYY
                # kao u grafiku. Bez aktivnog cenovnika: cenovnik = None.
                cenovnik_out = None
                cen_row = conn.execute(text("""
                    SELECT c.id, c.sobe, c.periodi
                    FROM cenovnici c
                    JOIN cenovnik_opcije o ON o.cenovnik_id = c.id
                    WHERE c.smestaj_id = :sid AND o.datumod <= :d AND o.datumdo >= :d
                    ORDER BY c.id DESC LIMIT 1
                """), {"sid": srow.id, "d": sada.date()}).fetchone()
                if cen_row:
                    def _dmy(s):
                        return datetime.fromisoformat(str(s)[:10]).strftime("%d.%m.%Y")
                    per = {int(p["id"]): p for p in (cen_row.periodi or [])}
                    # Blokada (opcije_soba.blokirano): eksplicitan red po periodu, inače
                    # globalni red (period_id = 0) za sobu — isto pravilo kao opcije-celije
                    blok_rows = conn.execute(text(
                        "SELECT soba_id, period_id, blokirano FROM opcije_soba WHERE cenovnik_id = :c"
                    ), {"c": cen_row.id}).all()
                    blok_globalno = {int(s) for s, pid, b in blok_rows if int(pid) == 0 and b}
                    blok_eksplicitno = {(int(s), int(pid)): bool(b) for s, pid, b in blok_rows if int(pid) != 0}
                    # Popusti po (soba, period): eksplicitan period, inače globalni (period_id = 0)
                    popusti_mapa: dict = {}
                    for pr in conn.execute(text(
                        "SELECT soba_id, period_id, redni, tip_popusta, tip_placanja, umanjenje_vrsta, umanjenje, vazi_od, vazi_do "
                        "FROM popust_soba WHERE cenovnik_id = :c ORDER BY redni"
                    ), {"c": cen_row.id}).mappings():
                        popusti_mapa.setdefault((int(pr["soba_id"]), int(pr["period_id"])), []).append(pr)
                    danas_g = sada.date()
                    cene_out = []
                    for cr in conn.execute(text(
                        "SELECT soba_id, period_id, cena FROM cenovnik_cene WHERE cenovnik_id = :c"
                    ), {"c": cen_row.id}):
                        p = per.get(int(cr.period_id))
                        if p is None:
                            continue
                        sid, pid = int(cr.soba_id), int(cr.period_id)
                        pops = popusti_mapa.get((sid, pid)) or popusti_mapa.get((sid, 0)) or []
                        cene_out.append({
                            "soba_id": sid,
                            "datum_od": _dmy(p["datum_od"]), "datum_do": _dmy(p["datum_do"]),
                            "cena": float(cr.cena),
                            "blokirano": blok_eksplicitno.get((sid, pid), sid in blok_globalno),
                            "popusti": [{
                                "redni": int(pr["redni"]),
                                "tip_popusta": pr["tip_popusta"],
                                "tip_placanja": pr["tip_placanja"],
                                "vrsta": pr["umanjenje_vrsta"],
                                "umanjenje": float(pr["umanjenje"]),
                                "vazi": (pr["vazi_od"] is None or pr["vazi_od"] <= danas_g)
                                        and (pr["vazi_do"] is None or pr["vazi_do"] >= danas_g),
                            } for pr in pops],
                        })
                    cenovnik_out = {
                        "sobe": [{
                            "id": int(s["id"]), "broj_sobe": s.get("broj_sobe") or "",
                            "tip": s.get("tip") or "", "izvor_soba_id": s.get("izvor_soba_id"),
                        } for s in (cen_row.sobe or []) if s.get("id") is not None],
                        "cene": cene_out,
                    }
                return {
                    "smestaj": {"id": srow.id, "naziv": srow.naziv},
                    "cenovnik": cenovnik_out,
                    "periodi": periodi,
                    "sobe": [{
                        "id": r.id, "broj_sobe": r.broj_sobe, "tip": r.tip,
                        "opis": r.opis, "opis_dodatno": r.opis_dodatno,
                    } for r in sobe],
                    "ugovori": ugovori_out,
                }

            if sve:
                # "Prikaži sve" — smeštaji izabranog MESTA u grupi perioda (mesto + grupa)
                srows = conn.execute(text(
                    "SELECT id, naziv, mesto FROM smestaj WHERE grupa_datuma = :g AND mesto = :m AND status = 1 ORDER BY naziv"
                ), {"g": grupa_id, "m": mesto_id}).fetchall()
                return {"sve": True, "sekcije": [sekcija(s) for s in srows]}
            srow = conn.execute(text(
                "SELECT id, naziv, mesto FROM smestaj WHERE id = :id AND mesto = :m AND status = 1"
            ), {"id": smestaj_id, "m": mesto_id}).fetchone()
            if not srow:
                raise HTTPException(status_code=404, detail="Smeštaj nije pronađen u izabranom mestu ili nije aktivan")
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

    # ── Knjigovodstvo: lista ugovora (server-side search/sort/pagination) ───
    UGOVORI_SORT = {"kljuc", "danas", "putnik", "mesto", "naziv", "datumod", "datumdo", "subagent"}
    UGOVORI_SEARCH_COLS = [
        "kljuc", "putnik", "mesto", "naziv", "destinacija", "datumoddo",
        "obradio", "refno", "napomena", "napomena1", "soba", "tiprezervacije",
        "organizator", "poslovnica", "naziv1", "telefon", "adresa",
    ]
    # Kolone iz HTML tabele koje nisu proste kolone aranzman-a → SQL izraz (alias a = aranzman)
    UGOVORI_SEARCH_EXTRA = {
        "danas": "to_char(a.danas, 'DD.MM.YYYY')",
        "datumod": "to_char(a.datumod, 'DD.MM.YYYY')",
        "datumdo": "to_char(a.datumdo, 'DD.MM.YYYY')",
        "subagent": "COALESCE(a.subagent::text, '')",
        "apartman": "COALESCE(a.apartman::text, '')",
        "tip_sobe": "COALESCE((SELECT b.tip FROM sobe b WHERE b.veza_id_smestaj = a.smestaj_id AND TRIM(b.broj_sobe) = TRIM(a.soba) LIMIT 1), '')",
        "saputnici": "COALESCE((SELECT string_agg(ad.saputnik, ' ') FROM aranzman_dopuna ad WHERE ad.aranzman_id = a.id), '')",
    }
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
        dodatni_mapa = dodatni_za_ugovori([r._mapping.get("kljuc") for r in rows])
        for r in rows:
            row = dict(r._mapping)
            calc = calc_ugovor_values(row, dodatni_mapa.get(str(row.get("kljuc") or "").strip().strip("/"), []))
            provizija = calc["provizija"]
            naplata = calc["naplata"]
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

    @api.get("/pregledi/uplate")
    def pregled_uplata(
        datum: Optional[str] = None,
        _: dict = Depends(get_current_user),
    ):
        """Dnevni pregled uplata — sve uplate čiji uplate.danas pada na izabrani dan."""
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
                SELECT kljuc, to_char(danas, 'HH24:MI') AS vreme, id, faktura,
                       ime, nacin, din, svrha, obradio, poslovnica
                FROM uplate
                WHERE danas::date = :d
                ORDER BY danas NULLS LAST, kljuc
            """), {"d": d}).mappings().fetchall()

        kurs, _kurs_datum = get_eur_middle_za_datum(d.isoformat())
        kurs_ok = bool(kurs) and math.isfinite(kurs) and kurs > 0
        out = []
        sum_din = 0.0
        sum_eur = 0.0
        for r in rows:
            din = float(r["din"] or 0)
            eur = round(din / kurs, 2) if kurs_ok else None
            sum_din += din
            if eur is not None:
                sum_eur += eur
            ugovor = str(r["faktura"] or "").strip() or str(r["id"] or "").strip()
            out.append({
                "kljuc": r["kljuc"],
                "vreme": r["vreme"],
                "ugovor": ugovor,
                "ime": r["ime"],
                "nacin": r["nacin"],
                "svrha": r["svrha"],
                "din": round(din, 2),
                "eur": eur,
                "obradio": r["obradio"],
                "poslovnica": r["poslovnica"],
            })

        return {
            "datum": d.strftime("%d.%m.%Y"),
            "kurs": kurs if kurs_ok else None,
            "rows": out,
            "totals": {
                "broj": len(out),
                "din": round(sum_din, 2),
                "eur": round(sum_eur, 2) if kurs_ok else None,
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

    def _num_polje(row: dict, k: str) -> float:
        v = row.get(k)
        try:
            return float(v) if v not in (None, "") else 0.0
        except (TypeError, ValueError):
            return 0.0

    def smestaj_baze(row: dict) -> tuple[float, float]:
        """Bruto smeštaj (EUR, RSD) — ista osnova kao obračun osnovnog popusta (uklj. CHD)."""
        n = lambda k: _num_polje(row, k)
        return (n("kolaranz") * n("cenaaranz") + n("kolchd") * n("cenachd"),
                n("kolaranz") * n("cenaaranzd") + n("kolchd") * n("uplatasmestaj"))

    def smestaj_neto_eur(row: dict) -> float:
        """Smeštaj posle osnovnog popusta (EUR) — osnova za procenat dodatnog popusta."""
        base_eur, _ = smestaj_baze(row)
        return base_eur - _num_polje(row, "popustar") * base_eur / 100

    def dodatni_popusti_iznosi(row: dict, popusti) -> list[dict]:
        """Iznos svakog dodatnog popusta (EUR, RSD). Procenat se računa od smeštaja posle osnovnog popusta."""
        out = []
        for p in popusti or []:
            pct = p.get("procenat")
            if pct is not None:
                # procenat se uvek računa na EUR; isti iznos važi i u din
                eur = float(pct) / 100 * smestaj_neto_eur(row)
                rsd = eur
            else:
                eur, rsd = float(p.get("eur") or 0), float(p.get("rsd") or 0)
            out.append({"id": p.get("id"), "naziv": p.get("naziv"), "procenat": pct,
                        "eur": p.get("eur"), "rsd": p.get("rsd"),
                        "eur_iznos": round(eur, 2), "rsd_iznos": round(rsd, 2)})
        return out

    def dodatni_za_ugovor(kljuc) -> list[dict]:
        """Dodatni popusti na smeštaj za ugovor (po ključu aranžmana)."""
        k = str(kljuc or "").strip().strip("/")
        if not k:
            return []
        with engine.connect() as conn:
            return [dict(r) for r in conn.execute(text("""
                SELECT dp.id, dp.naziv, dp.eur, dp.rsd, dp.procenat
                FROM dodatni_popusti dp JOIN aranzman a ON a.id = dp.aranzman_id
                WHERE a.kljuc = :k ORDER BY dp.id
            """), {"k": k}).mappings().all()]

    def dodatni_za_ugovori(kljucevi) -> dict:
        """Dodatni popusti za više ugovora jednim upitom → {kljuc: [popust, ...]} (isti oblik kao dodatni_za_ugovor)."""
        keys = sorted({str(k or "").strip().strip("/") for k in kljucevi} - {""})
        if not keys:
            return {}
        out: dict = {}
        with engine.connect() as conn:
            for r in conn.execute(text("""
                SELECT a.kljuc, dp.id, dp.naziv, dp.eur, dp.rsd, dp.procenat
                FROM dodatni_popusti dp JOIN aranzman a ON a.id = dp.aranzman_id
                WHERE a.kljuc = ANY(:keys) ORDER BY dp.id
            """), {"keys": keys}).mappings().all():
                out.setdefault(r["kljuc"], []).append(
                    {k: r[k] for k in ("id", "naziv", "eur", "rsd", "procenat")})
        return out

    def calc_ugovor_values(row: dict, dodatni=None) -> dict:
        """Port PHP obračuna iz uplate.php — ulaz: kolone aranzman reda + dodatni popusti na smeštaj."""
        n = lambda k: _num_polje(row, k)

        cenaaranz_c = n("kolaranz") * n("cenaaranz") + n("kolchd") * n("cenachd")
        cenaprevoz_c = n("cenaow") * n("kolow") + n("cenart") * n("kolrt")
        cenaviza_c = n("kolviza") * n("cenaviza")
        popustsmestaj = n("popustar") * cenaaranz_c / 100
        # dodatni popusti: samo na smeštaj, posle osnovnog popusta (provizija se računa od neto smeštaja)
        dodatni_eur = sum(p["eur_iznos"] for p in dodatni_popusti_iznosi(row, dodatni))
        popustprevoz = n("popustpr") * cenaprevoz_c / 100
        popustviza = n("popustvi") * cenaviza_c
        provizijaar = (cenaaranz_c - popustsmestaj - dodatni_eur) * n("procenatar") / 100
        provizijapr = 0.0 if n("cenart") == 0 else n("procenatpr") * n("kolrt")
        provizijapr1 = 0.0 if n("cenaow") == 0 else n("procenatpr") * n("kolow")
        provizijaviza = n("kolviza") * n("procenatvi")
        provizija = provizijaar + provizijapr + provizijapr1 + provizijaviza
        naplata = (cenaaranz_c + cenaprevoz_c + cenaviza_c
                   - popustsmestaj - dodatni_eur - popustprevoz - popustviza
                   - provizijaar - provizijapr - provizijapr1 - provizijaviza
                   + n("cenadod") + n("osiguranje1"))
        uplaceno = n("uplaceno")
        saldo = naplata - uplaceno
        return {
            "smestaj": round(cenaaranz_c, 2),
            "prevoz": round(cenaprevoz_c, 2),
            "viza": round(cenaviza_c, 2),
            "popust": round(popustsmestaj + dodatni_eur + popustprevoz + popustviza, 2),
            "popust_dodatni": round(dodatni_eur, 2),
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
        sql = ("SELECT *, (SELECT COUNT(*) FROM cekovi c WHERE c.uplata_kljuc = uplate.kljuc) AS broj_cekova "
               "FROM uplate WHERE COALESCE(faktura, '') = :broj")
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
            arow_full = conn.execute(text(
                "SELECT * FROM aranzman WHERE kljuc = :k"
            ), {"k": kljuc_clean}).mappings().first()
            logo_row = conn.execute(text(
                "SELECT slika, slika_mime FROM dokumenti WHERE tip = 'logo'"
            )).fetchone()
        # Vrednost aranžmana u EUR (naplata iz obračuna ugovora) — osnova za OSTALO/EUR
        vrednost_eur = calc_ugovor_values(dict(arow_full), dodatni_za_ugovor(arow_full["kljuc"]))["naplata"] if arow_full else None
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
            vrednost_eur=vrednost_eur,
        )
        fname = f"Pregled_uplata_{kljuc_clean.replace('/', '-')}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )

    @api.get("/ugovori/{kljuc:path}/cis-link")
    def ugovor_cis_link(kljuc: str, cena_eur: str | None = Query(None), _: dict = Depends(get_current_user)):
        """Link za CIS (e-dokumenti importData): podaci iz sačuvanog ugovora,
        RGZ/JMBG/kod iz podešavanja agencije i programPutovanjaJID = mesto.cis.
        cena_eur (opciono) = 'Ukupno aranžman (EUR)' sa ekrana rezervacije; bez nje se računa iz ugovora."""
        cena_eur_ekran = cena_eur
        from urllib.parse import urlencode, quote
        import datetime as _dt

        kljuc_clean = kljuc.strip().strip("/")
        with engine.connect() as conn:
            arow = conn.execute(text("SELECT * FROM aranzman WHERE kljuc = :k"), {"k": kljuc_clean}).mappings().first()
            if not arow:
                raise HTTPException(status_code=404, detail="Ugovor nije pronađen")
            dopuni = conn.execute(text(
                "SELECT saputnik, adresa, email, telefon FROM aranzman_dopuna WHERE aranzman_id = :i ORDER BY id"
            ), {"i": arow["id"]}).mappings().all()
            mesto_cis = None
            if arow.get("smestaj_id"):
                mesto_cis = conn.execute(text(
                    "SELECT m.cis FROM smestaj s JOIN mesto m ON m.id = s.mesto WHERE s.id = :s"
                ), {"s": arow["smestaj_id"]}).scalar()
            ag = conn.execute(text("SELECT * FROM agencija ORDER BY id LIMIT 1")).mappings().first()

        if not (mesto_cis or "").strip():
            raise HTTPException(status_code=400, detail="Mesto nema CIS oznaku (programPutovanjaJID) — unesite je u Mesta")
        if not ag or not (ag.get("api_kljuc_cis") or "").strip():
            raise HTTPException(status_code=400, detail="U podešavanjima agencije nedostaje CIS kod")

        def _s(v) -> str:
            return str(v).strip() if v not in (None, "") else ""

        def _broj(v: float) -> str:
            return str(int(v)) if float(v).is_integer() else f"{v:.2f}"

        # Putnici: nosilac + saputnici (max 8)
        putnici = []
        putnik_full = _s(arow.get("putnik"))
        delovi = putnik_full.split(" ", 1)
        putnici.append({
            "ime": delovi[0] if delovi else "",
            "prezime": delovi[1] if len(delovi) > 1 else "",
            "adresa": _s(arow.get("adresa")),
            "email": _s(arow.get("refno")),
            "telefon": _s(arow.get("telefon")),
        })
        for p in dopuni:
            ime_prez = _s(p["saputnik"]).split(" ", 1)
            if not ime_prez[0]:
                continue
            putnici.append({
                "ime": ime_prez[0],
                "prezime": ime_prez[1] if len(ime_prez) > 1 else "",
                "adresa": _s(p["adresa"]),
                "email": _s(p["email"]),
                "telefon": _s(p["telefon"]),
            })
        putnici = putnici[:8]

        # Vrsta prevoza: isto pravilo kao ugovor (DA na prevozow/prevozrt = autobus)
        da = lambda v: str(v or "").strip().lower() in ("1", "true", "da", "-1")
        autobus = da(arow.get("prevozow")) or da(arow.get("prevozrt"))
        vrsta_prevoza = 254 if autobus else 253

        kurs = get_eur_middle()
        calc = calc_ugovor_values(dict(arow), dodatni_za_ugovor(arow.get("kljuc")))
        cena_eur = round(float(calc["naplata"]), 2)
        if cena_eur_ekran not in (None, ""):
            try:
                vrednost = round(float(str(cena_eur_ekran).replace(",", ".")), 2)
            except ValueError:
                raise HTTPException(status_code=400, detail="Neispravna vrednost cene (EUR)")
            cena_eur = vrednost
        cena_rsd = round(cena_eur * kurs, 2) if kurs else None
        od, do = arow.get("datumod"), arow.get("datumdo")
        noci = (do - od).days if od and do else 0

        params = [
            ("programPutovanjaJID", mesto_cis.strip()),
            ("brojUgovora", kljuc_clean),
            ("putnici", str(len(putnici))),
        ]
        for i in range(8):
            p = putnici[i] if i < len(putnici) else {"ime": "", "prezime": "", "adresa": "", "email": "", "telefon": ""}
            n = i + 1
            params += [(f"ime{n}", p["ime"]), (f"prezime{n}", p["prezime"]), (f"adresa{n}", p["adresa"]),
                       (f"email{n}", p["email"]), (f"telefon{n}", p["telefon"])]
        params += [
            ("opstinaRGZSifra", _s(ag.get("opstina_rgz"))),
            ("opstinaNaziv", _s(ag.get("opstina_naziv"))),
            ("mestoRGZSifra", _s(ag.get("mesto_rgz"))),
            ("mestoNaziv", _s(ag.get("mesto_naziv"))),
            ("ulicaRGZSifra", _s(ag.get("ulica_rgz"))),
            ("ulicaNaziv", _s(ag.get("ulica_naziv"))),
            ("cenaStranaVal", _broj(cena_eur)),
            ("valutaSifra", "251"),
            ("nbsKurs", f"{kurs:.2f}" if kurs else ""),
            ("cenaRSD", f"{cena_rsd:.2f}" if cena_rsd is not None else ""),
            ("vrstaPrevozaSifra", str(vrsta_prevoza)),
            ("datumPocetka", od.date().isoformat() if od else ""),
            ("datumZavrsetka", do.date().isoformat() if do else ""),
            ("gradOpstinaPolaska", _s(arow.get("mesto_izlaska")) or _s(arow.get("ulazak")) or "BEOGRAD"),
            ("brojNocenja", str(noci)),
            ("brojDana", str(noci + 1)),
            ("vrstaUslugeSmestajaSifra", "1"),
            ("nazivSmestajnihObjekata", _s(arow.get("naziv"))),
            ("jmbg", _s(ag.get("jmbg"))),
            ("code", _s(ag.get("api_kljuc_cis"))),
        ]
        url = "https://e-dokumenti.in.rs/importData.php?" + urlencode(params, quote_via=quote)
        return {"url": url}

    # ── Knjigovodstvo: unos nove uplate ─────────────────────────────────────
    def _kartica_cisto(conn, k: "KarticaPodaci | None") -> dict:
        """Validira podatke kartice (samo kad je način = Kartica) i vraća čist dict."""
        if k is None:
            raise HTTPException(status_code=400, detail="Unesite podatke kartice")
        tip = (k.tipKartice or "").strip()
        if not tip:
            raise HTTPException(status_code=400, detail="Izaberite tip kartice")
        if conn.execute(text("SELECT 1 FROM tipovi_kartica WHERE naziv = :n"), {"n": tip}).fetchone() is None:
            raise HTTPException(status_code=400, detail="Nepoznat tip kartice")
        broj_kartice = (k.brojKartice or "").strip()
        potvrda = (k.brojPotvrde or "").strip()
        odobrenje = (k.brojOdobrenja or "").strip()
        if len(potvrda) > 100 or len(odobrenje) > 100:
            raise HTTPException(status_code=400, detail="Broj potvrde i broj odobrenja mogu imati najviše 100 znakova")
        return {"broj_potvrde": potvrda or None, "tip_kartice": tip,
                "broj_kartice": broj_kartice or None, "broj_odobrenja": odobrenje or None}

    @api.get("/tipovi-kartica")
    def tipovi_kartica(_: dict = Depends(get_current_user)):
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT naziv FROM tipovi_kartica ORDER BY naziv")).fetchall()
        return [r.naziv for r in rows]

    @api.put("/uplate/{kljuc}/kartica")
    def izmeni_kartica_uplate(kljuc: int, body: KarticaPodaci, current_user: dict = Depends(get_current_user)):
        try:
            user_id = int(current_user["sub"])
        except (KeyError, TypeError, ValueError):
            raise HTTPException(status_code=401, detail="Neautorizovan pristup")
        with engine.begin() as conn:
            stari = conn.execute(text(
                "SELECT id, faktura, nacin, broj_potvrde, tip_kartice, broj_kartice, broj_odobrenja "
                "FROM uplate WHERE kljuc = :k"
            ), {"k": kljuc}).fetchone()
            if not stari:
                raise HTTPException(status_code=404, detail="Uplata nije pronađena")
            if (stari.nacin or "").strip() != "Kartica":
                raise HTTPException(status_code=400, detail="Uplata nije evidentirana karticom")
            novo = _kartica_cisto(conn, body)
            conn.execute(text(
                "UPDATE uplate SET broj_potvrde = :broj_potvrde, tip_kartice = :tip_kartice, "
                "broj_kartice = :broj_kartice, broj_odobrenja = :broj_odobrenja WHERE kljuc = :k"
            ), {**novo, "k": kljuc})
            obradio_row = conn.execute(text(
                "SELECT first_name, last_name FROM users WHERE id = :id"
            ), {"id": user_id}).fetchone()
            obradio = f"{(obradio_row.first_name or '').strip()} {(obradio_row.last_name or '').strip()}".strip() if obradio_row else ""
            promene = []
            for polje, labela in (("broj_potvrde", "Broj potvrde"), ("tip_kartice", "Tip kartice"),
                                  ("broj_kartice", "Broj kartice"), ("broj_odobrenja", "Broj odobrenja")):
                if (getattr(stari, polje) or None) != novo[polje]:
                    promene.append({"polje": labela, "stara": getattr(stari, polje), "nova": novo[polje]})
            if promene:
                arow = conn.execute(text(
                    "SELECT kljuc FROM aranzman WHERE split_part(kljuc, '/', 1) = :b "
                    "ORDER BY id DESC LIMIT 1"
                ), {"b": stari.faktura or ""}).fetchone()
                zabelezi(conn, arow.kljuc if arow else (stari.faktura or ""), OBLAST_UPLATA,
                         "uplata_kartica_izmenjena", user_id, obradio, promene)
        return {"status": "sacuvano", "kljuc": kljuc}

    @api.get("/uplate/{kljuc}/cekovi")
    def lista_cekova_uplate(kljuc: int, _: dict = Depends(get_current_user)):
        with engine.connect() as conn:
            if not conn.execute(text("SELECT 1 FROM uplate WHERE kljuc = :k"), {"k": kljuc}).fetchone():
                raise HTTPException(status_code=404, detail="Uplata nije pronađena")
            rows = conn.execute(text("""
                SELECT c.redni, to_char(c.datum, 'YYYY-MM-DD') AS datum, c.iznos, c.banka, c.banka_klijenta,
                       bk.naziv AS banka_klijenta_naziv,
                       c.broj_racuna_banke, c.broj_racuna_klijenta, c.serijski_broj
                FROM cekovi c LEFT JOIN banke bk ON bk.id = c.banka_klijenta
                WHERE c.uplata_kljuc = :k ORDER BY c.redni
            """), {"k": kljuc}).fetchall()
        return [
            {
                "redni": r.redni, "datum": r.datum, "iznos": float(r.iznos), "banka": r.banka,
                "bankaKlijentaId": r.banka_klijenta, "bankaKlijentaNaziv": r.banka_klijenta_naziv,
                "brojRacunaBanke": r.broj_racuna_banke, "brojRacunaKlijenta": r.broj_racuna_klijenta,
                "serijskiBroj": r.serijski_broj or "",
            }
            for r in rows
        ]

    @api.put("/uplate/{kljuc}/cekovi")
    def izmeni_cekove_uplate(kljuc: int, body: CekoviPodaci, current_user: dict = Depends(get_current_user)):
        try:
            user_id = int(current_user["sub"])
        except (KeyError, TypeError, ValueError):
            raise HTTPException(status_code=401, detail="Neautorizovan pristup")
        with engine.begin() as conn:
            stari = conn.execute(text(
                "SELECT id, faktura, nacin, din FROM uplate WHERE kljuc = :k"
            ), {"k": kljuc}).fetchone()
            if not stari:
                raise HTTPException(status_code=404, detail="Uplata nije pronađena")
            if (stari.nacin or "").strip() != "Ček":
                raise HTTPException(status_code=400, detail="Uplata nije evidentirana čekovima")
            novi = _cekovi_cisto(body.cekovi, float(stari.din))
            for bid in {c["banka_klijenta"] for c in novi}:
                if not conn.execute(text("SELECT 1 FROM banke WHERE id = :i"), {"i": bid}).fetchone():
                    raise HTTPException(status_code=400, detail=f"Banka klijenta {bid} ne postoji u tabeli banke")
            stari_c = {r.redni: r for r in conn.execute(text(
                "SELECT redni, datum, iznos, serijski_broj FROM cekovi WHERE uplata_kljuc = :k"
            ), {"k": kljuc}).fetchall()}
            conn.execute(text("DELETE FROM cekovi WHERE uplata_kljuc = :k"), {"k": kljuc})
            for c in novi:
                conn.execute(text("""
                    INSERT INTO cekovi (uplata_kljuc, faktura, redni, datum, iznos, banka, banka_klijenta,
                                        broj_racuna_banke, broj_racuna_klijenta, serijski_broj)
                    VALUES (:uplata_kljuc, :faktura, :redni, :datum, :iznos, :banka, :banka_klijenta,
                            :broj_racuna_banke, :broj_racuna_klijenta, :serijski_broj)
                """), {**c, "uplata_kljuc": kljuc, "faktura": stari.faktura or ""})

            promene = []
            nova_map = {c["redni"]: c for c in novi}
            for r, s in sorted(stari_c.items()):
                n = nova_map.get(r)
                if n is None:
                    promene.append({"polje": f"Ček {r}", "stara": float(s.iznos), "nova": "obrisan"})
                    continue
                if float(s.iznos) != n["iznos"]:
                    promene.append({"polje": f"Ček {r} — iznos", "stara": float(s.iznos), "nova": n["iznos"]})
                if (s.serijski_broj or "") != n["serijski_broj"]:
                    promene.append({"polje": f"Ček {r} — serijski broj", "stara": s.serijski_broj or None,
                                    "nova": n["serijski_broj"] or None})
                if s.datum.isoformat() != n["datum"].isoformat():
                    promene.append({"polje": f"Ček {r} — datum", "stara": s.datum.isoformat(),
                                    "nova": n["datum"].isoformat()})
            for r in sorted(set(nova_map) - set(stari_c)):
                promene.append({"polje": f"Ček {r}", "stara": None, "nova": nova_map[r]["iznos"]})
            if promene:
                obradio_row = conn.execute(text(
                    "SELECT first_name, last_name FROM users WHERE id = :id"
                ), {"id": user_id}).fetchone()
                obradio = (f"{(obradio_row.first_name or '').strip()} {(obradio_row.last_name or '').strip()}".strip()
                           if obradio_row else "")
                arow = conn.execute(text(
                    "SELECT kljuc FROM aranzman WHERE split_part(kljuc, '/', 1) = :b "
                    "ORDER BY id DESC LIMIT 1"
                ), {"b": stari.faktura or ""}).fetchone()
                zabelezi(conn, arow.kljuc if arow else (stari.faktura or ""), OBLAST_UPLATA,
                         "uplata_cekovi_izmenjeni", user_id, obradio, promene)
        return {"status": "sacuvano", "kljuc": kljuc, "broj_cekova": len(novi)}

    class PrebacivanjeUplate(BaseModel):
        ugovor: str

    @api.post("/uplate/{kljuc}/prebaci")
    def prebaci_uplatu(kljuc: int, body: PrebacivanjeUplate, current_user: dict = Depends(get_current_user)):
        """Povraćaj: prebacuje uplatu sa trenutnog ugovora na drugi ugovor.
        uplate.id / uplate.faktura → novi ugovor; napomene interne oba ugovora se dopunjuju;
        datum prebacivanja = danas."""
        try:
            user_id = int(current_user["sub"])
        except (KeyError, TypeError, ValueError):
            raise HTTPException(status_code=401, detail="Neautorizovan pristup")
        ugovor = (body.ugovor or "").strip().strip("/")
        if not ugovor:
            raise HTTPException(status_code=400, detail="Izaberite ugovor na koji se uplata prebacuje")
        with engine.begin() as conn:
            stari = conn.execute(text(
                "SELECT kljuc, id, faktura, din, nacin FROM uplate WHERE kljuc = :k"
            ), {"k": kljuc}).fetchone()
            if not stari:
                raise HTTPException(status_code=404, detail="Uplata nije pronađena")
            broj_stari = (stari.faktura or "").strip() or str(stari.id or "")
            if "/" in ugovor:
                nov = conn.execute(text(
                    "SELECT kljuc, napomena, tiprezervacije FROM aranzman WHERE kljuc = :k ORDER BY id DESC LIMIT 1"
                ), {"k": ugovor}).fetchone()
            else:
                nov = conn.execute(text(
                    "SELECT kljuc, napomena, tiprezervacije FROM aranzman WHERE split_part(kljuc, '/', 1) = :b "
                    "ORDER BY id DESC LIMIT 1"
                ), {"b": ugovor}).fetchone()
            if not nov:
                raise HTTPException(status_code=404, detail="Ugovor nije pronađen")
            if (nov.tiprezervacije or "").strip().upper() == "STORNO":
                raise HTTPException(status_code=400, detail="Uplata se ne može prebaciti na ugovor tipa STORNO")
            broj_novi = (nov.kljuc or "").split("/")[0].strip()
            if broj_novi == broj_stari:
                raise HTTPException(status_code=400, detail="Uplata je već na tom ugovoru")
            try:
                nid = int(broj_novi)
            except ValueError:
                raise HTTPException(status_code=400, detail="Neispravan broj ugovora")
            stari_ar = conn.execute(text(
                "SELECT kljuc, napomena FROM aranzman WHERE split_part(kljuc, '/', 1) = :b "
                "ORDER BY id DESC LIMIT 1"
            ), {"b": broj_stari}).fetchone()
            if not stari_ar:
                raise HTTPException(status_code=404, detail="Polazni ugovor nije pronađen")

            iznos = float(stari.din or 0)
            iznos_txt = f"{iznos:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            add_stari = f"Prebačena uplata {iznos_txt} din na novi aranžman {nov.kljuc}"
            add_novi = f"Prebačena uplata {iznos_txt} din sa starog ugovora {stari_ar.kljuc}"

            def _dopuni(staro: str | None, dodatak: str) -> str:
                tekst = f"{(staro or '').strip()}\n{dodatak}".strip() if (staro or "").strip() else dodatak
                if len(tekst) > 1024:
                    raise HTTPException(status_code=400,
                                        detail="Napomena ugovora je prepunjena — skratite je pa ponovite prebacivanje")
                return tekst

            conn.execute(text("UPDATE aranzman SET napomena = :n WHERE kljuc = :k"),
                         {"n": _dopuni(stari_ar.napomena, add_stari), "k": stari_ar.kljuc})
            conn.execute(text("UPDATE aranzman SET napomena = :n WHERE kljuc = :k"),
                         {"n": _dopuni(nov.napomena, add_novi), "k": nov.kljuc})
            sada = _belgrade_now()
            conn.execute(text(
                "UPDATE uplate SET id = :nid, faktura = :nb, prebaceno_sa = :sb, datum_prebacivanja = :dp "
                "WHERE kljuc = :k"
            ), {"nid": nid, "nb": broj_novi, "sb": broj_stari, "dp": sada, "k": kljuc})

            obradio_row = conn.execute(text(
                "SELECT first_name, last_name FROM users WHERE id = :id"
            ), {"id": user_id}).fetchone()
            obradio = f"{(obradio_row.first_name or '').strip()} {(obradio_row.last_name or '').strip()}".strip() if obradio_row else ""
            conn.execute(text(
                "INSERT INTO prebacivanje (datum, uplata_kljuc, iznos, stari_ugovor, novi_ugovor, operater_id, operater) "
                "VALUES (:dp, :uk, :iznos, :stari, :novi, :uid, :op)"
            ), {"dp": sada, "uk": kljuc, "iznos": iznos, "stari": stari_ar.kljuc,
                "novi": nov.kljuc, "uid": user_id, "op": obradio})
            zabelezi(conn, stari_ar.kljuc, OBLAST_UPLATA, "uplata_prebacena_odlazna", user_id, obradio, [
                {"polje": "Prebačena na ugovor", "stara": None, "nova": nov.kljuc},
                {"polje": "Iznos (DIN)", "stara": norm_vrednost(iznos), "nova": None},
            ])
            zabelezi(conn, nov.kljuc, OBLAST_UPLATA, "uplata_prebacena_dolazna", user_id, obradio, [
                {"polje": "Prebačena sa ugovora", "stara": None, "nova": stari_ar.kljuc},
                {"polje": "Iznos (DIN)", "stara": None, "nova": norm_vrednost(iznos)},
            ])
        return {"status": "prebaceno", "kljuc": kljuc, "ugovor": nov.kljuc}

    register_zabrana(api, engine, get_current_user, lambda: get_eur_middle(),
                     lambda r: calc_ugovor_values(r, dodatni_za_ugovor(r.get("kljuc"))))

    @api.get("/prebacivanja")
    def lista_prebacivanja(q: str = "", limit: int = 500, _: dict = Depends(get_current_user)):
        """Evidencija prebačenih uplata (tabela prebacivanje), najnovije prve."""
        limit = max(1, min(int(limit), 2000))
        sql = ("SELECT id, datum, uplata_kljuc, iznos, stari_ugovor, novi_ugovor, operater_id, operater "
               "FROM prebacivanje")
        bind: dict = {"lim": limit}
        pojam = (q or "").strip()
        if pojam:
            sql += (" WHERE stari_ugovor ILIKE :q OR novi_ugovor ILIKE :q OR operater ILIKE :q"
                    " OR CAST(uplata_kljuc AS TEXT) ILIKE :q")
            bind["q"] = f"%{pojam}%"
        sql += " ORDER BY datum DESC, id DESC LIMIT :lim"
        with engine.connect() as conn:
            rows = conn.execute(text(sql), bind).fetchall()
        out = []
        for r in rows:
            d = dict(r._mapping)
            d["datum"] = d["datum"].isoformat() if d.get("datum") else None
            out.append(d)
        return {"rows": out, "total": len(out)}

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
        if not math.isfinite(din) or din == 0:
            raise HTTPException(status_code=400, detail="Iznos mora biti broj različit od nule")
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
                "SELECT u.id, u.first_name, u.last_name, u.status, p.naziv AS poslovnica_naziv "
                "FROM users u LEFT JOIN poslovnice p ON p.id = u.poslovnica_id "
                "WHERE u.id = :id"
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
            # kartica i čekovi se dodaju posle unosa uplate (PUT /uplate/{kljuc}/kartica i /cekovi)
            kartica = {"broj_potvrde": None, "tip_kartice": None, "broj_kartice": None, "broj_odobrenja": None}

            new_kljuc = conn.execute(text("""
                INSERT INTO uplate
                    (id, danas, ime, adresa, nacin, din, evro, uevro, svrha,
                     obradio, vrsta, faktura, destinacija, mesto, subagent,
                     organizator, poslovnica,
                     broj_potvrde, tip_kartice, broj_kartice, broj_odobrenja)
                VALUES
                    (:id, :danas, :ime, :adresa, :nacin, :din, :evro, :uevro, :svrha,
                     :obradio, :vrsta, :faktura, :destinacija, :mesto, :subagent,
                     :organizator, :poslovnica,
                     :broj_potvrde, :tip_kartice, :broj_kartice, :broj_odobrenja)
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
                "poslovnica": urow.poslovnica_naziv or arow.poslovnica,
                **kartica,
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

    @api.post("/uplate/{kljuc}/fiskal")
    def uplata_fiskal(kljuc: int, current_user: dict = Depends(get_current_user)):
        """Fiskalizacija već sačuvane uplate. Uspešno poslata uplata se ne šalje ponovo."""
        import httpx
        import time
        from fiskal import (FISKAL_INVOICE_PAUSA_SEC, build_fiskal_params, dohvati_invoice, invoice_odbijen, je_uspeh,
                            parsiraj_invoice, posalji_fiskal)

        try:
            user_id = int(current_user["sub"])
        except (KeyError, TypeError, ValueError):
            raise HTTPException(status_code=401, detail="Neautorizovan pristup")

        with engine.connect() as conn:
            u = conn.execute(text("SELECT * FROM uplate WHERE kljuc = :k"), {"k": kljuc}).mappings().first()
            if not u:
                raise HTTPException(status_code=404, detail="Uplata nije pronađena")
            if u["fiskal_poslato"]:
                raise HTTPException(status_code=409, detail="Uplata je već fiskalizovana")
            urow = conn.execute(text(
                "SELECT u.username, u.first_name, u.last_name, p.naziv AS poslovnica_naziv FROM users u "
                "LEFT JOIN poslovnice p ON p.id = u.poslovnica_id WHERE u.id = :id"
            ), {"id": user_id}).mappings().first()
            if not urow:
                raise HTTPException(status_code=401, detail="Neautorizovan pristup")
            ag = conn.execute(text(
                "SELECT pib, fiskal_zahtev_link, fiskal_odgovor_link FROM agencija ORDER BY id LIMIT 1"
            )).mappings().first()
            broj_ugovora_bez_godine = str((u["faktura"] or "").strip() or u["id"])
            ar = conn.execute(text(
                "SELECT kljuc, mesto, datumod FROM aranzman "
                "WHERE split_part(kljuc, '/', 1) = :b ORDER BY id DESC LIMIT 1"
            ), {"b": broj_ugovora_bez_godine}).mappings().first()

        if not ar:
            raise HTTPException(status_code=404, detail="Ugovor za uplatu nije pronađen")
        if not ag or not (ag["pib"] or "").strip():
            raise HTTPException(status_code=422, detail="PIB agencije nije podešen (Osnovni podaci)")
        zahtev_url = (ag["fiskal_zahtev_link"] or "").strip()
        odgovor_url = (ag["fiskal_odgovor_link"] or "").strip()
        if not zahtev_url or not odgovor_url:
            raise HTTPException(status_code=422, detail="Linkovi za fiskalizaciju nisu podešeni (Osnovni podaci)")

        danas = u["danas"] or _belgrade_now()
        artikal = f"{ar['kljuc']} / {ar['mesto']} / {ar['datumod'].strftime('%d.%m.%Y') if ar['datumod'] else ''}"
        ime_prezime = f"{(urow['first_name'] or '').strip()} {(urow['last_name'] or '').strip()}".strip()
        korisnik = ime_prezime or (urow["username"] or "").strip()
        poslovnica = (urow["poslovnica_naziv"] or u["poslovnica"] or "").strip()
        try:
            params = build_fiskal_params(
                uplata_kljuc=kljuc,
                broj_priznanice=f"{kljuc}/{((ar['datumod'].year if ar['datumod'] else danas.year) % 100):02d}",
                aranzman_kljuc=ar["kljuc"],
                artikal=artikal,
                nacin=u["nacin"] or "",
                din=float(u["din"] or 0),
                datum_iso=danas.date().isoformat(),
                pib=ag["pib"].strip(),
                poslovnica=poslovnica,
                korisnik=korisnik,
                cashier=ime_prezime,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

        try:
            http_status, tekst = posalji_fiskal(zahtev_url, params)
        except httpx.TimeoutException:
            http_status, tekst = 0, "Fiskalni servis nije odgovorio u roku od 8 sekundi"
        except httpx.HTTPError as exc:
            http_status, tekst = 0, f"Greška veze sa fiskalnim servisom: {exc}"

        uspeh = je_uspeh(http_status, tekst)
        invoice = link_racuna = None
        invoice_status, invoice_tekst = None, None
        if uspeh:
            time.sleep(FISKAL_INVOICE_PAUSA_SEC)
            try:
                invoice_status, invoice_tekst = dohvati_invoice(odgovor_url, params["req_id"])
                invoice, link_racuna = parsiraj_invoice(invoice_tekst)
                if invoice_odbijen(invoice_tekst):
                    uspeh = False
            except httpx.HTTPError:
                invoice_status, invoice_tekst = 0, None

        with engine.begin() as conn:
            conn.execute(text(
                "UPDATE uplate SET fiskal_odgovor = :o, fiskal_poslato = :p, "
                "fiskal_invoice = COALESCE(:inv, fiskal_invoice), fiskal_link = COALESCE(:lnk, fiskal_link) "
                "WHERE kljuc = :k"
            ), {"o": tekst, "p": uspeh, "inv": invoice, "lnk": link_racuna, "k": kljuc})

        return {
            "uspeh": uspeh,
            "http_status": http_status or None,
            "odgovor": tekst,
            "invoice": invoice,
            "link_racuna": link_racuna,
            "invoice_http_status": invoice_status or None,
            "invoice_odgovor": invoice_tekst,
        }

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
                SELECT a.*,
                       to_char(a.datumod, 'DD.MM.YYYY') AS od,
                       to_char(a.datumdo, 'DD.MM.YYYY') AS do
                FROM aranzman a
                WHERE split_part(a.kljuc, '/', 1) = :broj
                ORDER BY a.id DESC LIMIT 1
            """), {"broj": str((u._mapping.get("faktura") or "").strip() or u.id)}).mappings().first()
            # Grad i email uplatioca: nosilac → aranzman (grad, refno = email);
            # saputnik (ime se ne poklapa sa nosiocem) → red u aranzman_dopuna
            ime_up = str(u._mapping.get("ime") or "").strip().upper()
            kontakt = None
            if ar and ime_up and ime_up != str(ar.get("putnik") or "").strip().upper():
                kontakt = conn.execute(text("""
                    SELECT grad, email FROM aranzman_dopuna
                    WHERE aranzman_id = :i AND UPPER(TRIM(saputnik)) = :ime
                    ORDER BY id LIMIT 1
                """), {"i": ar["id"], "ime": ime_up}).mappings().first()
        # Preostalo za uplatu (EUR) = naplata ugovora − zbir uplata (isto kao Pregled uplata)
        preostalo_eur = None
        if ar:
            uplate_ug = _uplate_za_ugovor(ar["kljuc"])
            uplaceno_eur = sum((r.get("suma_eur") or 0) for r in uplate_ug)
            preostalo_eur = round(calc_ugovor_values(dict(ar), dodatni_za_ugovor(ar["kljuc"]))["naplata"] - uplaceno_eur, 2)

        logo_data_url = None
        if logo_row and logo_row.slika:
            mime = logo_row.slika_mime or "image/png"
            logo_data_url = f"data:{mime};base64,{logo_row.slika}"
        uplata = dict(u._mapping)
        aranzman = dict(ar) if ar else None
        if not (uplata.get("ime") or "").strip() and aranzman:
            uplata["ime"] = aranzman.get("putnik")
        if not (uplata.get("adresa") or "").strip() and aranzman:
            uplata["adresa"] = aranzman.get("adresa")
        if kontakt is not None:
            uplata["grad"] = kontakt.get("grad")
            uplata["email"] = kontakt.get("email")
        elif aranzman:
            uplata["grad"] = aranzman.get("grad")
            uplata["email"] = aranzman.get("refno")
        pdf_bytes = build_priznanica_pdf(
            uplata=uplata,
            aranzman=aranzman,
            agencija=dict(ag._mapping) if ag else None,
            logo_data_url=logo_data_url,
            preostalo_eur=preostalo_eur,
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
                "SELECT u.id, u.first_name, u.last_name, u.status, p.naziv AS poslovnica_naziv "
                "FROM users u LEFT JOIN poslovnice p ON p.id = u.poslovnica_id "
                "WHERE u.id = :id"
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

    def rez_saputnici_snimak(saputnici: list[RezPutnikIn], conn) -> list[dict]:
        """Saputnici iz forme u obliku aranzman_dopuna kolona — za diff u logu."""
        out = []
        for s in saputnici:
            if not s.ime.strip():
                continue
            out.append({
                "saputnik": s.ime.strip()[:200],
                "rodjen": _rez_datum(s.datumRodjenja, "Datum rođenja saputnika"),
                "pasos": _rez_str(s.pasos, 50),
                "uzrast": _rez_str(s.uzrast, 20),
                "prevozow": 1 if s.ow else 0,
                "prevozrt": 1 if s.rt else 0,
                "prevozsp": 1 if s.sp else 0,
                "smer": _rez_str(s.smer, 50) if s.ow else None,
                "adresa": (s.adresa or "").strip()[:300],
                "grad": _rez_str(s.grad, 100),
                "email": (s.email or "").strip()[:300],
                "telefon": (s.telefon or "").strip()[:300],
                "ulazak": _rez_str(s.ulazak, 200),
                "mesto_izlaska": _rez_str(s.mestoIzlaska, 200) or _rez_str(s.ulazak, 200),
                "dodatno_sediste": bool(s.dodatnoSediste),
                **_rez_prevoz_polja(s, conn),
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
            pv = _rez_prevoz_polja(s, conn)
            conn.execute(text("""
                INSERT INTO aranzman_dopuna
                    (aranzman_id, saputnik, rodjen, pasos, prevozow, prevozrt, prevozsp, smer,
                     adresa, grad, email, telefon, ulazak, mesto_izlaska, uzrast, viza,
                     mesto_sedenja, placeno_prevoz, zelja_prevoz, datum_ow, destinacija_ow,
                     datum_polaska, destinacija_polaska, datum_povratka, destinacija_povratka,
                     destinacija_ow_id, destinacija_polaska_id, destinacija_povratka_id,
                     dodatno_sediste)
                VALUES (:aid, :ime, :rodjen, :pasos, :ow, :rt, :sp, :smer,
                        :adresa, :grad, :email, :telefon, :ulazak, :mesto_izlaska, :uzrast, :viza,
                        :mesto_sedenja, :placeno_prevoz, :zelja_prevoz, :datum_ow, :destinacija_ow,
                        :datum_polaska, :destinacija_polaska, :datum_povratka, :destinacija_povratka,
                        :destinacija_ow_id, :destinacija_polaska_id, :destinacija_povratka_id,
                        :dodatno_sediste)
            """), {
                "aid": aranzman_id,
                "ime": s.ime.strip()[:200],
                "rodjen": _rez_datum(s.datumRodjenja, "Datum rođenja saputnika"),
                "pasos": _rez_str(s.pasos, 50),
                "ow": 1 if s.ow else 0,
                "rt": 1 if s.rt else 0,
                "sp": 1 if s.sp else 0,
                "smer": _rez_str(s.smer, 50) if s.ow else None,
                "adresa": (s.adresa or "").strip()[:300],
                "grad": _rez_str(s.grad, 100),
                "email": (s.email or "").strip()[:300],
                "telefon": (s.telefon or "").strip()[:300],
                "ulazak": _rez_str(s.ulazak, 200),
                "mesto_izlaska": _rez_str(s.mestoIzlaska, 200) or _rez_str(s.ulazak, 200),
                "uzrast": _rez_str(s.uzrast, 20) or (st.uzrast if st else None),
                "viza": st.viza if st else None,
                "dodatno_sediste": bool(s.dodatnoSediste),
                **pv,
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
        if n.uzrast.strip() not in ("ADL", "CHD", "INF"):
            raise HTTPException(status_code=400, detail="Uzrast nosioca je obavezan (ADL / CHD / INF)")
        for i, s in enumerate(body.saputnici, start=1):
            if s.ime.strip() and s.uzrast.strip() not in ("ADL", "CHD", "INF"):
                raise HTTPException(status_code=400, detail=f"Uzrast saputnika {i} je obavezan (ADL / CHD / INF)")

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
        destinacija_prevoz_id = None
        if body.destinacijaPrevozId is not None:
            if not conn.execute(text("SELECT 1 FROM destinacija_prevoz WHERE id = :i"),
                                {"i": body.destinacijaPrevozId}).first():
                raise HTTPException(status_code=400, detail="Destinacija prevoza ne postoji")
            destinacija_prevoz_id = body.destinacijaPrevozId
        soba_broj = None
        if b.sobaId is not None:
            r = conn.execute(text("SELECT broj_sobe FROM sobe WHERE id = :i"), {"i": b.sobaId}).fetchone()
            if r:
                soba_broj = (r.broj_sobe or "").strip() or None
        if soba_broj is None:
            soba_broj = _rez_str(b.sobaBroj, 200)
        # Smeštajna jedinica iz izabrane (stvarne) sobe: apartman = sobe.tip, opis = sobe.opis;
        # gde = struktura VIRTUELNE sobe — Grafik/Pretraga šalju stvarnu sobu + strukturu
        # izabranog reda cenovnika; ako je to dodatni koeficijent sobe (≠ sobe.tip),
        # izabrana je virtuelna soba (npr. FLORA A v15-1 → soba 15, gde = 1/3).
        # Soba van šifarnika (stari ugovor) → kolone se ne diraju.
        smestajna_polja: dict = {}
        if b.sobaId is not None:
            srow = conn.execute(text(
                "SELECT TRIM(COALESCE(tip, '')) AS tip, TRIM(COALESCE(opis, '')) AS opis FROM sobe WHERE id = :i"
            ), {"i": b.sobaId}).fetchone()
            if srow:
                def _norm_str(v) -> str:
                    return re.sub(r"\s+", "", v or "").upper()
                struktura_val = (b.struktura or "").strip()
                gde_val = None
                if struktura_val and _norm_str(struktura_val) != _norm_str(srow.tip):
                    for (k_str,) in conn.execute(text(
                        "SELECT TRIM(struktura) FROM soba_koeficijenti WHERE soba_id = :i ORDER BY id"
                    ), {"i": b.sobaId}).fetchall():
                        if _norm_str(k_str) == _norm_str(struktura_val):
                            gde_val = k_str[:200]
                            break
                smestajna_polja = {
                    "apartman": srow.tip[:10] or None,
                    "opis": srow.opis[:20] or None,
                    "gde": gde_val,
                }

        # obavezna provera zauzeća pre upisa (POST i PUT; PUT izuzima sebe)
        _rez_proveri_konflikt(conn, smestaj_naziv, soba_broj, datum_od, datum_do, exclude_kljuc)

        # bruto osnove za konverziju iznosa u procente
        bruto_sm_eur = round(c.cenaSmestajEUR * c.kolSmestajEUR, 2)
        bruto_sm_rsd = round(c.cenaSmestajRSD * c.kolSmestajRSD, 2)
        bruto_pr_eur = round(c.cenaPrevozEUR * c.kolPrevozEUR, 2)
        bruto_pr_rsd = round(c.cenaPrevozRSD * c.kolPrevozRSD, 2)

        popustar = _rez_procenat_iz_reda(c.popustSmestaj, bruto_sm_eur, bruto_sm_rsd)
        popustpr = _rez_procenat_iz_reda(c.popustPrevoz, bruto_pr_eur, bruto_pr_rsd)
        # provizija smeštaja = procenat × (bruto − popust): iznos → % računamo nad NETO osnovom
        neto_sm_eur = round(bruto_sm_eur * (1 - popustar / 100.0), 2)
        neto_sm_rsd = round(bruto_sm_rsd * (1 - popustar / 100.0), 2)
        procenatar = _rez_procenat_iz_reda(c.provizijaSmestaj, neto_sm_eur, neto_sm_rsd)
        # provizija prevoza: legacy obračun = procenatpr × količina (iznos po osobi); računa se nad NETO prevozom
        neto_pr_eur = round(bruto_pr_eur * (1 - popustpr / 100.0), 2)
        neto_pr_rsd = round(bruto_pr_rsd * (1 - popustpr / 100.0), 2)
        prv_ukupno = _rez_red_ukupno(c.provizijaPrevoz, neto_pr_eur, neto_pr_rsd)
        kol_pr = c.kolPrevozRSD if (c.provizijaPrevoz.eur is None and c.provizijaPrevoz.rsd is not None) \
            else c.kolPrevozEUR
        procenatpr = round(prv_ukupno / kol_pr, 2) if prv_ukupno is not None and kol_pr > 0 else 0.0

        ow, rt = bool(n.ow), bool(n.rt)
        kol_pr_int = int(round(c.kolPrevozEUR))
        return {
            "putnik": n.ime.strip()[:200],
            "rodjen": _rez_datum(n.datumRodjenja, "Datum rođenja"),
            "pasos": _rez_str(n.pasos, 50),
            "uzrast": _rez_str(n.uzrast, 20),
            "adresa": (n.adresa or "").strip()[:200],
            "grad": _rez_str(n.grad, 100),
            "telefon": (n.telefon or "").strip()[:200],
            "refno": _rez_str(n.email, 200),  # refno = email (isti maping kao pri učitavanju)
            "prevozow": 1 if ow else 0,
            "prevozrt": 1 if rt else 0,
            "prevozsp": 1 if n.sp else 0,
            "smer": _rez_str(n.smer, 50) if ow else None,
            "tiprezervacije": _rez_str(body.tiprezervacije, 200),
            "subagent": (body.subagent or "").strip()[:300],
            "timelimit": _rez_ts(body.timelimit),
            "mesto": mesto_naziv,
            "naziv": smestaj_naziv,
            "smestaj_id": smestaj_id_val,
            "soba": soba_broj,
            **smestajna_polja,
            "destinacija": destinacija_naziv,
            "destinacija_prevoz_id": destinacija_prevoz_id,
            "datumod": datetime(datum_od.year, datum_od.month, datum_od.day),
            "datumdo": datetime(datum_do.year, datum_do.month, datum_do.day),
            "datumoddo": f"{datum_od:%d.%m.%Y}-{datum_do:%d.%m.%Y}",
            "napomena": (b.napomena or "")[:1024],
            "napomena1": _rez_str(b.napomenaInterna, 255),
            "ulazak": _rez_str(body.ulazak, 200),
            "mesto_izlaska": _rez_str(body.izlazak, 200) or _rez_str(body.ulazak, 200),
            "viza": 1 if b.viza else 0,
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
            # obradio i poslovnica se upisuju SAMO pri kreiranju (vidi kreiraj_rezervaciju)
            "napomena_prevoz": _rez_str(body.napomenaPrevoz, 500),
            "nacin_placanja": body.nacinPlacanja if body.nacinPlacanja in ("delimicno", "u_celosti") else None,
            **_rez_prevoz_polja(n, conn),
        }

    def rez_transferi_upisi(conn, kljuc: str, transferi: list[RezTransferStavka]):
        """Zamena izračunatih stavki ugovora (TRANSFER i PLAĆENO MESTO; dodatne.ugovor = ceo ključ).
        Redovi sa tim prefiksima se brišu pa ponovo upisuju; nulti iznosi se preskaču."""
        ugovor = kljuc.strip().strip("/")
        if not re.fullmatch(r"[0-9]+(/[0-9]+)?", ugovor):
            raise HTTPException(status_code=400, detail="Neispravan broj ugovora")
        conn.execute(text(
            "DELETE FROM dodatne WHERE ugovor = :u AND (LEFT(usluga, :n1) = :p1 OR LEFT(usluga, :n2) = :p2)"
        ), {"u": ugovor, "p1": IZRACUNATE_PREFIKS[0], "n1": len(IZRACUNATE_PREFIKS[0]),
            "p2": IZRACUNATE_PREFIKS[1], "n2": len(IZRACUNATE_PREFIKS[1])})
        for t in transferi:
            if not t.eur:
                continue
            vals = _dodatna_values(DodatnaCreate(usluga=t.usluga, eur=t.eur, din=None))
            conn.execute(text(
                "INSERT INTO dodatne (ugovor, usluga, eur, din) VALUES (:u, :usluga, :eur, :din)"
            ), {"u": ugovor, **vals})

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
                    # obradio + poslovnica = korisnik koji kreira; kasnije se ne menjaju
                    vals["obradio"] = f"{(urow.first_name or '').strip()} {(urow.last_name or '').strip()}".strip()
                    vals["poslovnica"] = urow.poslovnica_naziv or None
                    cols = list(vals.keys())
                    ph = ", ".join(f":{k}" for k in cols)
                    aid = conn.execute(text(
                        f"INSERT INTO aranzman ({', '.join(cols)}) VALUES ({ph}) RETURNING id"
                    ), vals).scalar_one()
                    rez_saputnici_upisi(conn, aid, body.saputnici)
                    obracun_iz_rezervacije(conn, aid, **_obracun_argumenti(body, vals))
                    if body.transferi:
                        rez_transferi_upisi(conn, kljuc, body.transferi)
                    uid, uime = log_user(conn, current_user)
                    for oblast, promene in podeli_po_oblastima({}, vals).items():
                        zabelezi(conn, kljuc, oblast, "kreirana", uid, uime, promene)
                    zabelezi(conn, kljuc, OBLAST_SAPUTNICI, "kreirana", uid, uime,
                             diff_saputnike([], rez_saputnici_snimak(body.saputnici, conn)))
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
                "SELECT saputnik, rodjen, pasos, uzrast, prevozow, prevozrt, prevozsp, smer, adresa, grad, "
                "email, telefon, ulazak, mesto_izlaska, mesto_sedenja, placeno_prevoz, zelja_prevoz, "
                "datum_ow, destinacija_ow, datum_polaska, destinacija_polaska, "
                "datum_povratka, destinacija_povratka "
                "FROM aranzman_dopuna WHERE aranzman_id = :i"
            ), {"i": arow.id}).mappings().all()]
            sets = ", ".join(f"{k} = :{k}" for k in vals)
            conn.execute(text(f"UPDATE aranzman SET {sets} WHERE kljuc = :wk"),
                         {**vals, "wk": kljuc})
            rez_saputnici_upisi(conn, arow.id, body.saputnici)
            obracun_iz_rezervacije(conn, arow.id, **_obracun_argumenti(body, vals))
            if body.transferi is not None:
                rez_transferi_upisi(conn, kljuc, body.transferi)
            uid, uime = log_user(conn, current_user)
            for oblast, promene in podeli_po_oblastima(stari, vals).items():
                zabelezi(conn, kljuc, oblast, "izmena", uid, uime, promene)
            zabelezi(conn, kljuc, OBLAST_SAPUTNICI, "izmena", uid, uime,
                     diff_saputnike(stari_sap, rez_saputnici_snimak(body.saputnici, conn)))
        return {"ok": True, "kljuc": kljuc, "message": "Izmene su sačuvane"}

    @api.get("/keptp/ugovor/{kljuc:path}")
    def keptp_za_ugovor(kljuc: str, _: dict = Depends(get_current_user)):
        """KEPTP evidencija za ugovor — null ako broj nije dodeljen."""
        kljuc = kljuc.strip().strip("/")
        with engine.connect() as conn:
            r = conn.execute(text(
                "SELECT broj_keptp, datum FROM keptp WHERE broj_ugovora = :k"
            ), {"k": kljuc}).fetchone()
        if not r:
            return None
        return {"broj_keptp": r.broj_keptp, "datum": f"{r.datum:%d.%m.%Y}"}

    @api.post("/keptp/dodeli")
    def keptp_dodeli(body: KeptpDodeliIn, _: dict = Depends(get_current_user)):
        """Dodeli sledeći broj KEPTP ugovoru (idempotentno). Numeracija kreće od 1,
        pod advisory lock-om; datum = danas (Europe/Belgrade)."""
        kljuc = body.kljuc.strip().strip("/")
        with engine.begin() as conn:
            ugovor = conn.execute(text(
                "SELECT viza FROM aranzman WHERE kljuc = :k ORDER BY id FOR UPDATE"
            ), {"k": kljuc}).fetchall()
            if not ugovor:
                raise HTTPException(status_code=404, detail="Ugovor nije pronađen")
            if any(int(red.viza or 0) == 1 for red in ugovor):
                raise HTTPException(status_code=400, detail="KEPTP se ne dodeljuje kada je označena Viza")
            conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": KEPTP_ADVISORY_LOCK})
            postojeci = conn.execute(text(
                "SELECT broj_keptp, datum FROM keptp WHERE broj_ugovora = :k"
            ), {"k": kljuc}).fetchone()
            if postojeci:
                return {"broj_keptp": postojeci.broj_keptp, "datum": f"{postojeci.datum:%d.%m.%Y}"}
            sledeci = conn.execute(text("SELECT COALESCE(MAX(broj_keptp), 0) + 1 FROM keptp")).scalar_one()
            danas = _belgrade_now().date()
            conn.execute(text(
                "INSERT INTO keptp (datum, broj_keptp, broj_ugovora) VALUES (:d, :b, :k)"
            ), {"d": danas, "b": sledeci, "k": kljuc})
        return {"broj_keptp": sledeci, "datum": f"{danas:%d.%m.%Y}"}

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
        ugovor = (arow.kljuc or "").strip()
        prefix = ugovor.split("/", 1)[0]
        if not re.fullmatch(r"[+-]?[0-9]+", prefix):
            raise HTTPException(status_code=400, detail="Neispravan broj ugovora")
        return ugovor

    def dodatna_katalog_proveri(conn, katalog_id: int | None):
        if katalog_id is None:
            return
        postoji = conn.execute(text(
            "SELECT 1 FROM dodatne_usluge WHERE id = :id"
        ), {"id": katalog_id}).fetchone()
        if not postoji:
            raise HTTPException(status_code=400, detail="Dodatna usluga iz kataloga nije pronađena")

    @api.post("/ugovori/{kljuc:path}/dodatne", status_code=201)
    def create_dodatna(kljuc: str, body: DodatnaCreate,
                       current_user: dict = Depends(get_current_user)):
        values = _dodatna_values(body)
        with engine.begin() as conn:
            ugovor = dodatne_contract(conn, kljuc, current_user)
            dodatna_katalog_proveri(conn, body.dodatna_usluga_id)
            row = conn.execute(text("""
                INSERT INTO dodatne (ugovor, usluga, eur, din, dodatna_usluga_id)
                VALUES (:ugovor, :usluga, :eur, :din, :katalog)
                RETURNING stavka_id, usluga, eur, din, dodatna_usluga_id
            """), {"ugovor": ugovor, "katalog": body.dodatna_usluga_id, **values}).mappings().one()
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
            ugovor = dodatne_contract(conn, kljuc, current_user)
            dodatna_katalog_proveri(conn, body.dodatna_usluga_id)
            row = conn.execute(text("""
                UPDATE dodatne SET usluga = :usluga, eur = :eur, din = :din, dodatna_usluga_id = :katalog
                WHERE stavka_id = :stavka_id AND ugovor = :ugovor
                  AND usluga IS NOT DISTINCT FROM :original_usluga
                  AND eur IS NOT DISTINCT FROM :original_eur
                  AND din IS NOT DISTINCT FROM :original_din
                RETURNING stavka_id, usluga, eur, din, dodatna_usluga_id
            """), {
                "ugovor": ugovor, "stavka_id": stavka_id, "katalog": body.dodatna_usluga_id, **values,
                "original_usluga": body.original.usluga,
                "original_eur": body.original.eur,
                "original_din": body.original.din,
            }).mappings().first()
            if row is None:
                exists = conn.execute(text(
                    "SELECT stavka_id FROM dodatne WHERE stavka_id = :stavka_id AND ugovor = :ugovor"
                ), {"stavka_id": stavka_id, "ugovor": ugovor}).fetchone()
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
            ugovor = dodatne_contract(conn, kljuc, current_user)
            row = conn.execute(text("""
                DELETE FROM dodatne WHERE stavka_id = :stavka_id AND ugovor = :ugovor
                  AND usluga IS NOT DISTINCT FROM :usluga
                  AND eur IS NOT DISTINCT FROM :eur
                  AND din IS NOT DISTINCT FROM :din
                RETURNING stavka_id
            """), {"stavka_id": stavka_id, "ugovor": ugovor,
                    "usluga": body.usluga, "eur": body.eur, "din": body.din}).first()
            if row is None:
                exists = conn.execute(text(
                    "SELECT stavka_id FROM dodatne WHERE stavka_id = :s AND ugovor = :u"
                ), {"s": stavka_id, "u": ugovor}).first()
                raise HTTPException(status_code=409 if exists else 404,
                    detail="Stavka je u međuvremenu izmenjena" if exists else "Stavka nije pronađena")
            uid, uime = log_user(conn, current_user)
            zabelezi(conn, kljuc, OBLAST_OBRACUN, "usluga_obrisana", uid, uime, [
                {"polje": "Usluga", "stara": norm_vrednost(body.usluga), "nova": None},
                {"polje": "EUR", "stara": norm_vrednost(body.eur), "nova": None},
                {"polje": "DIN", "stara": norm_vrednost(body.din), "nova": None},
            ])
        return {"message": "Dodatna stavka je obrisana"}

    def dodatni_popust_aranzman_id(conn, kljuc: str, current_user: dict) -> int:
        """Autorizacija + id aranžmana (veza dodatnih popusta)."""
        dodatne_contract(conn, kljuc, current_user)
        arow = conn.execute(text(
            "SELECT id FROM aranzman WHERE kljuc = :k"
        ), {"k": kljuc.strip().strip("/")}).fetchone()
        if not arow:
            raise HTTPException(status_code=404, detail="Ugovor nije pronađen")
        return arow.id

    def dodatni_popust_sa_iznosom(conn, aid: int, values: dict) -> dict:
        """Uz procenat čuva i izračunati iznos (EUR i RSD) od bruto smeštaja u trenutku snimanja."""
        if values.get("procenat") is None:
            return values
        ar = conn.execute(text("SELECT * FROM aranzman WHERE id = :i"), {"i": aid}).mappings().first()
        base_eur = smestaj_neto_eur(dict(ar))
        pct = float(values["procenat"])
        eur = round(pct / 100 * base_eur, 2)
        return {**values, "eur": eur, "rsd": eur}

    @api.post("/ugovori/{kljuc:path}/dodatni-popusti", status_code=201)
    def create_dodatni_popust(kljuc: str, body: DodatniPopustIn,
                              current_user: dict = Depends(get_current_user)):
        values = _dodatni_popust_values(body)
        with engine.begin() as conn:
            aid = dodatni_popust_aranzman_id(conn, kljuc, current_user)
            values = dodatni_popust_sa_iznosom(conn, aid, values)
            row = conn.execute(text("""
                INSERT INTO dodatni_popusti (aranzman_id, naziv, eur, rsd, procenat)
                VALUES (:aid, :naziv, :eur, :rsd, :procenat)
                RETURNING id, naziv, eur, rsd, procenat
            """), {"aid": aid, **values}).mappings().one()
            ar = conn.execute(text("SELECT * FROM aranzman WHERE id = :i"), {"i": aid}).mappings().first()
        return dodatni_popusti_iznosi(dict(ar), [dict(row)])[0]

    @api.patch("/ugovori/{kljuc:path}/dodatni-popusti/{popust_id}")
    def update_dodatni_popust(kljuc: str, popust_id: int, body: DodatniPopustIn,
                              current_user: dict = Depends(get_current_user)):
        values = _dodatni_popust_values(body)
        with engine.begin() as conn:
            aid = dodatni_popust_aranzman_id(conn, kljuc, current_user)
            values = dodatni_popust_sa_iznosom(conn, aid, values)
            row = conn.execute(text("""
                UPDATE dodatni_popusti SET naziv = :naziv, eur = :eur, rsd = :rsd, procenat = :procenat
                WHERE id = :id AND aranzman_id = :aid
                RETURNING id, naziv, eur, rsd, procenat
            """), {"id": popust_id, "aid": aid, **values}).mappings().first()
            if row is None:
                raise HTTPException(status_code=404, detail="Dodatni popust nije pronađen")
            ar = conn.execute(text("SELECT * FROM aranzman WHERE id = :i"), {"i": aid}).mappings().first()
        return dodatni_popusti_iznosi(dict(ar), [dict(row)])[0]

    @api.delete("/ugovori/{kljuc:path}/dodatni-popusti/{popust_id}")
    def delete_dodatni_popust(kljuc: str, popust_id: int,
                              current_user: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            aid = dodatni_popust_aranzman_id(conn, kljuc, current_user)
            row = conn.execute(text(
                "DELETE FROM dodatni_popusti WHERE id = :id AND aranzman_id = :aid RETURNING id"
            ), {"id": popust_id, "aid": aid}).first()
            if row is None:
                raise HTTPException(status_code=404, detail="Dodatni popust nije pronađen")
        return {"message": "Dodatni popust je obrisan"}

    @api.get("/ugovori/{kljuc:path}/pdf")
    def download_ugovor_pdf(kljuc: str, current_user: dict = Depends(get_current_user)):
        from decimal import Decimal, ROUND_HALF_UP
        from ugovor_pdf import generate_ugovor_pdf, ukupno_ugovora
        with engine.connect() as conn:
            ugovor = dodatne_contract(conn, kljuc, current_user)
            row = conn.execute(text("SELECT * FROM aranzman WHERE kljuc = :k"),
                               {"k": kljuc}).mappings().one()
            data = dict(row)
            data["email"] = data.get("refno") or ""
            data["putnici_detalji"] = [dict(p) for p in conn.execute(text(
                "SELECT * FROM aranzman_dopuna WHERE aranzman_id = :i ORDER BY id"
            ), {"i": data["id"]}).mappings()]
            data["dodatne"] = [dict(p) for p in conn.execute(text(
                "SELECT stavka_id, usluga, eur, din FROM dodatne WHERE ugovor = :u ORDER BY stavka_id"
            ), {"u": ugovor}).mappings()]
            # KEPTP broj: nova evidencija (tabela keptp), ne legacy aranzman.keptp
            kep = conn.execute(text(
                "SELECT broj_keptp FROM keptp WHERE broj_ugovora = :k"
            ), {"k": kljuc.strip().strip("/")}).first()
            if kep:
                data["keptp"] = kep.broj_keptp
            agency = conn.execute(text("SELECT * FROM agencija WHERE id = 1")).mappings().first()
            # smeštaj: napomena + JID (mesto.cis); soba: opis (STD/APP) i opis dodatno
            if data.get("smestaj_id"):
                sm = conn.execute(text(
                    "SELECT s.napomena, m.cis FROM smestaj s LEFT JOIN mesto m ON m.id = s.mesto WHERE s.id = :s"
                ), {"s": data["smestaj_id"]}).mappings().first()
                if sm:
                    data["smestaj_napomena"] = sm["napomena"]
                    data["mesto_cis"] = sm["cis"]
                soba = conn.execute(text(
                    "SELECT opis, opis_dodatno, tip, opis_ugovor FROM sobe WHERE veza_id_smestaj = :s AND TRIM(broj_sobe) = TRIM(:b) ORDER BY id LIMIT 1"
                ), {"s": data["smestaj_id"], "b": data.get("soba") or ""}).mappings().first()
                if soba:
                    data["soba_opis"] = soba["opis"]
                    data["soba_opis_dodatno"] = soba["opis_dodatno"]
                    data["soba_tip"] = soba["tip"]
                    data["soba_opis_ugovor"] = soba["opis_ugovor"]
            # subagent (isti uslov kao u ugovor_detail): podaci za podnosioca prijave
            if (data.get("subagent") or "").strip():
                sub = conn.execute(text(
                    "SELECT naziv, pib, matbroj, adresa, mesto, email, tel FROM subagenti "
                    "WHERE naziv = :n AND naziv <> '' ORDER BY id LIMIT 1"
                ), {"n": data["subagent"]}).mappings().first()
                data["subagent_info"] = dict(sub) if sub else None
            # potpis službenika = aranzman.obradio (ko je obradio ugovor, ne ulogovani korisnik)
            data["ulogovan"] = str(data.get("obradio") or "").strip()
        if not data.get("danas"):
            raise HTTPException(status_code=422, detail="Ugovor nema datum izdavanja")
        # zbir uplata u EUR (isto kao u rezervaciji: suma_eur = din / kurs na dan uplate)
        data["uplaceno_eur"] = sum((Decimal(str(u["suma_eur"])) for u in _uplate_za_ugovor(kljuc)
                                    if u.get("suma_eur") is not None), Decimal(0))
        datum = data["danas"].date() if hasattr(data["danas"], "date") else data["danas"]
        kurs, kurs_datum = get_eur_middle_za_datum(datum.isoformat())
        if not kurs or not math.isfinite(kurs) or kurs <= 0:
            raise HTTPException(status_code=503, detail="Kurs NBS za datum ugovora nije dostupan. Pokušajte ponovo.")
        calc = calc_ugovor_values(data, dodatni_za_ugovor(data.get("kljuc")))
        ukupno, ukupno_din_dodatne = ukupno_ugovora(data, calc, data.get("dodatne"))
        ukupno_rsd = (Decimal(str(ukupno)) * Decimal(str(kurs))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) + Decimal(str(ukupno_din_dodatne))
        data.update(obracun=calc, ukupno_eur=ukupno,
                    ukupno_rsd=ukupno_rsd,
                    kurs=kurs, kurs_datum=kurs_datum, datum_izdavanja=datum)
        izdavalac = dict(agency) if agency else {}
        izdavalac["racun"] = next((izdavalac.get(f"tekuci_racun{i}") for i in range(1, 5)
                                  if izdavalac.get(f"tekuci_racun{i}")), "")
        izdavalac["banka"] = next((izdavalac.get(f"banka{i}") for i in range(1, 5)
                                  if izdavalac.get(f"tekuci_racun{i}")), "")
        izdavalac["banke"] = _banke_izdavaoca(izdavalac)
        izdavalac["logo_data_url"] = _logo_data_url_iz_baze()
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
                SELECT saputnik, uzrast, prevozow, prevozrt, prevozsp, viza, ulazak, mesto_izlaska, smer,
                       adresa, grad, email, telefon, rodjen, pasos,
                       mesto_sedenja, placeno_prevoz, zelja_prevoz, datum_ow, destinacija_ow,
                       datum_polaska, destinacija_polaska, datum_povratka, destinacija_povratka,
                       destinacija_ow_id, destinacija_polaska_id, destinacija_povratka_id,
                       dodatno_sediste
                FROM aranzman_dopuna WHERE aranzman_id = :i ORDER BY id
            """), {"i": row.id}).fetchall()
            # dodatne.ugovor = ceo ključ ugovora (npr. 213/26), ne interni aranzman.id.
            dodatne = conn.execute(text("""
                SELECT stavka_id, usluga, eur, din, dodatna_usluga_id FROM dodatne WHERE ugovor = :k
                ORDER BY usluga NULLS LAST, eur NULLS LAST, din NULLS LAST
            """), {"k": kljuc}).mappings().all()
            dodatni_popusti = conn.execute(text("""
                SELECT id, naziv, eur, rsd, procenat FROM dodatni_popusti WHERE aranzman_id = :i ORDER BY id
            """), {"i": row.id}).mappings().all()
            obr = conn.execute(text(
                "SELECT soba_cenovnik, struktura, prevoz FROM obracun_po_aranzmanu WHERE aranzman_id = :i"
            ), {"i": row.id}).fetchone()
        d = dict(row._mapping)
        dodatni_lista = dodatni_popusti_iznosi(d, [dict(p) for p in dodatni_popusti])
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
        calc = calc_ugovor_values(d, dodatni_lista)
        ukupna = round((calc["naplata"] + calc["provizija"]) * kurs, 2) if kurs else None
        fmt_date = lambda v: v.strftime("%d.%m.%Y") if v else None
        putnici_detalji = [{
            "saputnik": (p.saputnik or "").strip(),
            "rodjen": fmt_date(p.rodjen),
            "pasos": p.pasos,
            "uzrast": (p.uzrast or "").strip() or None,
            "dodatno_sediste": bool(p.dodatno_sediste),
            "prevozow": p.prevozow,
            "prevozrt": p.prevozrt,
            "prevozsp": p.prevozsp,
            "ulazak": p.ulazak,
            "mesto_izlaska": p.mesto_izlaska,
            "smer": p.smer,
            "adresa": (p.adresa or "").strip() or None,
            "grad": (p.grad or "").strip() or None,
            "email": (p.email or "").strip() or None,
            "telefon": (p.telefon or "").strip() or None,
            "mesto_sedenja": p.mesto_sedenja,
            "placeno_prevoz": bool(p.placeno_prevoz),
            "zelja_prevoz": bool(p.zelja_prevoz),
            "datum_ow": p.datum_ow.isoformat() if p.datum_ow else None,
            "destinacija_ow": p.destinacija_ow,
            "datum_polaska": p.datum_polaska.isoformat() if p.datum_polaska else None,
            "destinacija_polaska": p.destinacija_polaska,
            "datum_povratka": p.datum_povratka.isoformat() if p.datum_povratka else None,
            "destinacija_povratka": p.destinacija_povratka,
            "destinacija_ow_id": p.destinacija_ow_id,
            "destinacija_polaska_id": p.destinacija_polaska_id,
            "destinacija_povratka_id": p.destinacija_povratka_id,
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
            "uzrast": d.get("uzrast") or None,
            "putnici": putnici,
            "putnici_detalji": putnici_detalji,
            "dodatne": [dict(stavka) for stavka in dodatne],
            "dodatni_popusti": dodatni_lista,
            "smer": d.get("smer"),
            "tiprezervacije": d.get("tiprezervacije"),
            "viza": d.get("viza"),
            "subagent": d.get("subagent") or "",
            "timelimit": d["timelimit"].strftime("%d.%m.%Y %H:%M") if d.get("timelimit") else None,
            "adresa": d.get("adresa"),
            "grad": d.get("grad"),
            "telefon": d.get("telefon"),
            "refno": d.get("refno"),
            "prevozow": d.get("prevozow"),
            "prevozrt": d.get("prevozrt"),
            "prevozsp": d.get("prevozsp"),
            "mesto_sedenja": d.get("mesto_sedenja"),
            "placeno_prevoz": bool(d.get("placeno_prevoz")),
            "zelja_prevoz": bool(d.get("zelja_prevoz")),
            "datum_ow": d["datum_ow"].isoformat() if d.get("datum_ow") else None,
            "destinacija_ow": d.get("destinacija_ow"),
            "datum_polaska": d["datum_polaska"].isoformat() if d.get("datum_polaska") else None,
            "destinacija_polaska": d.get("destinacija_polaska"),
            "datum_povratka": d["datum_povratka"].isoformat() if d.get("datum_povratka") else None,
            "destinacija_povratka": d.get("destinacija_povratka"),
            "destinacija_ow_id": d.get("destinacija_ow_id"),
            "destinacija_polaska_id": d.get("destinacija_polaska_id"),
            "destinacija_povratka_id": d.get("destinacija_povratka_id"),
            "napomena_prevoz": d.get("napomena_prevoz"),
            "destinacija_prevoz_id": d.get("destinacija_prevoz_id"),
            "nacin_placanja": d.get("nacin_placanja"),

            "osiguranje1": d.get("osiguranje1"),
            "soba": d.get("soba"),
            "apartman": d.get("apartman"),
            "opis": d.get("opis"),
            "gde": d.get("gde"),
            # varijanta iz PROVERI OBRAČUN (soba_cenovnik + struktura iz obračuna ugovora)
            "obracun": {"soba_cenovnik": obr.soba_cenovnik, "struktura": obr.struktura,
                        "prevoz": bool(obr.prevoz)} if obr else None,
            "napomena": d.get("napomena"),
            "napomena1": d.get("napomena1"),
            "obradio": d.get("obradio"),
            "ulazak": d.get("ulazak"),
            "mesto_izlaska": d.get("mesto_izlaska") or d.get("ulazak"),
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
            cols = UGOVORI_SEARCH_COLS + list(UGOVORI_SEARCH_EXTRA)
            search_in = (q.get("search_in") or "").strip()
            if search_in:
                dozvoljene = set(UGOVORI_SEARCH_COLS) | set(UGOVORI_SEARCH_EXTRA)
                req = [c.strip() for c in search_in.split(",") if c.strip() in dozvoljene]
                if req:
                    cols = req
            ors = " OR ".join(
                f"{UGOVORI_SEARCH_EXTRA[c]} ILIKE :search" if c in UGOVORI_SEARCH_EXTRA
                else f"COALESCE({c}::text, '') ILIKE :search"
                for c in cols
            )
            conds.append(f"({ors})")
            bind["search"] = like
        # Filter-red tabele: svako polje sa ≥3 karaktera dodaje svoj uslov (AND)
        for fkey, fexpr in UGOVORI_FILTER_COLS.items():
            fval = (q.get(f"f_{fkey}") or "").strip()
            if len(fval) >= 3:
                conds.append(f"{fexpr} ILIKE :f_{fkey}")
                bind[f"f_{fkey}"] = f"%{fval}%"

        # Tabovi stranice Ugovori: tip = predrezervacija | storno | rezervacije (sve ostalo)
        tip_expr = "UPPER(TRIM(COALESCE(a.tiprezervacije, '')))"
        tip_grupa_expr = (
            f"CASE WHEN {tip_expr} = 'PREDREZERVACIJA' THEN 'predrezervacija' "
            f"WHEN {tip_expr} = 'STORNO' THEN 'storno' ELSE 'rezervacije' END"
        )
        where_bez_tipa = ("WHERE " + " AND ".join(conds)) if conds else ""
        tip = (q.get("tip") or "").strip().lower()
        if tip in ("predrezervacija", "storno", "rezervacije"):
            conds.append(f"({tip_grupa_expr}) = :tip_grupa")
            bind["tip_grupa"] = tip
        where = ("WHERE " + " AND ".join(conds)) if conds else ""

        with engine.connect() as conn:
            total = conn.execute(text(f"SELECT COUNT(*) FROM aranzman a {where}"), bind).scalar() or 0
            bind_bez_tipa = {k: v for k, v in bind.items() if k != "tip_grupa"}
            po_tipu = {"predrezervacija": 0, "storno": 0, "rezervacije": 0}
            for g, c in conn.execute(text(
                f"SELECT {tip_grupa_expr} AS g, COUNT(*) FROM aranzman a {where_bez_tipa} GROUP BY 1"
            ), bind_bez_tipa).fetchall():
                po_tipu[g] = int(c)
            rows = conn.execute(text(f"""
                SELECT kljuc,
                       to_char(danas, 'DD.MM.YYYY') AS danas_fmt,
                       putnik, mesto, naziv, subagent, apartman, soba,
                       (SELECT b.tip FROM sobe b
                         WHERE b.veza_id_smestaj = a.smestaj_id
                           AND TRIM(b.broj_sobe) = TRIM(a.soba)
                         LIMIT 1) AS tip_sobe,
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
                LIMIT :limit OFFSET :offset
            """), {**bind, "limit": page_size, "offset": (page - 1) * page_size}).fetchall()

        kurs = get_eur_middle()
        dodatni_map = dodatni_za_ugovori([r.kljuc for r in rows]) if kurs else {}

        def row_putnici(r) -> list:
            ps = [str(r.putnik or "").strip()]
            ps += [str(s or "").strip() for s in (r.saputnici_list or [])]
            return [p for p in ps if p]

        def row_ukupna(r) -> float | None:
            if not kurs:
                return None
            kljuc = str(r.kljuc or "").strip().strip("/")
            calc = calc_ugovor_values(dict(r._mapping), dodatni_map.get(kljuc, []))
            return round((calc["naplata"] + calc["provizija"]) * kurs, 2)

        return {
            "rows": [{
                "kljuc": r.kljuc,
                "danas": r.danas_fmt,
                "putnik": r.putnik,
                "putnici": row_putnici(r),
                "mesto": r.mesto,
                "naziv": r.naziv,
                "struktura": (r.apartman or "").strip() or (r.tip_sobe or "").strip() or None,
                "soba": r.soba,
                "subagent": r.subagent,
                "datumod": r.datumod_fmt,
                "datumdo": r.datumdo_fmt,
                "ukupna_vrednost": row_ukupna(r),
            } for r in rows],
            "total": total,
            "po_tipu": po_tipu,
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
        "s.pib", "s.matbroj", "s.email", "s.ugovor_broj",
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
                       s.pib, s.matbroj, s.email, s.ugovor_broj, s.ugovor_datumod, s.ugovor_datumdo, s.ta,
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
                                       provizija2, punnaziv, kontakt, pib, matbroj, email,
                                       ugovor_broj, ugovor_datumod, ugovor_datumdo, ta)
                VALUES (:naziv, :adresa, :mesto, :osoba, :tel, :tel1, :tel2,
                        :fax, :racun, :provizija, :provizija1, :provizija1a,
                        :provizija2, :punnaziv, :kontakt, COALESCE(:pib, ''),
                        COALESCE(:matbroj, ''), COALESCE(:email, ''),
                        COALESCE(:ugovor_broj, ''), :ugovor_datumod, :ugovor_datumdo, COALESCE(:ta, true))
                RETURNING id
            """), body.model_dump()).fetchone()
        return {"id": row.id}

    @api.put("/subagenti/{item_id}")
    def update_subagent(item_id: int, body: SubagentUpdate, _: dict = Depends(get_current_user)):
        fields = {k: v for k, v in body.model_dump(exclude_unset=True).items() if not (k == "naziv" and v is None)}
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

    def calc_ugovor_d_values(row: dict, dodatni=None) -> dict:
        """Obračun 'd' varijanti (dinarske kolone) — za predracun.provizija."""
        n = lambda k: _num_polje(row, k)

        cenaaranzd_c = n("kolaranz") * n("cenaaranzd") + n("kolchd") * n("uplatasmestaj")
        cenaprevozd_c = n("cenadow") * n("kolow") + n("cenadrt") * n("kolrt")
        popustsmestajd = n("popustar") * cenaaranzd_c / 100
        dodatni_din = sum(p["rsd_iznos"] for p in dodatni_popusti_iznosi(row, dodatni))
        popustprevozd = n("popustpr") * cenaprevozd_c / 100
        provizijaard = (cenaaranzd_c - popustsmestajd - dodatni_din) * n("procenatar") / 100
        provizijaprd = 0.0 if n("cenadrt") == 0 else n("procenatpr") * n("koldrt")
        provizijapr1d = 0.0 if n("cenadow") == 0 else n("procenatpr") * n("koldow")
        provizijavizad = 0.0
        provizijad = provizijaard + provizijaprd + provizijapr1d + provizijavizad
        naplatad = (cenaaranzd_c + cenaprevozd_c
                    - popustsmestajd - dodatni_din - popustprevozd
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
        calc = calc_ugovor_values(d, dodatni_za_ugovor(d.get("kljuc")))
        calc_d = calc_ugovor_d_values(d, dodatni_za_ugovor(d.get("kljuc")))
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
            calc = calc_ugovor_values(d, dodatni_za_ugovor(d.get("kljuc")))
            calc_d = calc_ugovor_d_values(d, dodatni_za_ugovor(d.get("kljuc")))
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
            "licenca": a.get("licenca") or "",
            "banke": _banke_izdavaoca(a),
            "logo_data_url": _logo_data_url_iz_baze(),
        }
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

    @api.get("/saglasnost/pdf")
    def get_saglasnost_pdf(kljuc: str, _: dict = Depends(get_current_user)):
        """Saglasnost za obradu podataka — zaglavlje iz Osnovnih podataka, davalac = nosilac."""
        from saglasnost_pdf import build_saglasnost_pdf

        k = kljuc.strip().strip("/")
        with engine.connect() as conn:
            ag = conn.execute(text("SELECT * FROM agencija WHERE id = 1")).mappings().first() or {}
            ar = conn.execute(
                text("SELECT kljuc, putnik FROM aranzman WHERE kljuc = :k"), {"k": k}
            ).mappings().first()
        if not ar:
            raise HTTPException(status_code=404, detail="Ugovor nije pronađen")
        ag = dict(ag)
        ag["banke"] = _banke_izdavaoca(ag)
        ag["logo_data_url"] = _logo_data_url_iz_baze()
        pdf = build_saglasnost_pdf(
            ag, ar["kljuc"], _belgrade_now().strftime("%d.%m.%Y"), (ar["putnik"] or "").strip()
        )
        return Response(
            content=pdf,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="Saglasnost_{k.replace("/", "-")}.pdf"'},
        )

    @api.put("/agencija")
    async def update_agencija(request: Request, _: dict = Depends(get_current_user)):
        data = await request.json()
        allowed = [
            "naziv", "poslovno_ime", "licenca", "email1", "email2", "telefon1", "telefon2",
            "ulica", "broj", "post_broj", "mesto", "drzava",
            "opstina_rgz", "opstina_naziv", "mesto_rgz", "mesto_naziv",
            "ulica_rgz", "ulica_naziv", "api_kljuc_efakture", "api_kljuc_cis",
            "fiskal_zahtev_link", "fiskal_odgovor_link",
            "pib", "mb", "jbkjs", "jmbg",
            "tekuci_racun1", "banka1", "tekuci_racun2", "banka2",
            "tekuci_racun3", "banka3", "tekuci_racun4", "banka4",
            "lice_reklamacije",
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

    # ─── Parametri obračuna ──────────────────────────────────────────────────
    PARAMETRI_POLJA = ("visina_popusta", "visina_provizije", *MESTA_SEDENJA_POLJA,
                       "datumod1", "datumdo1", "koeficijent1",
                       "datumod2", "datumdo2", "koeficijent2")

    @api.get("/parametri-obracuna")
    def get_parametri_obracuna(_: dict = Depends(get_current_user)):
        with engine.connect() as conn:
            row = conn.execute(text(
                f"SELECT {', '.join(PARAMETRI_POLJA)} FROM parametri_obracuna WHERE id = 1"
            )).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="Parametri obračuna nisu pronađeni")
        out = dict(row)
        for k in MESTA_SEDENJA_POLJA:
            out[k] = float(out[k] or 0)
        for k in ("datumod1", "datumdo1", "datumod2", "datumdo2"):
            out[k] = out[k].isoformat() if out[k] else None
        return out

    @api.put("/parametri-obracuna")
    def update_parametri_obracuna(body: ParametriObracuna, _: dict = Depends(get_current_user)):
        if not (0 <= body.visina_popusta <= 100):
            raise HTTPException(status_code=400, detail="Visina popusta mora biti između 0 i 100")
        if not (0 <= body.visina_provizije <= 100):
            raise HTTPException(status_code=400, detail="Visina provizije mora biti između 0 i 100")
        for n in ("1", "2"):
            od, do, koef = getattr(body, f"datumod{n}"), getattr(body, f"datumdo{n}"), getattr(body, f"koeficijent{n}")
            if od and do and od > do:
                raise HTTPException(status_code=400, detail=f"Datum početka mora biti pre ili jednak datumu kraja ({n}. period)")
            if koef is not None and not (0 <= koef < 1e6):
                raise HTTPException(status_code=400, detail=f"Koeficijent {n} mora biti nenegativan broj")
        data = body.model_dump()
        set_clause = ", ".join(f"{k} = :{k}" for k in data)
        data["id"] = 1
        with engine.begin() as conn:
            conn.execute(text(f"UPDATE parametri_obracuna SET {set_clause} WHERE id = :id"), data)
        return {"ok": True}

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
