"""UI provera: zaglavlje Obračuna „Broj sobe: X | Struktura: Y | Tip: Z“ + dugme PROVERI OBRAČUN.

Pokretanje: PLAYWRIGHT_BROWSERS_PATH=/tmp/pw-browsers uv run python test_rez_obracun_zaglavlje.py
Ništa se ne čuva.
"""
import os

from playwright.sync_api import expect, sync_playwright
from sqlalchemy import text

from db_config import get_engine
from routes import create_access_token

BASE = f"http://localhost:{os.environ.get('APP_PORT', '3062')}"


def ugovor_sa_sobom():
    with get_engine().connect() as c:
        return c.execute(text("""
            SELECT a.kljuc, b.broj_sobe, b.tip, b.opis
            FROM aranzman a
            JOIN smestaj s ON lower(trim(s.naziv)) = lower(trim(a.naziv))
            JOIN sobe b ON b.veza_id_smestaj = s.id AND lower(trim(b.broj_sobe)) = lower(trim(a.soba))
            WHERE COALESCE(trim(b.tip), '') <> '' AND COALESCE(trim(b.opis), '') <> ''
              AND UPPER(TRIM(COALESCE(a.tiprezervacije, ''))) <> 'STORNO'
            ORDER BY a.id LIMIT 1
        """)).mappings().first()


def main():
    u = ugovor_sa_sobom()
    token = create_access_token({"sub": "1"})
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1600, "height": 1000})
        ctx.add_init_script(f"localStorage.setItem('ta_token', '{token}')")
        pg = ctx.new_page()
        pg.goto(f"{BASE}/prodaja/rezervacije?u={u['kljuc']}")
        expect(pg.get_by_label("Pregled učitanog ugovora")).to_contain_text(u["broj_sobe"].strip(), timeout=20000)
        pg.get_by_role("tab", name="Obračun").click()
        zaglavlje = pg.get_by_text("Broj sobe:", exact=False).first.locator("..")
        tekst = zaglavlje.inner_text()
        print("Zaglavlje:", tekst)
        assert "Broj sobe:" in tekst and "Struktura:" in tekst and "Tip:" in tekst, tekst
        assert u["tip"].strip() in tekst, tekst
        assert u["opis"].strip() in tekst, tekst
        print("OK format i sadržaj zaglavlja")
        expect(pg.get_by_role("button", name="PROVERI OBRAČUN")).to_be_visible()
        print("OK dugme PROVERI OBRAČUN vidljivo")
        b.close()


if __name__ == "__main__":
    main()
