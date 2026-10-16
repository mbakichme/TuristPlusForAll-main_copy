"""Cenovnici — masovne opcije/popusti: dugme Opcije · Popusti iznad matrice u edit editoru.

API: GET/PUT/DELETE /cenovnici/{id}/opcije-soba-sve i /popust-soba-sve — primena na SVE sobe
snimka (realne + virtuelne negativni id-jevi). UI: dugme pored „Kopiraj cene“ checkboxa,
disabled dok je editor zaključan; dijalog bez selektora sobe, prefill = vrednost koju dele
SVE sobe (mešovito → neutralno); Snimi/Obriši idu na -sve endpointe.
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
        "mesto_id": 1, "grupa_id": 6, "smestaj_id": 10,  # ELENI 2 — realne + virtuelne sobe
        "datumod": "2026-05-25", "datumdo": "2026-10-02", "cene": []})
    assert r.status_code == 201, r.text
    return r.json()


# ── 1) API — masovne opcije ─────────────────────────────────────────────────
d = postavi_cenovnik()
cid = d["id"]
N = len(d["sobe"])
soba12 = next(s for s in d["sobe"] if s["broj_sobe"] == "12" and not s.get("virtuelna"))
v12 = next(s for s in d["sobe"] if s.get("virtuelna") and s["izvor_soba_id"] == soba12["id"])

r = c.get(f"/api/cenovnici/{cid}/opcije-soba-sve", headers=H)
check("opcije-sve GET prazno → sobe lista + postoji False + zapisi []",
      r.status_code == 200 and r.json()["postoji"] is False and r.json()["zapisi"] == []
      and sorted(r.json()["sobe"]) == sorted(s["id"] for s in d["sobe"]))

body = {"blokirano": True, "istaknuto": False, "blokirano_subagenci": False, "blokirano_sajt": True,
        "prevoz": "obavezan", "tip_aranzmana": "sa_prevozom", "tip_cene": "po_sobi",
        "popust_sopstveni_prevoz": "15.5"}
r = c.put(f"/api/cenovnici/{cid}/opcije-soba-sve", headers=H, json=body)
check("opcije-sve PUT → sacuvano, broj_soba = N", r.status_code == 200
      and r.json()["status"] == "sacuvano" and r.json()["broj_soba"] == N)
redovi = db_rows("opcije_soba", cid)
check("opcije-sve: red za SVAKU sobu uključujući virtuelnu (negativan id)",
      len(redovi) == N and any(r["soba_id"] == v12["id"] for r in redovi)
      and all(r["blokirano"] is True and r["blokirano_sajt"] is True for r in redovi)
      and all(r["prevoz"] == "obavezan" for r in redovi))

r = c.get(f"/api/cenovnici/{cid}/opcije-soba-sve", headers=H)
z = r.json()["zapisi"]
check("opcije-sve GET → postoji True + zapisi u redosledu snimka",
      r.json()["postoji"] is True and len(z) == N
      and [x["soba_id"] for x in z] == [s["id"] for s in d["sobe"]])

r = c.put(f"/api/cenovnici/{cid}/opcije-soba-sve", headers=H,
          json={"blokirano": False, "prevoz": "nemoguc", "tip_cene": "po_osobi"})
redovi = db_rows("opcije_soba", cid)
check("opcije-sve ponovo → full-replace bez duplikata",
      r.status_code == 200 and len(redovi) == N
      and all(r["blokirano"] is False and r["istaknuto"] is False and r["prevoz"] == "nemoguc"
              and r["tip_cene"] == "po_osobi" for r in redovi))

c.put(f"/api/cenovnici/{cid}/opcije-soba/{soba12['id']}", headers=H, json={"istaknuto": True})
redovi = db_rows("opcije_soba", cid)
check("masovno + pojedinačno koegzistiraju (jedna soba prepravljena)",
      len(redovi) == N and sum(1 for r in redovi if r["istaknuto"] is True) == 1)

r = c.delete(f"/api/cenovnici/{cid}/opcije-soba-sve", headers=H)
check("opcije-sve DELETE → broj = N, baza prazna, ponovo idempotentno",
      r.status_code == 200 and r.json()["broj"] == N and db_rows("opcije_soba", cid) == []
      and c.delete(f"/api/cenovnici/{cid}/opcije-soba-sve", headers=H).json()["broj"] == 0)

check("opcije-sve: nepoznat cenovnik → 404 (GET/PUT/DELETE)",
      c.get("/api/cenovnici/99999902/opcije-soba-sve", headers=H).status_code == 404
      and c.put("/api/cenovnici/99999902/opcije-soba-sve", headers=H, json={}).status_code == 404
      and c.delete("/api/cenovnici/99999902/opcije-soba-sve", headers=H).status_code == 404)

# ── 2) API — masovni popusti ────────────────────────────────────────────────
r = c.get(f"/api/cenovnici/{cid}/popust-soba-sve", headers=H)
check("popust-sve GET prazno → postoji False", r.status_code == 200 and r.json()["postoji"] is False)

r = c.put(f"/api/cenovnici/{cid}/popust-soba-sve", headers=H,
          json={"umanjenje_vrsta": "procenat", "umanjenje": "10", "tip_popusta": "last_minute",
                "tip_placanja": "delimicno", "vazi_od": "2026-06-01", "vazi_do": "2026-06-30"})
check("popust-sve PUT → sacuvano za N soba", r.status_code == 200 and r.json()["broj_soba"] == N)
redovi = db_rows("popust_soba", cid)
check("popust-sve: red za svaku sobu (uklj. virtuelnu), iste vrednosti",
      len(redovi) == N and any(r["soba_id"] == v12["id"] for r in redovi)
      and all(r["tip_popusta"] == "last_minute" and r["tip_placanja"] == "delimicno" for r in redovi))

r = c.get(f"/api/cenovnici/{cid}/popust-soba-sve", headers=H)
check("popust-sve GET → zapisi N, datumi ISO",
      len(r.json()["zapisi"]) == N
      and all(x["vazi_od"] == "2026-06-01" and x["vazi_do"] == "2026-06-30" for x in r.json()["zapisi"]))

r = c.delete(f"/api/cenovnici/{cid}/popust-soba-sve", headers=H)
check("popust-sve DELETE → broj = N, baza prazna",
      r.status_code == 200 and r.json()["broj"] == N and db_rows("popust_soba", cid) == [])

# cascade sa cenovnikom i za masovne zapise
c.put(f"/api/cenovnici/{cid}/opcije-soba-sve", headers=H, json={"blokirano": True})
c.put(f"/api/cenovnici/{cid}/popust-soba-sve", headers=H,
      json={"umanjenje_vrsta": "iznos", "umanjenje": "10", "tip_popusta": "last_minute"})
c.delete(f"/api/cenovnici/{cid}", headers=H)
check("cascade: masovni zapisi obrisani sa cenovnikom",
      db_rows("opcije_soba", cid) == [] and db_rows("popust_soba", cid) == [])

# ── 3) UI — dugme iznad matrice u edit editoru ──────────────────────────────
d2 = postavi_cenovnik()
ui_cid = d2["id"]
ui_N = len(d2["sobe"])
soba12_2 = next(s for s in d2["sobe"] if s["broj_sobe"] == "12" and not s.get("virtuelna"))
v12_2 = next(s for s in d2["sobe"] if s.get("virtuelna") and s["izvor_soba_id"] == soba12_2["id"])

# pre-seed: dve sobe dele blokirano+prevoz, mešovito istaknuto
c.put(f"/api/cenovnici/{ui_cid}/opcije-soba/{soba12_2['id']}", headers=H,
      json={"blokirano": True, "prevoz": "obavezan"})
c.put(f"/api/cenovnici/{ui_cid}/opcije-soba/{v12_2['id']}", headers=H,
      json={"blokirano": True, "prevoz": "obavezan", "istaknuto": True})

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
    redovi.first.get_by_role("button", name=f"Izmeni cenovnik {d2['naziv']}").click()

    pg.wait_for_selector("#edit-kopiraj", timeout=15000)
    btn = pg.get_by_role("button", name="Opcije · Popusti", exact=True)
    expect(btn).to_be_attached(timeout=10000)
    check("UI: dugme iznad matrice postoji i DISABLED dok je editor zaključan", btn.is_disabled())

    pg.get_by_role("button", name="Izmeni cenovnik", exact=True).click()
    expect(btn).to_be_enabled(timeout=5000)
    btn.click()

    dijalog = pg.locator("[role=dialog]")
    expect(pg.get_by_role("tab", name="Opcije")).to_be_visible(timeout=10000)
    check("UI: masovni dijalog bez selektora sobe + banner 'sve termine'",
          dijalog.get_by_text("Soba", exact=True).count() == 0
          and dijalog.get_by_text("sve termine").count() > 0)

    # prefill: zajedničke vrednosti prikazane, mešovito → neutralno
    check("UI: prefill — blokirano čekirano (svi), istaknuto neutralno (mešovito), prevoz Obavezan",
          pg.locator("#opc-blokirano").get_attribute("aria-checked") == "true"
          and pg.locator("#opc-istaknuto").get_attribute("aria-checked") == "false"
          and "Obavezan" in pg.locator("#opc-prevoz").inner_text())

    with pg.expect_response(lambda r: r.request.method == "PUT"
                            and r.url.endswith("/opcije-soba-sve")) as ri:
        pg.get_by_role("button", name="Snimi", exact=True).click()
    telo = json.loads(ri.value.request.post_data)
    check("UI: masovni PUT payload (blokirano true, istaknuto false, prevoz obavezan) → sacuvano",
          telo["blokirano"] is True and telo["istaknuto"] is False and telo["prevoz"] == "obavezan"
          and ri.value.json()["status"] == "sacuvano")
    pg.get_by_text("Opcije su sačuvane za sve sobe").wait_for(timeout=8000)
    redovi_db = db_rows("opcije_soba", ui_cid)
    check("UI: snimljeno na SVE sobe (uklj. virtuelne), prepravljeno i mešovito istaknuto",
          len(redovi_db) == ui_N and all(r["blokirano"] is True for r in redovi_db)
          and not any(r["istaknuto"] is True for r in redovi_db)
          and any(r["soba_id"] == v12_2["id"] for r in redovi_db))

    dijalog.get_by_role("button", name="Obriši opcije").click()
    pg.get_by_text("Opcije su obrisane za sve sobe").wait_for(timeout=8000)
    check("UI: masovno brisanje opcija", db_rows("opcije_soba", ui_cid) == [])

    # Popusti tab: masovno snimanje popusta
    pg.get_by_role("tab", name="Popusti").click()
    pg.locator("#pop-umanjenje").fill("10")
    pg.locator("#pop-tip").click()
    pg.get_by_role("option", name="Last minute", exact=True).click()
    with pg.expect_response(lambda r: r.request.method == "PUT"
                            and r.url.endswith("/popust-soba-sve")) as ri2:
        pg.get_by_role("button", name="Snimi", exact=True).click()
    telo2 = json.loads(ri2.value.request.post_data)
    check("UI: masovni popust PUT (iznos 10, last_minute) → sacuvano",
          telo2["umanjenje_vrsta"] == "iznos" and float(telo2["umanjenje"]) == 10.0
          and telo2["tip_popusta"] == "last_minute" and ri2.value.json()["broj_soba"] == ui_N)
    pg.get_by_text("Popust je sačuvan za sve sobe").wait_for(timeout=8000)
    redovi_db = db_rows("popust_soba", ui_cid)
    check("UI: popust na sve sobe (uklj. virtuelne)",
          len(redovi_db) == ui_N and any(r["soba_id"] == v12_2["id"] for r in redovi_db)
          and all(r["tip_popusta"] == "last_minute" for r in redovi_db))
    b.close()

check("cleanup UI cenovnik obrisan", c.delete(f"/api/cenovnici/{ui_cid}", headers=H).status_code == 200)

print(f"\n{sum(OK)}/{len(OK)} PASS")
sys.exit(0 if all(OK) else 1)
