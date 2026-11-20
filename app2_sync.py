"""Direktan upis rezervacija iz App1 u App2 bazu (best effort).

Posle svake promene rezervacije (kreiranje, izmena, storno) App1 kopira redove
`aranzman`, `aranzman_dopuna` i `rezervacija_log` za taj broj ugovora u App2 bazu,
preko role `app1_sync`. Upis ide u tenant čiji je par (instanca, subagent) povezan
u App2 (`tenants.app1_instance`, `tenants.app1_subagent_id`).

Greška se loguje i ne ruši App1 zapis. App2 se sustiže punim osvežavanjem
(`sinhronizuj_sve`).

Podešavanje (env):
  APP2_SYNC_DATABASE_URL  konekcija na App2 bazu kao rola app1_sync (bez te
                          promenljive sinhronizacija je isključena)
  APP2_SYNC_KEY           deljeni ključ za POST /sync/puna (App2 ga šalje u X-Sync-Key)
  ORGANIZER_CODE          naziv instance u App2 (npr. "oktopod")

CLI za puno osvežavanje:
  uv run python -m app2_sync
"""
import hmac
import json
import logging
import os
import threading
import time
from pathlib import Path

from fastapi import HTTPException, Request
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

log = logging.getLogger(__name__)

APP2_SYNC_URL_ENV = "APP2_SYNC_DATABASE_URL"
# Deljeni ključ za puno osvežavanje, App2 ga šalje u X-Sync-Key (različit od SUBAGENT_* ključeva).
APP2_SYNC_KEY_ENV = "APP2_SYNC_KEY"
# Kolone koje postoje samo u App1 (App2 ih ne čuva).
APP1_ONLY_KOLONE = {"subagent_id"}

_app2_engine: Engine | None = None

# Keš uspešne subagent autentifikacije: (client_id, hash_secret) -> naziv subagenta.
# Skraćuje jedan round-trip po zahtevu; ukinut klijent prestaje da važi najviše AUTH_KES_SEKUNDI kasnije.
AUTH_KES_SEKUNDI = 60
_auth_lock = threading.Lock()
_auth_kes: dict[tuple[str, str], tuple[float, str]] = {}


def _app2() -> Engine | None:
    global _app2_engine
    url = (os.environ.get(APP2_SYNC_URL_ENV) or "").strip()
    if not url:
        return None
    if _app2_engine is None:
        _app2_engine = create_engine(url, pool_pre_ping=True, pool_size=2)
    return _app2_engine


def _instanca() -> str:
    return (os.environ.get("ORGANIZER_CODE") or "").strip().lower()


# Kopira se samo rezervacija kreirana posle aktiviranja lokalnog snimanja (App2 flag).
# Vreme kreiranja je najraniji događaj 'kreirana' u rezervacija_log za ugovor.
KREIRANE_POSLE_SQL = (
    "SELECT kljuc FROM rezervacija_log WHERE dogadjaj = 'kreirana' "
    "GROUP BY kljuc HAVING min(created_at) >= CAST(:od AS timestamptz)"
)


def _lokalno_od(app2: Engine, instanca: str, subagent_id: int):
    """Trenutak aktiviranja lokalnog snimanja za tenant (App2). None = isključeno ili nije povezan."""
    with app2.connect() as conn:
        return conn.execute(text(
            "SELECT app1_lokalno_snimanje_od(:i, :s)"
        ), {"i": instanca, "s": subagent_id}).scalar()


def kolone_za_upis(row: dict) -> dict:
    """Kolone reda koje se šalju u App2 (bez App1-only kolona i id-ja koji se koristi kao ključ)."""
    return {k: v for k, v in row.items() if k not in APP1_ONLY_KOLONE}


def _resolve_subagent_id(engine: Engine, row: dict) -> int | None:
    """subagent_id reda; ako je prazan, pronalazi po nazivu i upisuje u App1."""
    if row.get("subagent_id"):
        return int(row["subagent_id"])
    naziv = (row.get("subagent") or "").strip()
    if not naziv:
        return None
    with engine.begin() as conn:
        sid = conn.execute(text(
            "SELECT id FROM subagenti WHERE naziv = :n ORDER BY id LIMIT 1"
        ), {"n": naziv}).scalar()
        if sid is not None:
            conn.execute(text(
                "UPDATE aranzman SET subagent_id = :s WHERE id = :i"
            ), {"s": sid, "i": row["id"]})
    return int(sid) if sid is not None else None


