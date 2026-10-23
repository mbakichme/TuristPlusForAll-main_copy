"""Grafik — tooltip cene praznog polja (UI).

Prelazak mišem preko slobodnog polja → lebdeći prikaz „Slobodno … Cena …" se pojavi;
kad kursor napusti polje, prikaz mora da nestane (bez zadržavanja).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from playwright.sync_api import sync_playwright
import routes

tok = routes.create_access_token({"sub": "1"})
BASE = "http://localhost:3058"
OK = []


def check(label, cond):
    OK.append(cond)
    print(("PASS " if cond else "FAIL ") + label)


with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1400, "height": 900})
    pg.add_init_script(f"localStorage.setItem('ta_token', '{tok}')")
    pg.goto(f"{BASE}/agencija/grafik?mesto=1&smestaj=41")  # DELTA, grupa 16
    polja = pg.locator("table div.cursor-pointer.absolute")
    polja.first.wait_for(state="attached", timeout=20000)
    check("ima slobodnih polja u grafiku", polja.count() > 0)

    tip = pg.locator("div.fixed", has_text="Slobodno")
    check("tooltip nije vidljiv pre hover-a", tip.count() == 0)

    cilj = polja.first
    cilj.scroll_into_view_if_needed()
    box = cilj.bounding_box()
    pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    pg.mouse.move(box["x"] + box["width"] / 2 + 2, box["y"] + box["height"] / 2 + 1)
    tip.first.wait_for(state="visible", timeout=3000)
    check("tooltip se pojavi na hover", tip.count() == 1)
    tekst = tip.first.inner_text()
    check("tooltip ima naslov Soba + period", "Soba" in tekst and "–" in tekst)
    check("tooltip ima sekciju Cena ili napomenu", "Cena" in tekst or "cenovnika" in tekst or "cenu" in tekst)

    pg.mouse.move(5, 5)  # napušta polje i tabelu
    pg.wait_for_timeout(200)
    check("tooltip nestane kad kursor napusti polje", pg.locator("div.fixed", has_text="Slobodno").count() == 0)

    b.close()

print(f"\n{sum(OK)}/{len(OK)} provera prošlo")
sys.exit(0 if all(OK) else 1)
