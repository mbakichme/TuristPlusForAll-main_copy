"""API klijenti subagenata (App2 -> App1 autentifikacija).

Za svakog subagenta postoji najviše jedan aktivan API klijent (client_id + secret).
Secret generiše App1. U bazi se čuva samo HMAC-SHA256 hash (uz pepper iz env-a).
Plaintext secret se šalje App2 jednom, pri provisioningu, preko HTTPS-a.

Stanja (subagent_api_clients.sync_status):
  synced              App2 zna za klijenta, klijent je aktivan
  failed              provisioning na App2 nije uspeo (klijent je neaktivan)
  deactivate_pending  deaktivacija lokalno uspela, App2 još nije obavešten
  deactivated         App2 obavešten o deaktivaciji
  superseded          klijent zamenjen novim (rotacija)

Podešavanje (env):
  SUBAGENT_SECRET_PEPPER    tajna za HMAC; ne menjati posle prvog korišćenja
  SUBAGENT_APP_URL          osnovna adresa App2, npr. https://subagenti.example.com
  SUBAGENT_APP_SERVICE_KEY  servisni ključ kojim App1 poziva App2 (/internal/*)
  ORGANIZER_CODE            kratki kod organizatora, npr. "oktopod"
  ORGANIZER_NAME            puni naziv organizatora
"""
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
from concurrent.futures import ThreadPoolExecutor

import httpx
from fastapi import Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

log = logging.getLogger(__name__)

ORGANIZER_CODE_RE = re.compile(r"^[a-z0-9_-]{2,20}$")
DEFAULT_SCOPES = ["slobodni_kapaciteti:read", "rezervacija:write"]
# Zaštićeni subagent superadmin tenanta (isti naziv i email u svim bazama organizatora).
SUPER_ADMIN_EMAIL = os.environ.get("SUPER_ADMIN_EMAIL", "www@oktopod.rs").strip().lower()
SUPER_ADMIN_SUBAGENT_NAZIV = "SoftLand"
SUPER_ADMIN_SUBAGENT_EMAIL = "www@softland.rs"
SUPER_ADMIN_REF_PREFIX = "super-admin:"
SUPER_ADMIN_PIB = "123456789"
HTTP_TIMEOUT = 15
# Deljeni klijent sa keep-alive: bez novog TCP+TLS rukovanja za svaki poziv ka App2.
# httpx.Client je bezbedan za paralelne zahteve iz više niti.
_HTTP = httpx.Client(timeout=HTTP_TIMEOUT)


class SyncError(Exception):
    """Greška pri konfiguraciji ili pozivu App2."""


def init_subagent_api(engine):
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE subagenti ADD COLUMN IF NOT EXISTS "
            "is_active BOOLEAN NOT NULL DEFAULT TRUE"
        ))
        conn.execute(text(
            "ALTER TABLE subagenti ADD COLUMN IF NOT EXISTS "
            "zasticen BOOLEAN NOT NULL DEFAULT FALSE"
        ))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS subagent_api_clients (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                subagent_id INTEGER NOT NULL REFERENCES subagenti(id) ON DELETE CASCADE,
                client_id VARCHAR(64) UNIQUE NOT NULL,
                secret_hash CHAR(64) NOT NULL,
                allowed_scopes JSONB NOT NULL DEFAULT '[]',
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                sync_status VARCHAR(20) NOT NULL DEFAULT 'pending',
                sync_error TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                deactivated_at TIMESTAMPTZ
            )
        """))
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS ux_subagent_api_clients_active
            ON subagent_api_clients (subagent_id) WHERE is_active
        """))


# ── Kredencijali ─────────────────────────────────────────────────────────────
def _pepper() -> bytes:
    value = os.environ.get("SUBAGENT_SECRET_PEPPER", "").strip()
    if not value:
        raise SyncError("SUBAGENT_SECRET_PEPPER nije podešen")
    return value.encode()


