"""Cenovnici — Opcije · Popusti po sobi: tabele opcije_soba/popust_soba + API + UI dijalog.

API: GET/PUT/DELETE /cenovnici/{id}/opcije-soba/{soba_id} i /popust-soba/{soba_id}
(soba_id = id iz JSONB snimka, može biti negativan za virtuelne sobe).
UI: dugme Opcije · Popusti u listi taba Izmena → dijalog sa tabovima Opcije/Popusti.
"""
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


def db_rows(table, cid):
    with engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(
            text(f"SELECT * FROM {table} WHERE cenovnik_id = :c"), {"c": cid})]


def postavi_cenovnik():
    r = c.post("/api/cenovnici", headers=H, json={
        "mesto_id": 1, "grupa_id": 6, "smestaj_id": 10,  # ELENI 2 — ima i virtuelne sobe
        "datumod": "2026-05-25", "datumdo": "2026-10-02", "cene": []})
    assert r.status_code == 201, r.text
    return r.json()


# ── 1) API — Opcije ─────────────────────────────────────────────────────────
d = postavi_cenovnik()
cid = d["id"]
soba12 = next(s for s in d["sobe"] if s["broj_sobe"] == "12" and not s.get("virtuelna"))
v12 = next(s for s in d["sobe"] if s.get("virtuelna") and s["izvor_soba_id"] == soba12["id"])

r = c.get(f"/api/cenovnici/{cid}/opcije-soba/{soba12['id']}", headers=H)
check("opcije GET bez zapisa → postoji False + default-i",
      r.status_code == 200 and r.json()["postoji"] is False and r.json()["blokirano"] is False
      and r.json()["prevoz"] is None)

body = {"blokirano": True, "istaknuto": True, "blokirano_subagenci": True, "blokirano_sajt": False,
        "prevoz": "obavezan", "tip_aranzmana": "sa_prevozom", "tip_cene": "po_sobi",
        "popust_sopstveni_prevoz": "15.5"}
r = c.put(f"/api/cenovnici/{cid}/opcije-soba/{soba12['id']}", headers=H, json=body)
check("opcije PUT → 200, vrednosti vraćene",
      r.status_code == 200 and r.json()["postoji"] is True and r.json()["blokirano"] is True
      and r.json()["prevoz"] == "obavezan" and float(r.json()["popust_sopstveni_prevoz"]) == 15.5)
red = db_rows("opcije_soba", cid)
check("opcije upisane u bazu (UNIQUE cenovnik+soba)",
      len(red) == 1 and red[0]["blokirano"] is True and str(red[0]["popust_sopstveni_prevoz"]) == "15.50")

r = c.put(f"/api/cenovnici/{cid}/opcije-soba/{soba12['id']}", headers=H,
          json={"blokirano": True})
check("opcije PUT bez polja → full-replace (ostali resetovani)",
      r.status_code == 200 and r.json()["blokirano"] is True and r.json()["istaknuto"] is False
      and r.json()["prevoz"] is None and r.json()["popust_sopstveni_prevoz"] is None)

r = c.put(f"/api/cenovnici/{cid}/opcije-soba/{v12['id']}", headers=H,
          json={"istaknuto": True, "prevoz": "nemoguc"})
check("opcije na virtuelnoj sobi (negativan id) → 200",
      r.status_code == 200 and r.json()["prevoz"] == "nemoguc" and len(db_rows("opcije_soba", cid)) == 2)

r = c.delete(f"/api/cenovnici/{cid}/opcije-soba/{soba12['id']}", headers=H)
check("opcije DELETE → 200 i ponovo idempotentno",
      r.status_code == 200
      and c.delete(f"/api/cenovnici/{cid}/opcije-soba/{soba12['id']}", headers=H).status_code == 200)
check("opcije posle DELETE: postoji False",
      c.get(f"/api/cenovnici/{cid}/opcije-soba/{soba12['id']}", headers=H).json()["postoji"] is False)

check("opcije: nepoznat cenovnik → 404",
      c.get("/api/cenovnici/99999901/opcije-soba/1", headers=H).status_code == 404)
check("opcije: soba van snimka → 400",
      c.put(f"/api/cenovnici/{cid}/opcije-soba/987654", headers=H, json={}).status_code == 400)
check("opcije: los enum prevoz → 422",
      c.put(f"/api/cenovnici/{cid}/opcije-soba/{soba12['id']}", headers=H,
            json={"prevoz": "nekad"}).status_code == 422)

# ── 2) API — Popusti ────────────────────────────────────────────────────────
r = c.get(f"/api/cenovnici/{cid}/popust-soba/{soba12['id']}", headers=H)
check("popust GET bez zapisa → postoji False", r.status_code == 200 and r.json()["postoji"] is False)

pbody = {"umanjenje_vrsta": "procenat", "umanjenje": "10", "tip_popusta": "last_minute",
         "tip_placanja": "delimicno", "vazi_od": "2026-06-01", "vazi_do": "2026-06-30",
         "tip_aranzmana": "sa_prevozom", "tip_cene": "po_osobi", "popust_sopstveni_prevoz": "5.5"}
