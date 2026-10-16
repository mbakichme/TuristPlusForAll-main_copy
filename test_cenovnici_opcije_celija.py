"""Cenovnici — opcije/popusti po POLJU (soba × termin): klik na ćeliju cene kad je zaključano.

Endpointi termin-dijela prošireni opcionim ?soba_id= — puni replace SAMO tog polja (jedan zapis).
GET /cenovnici/{id}/opcije-celije → polja (soba_id, period_id) sa definisanim opcijama ILI
popustima (union) → svetloplavo obeležavanje ćelija; legacy pid=0 redovi se i dalje šire na sve
periode, a masovno snimanje piše svako polje eksplicitno.
"""
import json
import re
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


def dmy(iso):
    return f"{iso[8:10]}.{iso[5:7]}.{iso[:4]}"


def postavi_cenovnik():
    r = c.post("/api/cenovnici", headers=H, json={
        "mesto_id": 1, "grupa_id": 6, "smestaj_id": 10,  # ELENI 2 — realne + virtuelne sobe
        "datumod": "2026-05-25", "datumdo": "2026-10-02", "cene": []})
    assert r.status_code == 201, r.text
    return r.json()


# ── 1) API — opcije po polju (soba × termin) ────────────────────────────────
d = postavi_cenovnik()
cid = d["id"]
N = len(d["sobe"])
pid = d["periodi"][0]["id"]
pid2 = d["periodi"][1]["id"]
soba12 = next(s for s in d["sobe"] if s["broj_sobe"] == "12" and not s.get("virtuelna"))
soba18 = next(s for s in d["sobe"] if s["broj_sobe"] == "18" and not s.get("virtuelna"))

r = c.put(f"/api/cenovnici/{cid}/opcije-soba-termin/{pid}?soba_id={soba12['id']}", headers=H,
          json={"istaknuto": True, "prevoz": "nemoguc"})
check("cell PUT → sacuvano broj_soba=1, soba_id=[soba]",
      r.status_code == 200 and r.json()["status"] == "sacuvano"
      and r.json()["broj_soba"] == 1 and r.json()["soba_id"] == [soba12["id"]]
      and r.json()["period_id"] == pid)

redovi = db_rows("opcije_soba", cid, pid)
check("u bazi TAČNO jedan red (soba, pid), ostale sobe netaknute",
      len(redovi) == 1 and redovi[0]["soba_id"] == soba12["id"]
      and redovi[0]["istaknuto"] is True and redovi[0]["prevoz"] == "nemoguc")

r = c.get(f"/api/cenovnici/{cid}/opcije-soba-termin/{pid}?soba_id={soba12['id']}", headers=H)
check("cell GET → postoji True + jedan zapis te sobe",
      r.status_code == 200 and r.json()["postoji"] is True
      and len(r.json()["zapisi"]) == 1 and r.json()["zapisi"][0]["istaknuto"] is True)
r = c.get(f"/api/cenovnici/{cid}/opcije-soba-termin/{pid}", headers=H)
check("termin GET (bez soba_id) vidi samo cell-zapis te sobe",
      r.json()["postoji"] is True and [z["soba_id"] for z in r.json()["zapisi"]] == [soba12["id"]])

r = c.get(f"/api/cenovnici/{cid}/opcije-celije", headers=H)
check("opcije-celije → TAČNO jedno polje (soba, pid), globalni (0) NE ulazi",
      r.status_code == 200
      and r.json()["celije"] == [{"soba_id": soba12["id"], "period_id": pid}])

# drugo polje (druga soba, drugi termin) + popust-only polje
c.put(f"/api/cenovnici/{cid}/opcije-soba-termin/{pid2}?soba_id={soba18['id']}", headers=H,
      json={"blokirano": True})
c.put(f"/api/cenovnici/{cid}/popust-soba-termin/{pid2}?soba_id={soba12['id']}", headers=H,
      json={"umanjenje_vrsta": "iznos", "umanjenje": "5", "tip_popusta": "last_minute"})
r = c.get(f"/api/cenovnici/{cid}/opcije-celije", headers=H)
check("opcije-celije = union opcija i popusta (3 polja)",
      sorted((x["soba_id"], x["period_id"]) for x in r.json()["celije"])
      == sorted([(soba12["id"], pid), (soba18["id"], pid2), (soba12["id"], pid2)]))