def hash_secret(secret: str) -> str:
    return hmac.new(_pepper(), secret.encode(), hashlib.sha256).hexdigest()


def generate_credentials(organizer_code: str) -> tuple[str, str]:
    client_id = f"{organizer_code}_{secrets.token_hex(8)}"
    secret = secrets.token_urlsafe(32)
    return client_id, secret


def _config() -> tuple[str, str, str, str]:
    url = os.environ.get("SUBAGENT_APP_URL", "").strip().rstrip("/")
    key = os.environ.get("SUBAGENT_APP_SERVICE_KEY", "").strip()
    code = os.environ.get("ORGANIZER_CODE", "").strip().lower()
    name = os.environ.get("ORGANIZER_NAME", "").strip()
    if not url or not key:
        raise SyncError("SUBAGENT_APP_URL / SUBAGENT_APP_SERVICE_KEY nisu podešeni")
    if not ORGANIZER_CODE_RE.match(code):
        raise SyncError("ORGANIZER_CODE nije podešen ili nije validan")
    return url, key, code, name


# ── Poziv App2 ───────────────────────────────────────────────────────────────
def _app2_request(method: str, path: str, payload: dict) -> None:
    url, key, _, _ = _config()
    try:
        resp = _HTTP.request(
            method, f"{url}{path}", json=payload,
            headers={"X-Service-Key": key},
        )
    except httpx.HTTPError as exc:
        raise SyncError(f"App2 nedostupna: {exc}") from exc
    if resp.status_code >= 400:
        raise SyncError(f"App2 HTTP {resp.status_code}: {resp.text[:300]}")


def _profil_polja(sub: dict) -> dict:
    """Polja firme koja App2 prikazuje u svom redu subagenta."""
    return {
        "naziv": sub.get("naziv") or "",
        "punnaziv": sub.get("punnaziv") or "",
        "adresa": sub.get("adresa") or "",
        "mesto": sub.get("mesto") or "",
        "osoba": sub.get("osoba") or "",
        "tel": sub.get("tel") or "",
        "tel1": sub.get("tel1") or "",
        "tel2": sub.get("tel2") or "",
        "fax": sub.get("fax") or "",
        "racun": sub.get("racun") or "",
        "kontakt": sub.get("kontakt") or "",
        "provizija": sub.get("provizija") or 0,
        "provizija1": sub.get("provizija1") or 0,
        "provizija1a": sub.get("provizija1a") or 0,
        "provizija2": sub.get("provizija2") or 0,
    }


def _subagent_key(sub: dict, code: str) -> str:
    if sub.get("zasticen"):
        # Fiksan ključ: App2 superadmin tenant nalazi po external_ref u svim bazama.
        return f"{SUPER_ADMIN_REF_PREFIX}{SUPER_ADMIN_SUBAGENT_EMAIL}"
    pib = (sub.get("pib") or "").strip()
    # Ključ po kojem App2 prepoznaje isti subagent kod više organizatora.
    return pib or f"{code}:{sub['id']}"


def _provision_payload(sub: dict, client_id: str, secret: str, code: str, name: str) -> dict:
    pib = (sub.get("pib") or "").strip()
    return {
        "subagent_key": _subagent_key(sub, code),
        **_profil_polja(sub),
        "email": sub.get("email") or "",
        "pib": pib,
        "matbroj": sub.get("matbroj") or "",
        "organizer_code": code,
        "organizer_name": name,
        "client_id": client_id,
        "client_secret": secret,
        "scopes": DEFAULT_SCOPES,
    }


# ── Stanje u bazi ────────────────────────────────────────────────────────────
def _read_subagent(engine, subagent_id: int) -> dict | None:
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT id, naziv, punnaziv, adresa, mesto, osoba, tel, tel1, tel2, fax, racun, "
            "kontakt, provizija, provizija1, provizija1a, provizija2, "
            "email, pib, matbroj, is_active, zasticen "
            "FROM subagenti WHERE id = :id"
        ), {"id": subagent_id}).fetchone()
    return dict(row._mapping) if row else None


