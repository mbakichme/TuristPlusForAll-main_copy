"""UI provera: Opis sobe (sobe.opis) u „Boravak i smeštaj“ + opis/tip sobe u zaglavlju „Ugovor“.

Pokretanje: PLAYWRIGHT_BROWSERS_PATH=/tmp/pw-browsers uv run python test_rez_opis_sobe.py
Ništa se ne čuva — soba se menja samo u formi, bez klika na Sačuvaj.
"""
import os
import re

from playwright.sync_api import expect, sync_playwright
from sqlalchemy import text

from db_config import get_engine
from routes import create_access_token

BASE = f"http://localhost:{os.environ.get('APP_PORT', '3062')}"


def ugovor_sa_sobom():
    """Ugovor čija soba postoji u šifarniku + druga soba istog smeštaja sa drugačijim opisom."""
    with get_engine().connect() as c:
        r = c.execute(text("""
            SELECT a.kljuc, s.id AS smestaj_id, b.broj_sobe, b.opis, b.tip
            FROM aranzman a
            JOIN smestaj s ON lower(trim(s.naziv)) = lower(trim(a.naziv))
            JOIN sobe b ON b.veza_id_smestaj = s.id AND lower(trim(b.broj_sobe)) = lower(trim(a.soba))
            WHERE COALESCE(trim(b.opis), '') <> '' AND COALESCE(trim(b.tip), '') <> ''
              AND UPPER(TRIM(COALESCE(a.tiprezervacije, ''))) <> 'STORNO'
              AND EXISTS (SELECT 1 FROM sobe x WHERE x.veza_id_smestaj = s.id
                          AND COALESCE(trim(x.opis), '') NOT IN ('', trim(b.opis)))
            ORDER BY a.id LIMIT 1
        """)).mappings().first()
        druga = c.execute(text("""
            SELECT broj_sobe, opis, tip FROM sobe
            WHERE veza_id_smestaj = :s AND COALESCE(trim(opis), '') NOT IN ('', :o)
            ORDER BY id LIMIT 1
        """), {"s": r["smestaj_id"], "o": r["opis"].strip()}).mappings().first()
    return r, druga


def main():
    u, druga = ugovor_sa_sobom()
    print(f"Ugovor {u['kljuc']}: soba {u['broj_sobe']} / {u['opis']} / {u['tip']}; druga soba {druga['broj_sobe']} / {druga['opis']}")
    token = create_access_token({"sub": "1"})
    ok = 0
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1600, "height": 1000})
        ctx.add_init_script(f"localStorage.setItem('ta_token', '{token}')")
        pg = ctx.new_page()
        pg.goto(f"{BASE}/prodaja/rezervacije?u={u['kljuc']}")

        # 1. Zaglavlje „Ugovor“: broj sobe · opis · tip
        zaglavlje = pg.get_by_label("Pregled učitanog ugovora")
        segment = f"{u['broj_sobe'].strip()} · {u['opis'].strip()} · {u['tip'].strip()}"
        expect(zaglavlje).to_contain_text(segment, timeout=20000)
        ok += 1; print(f"OK zaglavlje sadrži „{segment}“")

        # 2. Opis sobe u Boravak i smeštaj — samo za čitanje, vrednost iz sobe.opis
        opis = pg.get_by_test_id("opis-sobe")
        expect(opis).to_have_value(u["opis"].strip(), timeout=10000)
        expect(opis).to_have_attribute("readonly", "")
        ok += 1; print("OK Opis sobe = sobe.opis, readonly")

        # 3. Promena sobe → opis prati izbor (bez čuvanja)
        pg.get_by_role("button", name="Izmeni").first.click()
        pg.get_by_role("button", name="Otključaj").click()
        soba_fld = pg.locator("div.space-y-1\\.5", has=pg.get_by_text("Soba", exact=True))
        soba_fld.get_by_role("combobox").click()
        pg.get_by_role("option", name=re.compile(rf"^{re.escape(druga['broj_sobe'].strip())}\b")).first.click()
        expect(opis).to_have_value(druga["opis"].strip(), timeout=5000)
        ok += 1; print(f"OK posle promene sobe opis = „{druga['opis'].strip()}“")

        # 4. Zaglavlje i dalje prikazuje sačuvanu sobu ugovora
        expect(zaglavlje).to_contain_text(segment)
        ok += 1; print("OK zaglavlje ostaje na sačuvanoj sobi")
        b.close()
    print(f"\n{ok} provera prošlo")


if __name__ == "__main__":
    main()