def _upsert(conn, tabela: str, red: dict, tenant_id: str, instanca: str, kljuc_konflikta: str) -> None:
    cols = kolone_za_upis(red)
    cols = {"tenant_id": tenant_id, "app1_instance": instanca, **cols}
    imena = ", ".join(cols)
    ph = ", ".join(f":{c}" for c in cols)
    sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c not in ("tenant_id", kljuc_konflikta))
    conn.execute(text(
        f"INSERT INTO {tabela} ({imena}) VALUES ({ph}) "
        f"ON CONFLICT (tenant_id, {kljuc_konflikta}) DO UPDATE SET {sets}, synced_at = now()"
    ), cols)


def sinhronizuj_kljuc(engine: Engine, kljuc: str) -> str:
    """Kopira sve redove jednog ugovora u App2. Vraća status:
    'synced', 'nema_reda', 'bez_subagenta', 'tenant_nije_povezan', 'app2_nedostupna',
    'lokalno_iskljuceno', 'kreirano_pre_aktiviranja'.
    Baca izuzetak samo za greške upisa u App2 (poziv hvata sinhronizuj_posle_izmene)."""
    app2 = _app2()
    if app2 is None:
        return "app2_nedostupna"
    instanca = _instanca()
    with engine.connect() as conn:
        redovi = [dict(r) for r in conn.execute(text(
            "SELECT * FROM aranzman WHERE kljuc = :k ORDER BY id"
        ), {"k": kljuc}).mappings().all()]
    if not redovi:
        return "nema_reda"
    subagent_id = _resolve_subagent_id(engine, redovi[0])
    if subagent_id is None:
        return "bez_subagenta"
    od = _lokalno_od(app2, instanca, subagent_id)
    if od is None:
        return "lokalno_iskljuceno"
    with engine.connect() as conn:
        kreirana_posle = conn.execute(text(
            f"SELECT 1 FROM ({KREIRANE_POSLE_SQL}) k WHERE k.kljuc = :k"
        ), {"k": kljuc, "od": od}).scalar()
    if not kreirana_posle:
        return "kreirano_pre_aktiviranja"

    with engine.connect() as conn:
        dopune = [dict(r) for r in conn.execute(text(
            "SELECT d.* FROM aranzman_dopuna d JOIN aranzman a ON a.id = d.aranzman_id "
            "WHERE a.kljuc = :k ORDER BY d.id"
        ), {"k": kljuc}).mappings().all()]
        log_redovi = [dict(r) for r in conn.execute(text(
            "SELECT * FROM rezervacija_log WHERE kljuc = :k ORDER BY id"
        ), {"k": kljuc}).mappings().all()]

    with app2.begin() as conn:
        tenant_id = conn.execute(text(
            "SELECT app1_resolve_tenant(:i, :s)"
        ), {"i": instanca, "s": subagent_id}).scalar()
        if tenant_id is None:
            return "tenant_nije_povezan"
        conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        for red in redovi:
            _upsert(conn, "aranzman", red, str(tenant_id), instanca, "id")
        ids = [r["id"] for r in redovi]
        conn.execute(text(
            "DELETE FROM aranzman_dopuna WHERE tenant_id = :t AND aranzman_id = ANY(:ids)"
        ), {"t": str(tenant_id), "ids": ids})
        for d in dopune:
            _upsert(conn, "aranzman_dopuna", d, str(tenant_id), instanca, "id")
        for lg in log_redovi:
            _upsert(conn, "rezervacija_log", lg, str(tenant_id), instanca, "id")
    return "synced"


def sinhronizuj_posle_izmene(engine: Engine, kljuc: str) -> None:
    """Poziva se posle commit-a u App1. Nikad ne baca izuzetak (best effort)."""
    if _app2() is None:
        return
    try:
        status = sinhronizuj_kljuc(engine, kljuc)
        if status != "synced":
            log.warning("App2 sinhronizacija %s: %s", kljuc, status)
    except Exception:
        log.exception("App2 sinhronizacija %s nije uspela; sustiže se punim osvežavanjem", kljuc)


BATCH_VELICINA = 100


def _chunks(lista: list, n: int):
    for i in range(0, len(lista), n):
        yield lista[i:i + n]


