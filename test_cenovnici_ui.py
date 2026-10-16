"""Playwright UI test — Cenovnici page (UI only; no source changes).

Flow:
  1. Cascade select Hanioti → Kasandra: termini (grupa 6) → ELENI 2, load template,
     inspect room/period grid.
  2. Enter 125,50 in the first cell, active 2026-01-01..2026-12-31, save,
     capture the newly created id from the POST response.
  3. Switch to the edit tab (verify the just-created row is visible before any
     search change), search by UUID, open the editor, confirm 125.50.
  4. Change price to 150, save, verify API value and that the UUID is unchanged,
     then verify the first tab state is synchronized.
  5. Negative: '-100' save is rejected (error toast, no save request, API value
     unchanged, input not silently rewritten).

Cleanup: deletes only the cenovnik it created.
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
MESTO_ID, GRUPA_ID, SMESTAJ_ID = 1, 6, 10  # Hanioti / Kasandra: termini / ELENI 2
DATUM_OD, DATUM_DO = "2026-01-01", "2026-12-31"


def fmt_iso(iso: str) -> str:
    y, m, d = iso[:10].split("-")
    return f"{d}.{m}.{y}"


def pick(page, trigger, option_text):
    trigger.click()
    page.get_by_role("option", name=option_text, exact=True).click()


def pick_date(page, selector, iso):
    page.locator(selector).click()
    calendar = page.locator('[data-radix-popper-content-wrapper]')
    dropdowns = calendar.locator("select")
    dropdowns.nth(1).select_option(iso[:4])
    dropdowns.nth(0).select_option(str(int(iso[5:7]) - 1))
    dan = calendar.locator(f'button[data-day="{int(iso[5:7])}/{int(iso[8:10])}/{iso[:4]}"]')
    dan.wait_for(state="attached", timeout=10000)
    page.wait_for_timeout(250)  # sačekaj da day-picker završi re-render (dva select naviga­cije)
    dan.click(force=True)
    expect(page.locator(selector)).to_have_text(fmt_iso(iso))


def main():
    token = create_access_token({"sub": "1"})  # never printed
    api = httpx.Client(base_url=API, headers={"Authorization": "Bearer " + token}, timeout=30)
    engine = get_engine()
    created_id = None
    page_errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context()
        context.add_init_script(f"localStorage.setItem('ta_token', {json.dumps(token)});")
        page = context.new_page()
        page.on("pageerror", lambda e: page_errors.append(str(e)))
        put_saves = []
        page.on(
            "response",
            lambda r: put_saves.append(r)
            if r.request.method == "PUT" and "/api/cenovnici" in r.url
            else None,
        )
        panel = page.locator('[role="tabpanel"]')
        try:
            # ── Reference combo via API (must be valid before UI steps) ──
            combo = {"mesto_id": MESTO_ID, "grupa_id": GRUPA_ID, "smestaj_id": SMESTAJ_ID}
            r = api.get("/cenovnici/sablon", params=combo)
            assert r.status_code == 200, r.text
            draft = r.json()
            soba0, per0 = draft["sobe"][0], draft["periodi"][0]
            naziv = draft["naziv"]
            cell_label = (
                f"Cena — soba {soba0['broj_sobe']}, period "
                f"{fmt_iso(per0['datum_od'])}–{fmt_iso(per0['datum_do'])}"
            )
            n_cells = len(draft["sobe"]) * len(draft["periodi"])
            print(f"[combo] {naziv}: {len(draft['sobe'])} sobe x {len(draft['periodi'])} perioda = {n_cells} celija")

            # ── Tab 1: cascade select → template grid ──
            page.goto(APP + "/agencija/cenovnici", wait_until="domcontentloaded")
            expect(panel.get_by_role("combobox")).to_have_count(3, timeout=15000)
            pick(page, panel.get_by_role("combobox").nth(0), "Hanioti")
            grupa_trigger = panel.get_by_role("combobox").nth(1)
            expect(grupa_trigger).to_be_enabled()
            pick(page, grupa_trigger, "Kasandra: termini")
            smestaj_trigger = panel.get_by_role("combobox").nth(2)
            expect(smestaj_trigger).to_be_enabled()
            pick(page, smestaj_trigger, "ELENI 2")

            panel.get_by_role("button", name="Kreiraj cenovnik").click()
            first_cell = page.get_by_label(cell_label, exact=True)
            expect(first_cell).to_be_visible(timeout=15000)
            assert page.locator('input[aria-label^="Cena"]').count() == n_cells, "grid size mismatch"
            header = page.locator("table thead th").nth(2)
            expect(header.get_by_text(fmt_iso(per0['datum_od'])[:5], exact=True)).to_be_visible()
            expect(header.get_by_text(fmt_iso(per0['datum_do'])[:5], exact=True)).to_be_visible()
            first_row = page.locator("table tbody tr").first
            expect(first_row.locator("td").first).to_have_text(soba0["broj_sobe"])
            print(f"[grid] soba {soba0['broj_sobe']} x period {per0['datum_od']}..{per0['datum_do']} prikazani, {n_cells} inputa")

            # ── Enter price + active dates, save, capture POST ──
            first_cell.fill("125,50")
            page.locator('a[href="/"]').first.click()
            popup = page.get_by_role("alertdialog")
            expect(popup).to_be_visible()
            expect(popup.get_by_text("Odbaciti nesačuvane izmene?")).to_be_visible()
            popup.get_by_role("button", name="Otkaži").click()
            expect(popup).not_to_be_visible()
            expect(first_cell).to_have_value("125.50")
            print("[navigation] popup shown; cancel preserves draft and current page")
            pick_date(page, "#create-od", DATUM_OD)
            pick_date(page, "#create-do", DATUM_DO)
            with page.expect_response(
                lambda r: r.request.method == "POST" and r.url.endswith("/api/cenovnici")
            ) as resp_info:
                panel.get_by_role("button", name="Sačuvaj cenovnik").click()
            created = resp_info.value
            assert created.status == 201, (created.status, created.text())
            detail = created.json()
            created_id, cuuid = detail["id"], detail["uuid"]
            expect(page.get_by_text(f"#{created_id} · {cuuid}", exact=True)).to_be_visible()
            print(f"[create] POST 201, id={created_id}, uuid={cuuid}")

            got = api.get(f"/cenovnici/{created_id}").json()
            cena0 = next(
                c for c in got["cene"] if c["soba_id"] == soba0["id"] and c["period_id"] == per0["id"]
            )
            assert cena0["cena"] == "125.50", cena0
            assert got["uuid"] == cuuid
            print("[api] posle kreiranja: cena=", cena0["cena"])

            # ── Tab 2: verify created row visible BEFORE touching search ──
            page.get_by_role("tab", name="Izmena kreiranih cenovnika").click()
            expect(page.get_by_text(cuuid, exact=True)).to_be_visible(timeout=15000)
            print("[tab2] novi cenovnik vidljiv u listi pre pretrage")

            page.get_by_label("Pretraga cenovnika").fill(cuuid)
            rows = page.get_by_role("row").filter(has_text=cuuid)
            expect(rows).to_have_count(1)
            print("[tab2] pretraga po UUID: 1 red")

            # ── Edit: load editor below list, confirm 125.50 ──
            rows.get_by_role("button", name=f"Izmeni cenovnik {naziv}").click()
            expect(page.locator("#edit-od")).to_be_visible(timeout=15000)
            edit_cell = page.get_by_label(cell_label, exact=True)
            expect(edit_cell).to_have_value("125.50")
            expect(page.get_by_text(f"#{created_id} · {cuuid}", exact=True)).to_be_visible()
            print("[edit] editor ucitan, prva celija = 125.50")
            assert edit_cell.is_disabled(), "cenovnik treba biti zakljucan na startu"
            page.get_by_role("button", name="Izmeni cenovnik", exact=True).click()
            page.wait_for_timeout(300)

            # ── Change price to 150, save, verify API + same UUID ──
            edit_cell.fill("150")
            with page.expect_response(
                lambda r: r.request.method == "PUT" and r.url.endswith(f"/api/cenovnici/{created_id}")
            ) as resp_info:
                panel.get_by_role("button", name="Sačuvaj izmene").click()
            updated = resp_info.value
            assert updated.status == 200, (updated.status, updated.text())
            assert updated.json()["uuid"] == cuuid, "UUID se smeo promeniti"
            got = api.get(f"/cenovnici/{created_id}").json()
            cena0 = next(
                c for c in got["cene"] if c["soba_id"] == soba0["id"] and c["period_id"] == per0["id"]
            )
            assert cena0["cena"] == "150.00", cena0
            expect(page.get_by_text(f"#{created_id} · {cuuid}", exact=True)).to_be_visible()
            print(f"[edit] PUT 200, ista uuid, API cena = {cena0['cena']}")

            # ── Negativan unos u editoru izmene: '-100' odbijen klijentskom validacijom ──
            # (posle uspešnog PUT-a editor je ponovo zaključan — prvo otključati)
            page.get_by_role("button", name="Izmeni cenovnik", exact=True).click()
            page.wait_for_timeout(300)
            puts_before = len(put_saves)
            edit_cell.fill("-100")
            panel.get_by_role("button", name="Sačuvaj izmene").click()
            expect(
                page.get_by_text("Cena mora biti nenegativan broj").first
            ).to_be_visible(timeout=15000)
            page.wait_for_timeout(800)
            assert len(put_saves) == puts_before, f"salvanje je ipak poslalo PUT: {[r.url for r in put_saves]}"
            assert edit_cell.input_value() == "-100", "vrednost je prepisana umesto odbijena"
            got = api.get(f"/cenovnici/{created_id}").json()
            cena0 = next(
                c for c in got["cene"] if c["soba_id"] == soba0["id"] and c["period_id"] == per0["id"]
            )
            assert cena0["cena"] == "150.00", cena0
            print(f"[invalid] '-100' odbijen: toast greske, bez PUT zahteva, API cena ostala {cena0['cena']}")

            # ── Tab 1: povratak na Kreiranje — draft je tiho resetovan ──
            page.get_by_role("tab", name="Kreiranje cenovnika").click()
            expect(page.get_by_role("button", name="Kreiraj cenovnik")).to_be_visible(timeout=15000)
            assert page.locator("#create-od").count() == 0, "draft kreacije treba biti resetovan"
            print("[tab1] povratak: kreacija resetovana (izbori mesta/grupe/smeštaja ostaju)")

            assert page_errors == [], f"pageerror nije prazan: {page_errors}"
            print("[pageerror] lista prazna")
            print("PASS UI")
        finally:
            context.close()
            browser.close()
            if created_id is not None:
                with engine.begin() as conn:
                    conn.execute(text("DELETE FROM cenovnici WHERE id = :id"), {"id": created_id})
                with engine.connect() as conn:
                    ostalo = conn.execute(
                        text("SELECT COUNT(*) FROM cenovnici WHERE id = :id"), {"id": created_id}
                    ).scalar()
                assert ostalo == 0
                print(f"[cleanup] obrisan cenovnik id={created_id} (ostalo={ostalo})")
            api.close()


if __name__ == "__main__":
    main()