def je_zasticen(engine, subagent_id: int) -> bool:
    sub = _read_subagent(engine, subagent_id)
    return bool(sub and sub.get("zasticen"))


def ensure_super_admin_subagent(engine) -> tuple[str | None, str | None]:
    """Zaštićen subagent superadmin tenanta u App2 (uvek aktivan, ne može se gasiti ni brisati).

    Kreira se jednom po bazi organizatora i provisionira u App2 pod ključem
    'super-admin:<email>', pa App2 veze pripadaju superadmin tenantu.
    Vraća (status, greška); (None, None) ako red već postoji i ima sinhronizovanu vezu.
    """
    with engine.begin() as conn:
        # Zaštićeni red je postojeći SoftLand subagent (ne pravi se novi red).
        row = conn.execute(text(
            "SELECT id FROM subagenti WHERE naziv = :naziv ORDER BY id LIMIT 1"
        ), {"naziv": SUPER_ADMIN_SUBAGENT_NAZIV}).fetchone()
        if row is None:
            row = conn.execute(text(
                "INSERT INTO subagenti (naziv, email, pib, matbroj, is_active, zasticen) "
                "VALUES (:naziv, :email, :pib, '', TRUE, TRUE) RETURNING id"
            ), {"naziv": SUPER_ADMIN_SUBAGENT_NAZIV,
                "email": SUPER_ADMIN_SUBAGENT_EMAIL, "pib": SUPER_ADMIN_PIB}).fetchone()
        else:
            # Zaključani email i PIB (update_subagent ih ne dozvoljava).
            conn.execute(text(
                "UPDATE subagenti SET zasticen = TRUE, email = :email, pib = :pib, is_active = TRUE "
                "WHERE id = :id AND (NOT zasticen OR email IS DISTINCT FROM :email "
                "OR pib IS DISTINCT FROM :pib OR NOT is_active)"
            ), {"email": SUPER_ADMIN_SUBAGENT_EMAIL, "pib": SUPER_ADMIN_PIB, "id": row.id})
    return sinhronizuj_subagenta(engine, row.id)



def _set_status(engine, client_id: str, status: str, error: str | None = None) -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE subagent_api_clients
            SET sync_status = :st,
                sync_error = :err,
                is_active = (is_active AND :st <> 'failed'),
                deactivated_at = CASE WHEN :st IN ('failed', 'deactivated')
                                      THEN COALESCE(deactivated_at, NOW())
                                      ELSE deactivated_at END
            WHERE client_id = :cid
        """), {"st": status, "err": error, "cid": client_id})


def _has_synced_active_client(engine, subagent_id: int) -> bool:
    with engine.connect() as conn:
        return conn.execute(text(
            "SELECT 1 FROM subagent_api_clients "
            "WHERE subagent_id = :s AND is_active AND sync_status = 'synced'"
        ), {"s": subagent_id}).fetchone() is not None


def _rotiraj_i_provisioniraj(engine, sub: dict) -> tuple[str, str | None]:
    _, _, code, name = _config()          # validacija pre bilo kakve promene
    if _has_synced_active_client(engine, sub["id"]):
        return "synced", None

    client_id, secret = generate_credentials(code)
    secret_hash = hash_secret(secret)     # baca grešku ako pepper nedostaje, pre upisa

    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE subagent_api_clients
            SET is_active = FALSE, sync_status = 'superseded',
                deactivated_at = COALESCE(deactivated_at, NOW())
            WHERE subagent_id = :s AND sync_status <> 'superseded'
        """), {"s": sub["id"]})
        conn.execute(text("""
            INSERT INTO subagent_api_clients
                (subagent_id, client_id, secret_hash, allowed_scopes, sync_status)
            VALUES (:s, :cid, :h, CAST(:scopes AS JSONB), 'pending')
        """), {"s": sub["id"], "cid": client_id, "h": secret_hash,
               "scopes": json.dumps(DEFAULT_SCOPES)})

    try:
        _app2_request("POST", "/api/internal/provision",
                      _provision_payload(sub, client_id, secret, code, name))
    except SyncError as exc:
        _set_status(engine, client_id, "failed", str(exc))
        log.warning("Provisioning subagenta %s nije uspeo: %s", sub["id"], exc)
        return "failed", str(exc)

    _set_status(engine, client_id, "synced")
    return "synced", None


