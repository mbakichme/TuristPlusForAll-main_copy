"""Cenovnici — Opcije · Popusti: tabele opcije_soba/popust_soba + API + UI dijalog.

API: GET/PUT/DELETE /cenovnici/{id}/opcije-soba/{soba_id} i /popust-soba/{soba_id} — opseg = soba
za SVE termine: PUT upisuje EKSPLICITNO po polju (soba × svaki period snimka, bez period_id=0),
GET spaja vrednosti (isto u svim redovima → vrednost, mešovito → neutralno). soba_id = id iz
JSONB snimka, može biti negativan za virtuelne sobe.
UI: dugme Opcije · Popusti u listi taba Izmena → dijalog u MASOVNOM modu (bez selektora sobe,
banner „sve sobe i sve termine“) — Snimi/Obriši idu na -sve endpointe.
"""
import json
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


# ── 1) API — Opcije po sobi (soba × SVI termini) ────────────────────────────
d = postavi_cenovnik()
cid = d["id"]
P = len(d["periodi"])
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
check("opcije PUT → 200, vrednosti vraćene (spojene preko svih perioda)",
      r.status_code == 200 and r.json()["postoji"] is True and r.json()["blokirano"] is True
      and r.json()["prevoz"] == "obavezan" and float(r.json()["popust_sopstveni_prevoz"]) == 15.5)
red = db_rows("opcije_soba", cid)
check("opcije upisane EKSPLICITNO po polju — P redova (soba × svaki termin), bez period_id=0",
      len(red) == P and all(r["period_id"] != 0 for r in red)
      and {(r["soba_id"], r["period_id"]) for r in red}
      == {(soba12["id"], p["id"]) for p in d["periodi"]}
      and str(red[0]["popust_sopstveni_prevoz"]) == "15.50")

r = c.put(f"/api/cenovnici/{cid}/opcije-soba/{soba12['id']}", headers=H,
          json={"blokirano": True})
check("opcije PUT bez polja → full-replace (ostali resetovani, i dalje P redova)",
      r.status_code == 200 and r.json()["blokirano"] is True and r.json()["istaknuto"] is False
      and r.json()["prevoz"] is None and r.json()["popust_sopstveni_prevoz"] is None
      and len(db_rows("opcije_soba", cid)) == P)

r = c.put(f"/api/cenovnici/{cid}/opcije-soba/{v12['id']}", headers=H,
          json={"istaknuto": True, "prevoz": "nemoguc"})
check("opcije na virtuelnoj sobi (negativan id) → 200 (2 sobe × P perioda)",
      r.status_code == 200 and r.json()["prevoz"] == "nemoguc"
      and len(db_rows("opcije_soba", cid)) == 2 * P)

