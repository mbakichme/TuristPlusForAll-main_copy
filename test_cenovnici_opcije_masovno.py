import db_config

"""Cenovnici — masovne opcije/popusti: dugme Opcije · Popusti iznad matrice u edit editoru.

API: GET/PUT/DELETE /cenovnici/{id}/opcije-soba-sve i /popust-soba-sve — snimanje je EKSPLICITNO
po polju: za SVAKU sobu snimka (realne + virtuelne negativni id-jevi) × SVAKI termin upisuje se
po jedan zapis (bez zbirnih period_id=0 redova). UI: dugme pored „Kopiraj cene“ checkboxa,
disabled dok je editor zaključan; dijalog bez selektora sobe, prefill = vrednost koju dele SVE
zapisi (mešovito → neutralno); Snimi/Obriši idu na -sve endpointe.
"""
import json
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from playwright.sync_api import sync_playwright, expect
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
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
P = len(d["periodi"])
NZ = N * P  # svaka soba × svaki termin = po jedan eksplicitan zapis
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
check("opcije-sve PUT → sacuvano, broj_soba = N, broj_zapisa = N × P", r.status_code == 200
      and r.json()["status"] == "sacuvano" and r.json()["broj_soba"] == N
      and r.json()["broj_zapisa"] == NZ)
redovi = db_rows("opcije_soba", cid)
check("opcije-sve: EKSPLICITNO po polju — N × P redova (uklj. virtuelnu), bez period_id=0",
      len(redovi) == NZ and all(r["period_id"] != 0 for r in redovi)
      and {(r["soba_id"], r["period_id"]) for r in redovi}
      == {(s["id"], p["id"]) for s in d["sobe"] for p in d["periodi"]}
      and all(r["blokirano"] is True and r["blokirano_sajt"] is True and r["prevoz"] == "obavezan"
              for r in redovi))

r = c.get(f"/api/cenovnici/{cid}/opcije-soba-sve", headers=H)
z = r.json()["zapisi"]
check("opcije-sve GET → postoji True + N × P zapisa u redosledu snimka (soba, pa period_id)",
      r.json()["postoji"] is True and len(z) == NZ
      and [x["soba_id"] for x in z] == [s["id"] for s in d["sobe"] for _ in d["periodi"]]
      and [x["period_id"] for x in z[:P]] == sorted(p["id"] for p in d["periodi"]))

r = c.put(f"/api/cenovnici/{cid}/opcije-soba-sve", headers=H,
          json={"blokirano": False, "prevoz": "nemoguc", "tip_cene": "po_osobi"})
redovi = db_rows("opcije_soba", cid)
check("opcije-sve ponovo → full-replace bez duplikata (i dalje N × P)",
      r.status_code == 200 and len(redovi) == NZ
      and all(r["blokirano"] is False and r["istaknuto"] is False and r["prevoz"] == "nemoguc"
              and r["tip_cene"] == "po_osobi" for r in redovi))

c.put(f"/api/cenovnici/{cid}/opcije-soba/{soba12['id']}", headers=H, json={"istaknuto": True})
redovi = db_rows("opcije_soba", cid)
check("masovno + pojedinačno koegzistiraju (soba12 × svi termini prepravljeni, ukupno N × P)",
      len(redovi) == NZ and sum(1 for r in redovi if r["istaknuto"] is True) == P
      and all(r["soba_id"] == soba12["id"] for r in redovi if r["istaknuto"] is True))

r = c.delete(f"/api/cenovnici/{cid}/opcije-soba-sve", headers=H)
check("opcije-sve DELETE → broj = N × P, baza prazna, ponovo idempotentno",
      r.status_code == 200 and r.json()["broj"] == NZ and db_rows("opcije_soba", cid) == []
      and c.delete(f"/api/cenovnici/{cid}/opcije-soba-sve", headers=H).json()["broj"] == 0)

check("opcije-sve: nepoznat cenovnik → 404 (GET/PUT/DELETE)",
      c.get("/api/cenovnici/99999902/opcije-soba-sve", headers=H).status_code == 404
      and c.put("/api/cenovnici/99999902/opcije-soba-sve", headers=H, json={}).status_code == 404
      and c.delete("/api/cenovnici/99999902/opcije-soba-sve", headers=H).status_code == 404)

# ── 2) API — masovni popusti ────────────────────────────────────────────────
r = c.get(f"/api/cenovnici/{cid}/popust-soba-sve", headers=H)
check("popust-sve GET prazno → postoji False", r.status_code == 200 and r.json()["postoji"] is False)