def _deaktiviraj_u_app2(engine, subagent_id: int) -> tuple[str, str | None]:
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE subagent_api_clients
            SET is_active = FALSE, sync_status = 'deactivate_pending',
                deactivated_at = COALESCE(deactivated_at, NOW())
            WHERE subagent_id = :s
              AND (sync_status = 'synced' OR (sync_status = 'failed' AND is_active))
        """), {"s": subagent_id})
    with engine.connect() as conn:
        pending = conn.execute(text(
            "SELECT client_id FROM subagent_api_clients "
            "WHERE subagent_id = :s AND sync_status = 'deactivate_pending'"
        ), {"s": subagent_id}).fetchall()

    greska = None
    for row in pending:
        try:
            _app2_request("PATCH", f"/api/internal/organizer-connections/{row.client_id}",
                          {"is_active": False})
            _set_status(engine, row.client_id, "deactivated")
        except SyncError as exc:
            greska = str(exc)
            log.warning("Deaktivacija klijenta %s u App2 nije uspela: %s", row.client_id, exc)
    if greska:
        return "deactivate_pending", greska
    return "deactivated", None


def _push_profil(engine, sub: dict, client_id: str) -> tuple[str, str | None]:
    """Šalje podatke firme u App2 bez rotacije veze i tajne.

    Ako push padne, veza u App1 ostaje aktivna (App2 je i dalje koristi), a status
    je 'failed' da bi se prikazala greška i ponudio retry.
    """
    _, _, code, _ = _config()
    payload = {"subagent_key": _subagent_key(sub, code), **_profil_polja(sub)}
    try:
        _app2_request("PUT", "/api/internal/subagent-profile", payload)
    except SyncError as exc:
        log.warning("Osvežavanje profila subagenta %s nije uspelo: %s", sub["id"], exc)
        with engine.begin() as conn:
            conn.execute(text(
                "UPDATE subagent_api_clients SET sync_status = 'failed', sync_error = :err "
                "WHERE client_id = :cid"
            ), {"err": str(exc), "cid": client_id})
        return "failed", str(exc)
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE subagent_api_clients SET sync_status = 'synced', sync_error = NULL "
            "WHERE client_id = :cid"
        ), {"cid": client_id})
    return "synced", None


def _aktivni_klijent(engine, subagent_id: int) -> str | None:
    """client_id aktivne veze koja je u App2 (synced, ili failed posle neuspelog profila)."""
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT client_id FROM subagent_api_clients "
            "WHERE subagent_id = :s AND is_active AND sync_status IN ('synced', 'failed') "
            "ORDER BY created_at DESC LIMIT 1"
        ), {"s": subagent_id}).fetchone()
    return row.client_id if row else None


def sinhronizuj_nakon_izmene(
    engine, subagent_id: int, kljucna_promena: bool
) -> tuple[str | None, str | None]:
    """Poziva se posle svake izmene subagenta.

    kljucna_promena=True (PIB ili email): deaktivira postojeću vezu u App2 pa
    provisionira novu. Tako stari tenant ostaje bez aktivnog pristupa.
    kljucna_promena=False: samo osvežava podatke firme u App2 (bez nove tajne).
    Vraća (None, None) ako subagent nema API klijenta ili nije aktivan.
    """
    sub = _read_subagent(engine, subagent_id)
    if sub is None:
        raise LookupError(f"Subagent {subagent_id} ne postoji")
    if not sub["is_active"]:
        return None, None
    with engine.connect() as conn:
        ima_klijenta = conn.execute(text(
            "SELECT 1 FROM subagent_api_clients "
            "WHERE subagent_id = :s AND sync_status <> 'superseded'"
        ), {"s": subagent_id}).fetchone() is not None
    if not ima_klijenta:
        return None, None
    if not kljucna_promena:
        return sinhronizuj_subagenta(engine, subagent_id)
    try:
        status, greska = _deaktiviraj_u_app2(engine, subagent_id)
        if status != "deactivated":
            return status, greska
        return _rotiraj_i_provisioniraj(engine, sub)
    except SyncError as exc:
        return "failed", str(exc)


def sinhronizuj_subagenta(engine, subagent_id: int) -> tuple[str, str | None]:
    """Usklađuje stanje App1 sa App2. Vraća (status, greška).

    Aktivan subagent sa sinhronizovanom vezom: osvežava podatke firme u App2.
    Aktivan subagent bez sinhronizovane veze: novi klijent i provisioning.
    Neaktivan subagent: obaveštava App2 o deaktivaciji.
    Pozivati ponovo za retry nakon neuspeha.
    """
    sub = _read_subagent(engine, subagent_id)
    if sub is None:
        raise LookupError(f"Subagent {subagent_id} ne postoji")
    try:
        if sub["is_active"]:
            client_id = _aktivni_klijent(engine, sub["id"])
            if client_id:
                return _push_profil(engine, sub, client_id)
            return _rotiraj_i_provisioniraj(engine, sub)
        return _deaktiviraj_u_app2(engine, subagent_id)
    except SyncError as exc:
        return "failed", str(exc)


def deaktiviraj_pre_brisanja(engine, subagent_id: int) -> tuple[str, str | None]:
    """Pre brisanja subagenta u App1: deaktivira njegove veze u App2.

    App2 podatke ne briše (samo gasi pristup), pa se red u App2 može ponovo
    aktivirati provisioningom. Ako deaktivacija padne, App1 red se ne briše.
    """
    if _read_subagent(engine, subagent_id) is None:
        raise LookupError(f"Subagent {subagent_id} ne postoji")
    try:
        return _deaktiviraj_u_app2(engine, subagent_id)
    except SyncError as exc:
        return "failed", str(exc)


# ── Provera klijenta (za buduće App2 → App1 pozive) ─────────────────────────
def verify_client(engine, client_id: str, secret: str) -> dict | None:
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT c.subagent_id, c.secret_hash, c.allowed_scopes
            FROM subagent_api_clients c
            JOIN subagenti s ON s.id = c.subagent_id
            WHERE c.client_id = :cid AND c.is_active
              AND c.sync_status = 'synced' AND s.is_active
        """), {"cid": client_id}).fetchone()
    if row is None:
        return None
    if not hmac.compare_digest(row.secret_hash, hash_secret(secret)):
        return None
    return {"subagent_id": row.subagent_id, "scopes": row.allowed_scopes}