r = c.delete(f"/api/cenovnici/{cid}/opcije-soba/{soba12['id']}", headers=H)
check("opcije DELETE → 200 i ponovo idempotentno (briše SVih P redova te sobe)",
      r.status_code == 200 and len(db_rows("opcije_soba", cid)) == P
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

# ── 2) API — Popusti po sobi (soba × SVI termini) ───────────────────────────
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
check("popust u bazi — P redova po polju",
      len(db_rows("popust_soba", cid)) == P
      and all(r["tip_placanja"] == "delimicno" for r in db_rows("popust_soba", cid)))

r = c.put(f"/api/cenovnici/{cid}/popust-soba/{soba12['id']}", headers=H,
          json={"umanjenje_vrsta": "iznos", "umanjenje": "50", "tip_popusta": "first_minute"})
check("popust PUT menja zapise (full-replace, i dalje P redova)",
      r.status_code == 200 and r.json()["umanjenje_vrsta"] == "iznos"
      and float(r.json()["umanjenje"]) == 50.0 and r.json()["tip_placanja"] is None
      and len(db_rows("popust_soba", cid)) == P)

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

# ── 3) UI — dijalog iz liste (masovni mod) ──────────────────────────────────
d2 = postavi_cenovnik()
ui_cid = d2["id"]
ui_N = len(d2["sobe"])
ui_P = len(d2["periodi"])
ui_NZ = ui_N * ui_P

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

    # klik na Opcije dugme u redu liste otvara MASOVNI mod: detail (za sobe) + GET -sve
    with pg.expect_response(lambda r: r.request.method == "GET"
                            and r.url.endswith("/opcije-soba-sve"), timeout=10000):
        redovi.first.get_by_label(f"Opcije i popusti cenovnika #{ui_cid}").click()
    pg.get_by_role("heading", name="Opcije · Popusti").wait_for(timeout=10000)
    expect(pg.get_by_role("tab", name="Opcije")).to_be_visible(timeout=10000)
    pg.wait_for_timeout(300)
    check("dijalog se otvara sa tabovima", pg.get_by_role("tab", name="Opcije").is_visible()
          and pg.get_by_role("tab", name="Popusti").is_visible())
    dijalog = pg.locator("[role=dialog]")
    check("UI: dijalog iz liste bez selektora sobe + banner 'sve termine'",
          dijalog.get_by_text("Soba", exact=True).count() == 0
          and dijalog.get_by_text("sve termine").count() > 0)

    # tab Opcije: prekidači + selectovi + iznos → Snimi (masovni -sve PUT)
    pg.locator("#opc-blokirano").click()
    pg.locator("#opc-istaknuto").click()
    pg.locator("#opc-prevoz").click()
    pg.get_by_role("option", name="Obavezan").click()
    pg.locator("#opc-cena").click()
    pg.get_by_role("option", name="Po sobi").click()
    pg.locator("#opc-psp").fill("15")
    with pg.expect_response(lambda r: r.request.method == "PUT"
                            and r.url.endswith("/opcije-soba-sve")) as ri:
        pg.get_by_role("button", name="Snimi", exact=True).click()
    _odg = ri.value.json()
    check("UI: masovni PUT payload tačan + broj_zapisa = sobe × termini",
          _odg["status"] == "sacuvano" and _odg["broj_soba"] == ui_N
          and _odg["broj_zapisa"] == ui_NZ
          and json.loads(ri.value.request.post_data)["prevoz"] == "obavezan")
    pg.get_by_text(f"Opcije su sačuvane za sve sobe i sve termine ({ui_NZ})").wait_for(timeout=8000)
    red_db = db_rows("opcije_soba", ui_cid)
    check("UI: opcije eksplicitno za svaku sobu × svaki termin (bez period_id=0)",
          len(red_db) == ui_NZ and all(r["period_id"] != 0 for r in red_db)
          and all(r["blokirano"] is True and r["prevoz"] == "obavezan" for r in red_db))
    check("UI: dugme Obriši omogućeno posle Snimi",
          dijalog.get_by_role("button", name="Obriši opcije").is_enabled())

    # Obriši opcije (masovno)
    dijalog.get_by_role("button", name="Obriši opcije").click()
    pg.get_by_text("Opcije su obrisane za sve sobe i sve termine").wait_for(timeout=8000)
    check("UI: opcije obrisane kroz dijalog", db_rows("opcije_soba", ui_cid) == [])

    # tab Popusti: procenat + sva polja → Snimi (masovni -sve PUT)
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
                            and r.url.endswith("/popust-soba-sve")) as ri2:
        pg.get_by_role("button", name="Snimi", exact=True).click()
    pj = ri2.value.json()
    check("UI: masovni popust PUT payload tačan (procenat 12.5, last_minute, delimično, datumi, psp 5)",
          pj["status"] == "sacuvano" and pj["broj_soba"] == ui_N and pj["broj_zapisa"] == ui_NZ
          and json.loads(ri2.value.request.post_data)["umanjenje_vrsta"] == "procenat"
          and float(json.loads(ri2.value.request.post_data)["umanjenje"]) == 12.5
          and json.loads(ri2.value.request.post_data)["tip_popusta"] == "last_minute")
    pg.get_by_text(f"Popust je sačuvan za sve sobe i sve termine ({ui_NZ})").wait_for(timeout=8000)

    # validacija: procenat 150 → toast greške, bez PUT-a
    pg.locator("#pop-umanjenje").fill("150")
    pg.get_by_role("button", name="Snimi", exact=True).click()
    pg.get_by_text("Procenat može biti najviše 100").wait_for(timeout=8000)
    zapisi = c.get(f"/api/cenovnici/{ui_cid}/popust-soba-sve", headers=H).json()["zapisi"]
    check("UI: procenat 150 odbijen na klijentu (API vrednost nepromenjena)",
          len(zapisi) == ui_NZ and all(float(x["umanjenje"]) == 12.5 for x in zapisi))

    # Obriši popust (masovno)
    dijalog.get_by_role("button", name="Obriši popust").click()
    pg.get_by_text("Popust je obrisan za sve sobe i sve termine").wait_for(timeout=8000)
    check("UI: popust obrisan kroz dijalog", db_rows("popust_soba", ui_cid) == [])
    b.close()

check("cleanup UI cenovnik obrisan", c.delete(f"/api/cenovnici/{ui_cid}", headers=H).status_code == 200)

print(f"\n{sum(OK)}/{len(OK)} PASS")
sys.exit(0 if all(OK) else 1)