r = c.put(f"/api/cenovnici/{cid}/popust-soba/{soba12['id']}", headers=H, json=pbody)
check("popust PUT → 200, vrednosti vraćene",
      r.status_code == 200 and r.json()["postoji"] is True
      and r.json()["umanjenje_vrsta"] == "procenat" and float(r.json()["umanjenje"]) == 10.0
      and r.json()["tip_popusta"] == "last_minute" and r.json()["vazi_od"] == "2026-06-01")
check("popust u bazi", len(db_rows("popust_soba", cid)) == 1
      and db_rows("popust_soba", cid)[0]["tip_placanja"] == "delimicno")

r = c.put(f"/api/cenovnici/{cid}/popust-soba/{soba12['id']}", headers=H,
          json={"umanjenje_vrsta": "iznos", "umanjenje": "50", "tip_popusta": "first_minute"})
check("popust PUT menja zapis (jedan po sobi)",
      r.status_code == 200 and r.json()["umanjenje_vrsta"] == "iznos"
      and float(r.json()["umanjenje"]) == 50.0 and r.json()["tip_placanja"] is None
      and len(db_rows("popust_soba", cid)) == 1)

check("popust procenat 150 → 422",
      c.put(f"/api/cenovnici/{cid}/popust-soba/{soba12['id']}", headers=H,
            json={"umanjenje_vrsta": "procenat", "umanjenje": "150",
                  "tip_popusta": "last_minute"}).status_code == 422)
check("popust umanjenje 0 → 422",
      c.put(f"/api/cenovnici/{cid}/popust-soba/{soba12['id']}", headers=H,
            json={"umanjenje_vrsta": "iznos", "umanjenje": "0",
                  "tip_popusta": "last_minute"}).status_code == 422)
check("popust vazi_od > vazi_do → 422",
      c.put(f"/api/cenovnici/{cid}/popust-soba/{soba12['id']}", headers=H,
            json={"umanjenje_vrsta": "iznos", "umanjenje": "10", "tip_popusta": "last_minute",
                  "vazi_od": "2026-07-01", "vazi_do": "2026-06-01"}).status_code == 422)
check("popust los tip popusta → 422",
      c.put(f"/api/cenovnici/{cid}/popust-soba/{soba12['id']}", headers=H,
            json={"umanjenje_vrsta": "iznos", "umanjenje": "10",
                  "tip_popusta": "super_popust"}).status_code == 422)
check("popust los tip_placanja → 422",
      c.put(f"/api/cenovnici/{cid}/popust-soba/{soba12['id']}", headers=H,
            json={"umanjenje_vrsta": "iznos", "umanjenje": "10", "tip_popusta": "last_minute",
                  "tip_placanja": "na rate"}).status_code == 422)

r = c.delete(f"/api/cenovnici/{cid}/popust-soba/{soba12['id']}", headers=H)
check("popust DELETE → postoji False",
      r.status_code == 200
      and c.get(f"/api/cenovnici/{cid}/popust-soba/{soba12['id']}", headers=H).json()["postoji"] is False)

# cascade: obe tabele idu sa cenovnikom
c.put(f"/api/cenovnici/{cid}/opcije-soba/{soba12['id']}", headers=H, json={"blokirano": True})
c.put(f"/api/cenovnici/{cid}/popust-soba/{soba12['id']}", headers=H,
      json={"umanjenje_vrsta": "iznos", "umanjenje": "10", "tip_popusta": "last_minute"})
c.delete(f"/api/cenovnici/{cid}", headers=H)
check("cascade: opcije_soba i popust_soba obrisani sa cenovnikom",
      db_rows("opcije_soba", cid) == [] and db_rows("popust_soba", cid) == [])

