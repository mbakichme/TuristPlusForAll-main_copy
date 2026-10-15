"""Cenovnici — opcija „Kopiraj cene“: unos cene se kopira na sobe iste strukture i opisa.

ELENI 2 (smeštaj 10, Hanioti / Kasandra: termini): realne sobe 12, 18, 21, 22, 23,
24, 25, 26, 5, 6 su sve 1/3 · STD; virtuelne v12, v18, …, v5, v6 su sve 1/2 · STD.
UI test: kreiranje (realna → realne, virtuelna → virtuelne, bez kopiranja na
različite strukture) + izmena (ista logika u tabu Izmena) + provera sacuvanih cena.
"""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from playwright.sync_api import sync_playwright, expect
from fastapi.testclient import TestClient
import routes

app = routes.create_app("dist")
c = TestClient(app)
tok = routes.create_access_token({"sub": "1"})
H = {"Authorization": f"Bearer {tok}"}
OK = []

# brojevi soba ELENI 2 (smeštaj 10) po strukturi
STD_13 = ["12", "18", "21", "22", "23", "24", "25", "26", "5", "6"]   # realne 1/3 · STD
V_12   = ["v12", "v18", "v21", "v22", "v23", "v24", "v25", "v26", "v5", "v6"]  # virtuelne 1/2 · STD


def check(label, cond):
    OK.append(cond)
    print(("PASS " if cond else "FAIL ") + label)


def cene_map(detail):
    return {(x["soba_id"], x["period_id"]): float(x["cena"]) for x in detail["cene"]}


