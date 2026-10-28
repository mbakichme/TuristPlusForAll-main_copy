import db_config

"""Cenovnici — opcije/popusti po TERMINU: O·P dugme u koloni matrice (sve sobe, jedan termin).

Za SVAKU sobu × taj termin upisuje se po jedan eksplicitan zapis (bez zbirnih period_id=0
redova — masovno snimanje iznad matrice takođe materijalizuje svako polje ponaosob).
Endpointi: GET/PUT/DELETE /cenovnici/{id}/opcije-soba-termin/{period_id} i /popust-soba-termin/...
Scope-clearing: termin PUT briše ceo taj period; masovno PUT (-sve) briše SVE redove cenovnika;
single PUT (soba) briše sve redove te sobe pa upisuje soba × SVI termini.
"""
import json
import re
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


def dmy(iso):
    return f"{iso[8:10]}.{iso[5:7]}.{iso[:4]}"


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
      json={"blokirano": True, "prevoz": "obavezan"})  # masovno — materijalizuje SVAKO polje (N × P)
P = len(d["periodi"])
pid2 = d["periodi"][1]["id"]

r = c.put(f"/api/cenovnici/{cid}/opcije-soba-termin/{pid}", headers=H,
          json={"istaknuto": True, "prevoz": "nemoguc", "tip_cene": "po_sobi"})
check("termin PUT → sacuvano broj_soba = N",
      r.status_code == 200 and r.json()["status"] == "sacuvano"
      and r.json()["broj_soba"] == N and r.json()["period_id"] == pid)

check("termin override u bazi (N redova period_id=pid, istaknuto)",
      len(db_rows("opcije_soba", cid, pid)) == N
      and all(r["istaknuto"] is True and r["prevoz"] == "nemoguc" for r in db_rows("opcije_soba", cid, pid)))
check("ostali termini zadržavaju masovne vrednosti (N redova po periodu, bez pid=0 redova)",
      len(db_rows("opcije_soba", cid, pid2)) == N
      and all(r["blokirano"] is True and r["istaknuto"] is False and r["prevoz"] == "obavezan"
              for r in db_rows("opcije_soba", cid, pid2))
      and db_rows("opcije_soba", cid, 0) == [])

r = c.get(f"/api/cenovnici/{cid}/opcije-soba/{soba12['id']}", headers=H)
check("single GET spaja redove sobe preko SVIH perioda (mešovito → neutralno)",
      r.json()["postoji"] is True and r.json()["blokirano"] is False
      and r.json()["istaknuto"] is False and r.json()["prevoz"] is None)

r = c.get(f"/api/cenovnici/{cid}/opcije-soba-termin/{pid}", headers=H)
check("termin GET → zapisi N u redosledu snimka",
      r.json()["postoji"] is True and len(r.json()["zapisi"]) == N
      and [z["soba_id"] for z in r.json()["zapisi"]] == [s["id"] for s in d["sobe"]])

# single PUT (soba × SVI termini) pregazuje i override termina te sobe
c.put(f"/api/cenovnici/{cid}/opcije-soba/{soba12['id']}", headers=H, json={"blokirano": True})
check("single PUT upisuje soba × SVE termine (P redova te sobe, ukupno N × P)",
      len(db_rows("opcije_soba", cid)) == N * P
      and len(db_rows("opcije_soba", cid, pid)) == N
      and all(r["blokirano"] is True and r["istaknuto"] is False
              for r in db_rows("opcije_soba", cid, pid) if r["soba_id"] == soba12["id"]))

# masovno PUT (-sve) briše SVE redove cenovnika i upisuje svako polje ponaosob
c.put(f"/api/cenovnici/{cid}/opcije-soba-sve", headers=H, json={"blokirano": False})
check("masovno PUT briše SVE (override termina nestaje) i upisuje N × P eksplicitnih redova",
      len(db_rows("opcije_soba", cid)) == N * P and db_rows("opcije_soba", cid, 0) == []
      and all(r["blokirano"] is False for r in db_rows("opcije_soba", cid, pid)))

c.put(f"/api/cenovnici/{cid}/opcije-soba-termin/{pid}", headers=H,
      json={"istaknuto": True, "prevoz": "nemoguc"})