# ── 3) UI ───────────────────────────────────────────────────────────────────
d2 = postavi_cenovnik()
ui_cid = d2["id"]
soba12_2 = next(s for s in d2["sobe"] if s["broj_sobe"] == "12" and not s.get("virtuelna"))

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    BASE = "http://localhost:3058"
    pg.goto(f"{BASE}/agencija/cenovnici")
    pg.evaluate("t => localStorage.setItem('ta_token', t)", tok)
    pg.goto(f"{BASE}/agencija/cenovnici")
    pg.wait_for_selector("[role=tablist]")
    pg.get_by_role("tab", name="Izmena kreiranih cenovnika").click()
    pg.get_by_label("Pretraga cenovnika").fill(str(ui_cid))
    redovi = pg.get_by_role("row").filter(has=pg.get_by_role("cell", name=str(ui_cid), exact=True))
    expect(redovi).to_have_count(1, timeout=10000)

    # čekaj i inicijalni GET opcija te sobe (efekt učitavanja resetuje formu — klikovi pre
    # njega bi bili pregazeni); klik na Opcije dugme pokreće lanac: detail → GET opcije
    with pg.expect_response(lambda r: r.request.method == "GET"
                            and r.url.endswith(f"/opcije-soba/{soba12_2['id']}"), timeout=10000):
        redovi.first.get_by_label(f"Opcije i popusti cenovnika #{ui_cid}").click()
    pg.get_by_role("heading", name="Opcije · Popusti").wait_for(timeout=10000)
    expect(pg.get_by_role("tab", name="Opcije")).to_be_visible(timeout=10000)
    pg.wait_for_timeout(300)  # .then obrade (forma iz odgovora)
    check("dijalog se otvara sa tabovima", pg.get_by_role("tab", name="Opcije").is_visible()
          and pg.get_by_role("tab", name="Popusti").is_visible())
    soba_sel = pg.locator("[role=dialog]").get_by_role("combobox").first
    expect(soba_sel).to_contain_text("12 · 1/3 STD", timeout=10000)

    # tab Opcije: prekidači + selectovi + iznos → Snimi
    pg.locator("#opc-blokirano").click()
    pg.locator("#opc-istaknuto").click()
    pg.locator("#opc-prevoz").click()
    pg.get_by_role("option", name="Obavezan").click()
    pg.locator("#opc-cena").click()
    pg.get_by_role("option", name="Po sobi").click()
    pg.locator("#opc-psp").fill("15")
    with pg.expect_response(lambda r: r.request.method == "PUT"
                            and r.url.endswith(f"/opcije-soba/{soba12_2['id']}")) as ri:
        pg.get_by_role("button", name="Snimi", exact=True).click()
    _odg = ri.value.json()
    check("UI: opcije PUT payload tačan",
          _odg["blokirano"] is True and _odg["istaknuto"] is True
          and _odg["prevoz"] == "obavezan" and _odg["tip_cene"] == "po_sobi"
          and float(_odg["popust_sopstveni_prevoz"]) == 15.0)
    pg.get_by_text("Opcije su sačuvane").wait_for(timeout=8000)
    check("UI: toast 'Opcije su sačuvane' + dugme Obriši omogućeno",
          pg.locator("[role=dialog]").get_by_role("button", name="Obriši opcije").is_enabled())

    # Obriši opcije
    pg.locator("[role=dialog]").get_by_role("button", name="Obriši opcije").click()
    pg.get_by_text("Opcije su obrisane").wait_for(timeout=8000)
    check("UI: opcije obrisane kroz dijalog",
          c.get(f"/api/cenovnici/{ui_cid}/opcije-soba/{soba12_2['id']}", headers=H).json()["postoji"] is False)

    # tab Popusti: procenat + sva polja → Snimi
    pg.get_by_role("tab", name="Popusti").click()
    pg.get_by_role("button", name="Procenat").click()
    pg.locator("#pop-umanjenje").fill("12,5")
    pg.locator("#pop-tip").click()
    pg.get_by_role("option", name="Last minute", exact=True).click()
    pg.locator("#pop-placanja").click()
    pg.get_by_role("option", name="Delimično").click()
    for trg, idx in (("pop-od", 10), ("pop-do", 15)):
        pg.locator(f"#{trg}").click()
        pg.locator("[data-radix-popper-content-wrapper]").last \
          .get_by_role("gridcell").get_by_role("button").nth(idx).click()
        pg.wait_for_timeout(200)
    pg.locator("#pop-psp").fill("5")
    with pg.expect_response(lambda r: r.request.method == "PUT"
                            and r.url.endswith(f"/popust-soba/{soba12_2['id']}")) as ri2:
        pg.get_by_role("button", name="Snimi", exact=True).click()
    pj = ri2.value.json()
    check("UI: popust PUT payload tačan (procenat 12.5, last_minute, delimično, datumi, psp 5)",
          pj["umanjenje_vrsta"] == "procenat" and float(pj["umanjenje"]) == 12.5
          and pj["tip_popusta"] == "last_minute" and pj["tip_placanja"] == "delimicno"
          and pj["vazi_od"] is not None and pj["vazi_do"] is not None
          and float(pj["popust_sopstveni_prevoz"]) == 5.0)
    pg.get_by_text("Popust je sačuvan").wait_for(timeout=8000)

    # validacija: procenat 150 → toast greške, bez PUT-a
    pg.locator("#pop-umanjenje").fill("150")
    pg.get_by_role("button", name="Snimi", exact=True).click()
    pg.get_by_text("Procenat može biti najviše 100").wait_for(timeout=8000)
    check("UI: procenat 150 odbijen na klijentu (API vrednost nepromenjena)",
          float(c.get(f"/api/cenovnici/{ui_cid}/popust-soba/{soba12_2['id']}", headers=H)
                .json()["umanjenje"]) == 12.5)

    # Obriši popust
    pg.locator("[role=dialog]").get_by_role("button", name="Obriši popust").click()
    pg.get_by_text("Popust je obrisan").wait_for(timeout=8000)
    check("UI: popust obrisan kroz dijalog",
          c.get(f"/api/cenovnici/{ui_cid}/popust-soba/{soba12_2['id']}", headers=H).json()["postoji"] is False)
    b.close()

check("cleanup UI cenovnik obrisan", c.delete(f"/api/cenovnici/{ui_cid}", headers=H).status_code == 200)

print(f"\n{sum(OK)}/{len(OK)} PASS")
sys.exit(0 if all(OK) else 1)
