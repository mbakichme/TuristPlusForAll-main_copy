"""Cenovnici — zaključavanje polja posle čuvanja (tab Kreiranje cenovnika).

Tok: kreiraj cenovnik → unesi cene → „Sačuvaj cenovnik“ → polja (cene +
Aktivan od/do) su ZAKLJUČANA, dugme „Izmeni cenovnik“ se pojavljuje → klik
na „Izmeni cenovnik“ → polja za unos cena su OTKLJUČANA.

Cleanup: briše kreirani cenovnik direktno iz baze (cenovnik_cene/cenovnik_opcije
imaju ON DELETE CASCADE).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/tmp/pw-browsers")
from playwright.sync_api import sync_playwright, expect
from sqlalchemy import create_engine, text
import db_config
import routes

BASE = "http://localhost:3058"
eng = db_config.get_engine()
cid = None

def proveri(naziv, uslov, detalj=""):
    print(f"{'PASS' if uslov else 'FAIL'} {naziv}" + (f" — {detalj}" if detalj and not uslov else ""))
    if not uslov:
        sys.exit(1)

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(f"{BASE}/agencija/cenovnici")
    pg.evaluate("t => localStorage.setItem('ta_token', t)", routes.create_access_token({"sub": "1"}))
    pg.goto(f"{BASE}/agencija/cenovnici")
    pg.wait_for_selector("[role=tablist]")

    # izbor aranžmana: Hanioti → prva grupa → DIMITRA (jedinstven naziv)
    pg.get_by_role("combobox").nth(0).click()
    pg.get_by_role("option", name="Hanioti").first.click()
    pg.get_by_role("combobox").nth(1).click()
    pg.get_by_role("option").filter(has_text="Kasandra: termini").first.click()
    pg.get_by_role("combobox").nth(2).click()
    pg.get_by_role("option", name="DIMITRA").first.click()
    pg.get_by_role("button", name="Kreiraj cenovnik").click()
    expect(pg.get_by_role("textbox").first).to_be_visible(timeout=15000)  # šablon učitan

    # polja otključana pre čuvanja; dugme Izmeni ne postoji
    box = pg.get_by_role("textbox").first
    expect(box).to_be_enabled()
    proveri("pre čuvanja: polja otključana, bez dugmeta Izmeni",
            pg.get_by_role("button", name="Izmeni cenovnik").count() == 0)

    # unesi cenu u prvu ćeliju
    box.fill("150")

    # Aktivan od / Aktivan do (kalendar: 10. i 20. dan u mreži istog meseca)
    for trg, idx in (("create-od", 10), ("create-do", 15)):
        pg.locator(f"#{trg}").click()
        kal = pg.locator("[data-radix-popper-content-wrapper]").last
        kal.get_by_role("gridcell").get_by_role("button").nth(idx).click()
        pg.wait_for_timeout(200)

    # Sačuvaj → hvataj POST odgovor radi cleanup-a
    with pg.expect_response(lambda r: r.url.rstrip("/").endswith("/api/cenovnici") and r.request.method == "POST") as ri:
        pg.get_by_role("button", name="Sačuvaj cenovnik").click()
    cid = ri.value.json()["id"]
    expect(pg.get_by_text("Cenovnik je kreiran")).to_be_visible(timeout=10000)

    # zaključano: badge, disabled polja, dugme Izmeni vidljivo, Save disabled
    expect(pg.get_by_text("Zaključano")).to_be_visible()
    expect(box).to_be_disabled()
    proveri("posle čuvanja: cene zaključane (disabled)", True)
    for trg in ("create-od", "create-do"):
        proveri(f"posle čuvanja: {trg} zaključan",
                pg.locator(f"#{trg}").is_disabled())
    izm = pg.get_by_role("button", name="Izmeni cenovnik")
    expect(izm).to_be_visible()
    proveri("posle čuvanja: dugme Izmeni cenovnik vidljivo", True)
    proveri("posle čuvanja: Sačuvaj disabled",
            pg.get_by_role("button", name="Sačuvaj cenovnik").is_disabled())

    # Izmeni cenovnik → otključano
    izm.click()
    expect(pg.get_by_text("Polja za unos cena su otključana")).to_be_visible(timeout=10000)
    expect(box).to_be_enabled()
    proveri("posle Izmeni: cene otključane", True)
    proveri("posle Izmeni: badge Zaključano nestao", pg.get_by_text("Zaključano").count() == 0)
    proveri("posle Izmeni: dugme Izmeni nestalo", pg.get_by_role("button", name="Izmeni cenovnik").count() == 0)
    proveri("posle Izmeni: Sačuvaj enabled",
            not pg.get_by_role("button", name="Sačuvaj cenovnik").is_disabled())

    assert errs == [], errs
    print("PASS UI — zaključavanje/otključavanje radi")
    b.close()

if cid:
    with eng.connect() as c:
        c.execute(text("DELETE FROM cenovnici WHERE id = :i"), {"i": cid})
        c.commit()
    print(f"[cleanup] cenovnik {cid} obrisan")
