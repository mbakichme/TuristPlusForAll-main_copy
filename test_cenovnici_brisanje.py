import db_config

"""Cenovnici — brisanje kompletnog cenovnika (tab Izmena + DELETE endpoint).

1) API: DELETE /cenovnici/{id} — 401 bez tokena, 404 nepoznat, roundtrip
   kreiraj→obriši→GET 404, cene/opcije CASCADE.
2) UI: korpa u redu liste → AlertDialog „Obrisati cenovnik?“ (upozorenje da je
   brisanje trajno) → „Obriši trajno“ → red nestaje, editor se čisti.

Cleanup: test briše svoj cenovnik (UI tok ga briše; API ostatak ide kroz SQL).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/tmp/pw-browsers")
import requests
from playwright.sync_api import sync_playwright, expect
from sqlalchemy import create_engine, text
import routes

BASE = os.environ.get("TA_BASE", "http://localhost:3158/api")
UI = "http://localhost:3058"
eng = db_config.get_engine()
H = {"Authorization": f"Bearer {routes.create_access_token({'sub': '1'})}"}

def proveri(naziv, uslov, detalj=""):
    print(f"{'PASS' if uslov else 'FAIL'} {naziv}" + (f" — {detalj}" if detalj and not uslov else ""))
    if not uslov:
        sys.exit(1)

# ── 1) API ───────────────────────────────────────────────────────────────────
r = requests.delete(f"{BASE}/cenovnici/999999", timeout=15)
proveri("DELETE bez tokena → 401", r.status_code == 401, f"status={r.status_code}")
r = requests.delete(f"{BASE}/cenovnici/999999", headers=H, timeout=15)
proveri("DELETE nepoznat → 404", r.status_code == 404, f"status={r.status_code}")

# roundtrip: kreiraj cenovnik (DIMITRA, grupa 6) pa ga obriši preko API-ja
r = requests.post(f"{BASE}/cenovnici", headers=H, timeout=30, json={
    "mesto_id": 1, "grupa_id": 6, "smestaj_id": 8,
    "datumod": "2026-10-01", "datumdo": "2026-10-31",
    "cene": [],
})
proveri("POST test cenovnika → 201", r.status_code == 201, f"status={r.status_code} {r.text[:150]}")
cid = r.json()["id"]
r = requests.delete(f"{BASE}/cenovnici/{cid}", headers=H, timeout=15)
proveri("DELETE → 200", r.status_code == 200, f"status={r.status_code}")
r = requests.get(f"{BASE}/cenovnici/{cid}", headers=H, timeout=15)
proveri("GET posle brisanja → 404", r.status_code == 404, f"status={r.status_code}")
with eng.connect() as c:
    n = c.execute(text("SELECT COUNT(*) FROM cenovnik_cene WHERE cenovnik_id=:i"), {"i": cid}).scalar()
proveri("CASCADE: nema zaostalih cena", n == 0, f"ostalo={n}")

# ── 2) UI ────────────────────────────────────────────────────────────────────
r = requests.post(f"{BASE}/cenovnici", headers=H, timeout=30, json={
    "mesto_id": 1, "grupa_id": 6, "smestaj_id": 8,
    "datumod": "2026-10-01", "datumdo": "2026-10-31",
    "cene": [],
}).json()
cid = r["id"]
naziv = r["naziv"]

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(f"{UI}/agencija/cenovnici")
    pg.evaluate("t => localStorage.setItem('ta_token', t)", routes.create_access_token({"sub": "1"}))
    pg.goto(f"{UI}/agencija/cenovnici")
    pg.wait_for_selector("[role=tablist]")
    pg.get_by_role("tab", name="Izmena kreiranih cenovnika").click()

    red = pg.get_by_role("row").filter(has=pg.get_by_role("cell", name=str(cid), exact=True))
    expect(red).to_be_visible(timeout=15000)

    # korpa → AlertDialog sa upozorenjem
    red.get_by_label(f"Obriši cenovnik {naziv}").click()
    expect(pg.get_by_text("Obrisati cenovnik?")).to_be_visible()
    expect(pg.get_by_text("Brisanje je trajno i ne može se opozvati.")).to_be_visible()
    proveri("AlertDialog: upozorenje da je brisanje trajno", True)

    # Otkaži → red ostaje
    pg.get_by_role("button", name="Otkaži").click()
    expect(red).to_be_visible()
    proveri("Otkaži: red ostaje", True)

    # korpa → Obriši trajno
    red.get_by_label(f"Obriši cenovnik {naziv}").click()
    pg.get_by_role("button", name="Obriši trajno").click()
    expect(pg.get_by_text(f"je obrisan")).to_be_visible(timeout=10000)
    expect(red).to_have_count(0, timeout=10000)
    proveri("Obriši trajno: red nestaje iz liste", True)

    assert errs == [], errs
    print("PASS UI — brisanje cenovnika radi")
    b.close()

with eng.connect() as c:
    n = c.execute(text("SELECT COUNT(*) FROM cenovnici WHERE id=:i"), {"i": cid}).scalar()
proveri("DB: cenovnik obrisan", n == 0, f"ostalo={n}")
print(f"[cleanup] test cenovnik {cid} obrisan kroz UI/API")
