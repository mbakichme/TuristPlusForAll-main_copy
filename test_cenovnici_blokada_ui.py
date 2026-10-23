"""Cenovnici — Blokada polja (UI): dugme „Blokada“ u tabu Izmena → dijalog → crvena polja.

Tok: izabrati opseg (datumi iz tabele perioda) + sobe (realne i virtuelne) → Snimi → polja
su crvena i u bazi blokirano=TRUE, ostale opcije netaknute; isključiti Blokirano + Snimi →
crveno nestaje i blokirano=FALSE.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from playwright.sync_api import sync_playwright, expect
from fastapi.testclient import TestClient
from sqlalchemy import text
import db_config
import routes

engine = db_config.get_engine()
app = routes.create_app("dist")
c = TestClient(app)
tok = routes.create_access_token({"sub": "1"})
H = {"Authorization": f"Bearer {tok}"}
OK = []


def check(label, cond):
    OK.append(cond)
    print(("PASS " if cond else "FAIL ") + label)


def dmy(iso):
    return f"{iso[8:10]}.{iso[5:7]}.{iso[:4]}"


def blok_u_bazi(cid):
    with engine.connect() as conn:
        return conn.execute(text(
            "SELECT COUNT(*) FROM opcije_soba WHERE cenovnik_id=:c AND blokirano = TRUE"),
            {"c": cid}).scalar_one()


r = c.post("/api/cenovnici", headers=H, json={
    "mesto_id": 1, "grupa_id": 6, "smestaj_id": 10,
    "datumod": "2026-05-25", "datumdo": "2026-10-02", "cene": []})
assert r.status_code == 201, r.text
d = r.json()
cid = d["id"]
naziv = d["naziv"]
realne = [s for s in d["sobe"] if not s.get("virtuelna")]
virtuelne = [s for s in d["sobe"] if s.get("virtuelna")]
izabrane_sobe = [realne[0], virtuelne[0]]  # realna + virtuelna
perioda = d["periodi"]
od_min = min(p["datum_od"] for p in perioda)
do_max = max(p["datum_do"] for p in perioda)
ocekivano = len(izabrane_sobe) * len(perioda)

try:
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        BASE = "http://localhost:3058"
        pg.add_init_script(f"localStorage.setItem('ta_token', '{tok}')")  # token pre prvog učitavanja
        pg.goto(f"{BASE}/agencija/cenovnici")
        pg.wait_for_selector("[role=tablist]")
        pg.get_by_role("tab", name="Izmena kreiranih cenovnika").click()
        pg.get_by_label("Pretraga cenovnika").fill(str(cid))
        redovi = pg.get_by_role("row").filter(has=pg.get_by_role("cell", name=str(cid), exact=True))
        expect(redovi).to_have_count(1, timeout=10000)
        redovi.first.get_by_role("button", name=f"Izmeni cenovnik {naziv}").click()
        pg.wait_for_selector("#edit-kopiraj", timeout=15000)

        pg.get_by_role("button", name="Blokada", exact=True).click()
        expect(pg.get_by_role("dialog").get_by_text("Blokada polja")).to_be_visible(timeout=8000)
        snimi = pg.get_by_role("button", name="Snimi", exact=True)
        check("UI: Snimi disabled dok nema opsega i soba", snimi.is_disabled())

        pg.locator("#blk-od").click()
        pg.get_by_role("option", name=dmy(od_min), exact=True).click()
        pg.locator("#blk-do").click()
        pg.get_by_role("option", name=dmy(do_max), exact=True).click()
        for s in izabrane_sobe:
            pg.locator(f"#blk-soba-{s['id']}").click()
        check("UI: Snimi aktivan kad je opseg + soba izabrano", snimi.is_enabled())

        with pg.expect_response(lambda r: r.request.method == "PUT"
                                and r.url.endswith(f"/cenovnici/{cid}/blokada")) as ri:
            snimi.click()
        check("UI: PUT /blokada payload = izabrane sobe + svi termini u opsegu, blokirano true",
              ri.value.status == 200 and ri.value.json()["broj_polja"] == ocekivano)
        check("DB: blokirano = TRUE za izabrana polja",
              blok_u_bazi(cid) == ocekivano)

        pg.get_by_text("Blokirano polja:").wait_for(timeout=8000)
        crvena = pg.locator("input.bg-red-100")
        expect(crvena).to_have_count(ocekivano, timeout=10000)
        check("UI: crvena polja u matrici = izabrane sobe × termini", crvena.count() == ocekivano)

        # odblokiraj isti izbor
        pg.get_by_role("button", name="Blokada", exact=True).click()
        expect(pg.get_by_role("dialog").get_by_text("Blokada polja")).to_be_visible(timeout=8000)
        pg.locator("#blk-od").click()
        pg.get_by_role("option", name=dmy(od_min), exact=True).click()
        pg.locator("#blk-do").click()
        pg.get_by_role("option", name=dmy(do_max), exact=True).click()
        for s in izabrane_sobe:
            pg.locator(f"#blk-soba-{s['id']}").click()
        pg.locator("#blk-blokirano").click()  # isključi Blokirano → skida blokadu
        with pg.expect_response(lambda r: r.request.method == "PUT"
                                and r.url.endswith(f"/cenovnici/{cid}/blokada")) as ri2:
            pg.get_by_role("button", name="Snimi", exact=True).click()
        check("UI: odblokiranje payload blokirano false → 200",
              ri2.value.status == 200 and ri2.value.json()["blokirano"] is False)
        pg.get_by_text("Blokada skinuta sa polja:").wait_for(timeout=8000)
        expect(crvena).to_have_count(0, timeout=10000)
        check("UI: nijedno polje nije crveno posle odblokiranja", crvena.count() == 0)
        check("DB: blokirano = FALSE posle odblokiranja", blok_u_bazi(cid) == 0)
        b.close()
finally:
    c.delete(f"/api/cenovnici/{cid}", headers=H)

print(f"\n{sum(OK)}/{len(OK)} provera prošlo")
sys.exit(0 if all(OK) else 1)