def _upsert_batch(conn, tabela: str, redovi: list[dict], tenant_id: str, instanca: str, kljuc_konflikta: str) -> None:
    """Jedan INSERT ... VALUES (...),(...) ON CONFLICT za do BATCH_VELICINA redova."""
    if not redovi:
        return
    prepared = [{"tenant_id": tenant_id, "app1_instance": instanca, **kolone_za_upis(r)} for r in redovi]
    imena = list(prepared[0].keys())
    params: dict = {}
    vrednosti = []
    for i, red in enumerate(prepared):
        for c in imena:
            params[f"{c}_{i}"] = red.get(c)
        vrednosti.append("(" + ", ".join(f":{c}_{i}" for c in imena) + ")")
    sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in imena if c not in ("tenant_id", kljuc_konflikta))
    conn.execute(text(
        f"INSERT INTO {tabela} ({', '.join(imena)}) VALUES {', '.join(vrednosti)} "
        f"ON CONFLICT (tenant_id, {kljuc_konflikta}) DO UPDATE SET {sets}, synced_at = now()"
    ), params)


def _backfill_subagent_id(engine: Engine) -> None:
    """Jednim UPDATE-om popunjava aranzman.subagent_id za redove koji ga nemaju (po nazivu)."""
    with engine.begin() as conn:
        conn.execute(text(
            "WITH m AS (SELECT DISTINCT ON (naziv) naziv, id FROM subagenti ORDER BY naziv, id) "
            "UPDATE aranzman a SET subagent_id = m.id FROM m "
            "WHERE a.subagent_id IS NULL AND m.naziv = btrim(a.subagent)"
        ))


def _sinhronizuj_subagenta(engine: Engine, app2: Engine, instanca: str, subagent_id: int) -> tuple[str, int]:
    """Ugovori jednog subagenta u tenant povezan sa (instanca, subagent_id), samo oni kreirani
    posle aktiviranja lokalnog snimanja. Vraća (status, broj ugovora)."""
    od = _lokalno_od(app2, instanca, subagent_id)
    if od is None:
        return "lokalno_iskljuceno", 0
    params = {"s": subagent_id, "od": od}
    with engine.connect() as conn:
        redovi = [dict(r) for r in conn.execute(text(
            "SELECT * FROM aranzman WHERE subagent_id = :s AND kljuc IN (" + KREIRANE_POSLE_SQL + ") "
            "ORDER BY id"
        ), params).mappings().all()]
        if not redovi:
            return "nema_reda", 0
        dopune = [dict(r) for r in conn.execute(text(
            "SELECT d.* FROM aranzman_dopuna d JOIN aranzman a ON a.id = d.aranzman_id "
            "WHERE a.subagent_id = :s AND a.kljuc IN (" + KREIRANE_POSLE_SQL + ") ORDER BY d.id"
        ), params).mappings().all()]
        log_redovi = [dict(r) for r in conn.execute(text(
            "SELECT * FROM rezervacija_log WHERE kljuc IN "
            "(SELECT kljuc FROM aranzman WHERE subagent_id = :s) "
            "AND kljuc IN (" + KREIRANE_POSLE_SQL + ") ORDER BY id"
        ), params).mappings().all()]

    with app2.begin() as conn:
        tenant_id = conn.execute(text(
            "SELECT app1_resolve_tenant(:i, :s)"
        ), {"i": instanca, "s": subagent_id}).scalar()
        if tenant_id is None:
            return "tenant_nije_povezan", len(redovi)
        tenant_id = str(tenant_id)
        conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tenant_id})
        for chunk in _chunks(redovi, BATCH_VELICINA):
            _upsert_batch(conn, "aranzman", chunk, tenant_id, instanca, "id")
        ids = [r["id"] for r in redovi]
        conn.execute(text(
            "DELETE FROM aranzman_dopuna WHERE tenant_id = :t AND aranzman_id = ANY(:ids)"
        ), {"t": tenant_id, "ids": ids})
        for chunk in _chunks(dopune, BATCH_VELICINA):
            _upsert_batch(conn, "aranzman_dopuna", chunk, tenant_id, instanca, "id")
        for chunk in _chunks(log_redovi, BATCH_VELICINA):
            _upsert_batch(conn, "rezervacija_log", chunk, tenant_id, instanca, "id")
    return "synced", len(redovi)


