"""Pretraga — obračun cene (pravila 1→2→3).

API: /slobodne-sobe?odrasli=&deca=&prevoz= vraća, posle provere raspoloživosti
(pravilo 1), samo sobe čija struktura (sobe.tip + soba_koeficijenti) ima red u
koeficijenti_prodaje za TAČNO (adl, chd, inf) (pravilo 2) i obračun cene iz
aktivnog cenovnika (pravilo 3) sa listom koraka `obracun`.

Ground truth se računa direktno iz baze (cenovnik_cene/opcije_soba/popust_soba).
UI: cena (precrtana osnovna + snižena) + tekst obračuna po sobi.
"""
import json
import os
import sys
from datetime import date, datetime
from decimal import Decimal

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/tmp/pw-browsers")

import httpx
from playwright.sync_api import sync_playwright
from sqlalchemy import create_engine, text

from routes import create_access_token

APP = os.environ.get("TEST_APP_URL", "http://localhost:3058")
API = os.environ.get("TEST_API_URL", "http://localhost:3158/api")
engine = create_engine(os.environ["EXTERNAL_NEON_DATABASE_URL"])
OD, DO = "25.05.2026", "14.06.2026"  # lanac od 2 termina (grupa 6)
KARTA_ADL, KARTA_CHD = Decimal(80), Decimal(70)

okovi = []
def proveri(naziv, uslov, detalj=""):
    okovi.append(uslov)
    print(f"{'PASS' if uslov else 'FAIL'} {naziv}" + (f" — {detalj}" if detalj and not uslov else ""))

def q2(x):
    return float(Decimal(x).quantize(Decimal("0.01")))

def ground_truth(conn, smestaj_id, soba, d_od, d_do, adl, chd, inf, sopstveni):
    """Očekivana (osnovna, snižena) za sobu ili None ako pravilo 2 ne prolazi."""
    danas = date.today()
    koef = {r.struktura.strip(): Decimal(str(r.koeficijent or 0)) for r in reversed(conn.execute(text(
        "SELECT struktura, koeficijent FROM koeficijenti_prodaje WHERE adl=:a AND chd=:c AND inf=:i "
        "ORDER BY (koeficijent > 0) DESC, rucno DESC, id DESC"), {"a": adl, "c": chd, "i": inf}).fetchall())}
    strukture = [soba["tip"].strip()] + [r.struktura.strip() for r in conn.execute(text(
        "SELECT struktura FROM soba_koeficijenti WHERE soba_id=:s"), {"s": soba["id"]})]
    kand = [(s, koef[s]) for s in strukture if s in koef]
    if not kand:
        return None
    c = conn.execute(text("""
        SELECT c.id, c.sobe, c.periodi FROM cenovnici c JOIN cenovnik_opcije o ON o.cenovnik_id=c.id
        WHERE c.smestaj_id=:s AND o.datumod <= :d AND o.datumdo >= :d ORDER BY c.id DESC LIMIT 1
    """), {"s": smestaj_id, "d": danas}).fetchone()
    if not c:
        return ("nema",)
    # lanac
    cur, lanac = d_od.isoformat(), []
    while cur != d_do.isoformat():
        p = next((p for p in sorted(c.periodi, key=lambda p: p["datum_do"], reverse=True)
                  if p["datum_od"] == cur and p["datum_do"] <= d_do.isoformat()), None)
        if not p:
            return ("nema",)
        lanac.append(p); cur = p["datum_do"]
    best = None
    for st, k in kand:
        if st == soba["tip"].strip():
            red = next((r for r in c.sobe if r["id"] == soba["id"]), None)
        else:
            red = next((r for r in c.sobe if r.get("virtuelna") and r.get("izvor_soba_id") == soba["id"] and r["tip"] == st), None)
        if not red:
            continue
        osnova = Decimal(0)
        ok = True
        for p in lanac:
            cena = conn.execute(text("SELECT cena FROM cenovnik_cene WHERE cenovnik_id=:c AND soba_id=:s AND period_id=:p"),
                                {"c": c.id, "s": red["id"], "p": p["id"]}).scalar()
            if not cena or cena <= 0:
                ok = False; break
            osnova += Decimal(str(cena))
        if not ok:
            continue
        pid = lanac[0]["id"]
        opc = conn.execute(text("SELECT * FROM opcije_soba WHERE cenovnik_id=:c AND soba_id=:s AND period_id IN (:p, 0) ORDER BY period_id DESC LIMIT 1"),
                           {"c": c.id, "s": red["id"], "p": pid}).mappings().first()
        tip_cene = (opc and opc["tip_cene"]) or "po_osobi"
        if tip_cene == "po_sobi":
            cena = osnova + (Decimal(0) if sopstveni else KARTA_ADL * adl + KARTA_CHD * chd)
        else:
            if k <= 0:
                continue  # po osobi bez unetog koeficijenta → nema cene
            cena = osnova * k
            if sopstveni and opc and opc["popust_sopstveni_prevoz"]:
                cena -= Decimal(str(opc["popust_sopstveni_prevoz"])) * (adl + chd)
        cena = max(Decimal(0), cena).quantize(Decimal("0.01"))
        pop = conn.execute(text("SELECT * FROM popust_soba WHERE cenovnik_id=:c AND soba_id=:s AND period_id IN (:p, 0) ORDER BY period_id DESC LIMIT 1"),
                           {"c": c.id, "s": red["id"], "p": pid}).mappings().first()
        sniz = None
        if pop and (pop["vazi_od"] is None or pop["vazi_od"] <= danas) and (pop["vazi_do"] is None or pop["vazi_do"] >= danas):
            um = Decimal(str(pop["umanjenje"]))
            sniz = (cena * (100 - um) / 100 if pop["umanjenje_vrsta"] == "procenat" else max(Decimal(0), cena - um)).quantize(Decimal("0.01"))
        r = (q2(cena), q2(sniz) if sniz is not None else None)
        if best is None or (r[1] or r[0]) < (best[1] or best[0]):
            best = r
    return best or ("nema",)

