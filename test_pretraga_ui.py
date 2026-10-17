"""Pretraga UI — tok: polazak → Trajanje opcije → biranje JEDNOG termina.

Flow: izbor mesta → kalendar (otvara se na prvi period mesta) → dan 25.05 →
popover ostaje otvoren i nudi SVE termine koji počinju na 25.05
(„N noćenja | Povratak: DD.MM.YYYY.“) → klik na jedan → Pretraži →
rezultati za TAČNO izabrani termin.
"""
import json
import os
import re
import sys

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/tmp/pw-browsers")

import httpx
from playwright.sync_api import sync_playwright

from routes import create_access_token

APP = os.environ.get("TEST_APP_URL", "http://localhost:3058")
API = os.environ.get("TEST_API_URL", "http://localhost:3158/api")
OD = "25.05.2026"

def nocenja_label(n: int) -> str:
    return f"{n} noćenje" if n % 10 == 1 and n % 100 != 11 else f"{n} noćenja"

def main() -> None:
    token = create_access_token({"sub": "1"})  # never printed
    api = httpx.Client(base_url=API, headers={"Authorization": "Bearer " + token}, timeout=60)
    mesto = next(m for m in api.get("/mesto").json() if m["id"] == 1)
    # Svi termini koji počinju na OD (grupe mesta) — kao doOpcije na klijentu
    grupe_ids = set(mesto["grupe"])
    do_opcije = sorted(
        ((d["datum_od"], d["datum_do"]) for g in api.get("/period-grupa").json()
         if g["id"] in grupe_ids for d in (g.get("datumi") or []) if d["datum_od"] == OD),
        key=lambda p: tuple(int(x) for x in reversed(p[1].split("."))),
    )
    print(f"[api] mesto={mesto['naziv']}, opcije trajanja: {do_opcije}")

    # Rezultat za izabrani termin — onaj sa 10 noćenja
    from datetime import datetime as _dt
    def _noc(d_s: str) -> int:
        return (_dt.strptime(d_s, "%d.%m.%Y") - _dt.strptime(OD, "%d.%m.%Y")).days
    izabrani_do = next(d for _, d in do_opcije if _noc(d) == 10)
    ocekivani = api.get("/slobodne-sobe", params={
        "mesto_id": 1, "datum_od": OD, "datum_do": izabrani_do}).json()
    print(f"[api] izabrani termin {OD} – {izabrani_do}, smeštaji: "
          f"{[g['smestaj_naziv'] for g in ocekivani]}")

    okovi = []
    def proveri(naziv, uslov, detalj=""):
        okovi.append(uslov)
        print(f"{'PASS' if uslov else 'FAIL'} {naziv}" + (f" — {detalj}" if detalj and not uslov else ""))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        ctx.add_init_script(f"localStorage.setItem('ta_token', {json.dumps(token)});")
        page = ctx.new_page()
        page.goto(APP + "/prodaja/pretraga", wait_until="domcontentloaded")

        # ── 1. mesto ──
        page.get_by_role("combobox").first.wait_for(timeout=15000)
        page.get_by_role("combobox").first.click()
        page.get_by_role("option", name=mesto["naziv"], exact=True).click()

        # ── 2. kalendar (otvara se na prvi period mesta — Maj 2026) → dan 25 ──
        page.get_by_text("Izaberite datum polaska").click()
        kal = page.locator("[data-radix-popper-content-wrapper]")
        kal.wait_for(timeout=5000)
        page.wait_for_timeout(200)
        proveri("kalendar prikazuje Maj 2026", "Maj 2026" in kal.first.inner_text())
        kal.first.locator("button:not([disabled])", has_text=re.compile(r"^25$")).first.click()
        page.wait_for_timeout(400)

        # ── 3. Trajanje opcije u popoveru ──
        for od_s, do_s in do_opcije:
            noc = _noc(do_s)
            txt = f"{nocenja_label(noc)} | Povratak: {do_s}."
            dugme = kal.first.get_by_text(txt, exact=True)
            dugme.wait_for(timeout=5000)
            proveri(f"opcija „{txt}“ ponuđena", dugme.is_visible())

        # ── 4. biramo 10 noćenja (04.06.2026) i Pretraži ──
        kal.first.get_by_text(f"10 noćenja | Povratak: {izabrani_do}.", exact=True).click(force=True)
        page.wait_for_timeout(300)
        page.get_by_role("button", name="Pretraži", exact=True).click()
        rez = page.get_by_text("Slobodni kapaciteti").first
        rez.wait_for(timeout=15000)
        proveri("rezultati prikazani", rez.is_visible())
        proveri("opis sadrži izabrani period",
                page.get_by_text(f"Period {OD} – {izabrani_do}").count() >= 1)
        for g in ocekivani:
            naziv = page.locator("h3", has_text=g["smestaj_naziv"]).first
            proveri(f"smeštaj {g['smestaj_naziv']} vidljiv", naziv.is_visible())
        ctx.close()
        browser.close()

    print()
    if not all(okovi):
        sys.exit(1)
    print("OK — pretraga: polazak → trajanje → rezultati")

if __name__ == "__main__":
    main()