def sinhronizuj_sve(engine: Engine) -> dict[str, int]:
    """Puno osvežavanje: svi ugovori iz App1, grupisano po subagentu (jedno povezivanje tenant-a
    po subagentu, multi-row upsert). Vraća brojeve: ugovora sinhronizovano, subagenata po statusu."""
    app2 = _app2()
    if app2 is None:
        return {"app2_nedostupna": 1}
    instanca = _instanca()
    _backfill_subagent_id(engine)
    # Samo subagenti povezani sa tenant-om u App2 (funkcija app1_linked_subagents, migracija 010).
    with app2.connect() as conn:
        povezani = [r[0] for r in conn.execute(text(
            "SELECT app1_linked_subagents(:i)"
        ), {"i": instanca}).fetchall()]
    with engine.connect() as conn:
        bez_subagenta = conn.execute(text(
            "SELECT count(DISTINCT kljuc) FROM aranzman WHERE subagent_id IS NULL"
        )).scalar()
    rezultat: dict[str, int] = {"ugovora_sinhronizovano": 0, "bez_subagenta_ugovora": int(bez_subagenta or 0)}
    for sid in povezani:
        try:
            status, n = _sinhronizuj_subagenta(engine, app2, instanca, sid)
        except Exception:
            log.exception("App2 puno osvežavanje, subagent %s nije uspelo", sid)
            status, n = "greska", 0
        if status == "synced":
            rezultat["ugovora_sinhronizovano"] += n
        rezultat[f"subagenata_{status}"] = rezultat.get(f"subagenata_{status}", 0) + 1
    return rezultat