r = c.delete(f"/api/cenovnici/{cid}/opcije-soba-termin/{pid}", headers=H)
check("termin DELETE → broj = N, samo pid redovi obrisani, ostali periodi ostaju",
      r.status_code == 200 and r.json()["broj"] == N and db_rows("opcije_soba", cid, pid) == []
      and len(db_rows("opcije_soba", cid)) == N * (P - 1)
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
popusti3 = [
    {"umanjenje_vrsta": "procenat", "umanjenje": "10", "tip_popusta": "last_minute"},
    {"umanjenje_vrsta": "iznos", "umanjenje": "20", "tip_popusta": "first_minute"},
    {"umanjenje_vrsta": "procenat", "umanjenje": "5", "tip_popusta": "specijalna_ponuda"},
]
popust1_drugi_termin = [{"umanjenje_vrsta": "iznos", "umanjenje": "7", "tip_popusta": "last_minute"}]
r = c.put(f"/api/cenovnici/{cid}/popust-soba-termin/{pid}", headers=H, json={"popusti": popusti3})
check("popust-termin PUT → N soba i tri zasebna zapisa po sobi",
      r.status_code == 200 and r.json()["broj_soba"] == N
      and len(db_rows("popust_soba", cid, pid)) == N * 3
      and sorted(x["redni"] for x in db_rows("popust_soba", cid, pid)) == [1] * N + [2] * N + [3] * N)
rows_pid = db_rows("popust_soba", cid, pid)
check("popust redni 1..3 nosi vrednosti nezavisno, bez sabiranja",
      all(any(x["redni"] == i and x["tip_popusta"] == popusti3[i-1]["tip_popusta"]
              and float(x["umanjenje"]) == float(popusti3[i-1]["umanjenje"]) for x in rows_pid)
          for i in (1, 2, 3)))
r = c.get(f"/api/cenovnici/{cid}/popust-soba-termin/{pid}", headers=H)
check("popust-termin GET → tri zapisa po sobi, redni 1..3",
      r.status_code == 200 and len(r.json()["zapisi"]) == N * 3
      and sorted(z["redni"] for z in r.json()["zapisi"]) == [1] * N + [2] * N + [3] * N)

r = c.put(f"/api/cenovnici/{cid}/popust-soba-termin/{pid2}", headers=H,
          json={"popusti": popust1_drugi_termin})
check("drugi termin ima nezavisan popust (N redova, redni=1)",
      r.status_code == 200 and len(db_rows("popust_soba", cid, pid2)) == N
      and all(x["redni"] == 1 and x["tip_popusta"] == "last_minute"
              for x in db_rows("popust_soba", cid, pid2)))

# Full replace na prvom terminu smanjuje skup sa tri na dva i ne dira drugi termin.
popusti2 = [popusti3[0], popusti3[2]]
r = c.put(f"/api/cenovnici/{cid}/popust-soba-termin/{pid}", headers=H, json={"popusti": popusti2})
check("termin PUT je full replace: dva nova redna zapisa po sobi",
      r.status_code == 200 and len(db_rows("popust_soba", cid, pid)) == N * 2
      and set(x["redni"] for x in db_rows("popust_soba", cid, pid)) == {1, 2}
      and all(x["tip_popusta"] != "first_minute" for x in db_rows("popust_soba", cid, pid)))
check("replace termina nije promenio popuste drugog termina",
      len(db_rows("popust_soba", cid, pid2)) == N
      and all(x["umanjenje"] == 7 for x in db_rows("popust_soba", cid, pid2)))

r = c.put(f"/api/cenovnici/{cid}/popust-soba-termin/{pid}", headers=H, json={"popusti": []})
check("prazna lista briše samo taj termin", r.status_code == 200
      and db_rows("popust_soba", cid, pid) == [] and len(db_rows("popust_soba", cid, pid2)) == N)
check("više od tri popusta → 422",
      c.put(f"/api/cenovnici/{cid}/popust-soba-termin/{pid}", headers=H,
            json={"popusti": popusti3 + [popusti3[0]]}).status_code == 422)
check("flat telo (stari oblik) se ne prihvata → 422",
      c.put(f"/api/cenovnici/{cid}/popust-soba-termin/{pid}", headers=H,
            json=popusti3[0]).status_code == 422)

r = c.put(f"/api/cenovnici/{cid}/popust-soba-termin/{pid}", headers=H,
          json={"popusti": popusti3})
r = c.delete(f"/api/cenovnici/{cid}/popust-soba-termin/{pid}", headers=H)
check("termin DELETE → broj = broj obrisanih redova, drugi termin ostaje",
      r.status_code == 200 and r.json()["broj"] == N * 3
      and db_rows("popust_soba", cid, pid) == [] and len(db_rows("popust_soba", cid, pid2)) == N
      and c.delete(f"/api/cenovnici/{cid}/popust-soba-termin/{pid}", headers=H).json()["broj"] == 0)

# cascade sa cenovnikom
c.put(f"/api/cenovnici/{cid}/opcije-soba-termin/{pid}", headers=H, json={"blokirano": True})
c.put(f"/api/cenovnici/{cid}/popust-soba-termin/{pid}", headers=H,
      json={"popusti": [popusti3[0], popusti3[1]]})
c.delete(f"/api/cenovnici/{cid}", headers=H)
check("cascade: termin + ostali redovi obrisani sa cenovnikom",
      db_rows("opcije_soba", cid) == [] and db_rows("popust_soba", cid) == [])

# ── 3) UI — O·P dugme u koloni matrice ──────────────────────────────────────
d2 = postavi_cenovnik()
ui_cid = d2["id"]
ui_N = len(d2["sobe"])
ui_pid = d2["periodi"][0]["id"]

c.put(f"/api/cenovnici/{ui_cid}/opcije-soba-sve", headers=H,
      json={"blokirano": True, "prevoz": "obavezan"})  # masovno — eksplicitni redovi i za ovaj termin

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    BASE = "http://localhost:3058"
    pg.goto(f"{BASE}/agencija/cenovnici")
    # prvi /auth/me ide bez tokena → 401 → clearToken(); sačekaj da se auth slegne (/login)
    # pre upisa tokena, inače 401 handler obriše sveže upisan token (race)
    pg.wait_for_url("**/login", timeout=15000)
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
    check("UI: prefill termina = sačuvane masovne vrednosti (eksplicitni redovi po polju)",
          pg.locator("#opc-blokirano").get_attribute("aria-checked") == "true"
          and "Obavezan" in pg.locator("#opc-prevoz").inner_text())

    c.delete(f"/api/cenovnici/{ui_cid}/opcije-soba-sve", headers=H)  # skinuti SVE → obeležje samo od termin snimanja

    pg.locator("#opc-istaknuto").click()  # blokirano ostaje čekirano iz prefilla
    with pg.expect_response(lambda r: r.request.method == "PUT"
                            and r.url.endswith(f"/opcije-soba-termin/{ui_pid}")) as ri:
        pg.get_by_role("button", name="Snimi", exact=True).click()
    telo = json.loads(ri.value.request.post_data)
    check("UI: termin PUT payload (blokirano true zadržano iz prefilla, istaknuto true) → sacuvano",
          telo["blokirano"] is True and telo["istaknuto"] is True
          and telo["prevoz"] == "obavezan" and ri.value.json()["status"] == "sacuvano")
    pg.get_by_text("Opcije su sačuvane za sve sobe i termin").wait_for(timeout=8000)
    check("UI: N eksplicitnih redova za taj termin (prevoz=obavezan iz prefilla), bez pid=0 redova",
          len(db_rows("opcije_soba", ui_cid, ui_pid)) == ui_N
          and all(r["istaknuto"] is True and r["prevoz"] == "obavezan"
                  for r in db_rows("opcije_soba", ui_cid, ui_pid))
          and db_rows("opcije_soba", ui_cid, 0) == [])

    # obeležja polja se osvežavaj ODMAH posle Snimi (i dok je dijalog još otvoren)
    ui_od = dmy(d2["periodi"][0]["datum_od"])
    ui_do = dmy(d2["periodi"][0]["datum_do"])
    celija0 = pg.get_by_label(
        f"Cena — soba {d2['sobe'][0]['broj_sobe']}, period {ui_od}–{ui_do}")
    expect(celija0).to_have_class(re.compile(r"bg-red-100"), timeout=8000)
    check("UI: blokirano polje termina je crveno odmah posle Snimi (dijalog još otvoren)",
          "border-red-300" in (celija0.get_attribute("class") or ""))

    dijalog.get_by_role("button", name="Obriši opcije").click()
    pg.get_by_text("Opcije su obrisane za sve sobe i termin").wait_for(timeout=8000)
    expect(celija0).not_to_have_class(re.compile(r"bg-red-100"), timeout=8000)
    check("UI: brisanje override-a termina", db_rows("opcije_soba", ui_cid, ui_pid) == [])

    pg.get_by_role("tab", name="Popusti").click()
    pg.get_by_role("button", name="Dodaj popust").click()  # nema popusta → forma skrivena dok se ne doda
    pg.locator("#pop-umanjenje").fill("10")
    pg.locator("#pop-tip").click()
    pg.get_by_role("option", name="Last minute", exact=True).click()
    with pg.expect_response(lambda r: r.request.method == "PUT"
                            and r.url.endswith(f"/popust-soba-termin/{ui_pid}")) as ri2:
        pg.get_by_role("button", name="Snimi", exact=True).click()
    telo2 = json.loads(ri2.value.request.post_data)["popusti"]
    check("UI: popust-termin PUT (1 popust: iznos 10, last_minute)",
          len(telo2) == 1 and telo2[0]["umanjenje_vrsta"] == "iznos"
          and float(telo2[0]["umanjenje"]) == 10.0 and telo2[0]["tip_popusta"] == "last_minute")
    pg.get_by_text("Popusti sačuvani (1) za sve sobe i termin").wait_for(timeout=8000)
    check("UI: popust na sve sobe za termin (redni 1)",
          len(db_rows("popust_soba", ui_cid, ui_pid)) == ui_N
          and all(r["tip_popusta"] == "last_minute" and r["redni"] == 1
                  for r in db_rows("popust_soba", ui_cid, ui_pid)))
    b.close()

check("cleanup UI cenovnik obrisan", c.delete(f"/api/cenovnici/{ui_cid}", headers=H).status_code == 200)

print(f"\n{sum(OK)}/{len(OK)} PASS")
sys.exit(0 if all(OK) else 1)