# popust po polju
r = c.get(f"/api/cenovnici/{cid}/popust-soba-termin/{pid2}?soba_id={soba12['id']}", headers=H)
check("popust cell GET → jedan zapis (iznos 5)",
      r.json()["postoji"] is True and len(r.json()["zapisi"]) == 1
      and float(r.json()["zapisi"][0]["umanjenje"]) == 5.0
      and len(db_rows("popust_soba", cid, pid2)) == 1)
check("popust globalni (pid 0) prazan", db_rows("popust_soba", cid, 0) == [])

# brisanje po polju
r = c.delete(f"/api/cenovnici/{cid}/opcije-soba-termin/{pid}?soba_id={soba12['id']}", headers=H)
check("cell DELETE → broj=1, ostala polja ostaju",
      r.status_code == 200 and r.json()["broj"] == 1
      and db_rows("opcije_soba", cid, pid) == []
      and len(db_rows("opcije_soba", cid, pid2)) == 1)
check("cell DELETE idempotentno → broj=0",
      c.delete(f"/api/cenovnici/{cid}/opcije-soba-termin/{pid}?soba_id={soba12['id']}",
               headers=H).json()["broj"] == 0)
r = c.delete(f"/api/cenovnici/{cid}/popust-soba-termin/{pid2}?soba_id={soba12['id']}", headers=H)
check("popust cell DELETE → broj=1", r.json()["broj"] == 1
      and db_rows("popust_soba", cid, pid2) == [])

# LEGACY pid=0 red (od starih verzija) se i dalje ŠIRI na sve periode u obeležjima
with engine.begin() as conn:
    conn.execute(text("""INSERT INTO opcije_soba (cenovnik_id, soba_id, period_id, blokirano)
        VALUES (:c, :s, 0, TRUE)"""), {"c": cid, "s": soba12["id"]})
r = c.get(f"/api/cenovnici/{cid}/opcije-celije", headers=H)
check("opcije-celije: legacy pid=0 red proširen na SVE periode + cell-zapis druge sobe",
      r.status_code == 200
      and {(x["soba_id"], x["period_id"]) for x in r.json()["celije"]}
      == {(soba12["id"], p["id"]) for p in d["periodi"]} | {(soba18["id"], pid2)})

# masovno snimanje — EKSPLICITNO po polju (N × P redova, bez pid=0); briše i legacy i cell-redove
c.put(f"/api/cenovnici/{cid}/opcije-soba-sve", headers=H,
      json={"blokirano": True, "prevoz": "obavezan"})
check("masovno snimanje upisuje N × P eksplicitnih redova (svaka soba × svaki termin)",
      len(db_rows("opcije_soba", cid)) == N * len(d["periodi"])
      and all(r["period_id"] != 0 and r["blokirano"] is True and r["prevoz"] == "obavezan"
              for r in db_rows("opcije_soba", cid)))
r = c.get(f"/api/cenovnici/{cid}/opcije-celije", headers=H)
check("opcije-celije posle masovnog snimanja → cela matrica (sobe × periodi)",
      r.status_code == 200
      and {(x["soba_id"], x["period_id"]) for x in r.json()["celije"]}
      == {(s["id"], p["id"]) for s in d["sobe"] for p in d["periodi"]})

# single PUT (soba × SVI termini) — scope-clearing: pregazuje i cell/masovne redove te sobe
c.put(f"/api/cenovnici/{cid}/opcije-soba/{soba18['id']}", headers=H, json={"blokirano": False})
check("single PUT sobe upisuje soba × SVE termine (pregazio njene cell-zapise)",
      len(db_rows("opcije_soba", cid)) == N * len(d["periodi"])
      and all(r["blokirano"] is False
              for r in db_rows("opcije_soba", cid) if r["soba_id"] == soba18["id"])
      and len([r for r in db_rows("opcije_soba", cid, pid2) if r["soba_id"] == soba18["id"]]) == 1)

