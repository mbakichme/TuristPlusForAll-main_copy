"""Playwright UI test — Koeficijenti prodaje stranica.

Flow:
  1. Stranica učitava 12 struktura iz sobe.tip kao auto-redove (nule, bez Select-a).
  2. „Dodaj red“ → ručni red sa Select-om; struktura 1/3, Adl=2, koeficijent 1,5.
  3. Negativ: „abc“ u Adl → toast greške, PUT nije poslat, unos nije prepisan.
  4. Sačuvaj → PUT 200; API ima 13 redova; reload → ručni red seća (Select + vrednosti).
  5. Dirty-guard: izmena → klik na link „/“ → AlertDialog → Otkaži ostaje; Nastavi navigira.
Cleanup: briše sve redove koeficijenata (test kontroliše celu tabelu).
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
        puts = []
        page.on(
            "response",
            lambda r: puts.append(r)
            if r.request.method == "PUT" and "/api/koeficijenti" in r.url
            else None,
        )
        try:
            # ── 1. Auto-redovi iz baze ──
            start = api.get("/koeficijenti").json()
            assert start["redovi"] == []
            strukture = start["strukture"]
            page.goto(APP + "/agencija/koeficijenti", wait_until="domcontentloaded")
            rows = page.locator("table tbody tr")
            expect(rows).to_have_count(len(strukture), timeout=15000)
            expect(page.get_by_role("combobox")).to_have_count(0)
            expect(rows.first.locator("td").first).to_have_text("1/2")
            expect(page.get_by_label("Adl — red 1", exact=True)).to_have_value("0")
            expect(page.get_by_label("Koeficijent — red 1", exact=True)).to_have_value("0")
            print(f"[grid] {len(strukture)} auto-redova sa nulama, struktura tekstom (bez Select-a)")

            # ── 2. Ručni red za istu strukturu ──
            red_n = len(strukture) + 1
            page.get_by_role("button", name="Dodaj red").click()
            expect(page.get_by_role("combobox")).to_have_count(1)
            trigger = page.get_by_role("combobox")
            trigger.click()
            page.get_by_role("option", name="1/3", exact=True).click()
            page.get_by_label(f"Adl — red {red_n}", exact=True).fill("2")
            page.get_by_label(f"Koeficijent — red {red_n}", exact=True).fill("1,5")
            print("[dodaj] rucni red: struktura 1/3, Adl=2, koeficijent 1,5")

            # ── 3. Negativ: 'abc' u Adl ──
            adl = page.get_by_label(f"Adl — red {red_n}", exact=True)
            adl.fill("abc")
            puts_before = len(puts)
            page.get_by_role("button", name="Sačuvaj").click()
            expect(page.get_by_text("ceo broj od 0 do 99").first).to_be_visible(timeout=15000)
            page.wait_for_timeout(800)
            assert len(puts) == puts_before, "nevalidan unos je ipak poslao PUT"
            assert adl.input_value() == "abc", "unos je prepisan umesto odbijen"
            print("[invalid] 'abc' odbijen: toast greške, bez PUT zahteva")

            # ── 4. Sačuvaj + reload ──
            adl.fill("2")
            page.get_by_role("button", name="Sačuvaj").click()
            expect(page.get_by_text("Koeficijenti su sačuvani.")).to_be_visible(timeout=15000)
            assert len(puts) == puts_before + 1 and puts[-1].status == 200
            stanje = api.get("/koeficijenti").json()
            assert len(stanje["redovi"]) == len(strukture) + 1, stanje
            rucni = next(x for x in stanje["redovi"] if x["rucno"])
            assert rucni["struktura"] == "1/3" and rucni["adl"] == 2
            assert float(rucni["koeficijent"]) == 1.5
            auto = [x for x in stanje["redovi"] if not x["rucno"]]
            assert len(auto) == len(strukture) and all(
                x["adl"] == 0 and x["chd"] == 0 and x["inf"] == 0 and float(x["koeficijent"]) == 0
                for x in auto
            )
            print(f"[save] PUT 200; API: {len(auto)} auto (nule) + 1 ručni red (1/3, Adl=2, koef=1.5)")

            page.reload(wait_until="domcontentloaded")
            expect(page.locator("table tbody tr")).to_have_count(len(strukture) + 1, timeout=15000)
            red_rucni = page.locator("table tbody tr").filter(
                has=page.get_by_role("combobox")
            )
            expect(red_rucni).to_have_count(1)
            expect(red_rucni.get_by_role("combobox")).to_have_text("1/3")
            # Inputi ručnog reda, nezavisno od pozicije posle sortiranja
            rucni_polja = red_rucni.get_by_role("textbox")
            expect(rucni_polja).to_have_count(4)
            expect(rucni_polja.nth(0)).to_have_value("2")
            expect(rucni_polja.nth(3)).to_have_value("1.5")
            print("[reload] ručni red seća: Select '1/3', Adl=2, koeficijent normalizovan na 1.5")

            # ── 5. Dirty-guard popup ──
            rucni_polja.nth(3).fill("2")
            link = page.locator('a[href="/"]').first
            link.click()
            expect(page.get_by_text("Odbaciti nesačuvane izmene?")).to_be_visible(timeout=15000)
            page.get_by_role("button", name="Otkaži").click()
            expect(page.get_by_role("combobox")).to_have_count(1, timeout=15000)
            assert "/agencija/koeficijenti" in page.url, page.url
            link.click()
            expect(page.get_by_text("Odbaciti nesačuvane izmene?")).to_be_visible(timeout=15000)
            page.get_by_role("button", name="Nastavi").click()
            page.wait_for_url(lambda u: "/agencija/koeficijenti" not in u, timeout=15000)
            print("[navigation] popup na izlasku: Otkaži ostaje na stranici, Nastavi navigira")

            assert page_errors == [], f"pageerror nije prazan: {page_errors}"
            print("[pageerror] lista prazna")
            print("PASS UI")
        finally:
            context.close()
            browser.close()
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM koeficijenti_prodaje"))
            with engine.connect() as conn:
                ostalo = conn.execute(text("SELECT COUNT(*) FROM koeficijenti_prodaje")).scalar()
            assert ostalo == 0
            print(f"[cleanup] tabela koeficijenata prazna (ostalo={ostalo})")
            api.close()


if __name__ == "__main__":
    main()