def register_app2_sync(api, engine):
    """Puno osvežavanje na zahtev App2 superadmina. Zaštita: deljeni ključ APP2_SYNC_KEY
    (header X-Sync-Key). Subagent klijenti ovde nemaju pristup.

    Vraća `subagent_iz_zahteva(request) -> str`: proverava X-Client-Id / X-Client-Secret
    (per-subagent, kao pretraga) i vraća naziv subagenta (aranzman.subagent). Koristi ga sync ruta za ugovore."""

    def subagent_iz_zahteva(request: Request) -> str:
        """Per-subagent autentifikacija (X-Client-Id / X-Client-Secret), isto kao pretraga i rezervacije.
        Vraća naziv subagenta čiji su kredencijali. Ne koristi globalni X-Sync-Key."""
        from subagent_api import hash_secret

        cid = request.headers.get("X-Client-Id", "").strip()
        secret = request.headers.get("X-Client-Secret", "")
        if not cid or not secret:
            raise HTTPException(status_code=401, detail="Nevalidni kredencijali subagenta")
        hes = hash_secret(secret)
        kljuc = (cid, hes)
        with _auth_lock:
            hit = _auth_kes.get(kljuc)
            if hit and time.monotonic() - hit[0] < AUTH_KES_SEKUNDI:
                return hit[1]
        # Jedan upit umesto dva (verify_client + naziv): klijent, hash i naziv subagenta zajedno.
        with engine.connect() as conn:
            red = conn.execute(text(
                "SELECT c.secret_hash, s.naziv FROM subagent_api_clients c "
                "JOIN subagenti s ON s.id = c.subagent_id "
                "WHERE c.client_id = :cid AND c.is_active AND c.sync_status = 'synced' "
                "AND s.is_active AND COALESCE(s.naziv, '') <> ''"
            ), {"cid": cid}).fetchone()
        if red is None or not hmac.compare_digest(red.secret_hash, hes):
            raise HTTPException(status_code=401, detail="Nevalidni kredencijali subagenta")
        with _auth_lock:
            sada = time.monotonic()
            for k in [k for k, (t, _) in _auth_kes.items() if sada - t >= AUTH_KES_SEKUNDI]:
                del _auth_kes[k]
            _auth_kes[kljuc] = (sada, red.naziv)
        return red.naziv

    @api.post("/sync/puna")
    def sync_puna(request: Request):
        ocekivano = (os.environ.get(APP2_SYNC_KEY_ENV) or "").strip()
        if not ocekivano:
            raise HTTPException(status_code=503, detail="Sinhronizacija nije podešena")
        primljen = request.headers.get("X-Sync-Key", "")
        if not hmac.compare_digest(primljen.encode(), ocekivano.encode()):
            raise HTTPException(status_code=401, detail="Nevalidan ključ")
        if _app2() is None:
            raise HTTPException(status_code=503, detail="APP2_SYNC_DATABASE_URL nije podešen")
        return {"instanca": _instanca(), "rezultat": sinhronizuj_sve(engine)}

    @api.get("/sync/meni/knjigovodstvo")
    def sync_meni_knjigovodstvo(request: Request):
        """Stavke menija Knjigovodstva za App2 levi meni (X-Sync-Key, isti ključ kao /sync/rezervacije)."""
        ocekivano = (os.environ.get(APP2_SYNC_KEY_ENV) or "").strip()
        if not ocekivano:
            raise HTTPException(status_code=503, detail="Sinhronizacija nije podešena")
        primljen = request.headers.get("X-Sync-Key", "")
        if not hmac.compare_digest(primljen.encode(), ocekivano.encode()):
            raise HTTPException(status_code=401, detail="Nevalidan ključ")
        putanja = Path(__file__).parent / "src" / "config" / "menuKnjigovodstvo.json"
        return {"sekcija": "knjigovodstvo", "stavke": json.loads(putanja.read_text(encoding="utf-8"))}

    @api.get("/sync/rezervacije")
    def sync_rezervacije(request: Request):
        """Rezervacije jednog subagenta za App2 listu (X-Sync-Key). Subagent se nalazi po
        client_id. Ne proverava is_active klijenta, pa istorija ostaje vidljiva i posle
        isključenja veze."""
        ocekivano = (os.environ.get(APP2_SYNC_KEY_ENV) or "").strip()
        if not ocekivano:
            raise HTTPException(status_code=503, detail="Sinhronizacija nije podešena")
        primljen = request.headers.get("X-Sync-Key", "")
        if not hmac.compare_digest(primljen.encode(), ocekivano.encode()):
            raise HTTPException(status_code=401, detail="Nevalidan ključ")
        client_id = request.query_params.get("client_id", "").strip()
        if not client_id:
            raise HTTPException(status_code=400, detail="client_id je obavezan")
        try:
            limit = min(max(int(request.query_params.get("limit", 25)), 1), 500)
            offset = max(int(request.query_params.get("offset", 0)), 0)
        except ValueError:
            raise HTTPException(status_code=400, detail="limit i offset moraju biti brojevi")
        # Jedan upit umesto tri: klijent -> naziv subagenta, ukupan broj i stranica.
        with engine.connect() as conn:
            red = conn.execute(text(
                "WITH k AS ("
                "  SELECT s.naziv FROM subagent_api_clients c "
                "  JOIN subagenti s ON s.id = c.subagent_id WHERE c.client_id = :cid"
                "), u AS ("
                "  SELECT count(*) AS ukupno FROM aranzman a "
                "  WHERE a.subagent = (SELECT naziv FROM k)"
                "), r AS ("
                "  SELECT a.id, a.kljuc, a.putnik, a.datumod, a.naziv, a.tiprezervacije, a.cenaaranz "
                "  FROM aranzman a WHERE a.subagent = (SELECT naziv FROM k) "
                "  ORDER BY a.datumod DESC NULLS LAST, a.id DESC LIMIT :l OFFSET :o"
                ") "
                "SELECT k.naziv, u.ukupno, r.* FROM k CROSS JOIN u "
                "LEFT JOIN r ON true"
            ), {"cid": client_id, "l": limit, "o": offset}).mappings().all()
        if not red:
            raise HTTPException(status_code=404, detail="Nepoznat klijent")
        naziv, ukupno = red[0]["naziv"], red[0]["ukupno"]
        redovi = [r for r in red if r["id"] is not None]
        return {
            "instanca": _instanca(),
            "subagent": naziv,
            "ukupno": ukupno,
            "stavke": [
                {
                    "id": r["id"],
                    "kljuc": r["kljuc"],
                    "putnik": r["putnik"] or "",
                    "datumod": r["datumod"].isoformat() if r["datumod"] else None,
                    "naziv": r["naziv"] or "",
                    "tiprezervacije": r["tiprezervacije"] or "",
                    "cenaaranz": float(r["cenaaranz"] or 0),
                }
                for r in redovi
            ],
        }

    return subagent_iz_zahteva


if __name__ == "__main__":
    from db_config import get_engine

    logging.basicConfig(level=logging.INFO)
    print(sinhronizuj_sve(get_engine()))