# termin PUT (bez soba_id) i dalje puni replace CELOG termina (regresija)
c.put(f"/api/cenovnici/{cid}/opcije-soba-termin/{pid2}", headers=H, json={"istaknuto": True})
check("termin PUT (bez soba_id) briše cell-ove i piše N redova za ceo termin",
      len(db_rows("opcije_soba", cid, pid2)) == N
      and all(r["istaknuto"] is True for r in db_rows("opcije_soba", cid, pid2)))
r = c.get(f"/api/cenovnici/{cid}/opcije-celije", headers=H)
check("opcije-celije posle termin PUT → cela matrica",
      len(r.json()["celije"]) == N * len(d["periodi"]))

check("404 nepoznat cenovnik (cell GET/PUT/DELETE)",
      c.get(f"/api/cenovnici/99999904/opcije-soba-termin/{pid}?soba_id=1", headers=H).status_code == 404
      and c.put(f"/api/cenovnici/99999904/opcije-soba-termin/{pid}?soba_id=1", headers=H,
                json={}).status_code == 404
      and c.delete(f"/api/cenovnici/99999904/opcije-soba-termin/{pid}?soba_id=1",
                   headers=H).status_code == 404
      and c.get("/api/cenovnici/99999904/opcije-celije", headers=H).status_code == 404)
check("400 soba van snimka (cell GET/PUT/DELETE)",
      c.get(f"/api/cenovnici/{cid}/opcije-soba-termin/{pid}?soba_id=999999", headers=H).status_code == 400
      and c.put(f"/api/cenovnici/{cid}/opcije-soba-termin/{pid}?soba_id=999999", headers=H,
                json={}).status_code == 400
      and c.delete(f"/api/cenovnici/{cid}/opcije-soba-termin/{pid}?soba_id=999999",
                   headers=H).status_code == 400)
check("400 period van snimka (cell)",
      c.put(f"/api/cenovnici/{cid}/opcije-soba-termin/999999?soba_id={soba12['id']}",
            headers=H, json={}).status_code == 400)

# cascade
c.delete(f"/api/cenovnici/{cid}", headers=H)
check("cascade: cell + globalni zapisi obrisani sa cenovnikom",
      db_rows("opcije_soba", cid) == [] and db_rows("popust_soba", cid) == [])

# ── 2) UI — klik na ćeliju cene kad je cenovnik zaključan ───────────────────
d2 = postavi_cenovnik()
ui_cid = d2["id"]
ui_pid = d2["periodi"][0]["id"]
ui_od = dmy(d2["periodi"][0]["datum_od"])
ui_do = dmy(d2["periodi"][0]["datum_do"])
s12 = next(s for s in d2["sobe"] if s["broj_sobe"] == "12" and not s.get("virtuelna"))
s18 = next(s for s in d2["sobe"] if s["broj_sobe"] == "18" and not s.get("virtuelna"))
polje12 = f"Opcije · Popusti za polje — soba 12 · {ui_od} – {ui_do}"

