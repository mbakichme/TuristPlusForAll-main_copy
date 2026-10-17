"""Istorija izmena rezervacije (audit log) — tabela `rezervacija_log`.

Jedan red = jedan događaj nad ugovorom u jednoj oblasti (rezervacija, prevoz,
obračun, uplata, saputnici). `promene` je JSON niz {polje, stara, nova} sa
diff-om vrednosti. Upis ide u ISTOJ transakciji kao i sama izmena, pa log ne
može ostati bez izmene niti izmena bez loga.
"""
import json
import re
from datetime import date, datetime
from decimal import Decimal

from fastapi import Depends, HTTPException
from sqlalchemy import text

OBLAST_REZERVACIJA = "rezervacija"
OBLAST_PREVOZ = "prevoz"
OBLAST_OBRACUN = "obracun"
OBLAST_UPLATA = "uplata"
OBLAST_SAPUTNICI = "saputnici"

# kolone aranzman-a po oblasti (sve ostalo ide u "rezervacija")
PREVOZ_POLJA = {"prevozow", "prevozrt", "smer", "cenaow", "kolow", "cenart",
                "kolrt", "cenadow", "cenadrt"}
OBRACUN_POLJA = {"cenaaranz", "kolaranz", "cenaaranzd", "osiguranje", "osiguranje1",
                 "popustar", "popustpr", "procenatar", "procenatpr"}
# kolone koje se ne loguju (tehnička polja, menjaju se pri svakom snimanju)
IGNORISANA_POLJA = {"kljuc", "danas", "obradio"}
BOOL_POLJA = {"prevozow", "prevozrt"}

LABELE = {
    "putnik": "Nosilac", "rodjen": "Datum rođenja nosioca", "pasos": "Pasoš",
    "adresa": "Adresa", "telefon": "Telefon", "refno": "Email",
    "prevozow": "Prevoz u jednom smeru", "prevozrt": "Povratni prevoz",
    "smer": "Smer", "tiprezervacije": "Tip rezervacije", "subagent": "Subagent",
    "timelimit": "Time limit", "mesto": "Mesto", "naziv": "Smeštaj",
    "smestaj_id": "Smeštaj (ID)", "soba": "Soba", "destinacija": "Destinacija",
    "apartman": "Struktura", "datumod": "Datum od", "datumdo": "Datum do",
    "datumoddo": "Period", "napomena": "Napomena", "napomena1": "Napomena interna",
    "ulazak": "Ulazak", "cenaaranz": "Smeštaj cena (EUR)",
    "kolaranz": "Smeštaj količina (EUR)", "cenaaranzd": "Smeštaj cena (RSD)",
    "cenaow": "Prevoz cena ow (EUR)", "kolow": "Prevoz količina ow",
    "cenart": "Prevoz cena rt (EUR)", "kolrt": "Prevoz količina rt",
    "cenadow": "Prevoz cena ow (RSD)", "cenadrt": "Prevoz cena rt (RSD)",
    "osiguranje": "Osiguranje (RSD)", "osiguranje1": "Osiguranje (EUR)",
    "popustar": "Popust smeštaj", "popustpr": "Popust prevoz",
    "procenatar": "Provizija smeštaj", "procenatpr": "Provizija prevoz",
    "usluga": "Usluga", "eur": "EUR", "din": "DIN", "platilac": "Platilac",
    "nacin": "Način plaćanja", "svrha": "Svrha", "iznos": "Iznos (DIN)",
}

SAPUTNIK_POLJA = {
    "rodjen": "datum rođenja", "pasos": "pasoš", "prevozow": "prevoz ow",
    "prevozrt": "prevoz rt", "smer": "smer", "adresa": "adresa",
    "email": "email", "telefon": "telefon", "ulazak": "ulazak",
}

_ISO_DATUM = re.compile(r"\d{4}-\d{2}-\d{2}")


def oblast_polja(polje: str) -> str:
    if polje in PREVOZ_POLJA:
        return OBLAST_PREVOZ
    if polje in OBRACUN_POLJA:
        return OBLAST_OBRACUN
    return OBLAST_REZERVACIJA


def norm_vrednost(v, polje: str | None = None) -> str | None:
    """Vrednost → čitljiv string za log; None i prazno su isto (nema vrednosti)."""
    if v is None:
        return None
    if polje in BOOL_POLJA:
        return "da" if int(v) else "ne"
    if isinstance(v, datetime):
        if v.hour or v.minute:
            return v.strftime("%d.%m.%Y %H:%M")
        return v.strftime("%d.%m.%Y")
    if isinstance(v, date):
        return v.strftime("%d.%m.%Y")
    if isinstance(v, bool):
        return "da" if v else "ne"
    if isinstance(v, (int, float, Decimal)):
        f = round(float(v), 2)
        return None if f == 0 else f"{f:g}"
    s = str(v).strip()
    if _ISO_DATUM.fullmatch(s):
        y, m, d = s.split("-")
        s = f"{d}.{m}.{y}"
    return s or None