with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    BASE = "http://localhost:3058"
    pg.goto(f"{BASE}/agencija/cenovnici")
    pg.evaluate("t => localStorage.setItem('ta_token', t)", tok)
    pg.goto(f"{BASE}/agencija/cenovnici")
    pg.wait_for_selector("[role=tablist]")

    # ── 1) Kreiranje: ELENI 2 ────────────────────────────────────────────────
    pg.get_by_role("combobox").nth(0).click()
    pg.get_by_role("option", name="Hanioti").first.click()
    pg.get_by_role("combobox").nth(1).click()
    pg.get_by_role("option").filter(has_text="Kasandra: termini").first.click()
    pg.get_by_role("combobox").nth(2).click()
    pg.get_by_role("option", name="ELENI 2").first.click()
    pg.get_by_role("button", name="Kreiraj cenovnik").click()
    pg.locator('input[aria-label^="Cena — soba 12,"]').first.wait_for(state="visible", timeout=15000)
    check("šablon ELENI 2 učitan (soba 12 u matrici)", True)

    def inp(broj):
        return pg.locator(f'input[aria-label^="Cena — soba {broj},"]')

    suf1 = inp("12").first.get_attribute("aria-label").split(", ", 1)[1]   # „period dd.mm.–dd.mm.“
    suf2 = inp("12").nth(1).get_attribute("aria-label").split(", ", 1)[1]

    def celija(broj, suf):
        return pg.locator(f'input[aria-label="Cena — soba {broj}, {suf}"]')

    # checkbox „Kopiraj cene“
    chk = pg.get_by_role("checkbox", name="Kopiraj cene")
    check("checkbox Kopiraj cene postoji i nenalepljen", chk.is_visible() and not chk.is_checked())
    chk.click()
    check("checkbox se stiklira", chk.is_checked())

    # unos u sobu 12 (1/3 · STD) → kopira se na sve 1/3 · STD sobe
    inp("12").first.fill("123")
    check("unos soba 12 → kopirano na 18,21,22,23,24,25,26,5,6 (P1)",
          all(celija(x, suf1).input_value() == "123" for x in STD_13))
    check("kopiranje ne dira: soba 31 (1/4+1 MEZ), 32 (1/4 MEZ), v12 (virtuelna), P2 sobe 12",
          celija("31", suf1).input_value() == "" and celija("32", suf1).input_value() == ""
          and celija("v12", suf1).input_value() == "" and inp("12").nth(1).input_value() == "")

    # isključeno → nema kopiranja
    chk.click()
    inp("23").nth(1).fill("55")
    check("isključeno: soba 23 P2=55 ostaje samo njoj",
          celija("23", suf2).input_value() == "55" and celija("18", suf2).input_value() == ""
          and celija("24", suf2).input_value() == "")
    check("isključeno: P1 vrednosti nepromenjene", celija("18", suf1).input_value() == "123")

    # virtuelna v12 (1/2 · STD) → kopira se na sve virtuelne 1/2 · STD, ne i na realne
    chk.click()
    inp("v12").first.fill("77")
    check("unos v12 → kopirano na v18,v21,v22,v23,v24,v25,v26,v5,v6 (P1)",
          all(celija(x, suf1).input_value() == "77" for x in V_12))
    check("v12 ne kopira na realne ni druge strukture",
          celija("12", suf1).input_value() == "123" and celija("v31-1", suf1).input_value() == ""
          and celija("v32", suf1).input_value() == "")

    # soba 31 (1/4+1 MEZ) — bez parova, ostaje samo njoj
    inp("31").first.fill("90")
    check("unos soba 31 (bez parova) → samo soba 31",
          celija("31", suf1).input_value() == "90" and celija("32", suf1).input_value() == ""
          and celija("33", suf1).input_value() == "")

    # datumi + sačuvaj
    for trg, idx in (("create-od", 10), ("create-do", 15)):
        pg.locator(f"#{trg}").click()
        pg.locator("[data-radix-popper-content-wrapper]").last \
          .get_by_role("gridcell").get_by_role("button").nth(idx).click()
        pg.wait_for_timeout(200)
    with pg.expect_response(lambda r: r.url.rstrip("/").endswith("/api/cenovnici")
                            and r.request.method == "POST") as ri:
        pg.get_by_role("button", name="Sačuvaj cenovnik").click()
    ui_cid = ri.value.json()["id"]
    d = ri.value.json()
    cm = cene_map(d)
    p1 = next(x["id"] for x in d["periodi"] if x["datum_od"] == min(y["datum_od"] for y in d["periodi"]))
    p2 = sorted(y["datum_od"] for y in d["periodi"])[1]
    p2 = next(x["id"] for x in d["periodi"] if x["datum_od"] == p2)
    real = {x["broj_sobe"]: x["id"] for x in d["sobe"] if not x.get("virtuelna")}
    virt = {x["broj_sobe"]: x["id"] for x in d["sobe"] if x.get("virtuelna")}
    check("POST: svih 10 soba 1/3·STD ima 123 na P1",
          all(cm.get((real[x], p1)) == 123.0 for x in STD_13))
    check("POST: svih 10 virtuelnih 1/2·STD ima 77 na P1",
          all(cm.get((virt[x], p1)) == 77.0 for x in V_12))
    check("POST: soba 23 P2=55, soba 31 P1=90, ukupno 22 cene",
          cm.get((real["23"], p2)) == 55.0 and cm.get((real["31"], p1)) == 90.0 and len(cm) == 22)
    check("POST: nema cena za sobe 32–35 ni za P2 osim sobe 23",
          all((real[str(x)], p1) not in cm for x in (32, 33, 34, 35))
          and sum(1 for (sid, pid) in cm if pid == p2) == 1)

    # ── 2) Tab Izmena: ista logika ───────────────────────────────────────────
    pg.get_by_role("tab", name="Izmena kreiranih cenovnika").click()
    pg.get_by_label("Pretraga cenovnika").fill(str(ui_cid))
    redovi = pg.get_by_role("row").filter(has=pg.get_by_role("cell", name=str(ui_cid), exact=True))
    expect(redovi).to_have_count(1, timeout=10000)
    redovi.first.click()
    inp("12").first.wait_for(state="visible", timeout=15000)

    chk2 = pg.get_by_role("checkbox", name="Kopiraj cene")
    check("checkbox dostupan i u tabu Izmena", chk2.is_visible())
    if not chk2.is_checked():
        chk2.click()
    inp("12").first.fill("150")
    check("izmena: unos soba 12 → kopirano na svih 10 (P1)",
          all(celija(x, suf1).input_value() == "150" for x in STD_13))
    check("izmena: virtuelne i dalje 77 na P1", celija("v12", suf1).input_value() == "77")

    with pg.expect_response(lambda r: r.url.rstrip("/").endswith(f"/api/cenovnici/{ui_cid}")
                            and r.request.method == "PUT") as ri2:
        pg.get_by_role("button", name="Sačuvaj izmene").click()
    cm2 = cene_map(ri2.value.json())
    check("PUT: realne 1/3·STD = 150 na P1", all(cm2.get((real[x], p1)) == 150.0 for x in STD_13))
    check("PUT: virtuelne i dalje 77, soba 31=90, soba 23 P2=55",
          all(cm2.get((virt[x], p1)) == 77.0 for x in V_12)
          and cm2.get((real["31"], p1)) == 90.0 and cm2.get((real["23"], p2)) == 55.0
          and len(cm2) == 22)
    b.close()

check("cleanup cenovnik obrisan", c.delete(f"/api/cenovnici/{ui_cid}", headers=H).status_code == 200)

print(f"\n{sum(OK)}/{len(OK)} PASS")
sys.exit(0 if all(OK) else 1)
