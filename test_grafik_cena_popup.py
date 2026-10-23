"""Grafik — cena u popupu slobodnog termina + blokirane cene (API + UI).

Smeštaj 43 (PANORAMA 2, mesto 1, grupa 16), cenovnik 314, period 83 (23.05–30.05).
Privremeno se blokira realna soba 251 za period 83 (eksplicitan red u opcije_soba),
a na kraju se red briše.
"""
import os, sys, re
from urllib.parse import urlparse, parse_qs
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import httpx
from sqlalchemy import text
from playwright.sync_api import sync_playwright
import routes
import db_config

tok = routes.create_access_token({"sub": "1"})
BASE = "http://localhost:3058"
API = "http://localhost:3158/api"
CEN, PER, SOBA = 314, 83, 251
OK = []


def check(label, cond):
    OK.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + label)


def nadji_blok(node, out):
    """Rekurzivno skuplja dict-ove koji imaju soba_id + blokirano."""
    if isinstance(node, dict):
        if "soba_id" in node and "blokirano" in node:
            out.append(node)
        for v in node.values():
            nadji_blok(v, out)
    elif isinstance(node, list):
        for v in node:
            nadji_blok(v, out)
    return out


def postavi_blok(vrednost):
    eng = db_config.get_engine()
    with eng.begin() as c:
        c.execute(text(
            "INSERT INTO opcije_soba (cenovnik_id, soba_id, period_id, blokirano) "
            "VALUES (:c, :s, :p, :b) "
            "ON CONFLICT (cenovnik_id, soba_id, period_id) DO UPDATE SET blokirano = EXCLUDED.blokirano"
        ), {"c": CEN, "s": SOBA, "p": PER, "b": vrednost})


def obrisi_blok():
    eng = db_config.get_engine()
    with eng.begin() as c:
        c.execute(text(
            "DELETE FROM opcije_soba WHERE cenovnik_id=:c AND soba_id=:s AND period_id=:p"
        ), {"c": CEN, "s": SOBA, "p": PER})


H = {"Authorization": f"Bearer {tok}"}
params = {"grupa_id": 16, "mesto_id": 1, "smestaj_id": 43}

try:
    # ---------- API: blokirano flag u cene ----------
    postavi_blok(True)
    r = httpx.get(f"{API}/grafik", params=params, headers=H, timeout=60)
    check("API /grafik vraca 200", r.status_code == 200)
    blokovi = nadji_blok(r.json(), [])
    mine = [b for b in blokovi if int(b["soba_id"]) == SOBA]
    check("API: cena sobe 251 ima blokirano polje", len(mine) > 0)
    check("API: sobe 251 je blokirano=true (eksplicitan period)",
          any(b["blokirano"] is True for b in mine))

    postavi_blok(False)
    r = httpx.get(f"{API}/grafik", params=params, headers=H, timeout=60)
    mine = [b for b in nadji_blok(r.json(), []) if int(b["soba_id"]) == SOBA]
    check("API: posle odblokiranja blokirano=false",
          mine and all(b["blokirano"] is False for b in mine))

    postavi_blok(True)

    # ---------- UI ----------
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1400, "height": 900})
        pg.add_init_script(f"localStorage.setItem('ta_token', '{tok}')")
        pg.goto(f"{BASE}/agencija/grafik?mesto=1&smestaj=43")
        polja = pg.locator("table div.cursor-pointer.absolute")
        polja.first.wait_for(state="attached", timeout=20000)
        n = polja.count()
        check("UI: ima slobodnih polja", n > 0)

        nasao_blok_tooltip = False
        nasao_blok_radio = False
        klasicna_ok = False

        for i in range(min(n, 40)):
            cilj = polja.nth(i)
            cilj.scroll_into_view_if_needed()
            box = cilj.bounding_box()
            if not box:
                continue
            # tooltip (hover) — blokirane cene moraju biti označene, ne prikazane kao cena
            pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            tip = pg.locator("div.fixed", has_text="Slobodno")
            try:
                tip.first.wait_for(state="visible", timeout=1500)
                tekst = tip.first.inner_text()
                if "blokirano" in tekst:
                    nasao_blok_tooltip = True
            except Exception:
                pass

            # klik → popup
            pg.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            dlg = pg.get_by_role("dialog").filter(has_text="Slobodan termin")
            try:
                dlg.wait_for(state="visible", timeout=3000)
            except Exception:
                continue
            radio = dlg.get_by_role("radio")
            if radio.count() == 0:
                pg.keyboard.press("Escape")
                pg.wait_for_timeout(150)
                continue

            blok = dlg.get_by_role("radio", name=re.compile("blokirano"))
            if blok.count() > 0:
                nasao_blok_radio = True
                check("UI popup: blokirana opcija je disabled", blok.first.is_disabled())
                check("UI popup: blokirana opcija nije izabrana (aria-checked=false)",
                      blok.first.get_attribute("aria-checked") == "false")

            # izaberi prvu dostupnu cenu, pa Klasična
            enabled = [r_ for r_ in radio.all() if r_.is_enabled()]
            if enabled:
                enabled[0].click()
                check("UI popup: izabrana cena dobija aria-checked=true",
                      enabled[0].get_attribute("aria-checked") == "true")
                pg.get_by_role("button", name=re.compile("Klasična rezervacija")).click()
                pg.wait_for_url(re.compile(r"/prodaja/rezervacije"), timeout=15000)
                q = parse_qs(urlparse(pg.url).query)
                check("UI Klasična: URL ima cena parametar", "cena" in q)
                check("UI Klasična: URL ima soba parametar", "soba" in q and q["soba"][0].isdigit())
                klasicna_ok = True
                break

            pg.keyboard.press("Escape")
            pg.wait_for_timeout(150)

        check("UI tooltip: blokirana cena se označava u tooltipu", nasao_blok_tooltip)
        check("UI popup: pronađen slot sa blokiranom opcijom", nasao_blok_radio)
        check("UI Klasična prenosi cenu u Rezervacije", klasicna_ok)

        b.close()
finally:
    obrisi_blok()

print(f"\n{sum(OK)}/{len(OK)} provera prošlo")
sys.exit(0 if all(OK) else 1)
