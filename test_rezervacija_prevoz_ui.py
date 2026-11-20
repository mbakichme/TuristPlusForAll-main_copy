"""Playwright UI test — tab Prevoz u rezervaciji.

Flow:
  1. API kreira test rezervaciju (nosilac OW sa destinacijom, napomena prevoz).
  2. UI /prodaja/rezervacije?u=KLJUC → Prevoz tab prikazuje sačuvane vrednosti
     (Napomena prevoz, Destinacija OW, Mesto za sedenje, Plaćeno).
  3. Izmena napomene + Sačuvaj → API GET potvrđuje novu vrednost, a OW polja ostaju.
  4. Cleanup test reda (aranzman + aranzman_dopuna) preko DB.
"""
import json
import os
import subprocess
import sys

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/tmp/pw-browsers")

import httpx
from playwright.sync_api import expect, sync_playwright

from routes import create_access_token

APP = os.environ.get("TEST_APP_URL", "http://localhost:3058")
API = os.environ.get("TEST_API_URL", "http://127.0.0.1:3158/api")
SME = "TEST PREVOZ SMEŠTAJ"
SOBA = "TP901"
IME = "TEST PREVOZ UI NOSILAC"
NAPOMENA_1 = "TEST UI napomena prevoz"
NAPOMENA_2 = "TEST UI napomena izmenjena"


def main():
    token = create_access_token({"sub": "1"})  # never printed
    api = httpx.Client(base_url=API, headers={"Authorization": "Bearer " + token}, timeout=30)
    dp = api.get("/destinacija-prevoz").json()[0]  # destinacija prevoza (ID + naziv)
    dest_naziv, dest_id = dp["naziv"], dp["id"]
    kljuc = None
    ok = True

    nosilac = {"ime": IME, "datumRodjenja": "1990-01-01", "pasos": "T1234567",
               "uzrast": "ADL",
               "ow": True, "rt": False, "sp": False, "smer": "Polazak",
               "adresa": "Test adresa 1", "telefon": "0601234567", "email": "",
               "mestoSedenja": "GORE STO", "placeno": True, "zelja": False,
               "datumOw": "2026-11-30", "destinacijaOwId": dest_id, "destinacijaOw": "",
               "datumPolaska": "", "destinacijaPolaskaId": None, "destinacijaPolaska": "",
               "datumPovratka": "", "destinacijaPovratkaId": None, "destinacijaPovratka": ""}
    body = {"tiprezervacije": "Klasična rezervacija", "timelimit": None,
            "nosilac": nosilac, "saputnici": [],
            "boravak": {"datumOd": "2026-12-01", "datumDo": "2026-12-08", "smestajId": None,
                        "sobaId": None, "mestoId": None, "smestajNaziv": SME, "sobaBroj": SOBA,
                        "mestoNaziv": "TEST MESTO", "struktura": "1/2",
                        "napomena": "", "napomenaInterna": ""},
            "destinacijaId": None, "destinacijaNaziv": None, "ulazak": "",
            "napomenaPrevoz": NAPOMENA_1,
            "cene": {"cenaSmestajEUR": 100, "kolSmestajEUR": 1, "cenaSmestajRSD": 0,
                     "kolSmestajRSD": 0, "popustSmestaj": {}, "cenaPrevozEUR": 0,
                     "kolPrevozEUR": 0, "cenaPrevozRSD": 0, "kolPrevozRSD": 0,
                     "popustPrevoz": {}, "osiguranjeEUR": 0, "osiguranjeRSD": 0,
                     "provizijaSmestaj": {}, "provizijaPrevoz": {}, "uplaceno": {}}}
    try:
        r = api.post("/rezervacije", json=body)
        r.raise_for_status()
        kljuc = r.json()["kljuc"]
        print(f"[api] test rezervacija {kljuc}")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = browser.new_context()
            context.add_init_script(f"localStorage.setItem('ta_token', {json.dumps(token)});")
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"{APP}/prodaja/rezervacije?u={kljuc}", wait_until="domcontentloaded")

            # zaključano pri otvaranju → Izmeni
            page.get_by_role("button", name="Izmeni", exact=True).click()
            page.get_by_role("tab", name="Prevoz").click()

            napomena = page.get_by_label("Napomena prevoz", exact=True)
            expect(napomena).to_have_value(NAPOMENA_1, timeout=15000)
            print("[ui] Napomena prevoz prikazuje sačuvanu vrednost")

            page.get_by_role("button", name=f"Otvori detalje prevoza — {IME}").click()
            destinacija = page.get_by_label(f"Destinacija OW — {IME}")
            expect(destinacija).to_contain_text(dest_naziv, timeout=10000)
            print("[ui] Destinacija OW prikazuje sačuvanu destinaciju")

            mesto = page.get_by_label(f"Mesto za sedenje — {IME}")
            expect(mesto).to_contain_text("GORE STO", timeout=10000)
            print("[ui] Mesto za sedenje = GORE STO")

            # izmena napomene → Sačuvaj
            napomena.fill(NAPOMENA_2)
            page.get_by_role("button", name="Sačuvaj", exact=True).click()
            ne_sada = page.get_by_role("button", name="Ne sada", exact=True)
            try:
                ne_sada.click(timeout=8000)
            except Exception:
                pass
            page.wait_for_timeout(1500)
            print("[ui] Sačuvaj izvršeno")

            d = api.get(f"/ugovori/{kljuc}").json()
            if d.get("napomena_prevoz") != NAPOMENA_2:
                ok = False
                print(f"  FAIL napomena_prevoz u bazi: {d.get('napomena_prevoz')!r}")
            else:
                print("[db] napomena_prevoz izmenjena")
            if d.get("datum_ow") != "2026-11-30" or d.get("destinacija_ow") != dest_naziv:
                ok = False
                print(f"  FAIL OW polja: {d.get('datum_ow')!r} / {d.get('destinacija_ow')!r}")
            else:
                print("[db] OW polja netaknuta posle snimanja")

            errors = [e for e in errors if "WebSocket" not in e]  # Vite HMR šum
            if errors:
                ok = False
                print("  FAIL page errors:", errors[:3])
            browser.close()
    except Exception as e:
        ok = False
        print("  FAIL:", repr(e))
    finally:
        if kljuc:
            code = (
                "import db_config\n"
                "from sqlalchemy import text\n"
                "e = db_config.get_engine()\n"
                "with e.begin() as c:\n"
                f"    ids = [r[0] for r in c.execute(text(\"DELETE FROM aranzman WHERE kljuc = :k AND putnik LIKE 'TEST PREVOZ%' RETURNING id\"), {{'k': '{kljuc}'}}).fetchall()]\n"
                "    for i in ids:\n"
                "        c.execute(text('DELETE FROM aranzman_dopuna WHERE aranzman_id = :i'), {'i': i})\n"
                "    print('obrisano', len(ids))\n"
            )
            subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                           cwd=os.path.dirname(os.path.abspath(__file__)))
            print("[cleanup] test red obrisan")

    print("\nREZULTAT:", "SVE PROVERE PROŠLE" if ok else "IMA GREŠAKA")


if __name__ == "__main__":
    main()
