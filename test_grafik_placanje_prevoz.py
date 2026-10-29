"""Grafik popup — Način plaćanja + Prevoz se prenose u Rezervacije (UI).

Smeštaj 43 (PANORAMA 2, mesto 1), kao u test_grafik_cena_popup.py.
Provere: select-ovi u popupu (default Autobuski / bez izbora), izbor
U celosti + Sopstveni → URL Rezervacija ima placanje=u_celosti&prevoz=sopstveni,
default → URL ima prevoz=autobuski i nema placanje.
"""
import os, sys, re
from urllib.parse import urlparse, parse_qs
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from playwright.sync_api import sync_playwright
import routes

tok = routes.create_access_token({"sub": "1"})
BASE = "http://localhost:3058"
OK = []


def check(label, cond):
    OK.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + label)


def otvori_slot(pg):
    """Klik na prvo slobodno polje → popup „Slobodan termin“ (vraća dialog ili None)."""
    polja = pg.locator("table div.cursor-pointer.absolute")
    polja.first.wait_for(state="attached", timeout=20000)
    for i in range(min(polja.count(), 40)):
        cilj = polja.nth(i)
        cilj.scroll_into_view_if_needed()
        box = cilj.bounding_box()
        if not box:
            continue
        pg.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        dlg = pg.get_by_role("dialog").filter(has_text="Slobodan termin")
        try:
            dlg.wait_for(state="visible", timeout=3000)
            return dlg
        except Exception:
            continue
    return None


def izaberi(pg, dlg, aria, opcija):
    dlg.locator(f"[aria-label='{aria}']").click()
    pg.get_by_role("option", name=opcija, exact=True).click()


with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1400, "height": 900})
    pg.add_init_script(f"localStorage.setItem('ta_token', '{tok}')")
    pg.goto(f"{BASE}/agencija/grafik?mesto=1&smestaj=43")
    dlg = None
    try:
        # ---------- 1) default vrednosti u popupu ----------
        dlg = otvori_slot(pg)
        check("UI popup: otvoren (Slobodan termin)", dlg is not None)
        if dlg is None:
            raise SystemExit("popup nije otvoren")
        check("UI popup: select Način plaćanja postoji",
              dlg.locator("[aria-label='Način plaćanja']").count() == 1)
        check("UI popup: select Prevoz postoji",
              dlg.locator("[aria-label='Prevoz']").count() == 1)
        check("UI popup: Prevoz default = Autobuski",
              "Autobuski" in (dlg.locator("[aria-label='Prevoz']").inner_text() or ""))

        pg.get_by_role("button", name=re.compile("Klasična rezervacija")).click()
        pg.wait_for_url(re.compile(r"/prodaja/rezervacije"), timeout=15000)
        q = parse_qs(urlparse(pg.url).query)
        check("UI default: URL prevoz=autobuski", q.get("prevoz") == ["autobuski"])
        check("UI default: URL bez placanje parametra", "placanje" not in q)

        # ---------- 2) U celosti + Sopstveni ----------
        pg.goto(f"{BASE}/agencija/grafik?mesto=1&smestaj=43")
        dlg = otvori_slot(pg)
        check("UI popup (2): otvoren", dlg is not None)
        if dlg is None:
            raise SystemExit("popup nije otvoren")
        izaberi(pg, dlg, "Način plaćanja", "U celosti")
        izaberi(pg, dlg, "Prevoz", "Sopstveni")
        check("UI popup: Način plaćanja = U celosti",
              "U celosti" in (dlg.locator("[aria-label='Način plaćanja']").inner_text() or ""))
        check("UI popup: Prevoz = Sopstveni",
              "Sopstveni" in (dlg.locator("[aria-label='Prevoz']").inner_text() or ""))

        pg.get_by_role("button", name=re.compile("Klasična rezervacija")).click()
        pg.wait_for_url(re.compile(r"/prodaja/rezervacije"), timeout=15000)
        q = parse_qs(urlparse(pg.url).query)
        check("UI izbor: URL placanje=u_celosti", q.get("placanje") == ["u_celosti"])
        check("UI izbor: URL prevoz=sopstveni", q.get("prevoz") == ["sopstveni"])
    finally:
        b.close()

print(f"\n{sum(OK)}/{len(OK)} provera prošlo")
sys.exit(0 if all(OK) else 1)