c.put(f"/api/cenovnici/{ui_cid}/opcije-soba-sve", headers=H,
      json={"blokirano": True, "prevoz": "obavezan"})  # masovno — eksplicitni redovi i za ovo polje

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

    polja = pg.get_by_title("Opcije · Popusti za polje", exact=False)
    expect(polja.first).to_be_attached(timeout=10000)
    check("UI: zaključan cenovnik — svaka ćelija ima klik-površinu za Opcije · Popusti",
          polja.count() == len(d2["sobe"]) * len(d2["periodi"]))

    pg.get_by_title(polje12, exact=True).click()
    dijalog = pg.locator("[role=dialog]")
    expect(pg.get_by_role("tab", name="Opcije")).to_be_visible(timeout=10000)
    check("UI: klik na ćeliju otvara dijalog po POLJU (banner + opis, bez selektora sobe)",
          dijalog.get_by_text("samo na polje soba 12", exact=False).count() > 0
          and dijalog.get_by_text("samo na polje soba 12", exact=False).count() > 0
          and dijalog.get_by_text("Soba", exact=True).count() == 0)
    check("UI: cell-zapis iz masovnog snimanja → prefill sa sačuvanim vrednostima",
          pg.locator("#opc-blokirano").get_attribute("aria-checked") == "true"
          and "Obavezan" in pg.locator("#opc-prevoz").inner_text())

    c.delete(f"/api/cenovnici/{ui_cid}/opcije-soba-sve", headers=H)  # skinuti masovne redove → cell Snimi piše TAČNO jedan red

    pg.locator("#opc-istaknuto").click()  # blokirano ostaje čekirano iz prefilla
    with pg.expect_response(lambda r: r.request.method == "PUT"
                            and f"/opcije-soba-termin/{ui_pid}" in r.url
                            and f"soba_id={s12['id']}" in r.url) as ri:
        pg.get_by_role("button", name="Snimi", exact=True).click()
    telo = json.loads(ri.value.request.post_data)
    check("UI: cell PUT payload (blokirano true iz prefilla, istaknuto true) → sacuvano broj_soba=1",
          telo["blokirano"] is True and telo["istaknuto"] is True
          and telo["prevoz"] == "obavezan"
          and ri.value.json()["status"] == "sacuvano" and ri.value.json()["broj_soba"] == 1)
    pg.get_by_text("Opcije su sačuvane za polje soba 12", exact=False).wait_for(timeout=8000)
    check("UI: u bazi TAČNO jedan cell-red (soba 12 × taj termin), bez pid=0 redova",
          len(db_rows("opcije_soba", ui_cid)) == 1
          and db_rows("opcije_soba", ui_cid, ui_pid)[0]["soba_id"] == s12["id"]
          and db_rows("opcije_soba", ui_cid, ui_pid)[0]["istaknuto"] is True
          and db_rows("opcije_soba", ui_cid, 0) == [])

    pg.keyboard.press("Escape")
    expect(dijalog).to_have_count(0, timeout=5000)

    def input_klasa(soba_id, od, do):
        return pg.get_by_label(f"Cena — soba {soba_id}, period {od}–{do}").get_attribute("class") or ""

    celija12 = pg.get_by_label(f"Cena — soba 12, period {ui_od}–{ui_do}")
    expect(celija12).to_have_class(re.compile(r"bg-sky-500/15"), timeout=8000)  # refetch posle zatvaranja
    check("UI: kliknuto polje SVETLO PLAVO na INPUTU (td bez tinta), susedno bez obeležja",
          "border-sky-400/70" in input_klasa("12", ui_od, ui_do)
          and "bg-sky-500/15" not in input_klasa("18", ui_od, ui_do))

    # ponovo otvori isto polje → prefill iz cell-zapisa, pa Obriši
    pg.get_by_title(polje12, exact=True).click()
    expect(pg.get_by_role("tab", name="Opcije")).to_be_visible(timeout=10000)
    check("UI: ponovno otvaranje — prefill iz cell-zapisa (istaknuto čekirano)",
          pg.locator("#opc-istaknuto").get_attribute("aria-checked") == "true")
    dijalog.get_by_role("button", name="Obriši opcije").click()
    pg.get_by_text("Opcije su obrisane za polje soba 12", exact=False).wait_for(timeout=8000)
    check("UI: brisanje cell-zapisa", db_rows("opcije_soba", ui_cid, ui_pid) == [])
    expect(celija12).not_to_have_class(re.compile(r"bg-sky-500/15"), timeout=8000)  # odmah uklonjeno

    pg.keyboard.press("Escape")
    expect(dijalog).to_have_count(0, timeout=5000)
    check("UI: posle brisanja polje više nije plavo",
          "bg-sky-500/15" not in input_klasa("12", ui_od, ui_do))

    # otključavanje — ćelije se vraćaju na unos cene (bez klik-površine)
    pg.get_by_role("button", name="Izmeni cenovnik", exact=True).click()
    expect(polja.first).not_to_be_attached(timeout=5000)
    check("UI: otključan cenovnik — ćelije za unos cene, bez Opcije·Popusti površina",
          pg.get_by_title("Opcije · Popusti za polje", exact=False).count() == 0)
    b.close()

check("cleanup UI cenovnik obrisan", c.delete(f"/api/cenovnici/{ui_cid}", headers=H).status_code == 200)

print(f"\n{sum(OK)}/{len(OK)} PASS")
sys.exit(0 if all(OK) else 1)
