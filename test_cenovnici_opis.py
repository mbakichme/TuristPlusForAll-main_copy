"""Cenovnici — polje Opis cenovnika: POST/PUT + UI (tab Kreiranje i tab Izmena)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from playwright.sync_api import sync_playwright, expect
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
import routes

engine = create_engine(os.environ["EXTERNAL_NEON_DATABASE_URL"])
app = routes.create_app("dist")
c = TestClient(app)
tok = routes.create_access_token({"sub": "1"})
H = {"Authorization": f"Bearer {tok}"}
OK = []


def check(label, cond):
    OK.append(cond)
    print(("PASS " if cond else "FAIL ") + label)


def bazni_opis(cid):
    with engine.connect() as conn:
        return conn.execute(text("SELECT opis FROM cenovnici WHERE id = :i"), {"i": cid}).scalar_one()


# ── 1) API ──────────────────────────────────────────────────────────────────
r = c.post("/api/cenovnici", headers=H, json={
    "mesto_id": 1, "grupa_id": 6, "smestaj_id": 8,
    "datumod": "2026-11-01", "datumdo": "2026-11-30", "cene": [],
    "opis": "  Termin 22.06–29.06, polazak iz Beograda  "})
check("POST sa opisom → 201", r.status_code == 201)
cid = r.json()["id"]
check("POST: opis sačuvan i trimovan",
      r.json()["opis"] == "Termin 22.06–29.06, polazak iz Beograda")

check("GET /cenovnici lista vraća opis",
      any(x["id"] == cid and x["opis"] == "Termin 22.06–29.06, polazak iz Beograda"
          for x in c.get("/api/cenovnici", headers=H).json()))

r2 = c.put(f"/api/cenovnici/{cid}", headers=H, json={
    "datumod": "2026-11-01", "datumdo": "2026-11-30", "cene": [],
    "opis": "Izmenjen opis kroz API"})
check("PUT menja opis", r2.status_code == 200 and r2.json()["opis"] == "Izmenjen opis kroz API")

r3 = c.put(f"/api/cenovnici/{cid}", headers=H, json={
    "datumod": "2026-11-01", "datumdo": "2026-11-30", "cene": []})
check("PUT bez opisa (None) ne dira postojeći", r3.status_code == 200
      and r3.json()["opis"] == "Izmenjen opis kroz API")

r4 = c.put(f"/api/cenovnici/{cid}", headers=H, json={
    "datumod": "2026-11-01", "datumdo": "2026-11-30", "cene": [], "opis": "x" * 501})
check("opis duži od 500 znakova → 422", r4.status_code == 422)

r5 = c.post("/api/cenovnici", headers=H, json={
    "mesto_id": 1, "grupa_id": 6, "smestaj_id": 8,
    "datumod": "2026-11-01", "datumdo": "2026-11-30", "cene": []})
check("POST bez opisa → prazan string", r5.status_code == 201 and r5.json()["opis"] == "")
c.delete(f"/api/cenovnici/{r5.json()['id']}", headers=H)

# ── 2) UI ───────────────────────────────────────────────────────────────────
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    BASE = "http://localhost:3058"
    pg.goto(f"{BASE}/agencija/cenovnici")
    pg.evaluate("t => localStorage.setItem('ta_token', t)", tok)
    pg.goto(f"{BASE}/agencija/cenovnici")
    pg.wait_for_selector("[role=tablist]")

    # tab Kreiranje: opis uz Aktivan od/do
    pg.get_by_role("combobox").nth(0).click()
    pg.get_by_role("option", name="Hanioti").first.click()
    pg.get_by_role("combobox").nth(1).click()
    pg.get_by_role("option").filter(has_text="Kasandra: termini").first.click()
    pg.get_by_role("combobox").nth(2).click()
    pg.get_by_role("option", name="DIMITRA").first.click()
    pg.get_by_role("button", name="Kreiraj cenovnik").click()
    expect(pg.get_by_role("textbox").first).to_be_visible(timeout=15000)

    opis_in = pg.locator("#create-opis")
    check("UI: polje Opis cenovnika vidljivo uz Aktivan od/do", opis_in.is_visible())
    opis_in.fill("Opis unet kroz UI")
    for trg, idx in (("create-od", 10), ("create-do", 15)):
        pg.locator(f"#{trg}").click()
        pg.locator("[data-radix-popper-content-wrapper]").last \
          .get_by_role("gridcell").get_by_role("button").nth(idx).click()
        pg.wait_for_timeout(200)

    with pg.expect_response(lambda r: r.url.rstrip("/").endswith("/api/cenovnici")
                            and r.request.method == "POST") as ri:
        pg.get_by_role("button", name="Sačuvaj cenovnik").click()
    ui_cid = ri.value.json()["id"]
    check("UI: opis poslat na POST i sačuvan u bazi",
          ri.value.json()["opis"] == "Opis unet kroz UI"
          and bazni_opis(ui_cid) == "Opis unet kroz UI")
    expect(pg.get_by_text("Zaključano")).to_be_visible()
    check("UI: posle čuvanja opis zaključan (disabled)", opis_in.is_disabled())

    # tab Izmena: polje sa postojećim opisom, može se izmeniti
    pg.get_by_role("tab", name="Izmena kreiranih cenovnika").click()
    red = pg.get_by_role("row").filter(has=pg.get_by_role("cell", name=str(ui_cid), exact=True))
    red.first.click()
    expect(pg.get_by_role("textbox").first).to_be_visible(timeout=15000)
    edit_opis = pg.locator("#edit-opis")
    check("UI: editor u tabu Izmena pokazuje sačuvani opis", edit_opis.input_value() == "Opis unet kroz UI")
    check("UI: red u listi prikazuje opis ispod naziva",
          red.first.filter(has_text="Opis unet kroz UI").count() > 0)
    edit_opis.fill("Opis izmenjen kroz UI")
    with pg.expect_response(lambda r: r.url.rstrip("/").endswith(f"/api/cenovnici/{ui_cid}")
                            and r.request.method == "PUT") as ri2:
        pg.get_by_role("button", name="Sačuvaj izmene").click()
    check("UI: izmena opisa sačuvana u bazi", bazni_opis(ui_cid) == "Opis izmenjen kroz UI")
    b.close()

# ── cleanup ─────────────────────────────────────────────────────────────────
check("cleanup cenovnik obrisan", c.delete(f"/api/cenovnici/{cid}", headers=H).status_code == 200)
check("cleanup UI cenovnik obrisan", c.delete(f"/api/cenovnici/{ui_cid}", headers=H).status_code == 200)

print(f"\n{sum(OK)}/{len(OK)} PASS")
sys.exit(0 if all(OK) else 1)