def podeli_po_oblastima(stari: dict, nove: dict) -> dict[str, list[dict]]:
    """Diff kolona aranzman-a (stari red vs. vrednosti iz forme) po oblastima."""
    out: dict[str, list[dict]] = {}
    for polje, nova_v in nove.items():
        if polje in IGNORISANA_POLJA:
            continue
        a = norm_vrednost(stari.get(polje), polje)
        b = norm_vrednost(nova_v, polje)
        if a == b:
            continue
        out.setdefault(oblast_polja(polje), []).append(
            {"polje": LABELE.get(polje, polje), "stara": a, "nova": b})
    return out


def diff_saputnike(stari: list[dict], novi: list[dict]) -> list[dict]:
    """Saputnici se upoređuju po imenu (kao pri upisu u aranzman_dopuna)."""
    def kljuc(s: dict) -> str:
        return (s.get("saputnik") or "").strip().upper()

    mapa_s = {kljuc(s): s for s in stari if kljuc(s)}
    mapa_n = {kljuc(s): s for s in novi if kljuc(s)}
    out: list[dict] = []
    for k, n in mapa_n.items():
        ime = n.get("saputnik")
        if k not in mapa_s:
            out.append({"polje": "Saputnik", "stara": None, "nova": f"{ime} (dodat)"})
            continue
        s = mapa_s[k]
        for polje, label in SAPUTNIK_POLJA.items():
            a = norm_vrednost(s.get(polje), polje)
            b = norm_vrednost(n.get(polje), polje)
            if a != b:
                out.append({"polje": f"Saputnik {ime} · {label}", "stara": a, "nova": b})
    for k, s in mapa_s.items():
        if k not in mapa_n:
            out.append({"polje": "Saputnik", "stara": f"{s.get('saputnik')} (uklonjen)", "nova": None})
    return out


def log_user(conn, current_user: dict) -> tuple[int | None, str]:
    try:
        uid = int(current_user["sub"])
    except (KeyError, TypeError, ValueError):
        return None, ""
    r = conn.execute(text("SELECT first_name, last_name FROM users WHERE id = :id"),
                     {"id": uid}).fetchone()
    ime = f"{(r.first_name or '').strip()} {(r.last_name or '').strip()}".strip() if r else ""
    return uid, ime


def zabelezi(conn, kljuc: str, oblast: str, dogadjaj: str,
             user_id: int | None, user_ime: str, promene: list[dict]) -> None:
    """Upis jednog događaja; bez promena se ništa ne upisuje."""
    if not promene:
        return
    conn.execute(text("""
        INSERT INTO rezervacija_log (kljuc, oblast, dogadjaj, user_id, user_ime, promene)
        VALUES (:kljuc, :oblast, :dogadjaj, :user_id, :user_ime, CAST(:promene AS JSONB))
    """), {
        "kljuc": kljuc, "oblast": oblast, "dogadjaj": dogadjaj,
        "user_id": user_id, "user_ime": user_ime or "",
        "promene": json.dumps(promene, ensure_ascii=False),
    })


def init_rezervacija_log(engine):
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS rezervacija_log (
                id SERIAL PRIMARY KEY,
                kljuc TEXT NOT NULL,
                oblast VARCHAR(30) NOT NULL,
                dogadjaj VARCHAR(60) NOT NULL,
                user_id INTEGER,
                user_ime VARCHAR(200) NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                promene JSONB NOT NULL DEFAULT '[]'::jsonb
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS rezervacija_log_kljuc_idx ON rezervacija_log (kljuc, id DESC)"
        ))


def register_rezervacija_log(api, engine, get_current_user):
    @api.get("/rezervacije-istorija")
    def istorija(kljuc: str, limit: int = 200, _: dict = Depends(get_current_user)):
        k = (kljuc or "").strip().strip("/")
        if not k:
            raise HTTPException(status_code=400, detail="Broj ugovora je obavezan")
        limit = max(1, min(limit, 500))
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT id, oblast, dogadjaj, user_id, user_ime, created_at, promene
                FROM rezervacija_log WHERE kljuc = :k
                ORDER BY id DESC LIMIT :l
            """), {"k": k, "l": limit}).mappings().all()
        return {"rows": [{
            "id": r["id"],
            "oblast": r["oblast"],
            "dogadjaj": r["dogadjaj"],
            "user_id": r["user_id"],
            "user_ime": r["user_ime"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "promene": r["promene"] or [],
        } for r in rows]}
