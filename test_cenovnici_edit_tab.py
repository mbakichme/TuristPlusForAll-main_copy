"""Tab Izmena kreiranih cenovnika: zaključavanje posle snimanja, sklanjanje
kreirane tabele pri prelasku na Izmenu (čak i sa nesačuvanim izmenama) i
paginacija liste cenovnika (5 poslednjih kreiranih po strani)."""
import os
import re
import sys

import routes
from fastapi.testclient import TestClient
from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
APP = "http://localhost:3058"
c = TestClient(routes.create_app("dist"))
tok = routes.create_access_token({"sub": "1"})
H = {"Authorization": f"Bearer {tok}"}
RE_CENA = re.compile(r"Cena — soba")

OK = []


def check(label, cond):
    OK.append(cond)
    print(("PASS " if cond else "FAIL ") + label)


# ── priprema: cenovnik za zaključavanje + batch za paginaciju ───────────────
r = c.post("/api/cenovnici", headers=H, json={
    "mesto_id": 1, "grupa_id": 6, "smestaj_id": 8,
    "datumod": "2026-11-01", "datumdo": "2026-11-30", "cene": []})
check("POST privremenog cenovnika (za zaključavanje) → 201", r.status_code == 201)
t1 = r.json()["id"]

n0 = len(c.get("/api/cenovnici", headers=H).json())
batch_n = (5 - n0 % 5) + 5  # garantuje ≥2 strane i poslednju stranu od tačno 5 redova
batch_ids = []
for _ in range(batch_n):
    rb = c.post("/api/cenovnici", headers=H, json={
        "mesto_id": 1, "grupa_id": 6, "smestaj_id": 8,
        "datumod": "2026-11-01", "datumdo": "2026-11-30", "cene": []})
    if rb.status_code == 201:
        batch_ids.append(rb.json()["id"])
ukupno = n0 + len(batch_ids)
strane = (ukupno + 4) // 5
print(f"[setup] postojećih: {n0}, dodatih: {len(batch_ids)}, ukupno: {ukupno}, strana: {strane}")
najnoviji = max(batch_ids + [t1])

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    pg.goto(f"{APP}/agencija/cenovnici")
    pg.evaluate("t => localStorage.setItem('ta_token', t)", tok)
    pg.goto(f"{APP}/agencija/cenovnici")
    pg.wait_for_selector("[role=tablist]")

    # ── A) nesačuvan draft iz taba Kreiranje se tiho briše pri prelasku na Izmenu
    combos = pg.get_by_role("combobox")
    combos.nth(0).click()
    pg.get_by_role("option", name="Hanioti").first.click()
    combos.nth(1).click()
    pg.get_by_role("option").filter(has_text="Kasandra: termini").first.click()
    combos.nth(2).click()
    pg.get_by_role("option", name="DIMITRA").first.click()
    pg.get_by_role("button", name="Kreiraj cenovnik").click()
    cena_create = pg.get_by_label(RE_CENA).first
    cena_create.wait_for(state="visible", timeout=15000)
    cena_create.fill("99")
    pg.get_by_role("tab", name="Izmena kreiranih cenovnika").click()
    pg.wait_for_timeout(400)
    check("prelazak na Izmenu: BEZ dijaloga „Odbaciti nesačuvane izmene?“",
          pg.get_by_text("Odbaciti nesačuvane izmene?").count() == 0)
    pg.get_by_role("tab", name="Kreiranje cenovnika").click()
    expect(pg.get_by_text("Izaberite mesto, grupu perioda i smeštaj")).to_be_visible(timeout=10000)
    check("povratak na Kreiranje: kreirana tabela uklonjena (nema polja za cene)",
          pg.get_by_label(RE_CENA).count() == 0)

    # ── B) paginacija: 5 poslednjih kreiranih na strani, ostatak na sledećim
    pg.reload()
    pg.wait_for_selector("[role=tablist]")
    pg.get_by_role("tab", name="Izmena kreiranih cenovnika").click()
    redovi = pg.locator("table tbody tr")
    expect(redovi).to_have_count(5, timeout=10000)
    prvi_id = redovi.first.locator("td").first.text_content().strip()
    check("strana 1: tačno 5 redova, prvi red = poslednji kreirani cenovnik",
          prvi_id == str(najnoviji))
    check("strana 1: prikazan broj strana", pg.get_by_text(f"strana 1 od {strane}").count() > 0)
    for _ in range(strane - 1):
        pg.get_by_role("button", name="Sledeća").click()
        pg.wait_for_timeout(200)
    check(f"poslednja strana ({strane}): prikazana u footeru",
          pg.get_by_text(f"strana {strane} od {strane}").count() > 0)
    check("poslednja strana: tačno 5 redova", redovi.count() == 5)
    check("poslednja strana: dugme Sledeća onemogućeno",
          pg.get_by_role("button", name="Sledeća").is_disabled())
    pg.get_by_role("button", name="Prethodna").click()
    pg.wait_for_timeout(200)
    check("Prethodna vraća na stranu unazad",
          pg.get_by_text(f"strana {strane - 1} od {strane}").count() > 0)

    # pretraga: jedan rezultat → footer paginacije se sklanja
    detalji = c.get(f"/api/cenovnici/{t1}", headers=H).json()
    pg.get_by_label("Pretraga cenovnika").fill(detalji["uuid"][:8])
    expect(redovi).to_have_count(1, timeout=10000)
    check("pretraga sa 1 rezultatom: footer paginacije nije prikazan",
          pg.get_by_role("button", name="Sledeća").count() == 0)

    # ── C) zaključavanje editora u tabu Izmena posle „Sačuvaj izmene“
    pg.get_by_label("Pretraga cenovnika").fill(str(t1))
    expect(redovi).to_have_count(1, timeout=10000)
    redovi.first.click()
    cena_edit = pg.get_by_label(RE_CENA).first
    cena_edit.wait_for(state="visible", timeout=15000)
    cena_edit.fill("55")
    pg.get_by_role("button", name="Sačuvaj izmene").click()
    pg.get_by_text("Izmene cenovnika su sačuvane").wait_for(timeout=10000)
    check("posle snimanja: polja za cene zaključana", cena_edit.is_disabled())
    check("posle snimanja: bedž „Zaključano“", pg.get_by_text("Zaključano", exact=True).count() > 0)
    check("posle snimanja: nudi se dugme „Izmeni cenovnik“",
          pg.get_by_role("button", name="Izmeni cenovnik", exact=True).count() > 0)
    pg.get_by_role("button", name="Izmeni cenovnik", exact=True).click()
    pg.wait_for_timeout(300)
    check("„Izmeni cenovnik“ otključava polja", cena_edit.is_enabled())
    expect(pg.get_by_text("Zaključano", exact=True)).to_have_count(0, timeout=5000)
    b.close()

# ── cleanup ─────────────────────────────────────────────────────────────────
trazeni = [t1] + batch_ids
obrisano = sum(1 for cid_ in trazeni if c.delete(f"/api/cenovnici/{cid_}", headers=H).status_code == 200)
check(f"cleanup: svih {len(trazeni)} privremenih cenovnika obrisano", obrisano == len(trazeni))

print(f"\n{sum(OK)}/{len(OK)} PASS")
sys.exit(0 if all(OK) else 1)
