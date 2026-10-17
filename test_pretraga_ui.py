"""Pretraga UI — tok: polazak → Trajanje opcije → biranje JEDNOG termina.

Flow: izbor mesta → kalendar (otvara se na prvi period mesta) → dan 25.05 →
popover ostaje otvoren i nudi SVE krajeve LANACA perioda od 25.05 (osnovni
termin + produženi boravci spajanjem uzastopnih perioda iste grupe, npr.
25.05–04.06 + 04.06–14.06 = 25.05–14.06, 20 noćenja) kao
„N noćenja | Povratak: DD.MM.YYYY.“ → klik na jedan → Pretraži →
rezultati za TAČNO izabrani boravak.
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
    api = httpx.Client(base_url=API, headers={"Authorization": "Bearer " + token}, timeout=120)
    mesto = next(m for m in api.get("/mesto").json() if m["id"] == 1)
    grupe_ids = set(mesto["grupe"])

    # Krajevi LANACA perioda od OD (ista logika kao doOpcije na klijentu)
    from datetime import datetime as _dt
    def _p(s: str):
        return _dt.strptime(s, "%d.%m.%Y")
    def _noc(d_s: str) -> int:
        return (_p(d_s) - _p(OD)).days

    do_opcije_set: set[str] = set()
    for g in api.get("/period-grupa").json():
        if g["id"] not in grupe_ids:
            continue
        poceci: dict[str, list[str]] = {}
        for d in (g.get("datumi") or []):
            poceci.setdefault(d["datum_od"], []).append(d["datum_do"])
        obradjeni, front = set(), [OD]
        while front:
            cur = front.pop()
            if cur in obradjeni:
                continue
            obradjeni.add(cur)
            for ddo in poceci.get(cur, []):
                do_opcije_set.add(ddo)
                front.append(ddo)
    do_opcije = sorted(do_opcije_set, key=lambda s: _p(s))
    print(f"[api] mesto={mesto['naziv']}, opcije trajanja (krajevi lanaca): {do_opcije}")

    # Svih 7 opcionih trajanja iz zahteva mora biti među opcijama
    ZAHTEVANI = ["30.05.2026", "01.06.2026", "04.06.2026", "08.06.2026",
                 "14.06.2026", "15.06.2026", "24.06.2026"]

    # Rezultat za izabrani boravak — produženi lanac od 20 noćenja (14.06.)
    izabrani_do = next(d for d in do_opcije if _noc(d) == 20)
    ocekivani = api.get("/slobodne-sobe", params={
        "mesto_id": 1, "datum_od": OD, "datum_do": izabrani_do}).json()
    print(f"[api] izabrani boravak {OD} – {izabrani_do}, smeštaji: "
          f"{[g['smestaj_naziv'] for g in ocekivani]}")

    okovi = []
    def proveri(naziv, uslov, detalj=""):
        okovi.append(uslov)
        print(f"{'PASS' if uslov else 'FAIL'} {naziv}" + (f" — {detalj}" if detalj and not uslov else ""))

    proveri("svih 7 opcionih trajanja iz zahteva je među krajevima lanaca",
            all(z in do_opcije_set for z in ZAHTEVANI),
            f"nedostaju={[z for z in ZAHTEVANI if z not in do_opcije_set]}")
    proveri("opcije hronološki po datumu povratka", do_opcije == sorted(do_opcije, key=_p))

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

        # ── 3. Trajanje opcije u popoveru (svi krajevi lanaca) ──
        for do_s in do_opcije:
            noc = _noc(do_s)
            txt = f"{nocenja_label(noc)} | Povratak: {do_s}."
            dugme = kal.first.get_by_text(txt, exact=True)
            dugme.wait_for(timeout=5000)
            proveri(f"opcija „{txt}“ ponuđena", dugme.is_visible())

        # ── 4. biramo produženi lanac 20 noćenja (14.06.2026) i Pretraži ──
        kal.first.get_by_text(f"20 noćenja | Povratak: {izabrani_do}.", exact=True).click(force=True)
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
    print("OK — pretraga: polazak → trajanje (lanci) → rezultati")

if __name__ == "__main__":
    main()
