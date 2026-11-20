"""Navigacija — mobilna verzija + clipping sekcija (max-h vs sadržaj).

Provere:
  1. Desktop: sekcije Agencija / Knjigovodstvo / Podešavanja / Pregledi —
     svaka expander div mora imati scrollHeight <= clientHeight (bez šišanja).
  2. Mobilni drawer (390×844): hamburger otvara panel; Agencija sadrži
     linkove „Cenovnici“ i „Koeficijenti prodaje“ (vidljivi); sekcije bez šišanja.
"""
import json
import os
import sys

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/tmp/pw-browsers")

from playwright.sync_api import sync_playwright

from routes import create_access_token

APP = os.environ.get("TEST_APP_URL", "http://localhost:3058")

MEASURE = """
() => Array.from(document.querySelectorAll('div.overflow-hidden'))
  .map(d => {
    const cs = getComputedStyle(d);
    return { max: cs.maxHeight, content: d.scrollHeight, visible: d.clientHeight };
  })
  .filter(x => x.max !== '0px' && x.max !== 'none' && x.content > 0)
"""

def proveri(page, label: str) -> bool:
    rows = page.evaluate(MEASURE)
    ok = True
    print(f"--- {label} ---")
    for r in rows:
        clipped = r["content"] > r["visible"] + 1
        if clipped:
            ok = False
        print(f"  max={r['max']:>9}  sadrzaj={r['content']:>4}  vidljivo={r['visible']:>4}  {'<< SHISENO' if clipped else 'ok'}")
    return ok

def expand(page, name: str) -> None:
    page.get_by_role("button", name=name, exact=True).click()
    page.wait_for_timeout(400)  # transition 200ms

def main() -> None:
    token = create_access_token({"sub": "1"})  # never printed
    neuspeh = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])

        # ── Desktop ──
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        ctx.add_init_script(f"localStorage.setItem('ta_token', {json.dumps(token)});")
        page = ctx.new_page()
        page.goto(APP + "/", wait_until="domcontentloaded")
        page.get_by_role("button", name="Agencija", exact=True).wait_for(timeout=15000)
        for sek in ["Agencija", "Prodaja", "Knjigovodstvo", "Pregledi", "Podešavanja"]:
            expand(page, sek)
        if not proveri(page, "DESKTOP sve sekcije otvorene"):
            neuspeh.append("desktop clipping")
        # sanity: desktop ima Cenovnici i Koeficijenti
        for lbl in ["Cenovnici", "Koeficijenti prodaje"]:
            page.get_by_role("link", name=lbl, exact=True).wait_for(timeout=5000)
        ctx.close()

        # ── Mobilni (iPhone klasa) ──
        ctx = browser.new_context(viewport={"width": 390, "height": 844})
        ctx.add_init_script(f"localStorage.setItem('ta_token', {json.dumps(token)});")
        page = ctx.new_page()
        page.goto(APP + "/", wait_until="domcontentloaded")
        hamburger = page.locator("button:has(svg.lucide-menu)")
        hamburger.first.wait_for(timeout=15000)
        hamburger.first.click()
        panel = page.locator("aside.fixed.inset-y-0.left-0")
        panel.wait_for(timeout=5000)

        # Agencija: linkovi Cenovnici + Koeficijenti prodaje moraju postojati i biti vidljivi
        expand(page, "Agencija")
        for lbl in ["Cenovnici", "Koeficijenti prodaje"]:
            lnk = panel.get_by_role("link", name=lbl, exact=True)
            if lnk.count() != 1 or not lnk.first.is_visible():
                neuspeh.append(f"mobilno: link '{lbl}' nedostaje / nevidljiv")
                print(f"  [mobilno] link '{lbl}': count={lnk.count()} visible={lnk.first.is_visible() if lnk.count() else '—'}")
            else:
                print(f"  [mobilno] link '{lbl}' vidljiv ✓")

        # sve sekcije otvorene → clipping provera
        for sek in ["Prodaja", "Knjigovodstvo", "Pregledi", "Podešavanja"]:
            expand(page, sek)
        if not proveri(page, "MOBILNI drawer — sve sekcije otvorene"):
            neuspeh.append("mobilno clipping")
        ctx.close()
        browser.close()

    print()
    if neuspeh:
        print("FAIL:", "; ".join(neuspeh))
        sys.exit(1)
    print(f"OK — navigacija kompletna, bez šišanja (desktop + mobilno)")

if __name__ == "__main__":
    main()
