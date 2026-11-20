"""Playwright UI test — provizija subagenta u novoj rezervaciji.

Flow:
  1. API čita proviziju subagenta "2T" iz tabele subagenti (očekivano 15).
  2. UI /prodaja/rezervacije?novi=1 → dugme Subagent (Aranžman tab) → izbor "2T".
  3. Bez popusta i bez popularnog smeštaja, polje procenta provizije smeštaja
     mora dobiti vrednost provizije subagenta.
  Nema upisa u bazu (nova rezervacija se ne snima).
"""
import json
import os
import re
import sys

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/tmp/pw-browsers")

import httpx
from playwright.sync_api import expect, sync_playwright

from routes import create_access_token

APP = os.environ.get("TEST_APP_URL", "http://localhost:3058")
API = os.environ.get("TEST_API_URL", "http://127.0.0.1:3158/api")
SUBAGENT = "2T"


def main():
    token = create_access_token({"sub": "1"})  # never printed
    api = httpx.Client(base_url=API, headers={"Authorization": "Bearer " + token}, timeout=30)
    ok = True

    rows = api.get("/subagenti", params={"search": SUBAGENT, "page_size": "100"}).json()["rows"]
    ocekivano = next((r["provizija"] for r in rows if (r.get("naziv") or "").strip() == SUBAGENT), None)
    if ocekivano is None:
        print(f"  FAIL subagent {SUBAGENT!r} nije nađen u tabeli subagenti")
        sys.exit(1)
    ocekivano_str = str(int(ocekivano)) if float(ocekivano).is_integer() else str(ocekivano)
    print(f"[api] provizija subagenta {SUBAGENT!r} = {ocekivano_str}")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = browser.new_context()
            context.add_init_script(f"localStorage.setItem('ta_token', {json.dumps(token)});")
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"{APP}/prodaja/rezervacije?novi=1", wait_until="domcontentloaded")

            # dugme Subagent u kartici Ugovor (Aranžman tab)
            page.get_by_role("button", name="Izaberite subagenta", exact=True).click()
            pretraga = page.get_by_placeholder("Naziv, mesto, osoba…")
            pretraga.fill(SUBAGENT)
            page.get_by_role("option", name=SUBAGENT, exact=True).click()
            print(f"[ui] izabran subagent {SUBAGENT}")

            # tab Obračun: polje procenta provizije smeštaja
            page.get_by_role("tab", name=re.compile("Obračun")).click()
            pct = page.get_by_test_id("provizija-smestaj-pct")
            expect(pct).to_have_value(ocekivano_str, timeout=10000)
            print(f"[ui] provizija smeštaja = {pct.input_value()}")

            errors = [e for e in errors if "WebSocket" not in e]  # Vite HMR šum
            if errors:
                ok = False
                print("  FAIL page errors:", errors[:3])
            browser.close()
    except Exception as e:
        ok = False
        print("  FAIL:", repr(e))

    print("\nREZULTAT:", "SVE PROVERE PROŠLE" if ok else "IMA GREŠAKA")


if __name__ == "__main__":
    main()
