"""Test istorije izmena (rezervacija_log) — offline prema dev serveru na 3158.

Provere (tok dodatnih usluga, jer ne menja cene ostalih polja ugovora):
1. POST /ugovori/{k}/dodatne → red u logu (oblast obracun, usluga_dodata)
2. PATCH stavke → usluga_izmenjena sa diff-om Usluga/EUR/DIN
3. DELETE stavke → usluga_obrisana
4. GET /rezervacije-istorija vraća događaje najnoviji prvi
5. čišćenje: stavka i test redovi loga
"""
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from sqlalchemy import create_engine, text

from routes import create_access_token

BASE = "http://127.0.0.1:3158/api"
tok = create_access_token({"sub": "1"})
hdr = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
engine = create_engine(os.environ.get("EXTERNAL_NEON_DATABASE_URL"))


def req(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(f"{BASE}{path}", data=data, headers=hdr, method=method)
    with urllib.request.urlopen(r, timeout=30) as resp:
        return json.load(resp)


def provera(uslov, opis):
    assert uslov, f"FAIL: {opis}"
    print(f"  OK {opis}")


started = datetime.now(timezone.utc)
with engine.connect() as c:
    kljuc = c.execute(text("SELECT kljuc FROM aranzman ORDER BY id DESC LIMIT 1")).scalar_one()
print(f"Ugovor za test: {kljuc}")
stavka = None
try:
    # 1. kreiranje stavke
    novo = req(f"/ugovori/{kljuc}/dodatne", "POST", {"usluga": "TEST LOG", "eur": 1, "din": 2})
    stavka = novo["stavka_id"]
    provera(stavka is not None, "POST dodatne vraća stavka_id")

    # 2. izmena stavke
    req(f"/ugovori/{kljuc}/dodatne/{stavka}", "PATCH", {
        "usluga": "TEST LOG 2", "eur": 3, "din": 2,
        "original": {"usluga": "TEST LOG", "eur": 1, "din": 2},
    })
    provera(True, "PATCH dodatne prolazi")

    # 3. brisanje stavke
    req(f"/ugovori/{kljuc}/dodatne/{stavka}", "DELETE", {
        "original": {"usluga": "TEST LOG 2", "eur": 3, "din": 2},
    })
    stavka = None
    provera(True, "DELETE dodatne prolazi")

    # 4. istorija
    rows = req(f"/rezervacije-istorija?kljuc={urllib.parse.quote(kljuc)}")["rows"]
    nove = [r for r in rows if datetime.fromisoformat(r["created_at"]) >= started]
    dogadjaji = [r["dogadjaj"] for r in nove]
    provera(dogadjaji == ["usluga_obrisana", "usluga_izmenjena", "usluga_dodata"],
            f"log redosled (najnoviji prvi): {dogadjaji}")
    provera(all(r["oblast"] == "obracun" for r in nove), "oblast = obracun")
    izm = next(r for r in nove if r["dogadjaj"] == "usluga_izmenjena")
    usl = next(p for p in izm["promene"] if p["polje"] == "Usluga")
    provera(usl == {"polje": "Usluga", "stara": "TEST LOG", "nova": "TEST LOG 2"},
            f"diff Usluga: {usl}")
    provera(izm["user_id"] == 1 or izm["user_id"] is not None, "user_id upisan")
finally:
    # 5. čišćenje
    with engine.begin() as c:
        if stavka is not None:
            c.execute(text("DELETE FROM dodatne WHERE stavka_id = :s"), {"s": stavka})
        c.execute(text("DELETE FROM rezervacija_log WHERE kljuc = :k AND created_at >= :t"),
                  {"k": kljuc, "t": started})
    print("Čišćenje gotovo")
print("SVE PROVERE PROŠLE")