SCOPE_PRETRAGA = "slobodni_kapaciteti:read"
SCOPE_REZERVACIJA = "rezervacija:write"


def autentifikuj_subagenta(engine, request, scope: str = SCOPE_PRETRAGA) -> dict:
    """App2 šalje X-Client-Id / X-Client-Secret; scope određuje rutu (pretraga ili snimanje)."""
    cid = request.headers.get("X-Client-Id", "").strip()
    secret = request.headers.get("X-Client-Secret", "")
    klijent = verify_client(engine, cid, secret) if cid and secret else None
    if klijent is None:
        raise HTTPException(status_code=401, detail="Nevalidni kredencijali subagenta")
    scopes = klijent["scopes"]
    if isinstance(scopes, str):
        scopes = json.loads(scopes)
    if scope not in (scopes or []):
        raise HTTPException(status_code=403, detail="Subagent nema pravo za ovu akciju")
    return klijent


# ── Rute ─────────────────────────────────────────────────────────────────────
class SelektovaniIn(BaseModel):
    ids: list[int]


def register_subagent_api(api, engine, get_current_user):
    def _rezultat(item_id: int, is_active: bool):
        status, greska = sinhronizuj_subagenta(engine, item_id)
        return {"id": item_id, "is_active": is_active,
                "api_sync": status, "api_sync_error": greska}

    def _postavi_aktivnost(item_id: int, aktivan: bool):
        if not aktivan and je_zasticen(engine, item_id):
            raise HTTPException(
                status_code=403,
                detail="Subagent superadmina je uvek aktivan i ne može se deaktivirati",
            )
        with engine.begin() as conn:
            row = conn.execute(text(
                "UPDATE subagenti SET is_active = :a WHERE id = :id RETURNING id"
            ), {"a": aktivan, "id": item_id}).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Subagent nije pronađen")
        return _rezultat(item_id, aktivan)

    @api.post("/subagenti/{item_id}/deaktiviraj")
    def deaktiviraj_subagenta(item_id: int, _: dict = Depends(get_current_user)):
        return _postavi_aktivnost(item_id, False)

    @api.post("/subagenti/{item_id}/aktiviraj")
    def aktiviraj_subagenta(item_id: int, _: dict = Depends(get_current_user)):
        return _postavi_aktivnost(item_id, True)

    @api.post("/subagenti/{item_id}/sinhronizuj")
    def ponovi_sinhronizaciju(item_id: int, _: dict = Depends(get_current_user)):
        sub = _read_subagent(engine, item_id)
        if sub is None:
            raise HTTPException(status_code=404, detail="Subagent nije pronađen")
        return _rezultat(item_id, bool(sub["is_active"]))

    @api.post("/subagenti/sinhronizuj-selektovane")
    def sinhronizuj_selektovane(body: SelektovaniIn, _: dict = Depends(get_current_user)):
        """Sinhronizuje izabrane subagente sa App2 paralelno (8 odjednom); preskače
        već sinhronizovane, a jedan neuspeh ne prekida paket."""
        ids = list(dict.fromkeys(body.ids))  # ukloni duplikate, sačuvaj redosled
        if not ids:
            raise HTTPException(status_code=400, detail="Nije izabran nijedan subagent")
        if len(ids) > 500:
            raise HTTPException(status_code=400, detail="Maksimalno 500 subagenata odjednom")

        def _jedan(item_id: int) -> dict:
            sub = _read_subagent(engine, item_id)
            if sub is None:
                return {"id": item_id, "naziv": "", "api_sync": "not_found",
                        "api_sync_error": "Subagent ne postoji"}
            if (sub["naziv"] or "").upper().find("ASNS") != -1:
                # ASNS subagenti ne mogu da se sinhronizuju kroz ovu listu.
                return {"id": item_id, "naziv": sub["naziv"] or "",
                        "api_sync": "skipped",
                        "api_sync_error": "ASNS subagent se ne sinhronizuje"}
            if sub["is_active"] and _has_synced_active_client(engine, item_id):
                # Već sinhronizovan: ništa ne šalji App2, samo nastavi sa sledećim.
                return {"id": item_id, "naziv": sub["naziv"] or "",
                        "api_sync": "skipped", "api_sync_error": None}
            try:
                status, greska = sinhronizuj_subagenta(engine, item_id)
            except Exception as exc:  # noqa: BLE001 - jedan neuspeh ne prekida paket
                status, greska = "failed", f"{type(exc).__name__}: {exc}"
            return {"id": item_id, "naziv": sub["naziv"] or "",
                    "api_sync": status, "api_sync_error": greska}

        with ThreadPoolExecutor(max_workers=min(8, len(ids))) as ex:
            rezultati = list(ex.map(_jedan, ids))
        return {"rezultati": rezultati}