def popust(umanjenje, tip="last_minute", placanje="delimicno", vrsta="procenat"):
    return {"umanjenje_vrsta": vrsta, "umanjenje": umanjenje, "tip_popusta": tip,
            "tip_placanja": placanje, "vazi_od": "2026-06-01", "vazi_do": "2026-06-30",
            "tip_aranzmana": None, "tip_cene": None, "popust_sopstveni_prevoz": None}


r = c.put(f"/api/cenovnici/{cid}/popust-soba-sve", headers=H, json={"popusti": [popust(10)]})
check("popust-sve PUT (1 popust) → sacuvano za N soba (broj_zapisa = N × P × 1)",
      r.status_code == 200 and r.json()["broj_soba"] == N and r.json()["broj_zapisa"] == NZ)
redovi = db_rows("popust_soba", cid)
check("popust-sve: N × P redova po polju (uklj. virtuelnu), redni 1, iste vrednosti",
      len(redovi) == NZ and all(r["period_id"] != 0 for r in redovi)
      and any(r["soba_id"] == v12["id"] for r in redovi)
      and all(r["redni"] == 1 and r["tip_popusta"] == "last_minute" and r["tip_placanja"] == "delimicno"
              for r in redovi))

r = c.put(f"/api/cenovnici/{cid}/popust-soba-sve", headers=H,
          json={"popusti": [popust(10, "last_minute"), popust(20, "first_minute"),
                            popust(5, "specijalna_ponuda", "u_celosti", "iznos")]})
redovi = db_rows("popust_soba", cid)
check("popust-sve PUT (3 popusta) → broj_zapisa = N × P × 3, u bazi redni 1..3 po polju",
      r.status_code == 200 and r.json()["broj_zapisa"] == NZ * 3 and len(redovi) == NZ * 3
      and all({x["redni"] for x in redovi if x["soba_id"] == s["id"] and x["period_id"] == p["id"]}
              == {1, 2, 3} for s in d["sobe"] for p in d["periodi"])
      and all(x["tip_popusta"] == "first_minute" for x in redovi if x["redni"] == 2))

r = c.get(f"/api/cenovnici/{cid}/popust-soba-sve", headers=H)
check("popust-sve GET → zapisi N × P × 3 sa redni, datumi ISO",
      r.json()["postoji"] is True and len(r.json()["zapisi"]) == NZ * 3
      and {x["redni"] for x in r.json()["zapisi"]} == {1, 2, 3}
      and all(x["vazi_od"] == "2026-06-01" and x["vazi_do"] == "2026-06-30" for x in r.json()["zapisi"]))

r = c.put(f"/api/cenovnici/{cid}/popust-soba-sve", headers=H,
          json={"popusti": [popust(1), popust(2), popust(3), popust(4)]})
check("popust-sve PUT sa 4 popusta → 422, baza nepromenjena (N × P × 3)",
      r.status_code == 422 and len(db_rows("popust_soba", cid)) == NZ * 3)

r = c.put(f"/api/cenovnici/{cid}/popust-soba-sve", headers=H, json={"popusti": []})
check("popust-sve PUT sa praznom listom → briše opseg (broj_zapisa 0), postoji False",
      r.status_code == 200 and r.json()["broj_zapisa"] == 0 and db_rows("popust_soba", cid) == []
      and c.get(f"/api/cenovnici/{cid}/popust-soba-sve", headers=H).json()["postoji"] is False)

c.put(f"/api/cenovnici/{cid}/popust-soba-sve", headers=H, json={"popusti": [popust(10), popust(20)]})
r = c.delete(f"/api/cenovnici/{cid}/popust-soba-sve", headers=H)
check("popust-sve DELETE → broj = N × P × 2, baza prazna, ponovo idempotentno",
      r.status_code == 200 and r.json()["broj"] == NZ * 2 and db_rows("popust_soba", cid) == []
      and c.delete(f"/api/cenovnici/{cid}/popust-soba-sve", headers=H).json()["broj"] == 0)

# cascade sa cenovnikom i za masovne zapise
c.put(f"/api/cenovnici/{cid}/opcije-soba-sve", headers=H, json={"blokirano": True})
c.put(f"/api/cenovnici/{cid}/popust-soba-sve", headers=H,
      json={"popusti": [popust(10, vrsta="iznos")]})
c.delete(f"/api/cenovnici/{cid}", headers=H)
check("cascade: masovni zapisi obrisani sa cenovnikom",
      db_rows("opcije_soba", cid) == [] and db_rows("popust_soba", cid) == [])

