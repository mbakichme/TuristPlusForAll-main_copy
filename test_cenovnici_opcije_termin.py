"""Cenovnici — opcije/popusti po TERMINU: O·P dugme u koloni matrice (sve sobe, jedan termin).

period_id u opcije_soba/popust_soba: 0 = „svi termini" (dijalog iz liste i masovno iznad
matrice), konkretan id perioda iz snimka = override za taj termin (O·P u koloni).
Endpointi: GET/PUT/DELETE /cenovnici/{id}/opcije-soba-termin/{period_id} i /popust-soba-termin/...
Scope-clearing: single PUT (soba) briše override-e te sobe; masovno PUT (-sve) briše SVE override-e.
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


def db_rows(table, cid, pid=None):
    sql = f"SELECT * FROM {table} WHERE cenovnik_id = :c"
    args = {"c": cid}
    if pid is not None:
        sql += " AND period_id = :p"
        args["p"] = pid
    with engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(text(sql), args)]


def postavi_cenovnik():
    r = c.post("/api/cenovnici", headers=H, json={
        "mesto_id": 1, "grupa_id": 6, "smestaj_id": 10,  # ELENI 2 — realne + virtuelne sobe
        "datumod": "2026-05-25", "datumdo": "2026-10-02", "cene": []})
    assert r.status_code == 201, r.text
    return r.json()


# ── 1) API — opcije po terminu ──────────────────────────────────────────────
d = postavi_cenovnik()
cid = d["id"]
N = len(d["sobe"])
pid = d["periodi"][0]["id"]
soba12 = next(s for s in d["sobe"] if s["broj_sobe"] == "12" and not s.get("virtuelna"))

r = c.get(f"/api/cenovnici/{cid}/opcije-soba-termin/{pid}", headers=H)
check("termin GET prazno → postoji False + sobe iz snimka",
      r.status_code == 200 and r.json()["postoji"] is False and r.json()["zapisi"] == []
      and sorted(r.json()["sobe"]) == sorted(s["id"] for s in d["sobe"]))

c.put(f"/api/cenovnici/{cid}/opcije-soba-sve", headers=H,
      json={"blokirano": True, "prevoz": "obavezan"})  # globalno (svi termini)

r = c.put(f"/api/cenovnici/{cid}/opcije-soba-termin/{pid}", headers=H,
          json={"istaknuto": True, "prevoz": "nemoguc", "tip_cene": "po_sobi"})
check("termin PUT → sacuvano broj_soba = N",
      r.status_code == 200 and r.json()["status"] == "sacuvano"
      and r.json()["broj_soba"] == N and r.json()["period_id"] == pid)

check("termin override u bazi (svi redovi period_id=pid, istaknuto)",
      len(db_rows("opcije_soba", cid, pid)) == N
      and all(r["istaknuto"] is True and r["prevoz"] == "nemoguc" for r in db_rows("opcije_soba", cid, pid)))
check("globalni zapisi (period_id=0) NETAKNUTI",
      len(db_rows("opcije_soba", cid, 0)) == N
      and all(r["blokirano"] is True and r["istaknuto"] is False for r in db_rows("opcije_soba", cid, 0)))

r = c.get(f"/api/cenovnici/{cid}/opcije-soba/{soba12['id']}", headers=H)
check("single GET i dalje vraća GLOBALNE vrednosti (bez override-a)",
      r.json()["postoji"] is True and r.json()["blokirano"] is True and r.json()["istaknuto"] is False)

r = c.get(f"/api/cenovnici/{cid}/opcije-soba-termin/{pid}", headers=H)
check("termin GET → zapisi N u redosledu snimka",
      r.json()["postoji"] is True and len(r.json()["zapisi"]) == N
      and [z["soba_id"] for z in r.json()["zapisi"]] == [s["id"] for s in d["sobe"]])

# single PUT (dijalog po sobi) briše override-e TE SOBE
c.put(f"/api/cenovnici/{cid}/opcije-soba/{soba12['id']}", headers=H, json={"blokirano": True})
check("single PUT briše period override-e te sobe (ostaje samo period_id=0)",
      db_rows("opcije_soba", cid, pid) == [r for r in db_rows("opcije_soba", cid, pid)
                                           if r["soba_id"] != soba12["id"]]
      and any(r["soba_id"] == soba12["id"] for r in db_rows("opcije_soba", cid, 0)))

# masovno PUT (-sve) briše SVE override-e termina
c.put(f"/api/cenovnici/{cid}/opcije-soba-sve", headers=H, json={"blokirano": False})
check("masovno PUT briše SVE override-e (ostaje N redova period_id=0)",
      len(db_rows("opcije_soba", cid)) == N and db_rows("opcije_soba", cid, pid) == [])

c.put(f"/api/cenovnici/{cid}/opcije-soba-termin/{pid}", headers=H,
      json={"istaknuto": True, "prevoz": "nemoguc"})
r = c.delete(f"/api/cenovnici/{cid}/opcije-soba-termin/{pid}", headers=H)
check("termin DELETE → broj = N, samo pid redovi obrisani, globalni ostaju",
      r.status_code == 200 and r.json()["broj"] == N and db_rows("opcije_soba", cid, pid) == []
      and len(db_rows("opcije_soba", cid, 0)) == N
      and c.delete(f"/api/cenovnici/{cid}/opcije-soba-termin/{pid}", headers=H).json()["broj"] == 0)

check("termin: nepoznat cenovnik → 404 (GET/PUT/DELETE)",
      c.get(f"/api/cenovnici/99999903/opcije-soba-termin/{pid}", headers=H).status_code == 404
      and c.put(f"/api/cenovnici/99999903/opcije-soba-termin/{pid}", headers=H,
                json={}).status_code == 404
      and c.delete(f"/api/cenovnici/99999903/opcije-soba-termin/{pid}", headers=H).status_code == 404)
check("termin: period van snimka → 400 (GET/PUT/DELETE)",
      c.get(f"/api/cenovnici/{cid}/opcije-soba-termin/999999", headers=H).status_code == 400
      and c.put(f"/api/cenovnici/{cid}/opcije-soba-termin/999999", headers=H,
                json={}).status_code == 400
      and c.delete(f"/api/cenovnici/{cid}/opcije-soba-termin/999999", headers=H).status_code == 400)

# ── 2) API — popusti po terminu ─────────────────────────────────────────────
r = c.put(f"/api/cenovnici/{cid}/popust-soba-termin/{pid}", headers=H,
          json={"umanjenje_vrsta": "procenat", "umanjenje": "10", "tip_popusta": "last_minute"})
check("popust-termin PUT → N redova", r.status_code == 200 and r.json()["broj_soba"] == N)
check("popust-termin u bazi", len(db_rows("popust_soba", cid, pid)) == N
      and all(r["tip_popusta"] == "last_minute" for r in db_rows("popust_soba", cid, pid)))
r = c.get(f"/api/cenovnici/{cid}/popust-soba-termin/{pid}", headers=H)
check("popust-termin GET → zapisi N", len(r.json()["zapisi"]) == N)
r = c.delete(f"/api/cenovnici/{cid}/popust-soba-termin/{pid}", headers=H)
check("popust-termin DELETE → broj = N", r.status_code == 200 and r.json()["broj"] == N
      and db_rows("popust_soba", cid, pid) == [])

# cascade sa cenovnikom
c.put(f"/api/cenovnici/{cid}/opcije-soba-termin/{pid}", headers=H, json={"blokirano": True})
c.put(f"/api/cenovnici/{cid}/popust-soba-termin/{pid}", headers=H,
      json={"umanjenje_vrsta": "iznos", "umanjenje": "10", "tip_popusta": "last_minute"})
c.delete(f"/api/cenovnici/{cid}", headers=H)
check("cascade: termin + globalni zapisi obrisani sa cenovnikom",
      db_rows("opcije_soba", cid) == [] and db_rows("popust_soba", cid) == [])

# ── 3) UI — O·P dugme u koloni matrice ──────────────────────────────────────
d2 = postavi_cenovnik()
ui_cid = d2["id"]
ui_N = len(d2["sobe"])
ui_pid = d2["periodi"][0]["id"]

c.put(f"/api/cenovnici/{ui_cid}/opcije-soba-sve", headers=H,
      json={"blokirano": True, "prevoz": "obavezan"})  # globalno → prefill fallback

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
    pg.get_by_role("button", name="Izmeni cenovnik", exact=True).click()  # otključaj

    op_dugmad = pg.get_by_title("Opcije · Popusti za termin")
    expect(op_dugmad.first).to_be_visible(timeout=10000)
    check("UI: O·P dugme u headeru svake kolone", op_dugmad.count() == len(d2["periodi"]))
    op_dugmad.first.click()  # prvi termin iz snimka

    dijalog = pg.locator("[role=dialog]")
    expect(pg.get_by_role("tab", name="Opcije")).to_be_visible(timeout=10000)
    check("UI: dijalog po terminu — banner sa 'samo za termin', bez selektora sobe",
          dijalog.get_by_text("Soba", exact=True).count() == 0
          and dijalog.get_by_text("samo za").count() > 0)
    check("UI: prefill fallback sa globalnih zapisa (blokirano, prevoz Obavezan)",
          pg.locator("#opc-blokirano").get_attribute("aria-checked") == "true"
          and "Obavezan" in pg.locator("#opc-prevoz").inner_text())

    pg.locator("#opc-istaknuto").click()
    with pg.expect_response(lambda r: r.request.method == "PUT"
                            and r.url.endswith(f"/opcije-soba-termin/{ui_pid}")) as ri:
        pg.get_by_role("button", name="Snimi", exact=True).click()
    telo = json.loads(ri.value.request.post_data)
    check("UI: termin PUT payload (blokirano true, istaknuto true) → sacuvano",
          telo["blokirano"] is True and telo["istaknuto"] is True
          and ri.value.json()["status"] == "sacuvano")
    pg.get_by_text("Opcije su sačuvane za sve sobe i termin").wait_for(timeout=8000)
    check("UI: override na SVE sobe za taj termin, globalni netaknuti",
          len(db_rows("opcije_soba", ui_cid, ui_pid)) == ui_N
          and all(r["istaknuto"] is True and r["prevoz"] == "obavezan"
                  for r in db_rows("opcije_soba", ui_cid, ui_pid))
          and all(r["istaknuto"] is False for r in db_rows("opcije_soba", ui_cid, 0)))

    dijalog.get_by_role("button", name="Obriši opcije").click()
    pg.get_by_text("Opcije su obrisane za sve sobe i termin").wait_for(timeout=8000)
    check("UI: brisanje override-a termina", db_rows("opcije_soba", ui_cid, ui_pid) == [])

    pg.get_by_role("tab", name="Popusti").click()
    pg.locator("#pop-umanjenje").fill("10")
    pg.locator("#pop-tip").click()
    pg.get_by_role("option", name="Last minute", exact=True).click()
    with pg.expect_response(lambda r: r.request.method == "PUT"
                            and r.url.endswith(f"/popust-soba-termin/{ui_pid}")) as ri2:
        pg.get_by_role("button", name="Snimi", exact=True).click()
    telo2 = json.loads(ri2.value.request.post_data)
    check("UI: popust-termin PUT (iznos 10, last_minute)",
          telo2["umanjenje_vrsta"] == "iznos" and float(telo2["umanjenje"]) == 10.0
          and telo2["tip_popusta"] == "last_minute")
    pg.get_by_text("Popust je sačuvan za sve sobe i termin").wait_for(timeout=8000)
    check("UI: popust na sve sobe za termin",
          len(db_rows("popust_soba", ui_cid, ui_pid)) == ui_N
          and all(r["tip_popusta"] == "last_minute" for r in db_rows("popust_soba", ui_cid, ui_pid)))
    b.close()

check("cleanup UI cenovnik obrisan", c.delete(f"/api/cenovnici/{ui_cid}", headers=H).status_code == 200)

print(f"\n{sum(OK)}/{len(OK)} PASS")
sys.exit(0 if all(OK) else 1)
