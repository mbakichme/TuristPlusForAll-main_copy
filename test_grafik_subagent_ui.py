"""Grafik UI — popup slobodnog termina: izbor subagenta (server-side pretraga) → Klasična / Brza.

Provere:
- filteri mesto / grupa / smeštaj rade,
- popup „Slobodan termin“ nudi „Izaberi subagenta“ (pretraga na serveru),
- Klasična: subagent u URL-u (subagent=) i u polju Subagent na Rezervacijama,
- Brza: POST /rezervacije nosi subagent i nosilac.uzrast = "ADL". POST se presreće
  (route.fulfill) — NIJE upis u bazu.
"""
import json
import os
import sys
import urllib.parse

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/tmp/pw-browsers")

import httpx
from playwright.sync_api import sync_playwright, expect

from routes import create_access_token

APP = os.environ.get("TEST_APP_URL", "http://localhost:3058")
API = os.environ.get("TEST_API_URL", "http://localhost:3158/api")


def otvori_slobodan(page, izabrani: str):
    page.goto(APP + "/agencija/grafik", wait_until="domcontentloaded")
    page.get_by_role("button", name="Izaberi mesto", exact=True).click()
    page.locator("[cmdk-item]").first.click()
    expect(page.get_by_role("button", name="Izaberi grupe perioda", exact=True)).to_be_enabled(timeout=15000)
    page.get_by_role("button", name="Izaberi grupe perioda", exact=True).click()
    page.locator("label:has([role=checkbox])").first.click()  # prva grupa mesta
    page.keyboard.press("Escape")
    expect(page.get_by_role("button", name="Izaberi smeštaj", exact=True)).to_be_enabled(timeout=15000)
    page.get_by_role("button", name="Izaberi smeštaj", exact=True).click()
    page.locator("[cmdk-item]").filter(has_text="Prikaži sve").first.click()

    page.locator("div.cursor-pointer.hover\\:bg-muted\\/50").first.wait_for(timeout=20000)
    page.locator("div.cursor-pointer.hover\\:bg-muted\\/50").first.click(force=True)
    dlg = page.get_by_role("dialog").filter(has_text="Slobodan termin")
    expect(dlg).to_be_visible(timeout=10000)

    btn = dlg.get_by_role("button", name="Izaberi subagenta", exact=True)
    expect(btn).to_have_text("Bez subagenta")
    btn.click()
    page.get_by_placeholder("Pretraga…").fill(izabrani[:6])
    page.locator("[cmdk-item]").filter(has_text=izabrani[:6]).first.click()
    expect(btn).to_contain_text(izabrani[:6])
    return dlg


def main() -> int:
    token = create_access_token({"sub": "1"})  # never printed
    api = httpx.Client(base_url=API, headers={"Authorization": "Bearer " + token}, timeout=60)
    sub = api.get("/subagenti-izbor").json()
    assert sub, "nema subagenata u bazi"
    izabrani = sub[0]["naziv"]
    print(f"[ok] subagenti-izbor: {len(sub)} stavki, prva = {izabrani!r}")

    ok = True
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1400, "height": 900})
        ctx.add_init_script(f"localStorage.setItem('ta_token', {token!r});")
        page = ctx.new_page()

        # --- Klasična ---
        dlg = otvori_slobodan(page, izabrani)
        print("[ok] popup + subagent izabran")
        dlg.get_by_role("button", name="Klasična rezervacija").click()
        page.wait_for_url("**/prodaja/rezervacije**", timeout=20000)
        q = urllib.parse.parse_qs(urllib.parse.urlparse(page.url).query)
        if q.get("subagent", [""])[0] == izabrani:
            print("[ok] Klasična: URL nosi subagent")
        else:
            print(f"[FAIL] Klasična: URL subagent={q.get('subagent')}")
            ok = False
        try:
            expect(page.locator("button").filter(has_text=izabrani).first).to_be_visible(timeout=15000)
            print("[ok] Klasična: Rezervacije prikazuju subagenta")
        except AssertionError:
            print("[FAIL] Klasična: Rezervacije nisu prikazale subagenta")
            ok = False

        # --- Brza (POST presretnut, nema upisa) ---
        captured: dict = {}

        def _route(route):
            captured["body"] = json.loads(route.request.post_data or "{}")
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"kljuc": "TEST/00", "message": "presretnuto"}))

        page.route("**/api/rezervacije", _route)
        otvori_slobodan(page, izabrani)
        page.get_by_role("button", name="Brza rezervacija").click()
        expect(page.get_by_role("dialog").filter(has_text="Brza rezervacija")).to_be_visible(timeout=10000)
        page.get_by_placeholder("Ime i prezime").fill("TEST PRESRETNUTO")
        page.get_by_role("button", name="Potvrdi", exact=True).click()
        page.wait_for_timeout(800)
        body = captured.get("body")
        if not body:
            print("[FAIL] Brza: POST nije presretnut")
            ok = False
        else:
            nos = body.get("nosilac", {})
            if body.get("subagent") == izabrani:
                print("[ok] Brza: POST nosi subagent")
            else:
                print(f"[FAIL] Brza: subagent={body.get('subagent')!r}")
                ok = False
            if nos.get("uzrast") == "ADL":
                print("[ok] Brza: nosilac.uzrast = ADL")
            else:
                print(f"[FAIL] Brza: nosilac.uzrast={nos.get('uzrast')!r}")
                ok = False
        browser.close()
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