def main():
    token = create_access_token({"sub": "1"})
    api = httpx.Client(base_url=API, headers={"Authorization": "Bearer " + token}, timeout=180)
    d_od, d_do = datetime.strptime(OD, "%d.%m.%Y").date(), datetime.strptime(DO, "%d.%m.%Y").date()
    raspolozivo = api.get("/slobodne-sobe", params={"mesto_id": 1, "datum_od": OD, "datum_do": DO}).json()
    proveri("stari poziv (bez odrasli) vraća sobe bez obračuna",
            raspolozivo and all("cena_osnovna" not in s for g in raspolozivo for s in g["sobe"]))

    with engine.connect() as conn:
        for adl, deca, prevoz in [(2, "", "autobuski"), (1, "5", "sopstveni"), (3, "", "autobuski"), (2, "1", "autobuski")]:
            godine = [int(x) for x in deca.split(",") if x]
            chd, inf = sum(1 for g in godine if g >= 2), sum(1 for g in godine if g < 2)
            sop = prevoz == "sopstveni"
            rez = api.get("/slobodne-sobe", params={"mesto_id": 1, "datum_od": OD, "datum_do": DO,
                                                    "odrasli": adl, "deca": deca, "prevoz": prevoz}).json()
            po_sobi = {(g["smestaj_id"], s["id"]): s for g in rez for s in g["sobe"]}
            ocek = {}
            isklj = {}
            for g in raspolozivo:
                for s in g["sobe"]:
                    gt = ground_truth(conn, g["smestaj_id"], s, d_od, d_do, adl, chd, inf, sop)
                    if gt is None:
                        isklj[g["smestaj_id"]] = isklj.get(g["smestaj_id"], 0) + 1
                    else:
                        ocek[(g["smestaj_id"], s["id"])] = gt
            tag = f"{adl} ADL/{chd} CHD/{inf} INF, {prevoz}"
            proveri(f"[{tag}] skup soba == ground truth (pravilo 2)", set(po_sobi) == set(ocek),
                    f"api-only={set(po_sobi) - set(ocek)}, gt-only={set(ocek) - set(po_sobi)}")
            for k, gt in ocek.items():
                s = po_sobi.get(k)
                if not s:
                    continue
                if gt == ("nema",):
                    ok = s["cena_osnovna"] is None and s["nema_cene"]
                else:
                    ok = (s["cena_osnovna"], s["cena_snizena"]) == gt
                if not ok:
                    proveri(f"[{tag}] cena sobe {k} == gt", False, f"api={(s['cena_osnovna'], s['cena_snizena'])} gt={gt}")
            proveri(f"[{tag}] sve cene == ground truth ({len(ocek)} soba)", True)
            proveri(f"[{tag}] svaka soba ima obracun tekst", all(s["obracun"] for s in po_sobi.values()))
            for g in rez:
                proveri(f"[{tag}] {g['smestaj_naziv']} iskljuceno_putnici == {isklj.get(g['smestaj_id'], 0)}",
                        g["iskljuceno_putnici"] == isklj.get(g["smestaj_id"], 0), f"api={g['iskljuceno_putnici']}")
            if adl == 1 and sop:
                s = next((s for s in po_sobi.values() if s.get("cena_snizena")), None)
                proveri("[sopstveni] obracun pominje umanjenje jednom (ne po terminu)",
                        s is not None and sum("Sopstveni prevoz" in l for l in s["obracun"]) == 1)
                proveri("[lanac] obracun pokazuje zbir termina",
                        s is not None and any("lanac od 2 termina" in l for l in s["obracun"]))

    # ── UI ──
    rez = api.get("/slobodne-sobe", params={"mesto_id": 1, "datum_od": OD, "datum_do": DO,
                                            "odrasli": 2, "deca": "", "prevoz": "autobuski"}).json()
    prva = next((s for g in rez for s in g["sobe"] if s.get("cena_snizena")), None)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        ctx.add_init_script(f"localStorage.setItem('ta_token', {json.dumps(token)});")
        page = ctx.new_page()
        page.goto(APP + "/prodaja/pretraga", wait_until="domcontentloaded")
        page.get_by_role("combobox").first.wait_for(timeout=15000)
        page.get_by_role("combobox").first.click()
        page.get_by_role("option", name="Hanioti", exact=True).click()
        page.get_by_text("Izaberite datum polaska").click()
        kal = page.locator("[data-radix-popper-content-wrapper]")
        kal.wait_for(timeout=5000)
        page.wait_for_timeout(200)
        import re
        kal.first.locator("button:not([disabled])", has_text=re.compile(r"^25$")).first.click()
        page.wait_for_timeout(400)
        kal.first.get_by_text(f"20 noćenja | Povratak: {DO}.", exact=True).click(force=True)
        page.wait_for_timeout(300)
        with page.expect_request(lambda r: "/slobodne-sobe" in r.url and "odrasli=2" in r.url and "prevoz=autobuski" in r.url, timeout=10000):
            page.get_by_role("button", name="Pretraži", exact=True).click()
        proveri("UI šalje odrasli/deca/prevoz parametre", True)
        page.get_by_text("Slobodni kapaciteti").first.wait_for(timeout=30000)
        page.locator("[data-testid=obracun]").first.wait_for(timeout=30000)
        proveri("tekst obračuna prikazan kod svake sobe",
                page.locator("[data-testid=obracun]").count() == sum(len(g["sobe"]) for g in rez))
        if prva:
            def eur(n): return (str(int(n)) if float(n).is_integer() else f"{n:.2f}") + " €"
            proveri("snižena cena prikazana", page.get_by_text(eur(prva["cena_snizena"]), exact=True).count() >= 1)
            proveri("osnovna cena precrtana", page.locator(".line-through", has_text=eur(prva["cena_osnovna"])).count() >= 1)
        ctx.close(); browser.close()

    print()
    if not all(okovi):
        sys.exit(1)
    print(f"OK — pretraga obračun cene: {len(okovi)}/{len(okovi)}")

if __name__ == "__main__":
    main()
