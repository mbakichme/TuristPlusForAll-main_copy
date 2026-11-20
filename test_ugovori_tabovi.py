"""UI provera: prečica Ugovori na naslovnoj + tabovi REZERVACIJE/PREDREZERVACIJA/STORNO.

Pokretanje: PLAYWRIGHT_BROWSERS_PATH=/tmp/pw-browsers uv run python test_ugovori_tabovi.py
"""
import os
import re

from playwright.sync_api import expect, sync_playwright
from sqlalchemy import text

from db_config import get_engine
from routes import create_access_token

BASE = f"http://localhost:{os.environ.get('APP_PORT', '3062')}"
TIP = "UPPER(TRIM(COALESCE(tiprezervacije, '')))"


def ocekivano() -> dict:
    with get_engine().connect() as c:
        return {
            "predrezervacija": c.execute(text(f"SELECT COUNT(*) FROM aranzman WHERE {TIP} = 'PREDREZERVACIJA'")).scalar(),
            "storno": c.execute(text(f"SELECT COUNT(*) FROM aranzman WHERE {TIP} = 'STORNO'")).scalar(),
            "rezervacije": c.execute(text(f"SELECT COUNT(*) FROM aranzman WHERE {TIP} NOT IN ('PREDREZERVACIJA', 'STORNO')")).scalar(),
        }


def main():
    gt = ocekivano()
    token = create_access_token({"sub": "1"})
    ok = 0
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1440, "height": 900})
        ctx.add_init_script(f"localStorage.setItem('ta_token', '{token}')")
        pg = ctx.new_page()
        pg.goto(BASE + "/")

        # 1. Prečica na naslovnoj
        precica = pg.get_by_role("button", name=re.compile(r"^Ugovori"))
        expect(precica).to_be_visible(timeout=15000)
        precica.click()
        pg.wait_for_url(re.compile(r"/knjigovodstvo/ugovori"))
        ok += 1; print("OK prečica → /knjigovodstvo/ugovori")

        # 2. Tabovi i brojači
        for key, label in (("rezervacije", "REZERVACIJE"), ("predrezervacija", "PREDREZERVACIJA"), ("storno", "STORNO")):
            tab = pg.get_by_role("tab", name=re.compile(rf"^{label}"))
            expect(tab).to_contain_text(str(gt[key]), timeout=15000)
            ok += 1; print(f"OK tab {label} brojač = {gt[key]}")

        # 3. Default = REZERVACIJE, svaki tab pokazuje svoj broj redova
        expect(pg.get_by_role("tab", name=re.compile("^REZERVACIJE"))).to_have_attribute("data-state", "active")
        ok += 1; print("OK podrazumevani tab REZERVACIJE")
        for key, label in (("rezervacije", "REZERVACIJE"), ("predrezervacija", "PREDREZERVACIJA"), ("storno", "STORNO")):
            pg.get_by_role("tab", name=re.compile(rf"^{label}")).click()
            expect(pg.get_by_text(re.compile(rf"Ukupno:\s*{gt[key]}\s*zapisa"))).to_be_visible(timeout=15000)
            expect(pg.locator("tbody tr")).to_have_count(gt[key], timeout=15000)
            # podrazumevani tab ne mora biti u URL-u (klik na već aktivan tab ne menja URL)
            assert f"tab={key}" in pg.url or (key == "rezervacije" and "tab=" not in pg.url), pg.url
            ok += 1; print(f"OK {label}: {gt[key]} redova")

        # 4. Tab ostaje posle reload-a (URL)
        pg.reload()
        expect(pg.get_by_role("tab", name=re.compile("^STORNO"))).to_have_attribute("data-state", "active", timeout=15000)
        ok += 1; print("OK tab sačuvan u URL-u posle reload-a")
        b.close()
    print(f"\n{ok} provera prošlo")


if __name__ == "__main__":
    main()
