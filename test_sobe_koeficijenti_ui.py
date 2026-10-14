"""Playwright UI test — Sobe: kolona Mesto, kolona Koeficijenti, dialog sa više koeficijenata.

Flow:
  1. Sobe tabela ima kolone Mesto i Koeficijenti; postojeće sobe prikazuju mesto.
  2. Nova soba (tip TST/8) → početni koeficijent „0“ u koloni (auto-zapis na serveru).
  3. Dialog: implicitni auto-red bez trash-a → „Dodaj koeficijent“ (Adl=2, koef 1,5)
     → dva reda, kolona u tabeli „0 · 1.5“.
  4. Brisanje ručnog koeficijenta → ostaje samo auto red; kolona „0“.
  5. Brisanje test sobe.
Cleanup: briše TST/8 koeficijente i test sobu (za svaki slučaj).
"""
import json
import os

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/tmp/pw-browsers")

import httpx
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import text

from routes import create_access_token, get_engine

APP = os.environ.get("TEST_APP_URL", "http://localhost:3058")
API = os.environ.get("TEST_API_URL", "http://localhost:3158/api")
TIP = "TST/8"
BROJ = "TEST-UI"


def main():
    token = create_access_token({"sub": "1"})  # never printed
    api = httpx.Client(base_url=API, headers={"Authorization": "Bearer " + token}, timeout=30)
    engine = get_engine()
    page_errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context()
        context.add_init_script(f"localStorage.setItem('ta_token', {json.dumps(token)});")
        page = context.new_page()
        page.on("pageerror", lambda e: page_errors.append(str(e)))
        try:
            smestaj_naziv = api.get("/smestaj").json()[0]["naziv"]

            page.goto(APP + "/agencija/sobe", wait_until="domcontentloaded")
            headeri = page.locator("table thead th")
            expect(headeri.filter(has_text="Mesto").first).to_be_visible(timeout=15000)
            expect(headeri.filter(has_text="Koeficijenti").first).to_be_visible()
            prvi_red = page.locator("table tbody tr").first
            expect(prvi_red.locator("td").nth(1)).not_to_have_text("", timeout=15000)
            print("[kolone] Mesto i Koeficijenti u tabeli; postojeće sobe imaju mesto")

            # ── Nova soba → početni koeficijent ──
            page.get_by_role("button", name="Dodaj", exact=True).click()
            sheet = page.locator('[role="dialog"]')
            smestaj_combo = sheet.get_by_role("combobox").first
            expect(smestaj_combo).to_be_visible(timeout=15000)
            smestaj_combo.click()
            page.get_by_role("option", name=smestaj_naziv, exact=True).first.click()
            sheet.get_by_placeholder("npr. 101").fill(BROJ)
            sheet.get_by_placeholder("npr. 1/2+2").fill(TIP)
            sheet.get_by_role("button", name="Dodaj sobu").click()
            expect(page.get_by_text("Soba kreirana")).to_be_visible(timeout=15000)
            print(f"[dodaj] soba {BROJ} ({TIP}) u smeštaju '{smestaj_naziv}' kreirana")

            page.get_by_placeholder("Pretraga: smeštaj, broj sobe, tip, opis...").fill(BROJ)
            red = page.locator("table tbody tr").filter(has_text=BROJ)
            expect(red).to_have_count(1, timeout=15000)
            expect(red.locator("td").nth(0)).to_have_text(smestaj_naziv)
            koef_dugme = red.get_by_label(f"Koeficijenti — soba {BROJ}")
            expect(koef_dugme).to_have_text("0")
            print("[auto] početni koeficijent '0' već u koloni (server ga je kreirao sa sobom)")

            # ── Dialog: auto red + dodavanje više koeficijenata ──
            koef_dugme.click()
            dialog = page.locator('[role="alertdialog"], [role="dialog"]').filter(has_text="Koeficijenti —")
            expect(dialog.get_by_text(f"Struktura")).to_be_visible(timeout=15000)
            redovi_dijaloga = dialog.locator("table tbody tr")
            expect(redovi_dijaloga).to_have_count(1)
            expect(redovi_dijaloga.first.get_by_label(f"Obriši koeficijent 0")).to_have_count(0)
            print("[dijalog] auto red bez trash-a")

            dialog.get_by_role("button", name="Dodaj koeficijent").click()
            dialog.get_by_label("Novi koeficijent — Adl").fill("2")
            dialog.get_by_label("Novi koeficijent — vrednost").fill("1,5")
            dialog.get_by_role("button", name="Dodaj", exact=True).click()
            expect(page.get_by_text("Koeficijent dodat")).to_be_visible(timeout=15000)
            expect(redovi_dijaloga).to_have_count(2, timeout=15000)
            expect(redovi_dijaloga.nth(1).get_by_label("Obriši koeficijent 1.5")).to_be_visible()
            expect(koef_dugme).to_have_text("0 · 1.5")
            print("[dodaj] drugi koeficijent (Adl=2, 1,5→1.5); kolona u tabeli '0 · 1.5'")

            # ── Brisanje ručnog koeficijenta ──
            redovi_dijaloga.nth(1).get_by_label("Obriši koeficijent 1.5").click()
            expect(page.get_by_text("Koeficijent obrisan")).to_be_visible(timeout=15000)
            expect(redovi_dijaloga).to_have_count(1, timeout=15000)
            expect(koef_dugme).to_have_text("0")
            print("[brisi] ručni koeficijent obrisan; kolona nazad na '0'")

            dialog.get_by_role("button", name="Zatvori").click()

            # ── Brisanje test sobe ──
            red.locator("button.text-destructive").click()
            expect(page.get_by_text("Obriši sobu?")).to_be_visible(timeout=15000)
            page.get_by_role("button", name="Obriši", exact=True).click()
            expect(page.get_by_text("Soba obrisana")).to_be_visible(timeout=15000)
            expect(page.locator("table tbody tr").filter(has_text=BROJ)).to_have_count(0, timeout=15000)
            print("[brisi] test soba obrisana")

            assert page_errors == [], f"pageerror nije prazan: {page_errors}"
            print("[pageerror] lista prazna")
            print("PASS UI")
        finally:
            context.close()
            browser.close()
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM sobe WHERE broj_sobe = :b AND tip = :t"), {"b": BROJ, "t": TIP})
                conn.execute(text("DELETE FROM koeficijenti_prodaje WHERE struktura = :t"), {"t": TIP})
            with engine.connect() as conn:
                ostalo = conn.execute(text("SELECT COUNT(*) FROM koeficijenti_prodaje WHERE struktura = :t"), {"t": TIP}).scalar()
            assert ostalo == 0
            print(f"[cleanup] test podaci obrisani (TST/8 ostalo={ostalo})")
            api.close()


if __name__ == "__main__":
    main()
