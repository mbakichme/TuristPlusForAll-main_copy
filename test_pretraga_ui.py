"""Pretraga UI — multi-termin pretraga (svi termini od datuma polaska).

Flow: izbor mesta → kalendar → polazak 25.05.2026 → Pretraži →
svaki termin iz API odgovora ima svoj blok (od – do · N noćenja) sa smeštajima.
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

def main() -> None:
    token = create_access_token({"sub": "1"})  # never printed
    api = httpx.Client(base_url=API, headers={"Authorization": "Bearer " + token}, timeout=60)
    mesto = next(m for m in api.get("/mesto").json() if m["id"] == 1)
    ocekivani = api.get("/slobodne-sobe", params={"mesto_id": 1, "datum_od": OD}).json()
    print(f"[api] mesto={mesto['naziv']}, termini sa slobodnim smeštajem: "
          f"{[(t['datum_od'], t['datum_do'], t['nocenja']) for t in ocekivani]}")

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

        # ── 2. datum polaska: kalendar se otvara na prvi period mesta (Maj 2026) ──
        page.get_by_text("Izaberite datum polaska").click()
        kal = page.locator("[data-radix-popper-content-wrapper]")
        kal.wait_for(timeout=5000)
        page.wait_for_timeout(200)
        proveri("kalendar prikazuje Maj 2026", "Maj 2026" in kal.first.inner_text())
        kal.first.locator("button:not([disabled])", has_text=re.compile(r"^25$")).first.click()
        page.wait_for_timeout(300)  # popover se zatvara izborom dana
        proveri("datum polaska upisan u trigger", page.get_by_text(OD, exact=True).count() >= 1)

        # ── 3. Pretraži ──
        page.get_by_role("button", name="Pretraži", exact=True).click()
        rez = page.get_by_text("Slobodni kapaciteti").first
        rez.wait_for(timeout=15000)
        proveri("rezultati prikazani", rez.is_visible())

        # ── 4. blokovi termina ──
        for t in ocekivani:
            naslov = f"{t['datum_od']} – {t['datum_do']}"
            blk = page.get_by_text(naslov, exact=True)
            blk.first.wait_for(timeout=5000)
            proveri(f"termin {naslov} ({t['nocenja']} noćenja) prikazan", blk.first.is_visible())
        broj_blokova = page.locator("div.rounded-md.bg-primary\\/10").count()
        proveri("broj blokova == broj termina iz API", broj_blokova == len(ocekivani),
                f"blokova={broj_blokova} termina={len(ocekivani)}")
        for t in ocekivani:
            for g in t["smestaji"]:
                soba = page.locator("h3", has_text=g["smestaj_naziv"]).first
                proveri(f"smeštaj {g['smestaj_naziv']} vidljiv", soba.is_visible())
                break  # dovoljan jedan po terminu
        ctx.close()
        browser.close()

    print()
    if not all(okovi):
        sys.exit(1)
    print(f"OK — UI multi-termin pretraga ({len(ocekivani)} termina)")

if __name__ == "__main__":
    main()