# ── 3) UI — dugme iznad matrice u edit editoru ──────────────────────────────
d2 = postavi_cenovnik()
ui_cid = d2["id"]
ui_N = len(d2["sobe"])
ui_P = len(d2["periodi"])
ui_NZ = ui_N * ui_P
soba12_2 = next(s for s in d2["sobe"] if s["broj_sobe"] == "12" and not s.get("virtuelna"))
v12_2 = next(s for s in d2["sobe"] if s.get("virtuelna") and s["izvor_soba_id"] == soba12_2["id"])

# pre-seed: dve sobe dele blokirano+prevoz, mešovito istaknuto
c.put(f"/api/cenovnici/{ui_cid}/opcije-soba/{soba12_2['id']}", headers=H,
      json={"blokirano": True, "prevoz": "obavezan"})
c.put(f"/api/cenovnici/{ui_cid}/opcije-soba/{v12_2['id']}", headers=H,
      json={"blokirano": True, "prevoz": "obavezan", "istaknuto": True})

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context()
    ctx.add_init_script(f"localStorage.setItem('ta_token', {json.dumps(tok)});")  # token pre prvog /auth/me
    pg = ctx.new_page()
    BASE = "http://localhost:3058"
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
    check("UI: dugme iznad matrice AKTIVNO i dok je editor zaključan", btn.is_enabled())

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
          and ri.value.json()["status"] == "sacuvano"
          and ri.value.json()["broj_zapisa"] == ui_NZ)
    pg.get_by_text(f"Opcije su sačuvane za sve sobe i sve termine ({ui_NZ})").wait_for(timeout=8000)
    redovi_db = db_rows("opcije_soba", ui_cid)
    check("UI: snimljeno EKSPLICITNO za svaku sobu × svaki termin (uklj. virtuelne)",
          len(redovi_db) == ui_NZ and all(r["blokirano"] is True for r in redovi_db)
          and not any(r["istaknuto"] is True for r in redovi_db)
          and any(r["soba_id"] == v12_2["id"] for r in redovi_db)
          and all(r["period_id"] != 0 for r in redovi_db))

    dijalog.get_by_role("button", name="Obriši opcije").click()
    pg.get_by_text("Opcije su obrisane za sve sobe i sve termine").wait_for(timeout=8000)
    check("UI: masovno brisanje opcija", db_rows("opcije_soba", ui_cid) == [])

    # Popusti tab: masovno snimanje popusta (prazan opseg → prvo "Dodaj popust")
    pg.get_by_role("tab", name="Popusti").click()
    expect(pg.get_by_text("Nema popusta za ovaj opseg")).to_be_visible(timeout=5000)
    pg.get_by_role("button", name="Dodaj popust", exact=True).click()
    pg.locator("#pop-umanjenje").fill("10")
    pg.locator("#pop-tip").click()
    pg.get_by_role("option", name="Last minute", exact=True).click()
    with pg.expect_response(lambda r: r.request.method == "PUT"
                            and r.url.endswith("/popust-soba-sve")) as ri2:
        pg.get_by_role("button", name="Snimi", exact=True).click()
    telo2 = json.loads(ri2.value.request.post_data)["popusti"]
    check("UI: masovni popust PUT (1 popust: iznos 10, last_minute) → sacuvano",
          len(telo2) == 1 and telo2[0]["umanjenje_vrsta"] == "iznos"
          and float(telo2[0]["umanjenje"]) == 10.0
          and telo2[0]["tip_popusta"] == "last_minute" and ri2.value.json()["broj_soba"] == ui_N
          and ri2.value.json()["broj_zapisa"] == ui_NZ)
    pg.get_by_text(f"Popusti sačuvani (1) za sve sobe i sve termine ({ui_NZ} zapisa)").wait_for(timeout=8000)
    redovi_db = db_rows("popust_soba", ui_cid)
    check("UI: popust eksplicitno za svaku sobu × svaki termin (uklj. virtuelne), redni 1",
          len(redovi_db) == ui_NZ and any(r["soba_id"] == v12_2["id"] for r in redovi_db)
          and all(r["tip_popusta"] == "last_minute" and r["redni"] == 1 for r in redovi_db))
    b.close()


check("cleanup UI cenovnik obrisan", c.delete(f"/api/cenovnici/{ui_cid}", headers=H).status_code == 200)

print(f"\n{sum(OK)}/{len(OK)} PASS")
sys.exit(0 if all(OK) else 1)
