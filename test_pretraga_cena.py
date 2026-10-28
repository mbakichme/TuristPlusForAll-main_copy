"""Pretraga — obračun cene (pravila 1→2→3).

API: /slobodne-sobe?odrasli=&deca=&prevoz= vraća, posle provere raspoloživosti
(pravilo 1), samo sobe čija struktura (sobe.tip + soba_koeficijenti) ima red u
koeficijenti_prodaje za TAČNO (adl, chd) (pravilo 2) i obračun cene iz
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
import db_config
from sqlalchemy import create_engine, text

from routes import create_access_token

APP = os.environ.get("TEST_APP_URL", "http://localhost:3058")
API = os.environ.get("TEST_API_URL", "http://localhost:3158/api")
engine = db_config.get_engine()
OD, DO = "25.05.2026", "14.06.2026"  # lanac od 2 termina (grupa 6)
KARTA_ADL, KARTA_CHD = Decimal(80), Decimal(70)

okovi = []
def proveri(naziv, uslov, detalj=""):
    okovi.append(uslov)
    print(f"{'PASS' if uslov else 'FAIL'} {naziv}" + (f" — {detalj}" if detalj and not uslov else ""))

def q2(x):
    return float(Decimal(x).quantize(Decimal("0.01")))

def ground_truth(conn, smestaj_id, soba, d_od, d_do, adl, chd, sopstveni):
    """Očekivana osnovna cena i sve važeće popust varijante, po rednom broju."""
    danas = date.today()
    koef = {r.struktura.strip(): Decimal(str(r.koeficijent or 0)) for r in reversed(conn.execute(text(
        "SELECT struktura, koeficijent FROM koeficijenti_prodaje WHERE adl=:a AND chd=:c AND inf=0 "
        "ORDER BY (koeficijent > 0) DESC, rucno DESC, id DESC"), {"a": adl, "c": chd}).fetchall())}
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
        # popusti: svaki važeći red (redni 1..3) je zasebna varijanta, nikad se ne sabiraju
        pop_redovi = conn.execute(text("SELECT * FROM popust_soba WHERE cenovnik_id=:c AND soba_id=:s AND period_id=:p ORDER BY redni"),
                                  {"c": c.id, "s": red["id"], "p": pid}).mappings().all()
        varijante = []
        for pop in pop_redovi:
            if not ((pop["vazi_od"] is None or pop["vazi_od"] <= danas) and (pop["vazi_do"] is None or pop["vazi_do"] >= danas)):
                continue
            um = Decimal(str(pop["umanjenje"]))
            sniz = (cena * (100 - um) / 100 if pop["umanjenje_vrsta"] == "procenat" else max(Decimal(0), cena - um)).quantize(Decimal("0.01"))
            varijante.append((pop["redni"], q2(sniz)))
        r = (q2(cena), varijante)
        if best is None or prvi_iznos(r) < prvi_iznos(best):
            best = r
    return best or ("nema",)

def prvi_iznos(gt):
    """Prvi važeći snižen iznos (ili osnovna ako nema važećeg popusta) — kriterijum izbora sobe."""
    osnova, varijante = gt
    return varijante[0][1] if varijante else osnova

def main():
    token = create_access_token({"sub": "1"})
    api = httpx.Client(base_url=API, headers={"Authorization": "Bearer " + token}, timeout=180)
    d_od, d_do = datetime.strptime(OD, "%d.%m.%Y").date(), datetime.strptime(DO, "%d.%m.%Y").date()
    raspolozivo = api.get("/slobodne-sobe", params={"mesto_id": 1, "datum_od": OD, "datum_do": DO}).json()
    proveri("stari poziv (bez odrasli) vraća sobe bez obračuna",
            raspolozivo and all("cena_osnovna" not in s for g in raspolozivo for s in g["sobe"]))

    with engine.connect() as conn:
        for odrasli, deca, prevoz in [(2, "", "autobuski"), (1, "5", "sopstveni"), (3, "", "autobuski"), (2, "1", "autobuski")]:
            godine = [int(x) for x in deca.split(",") if x]
            # CHD = dete do 6.99 (smeštaj.granica_chd, default); starije = ADL
            chd = sum(1 for g in godine if g <= 6.99)
            adl = odrasli + len(godine) - chd
            sop = prevoz == "sopstveni"
            rez = api.get("/slobodne-sobe", params={"mesto_id": 1, "datum_od": OD, "datum_do": DO,
                                                    "odrasli": odrasli, "deca": deca, "prevoz": prevoz}).json()
            po_sobi = {(g["smestaj_id"], s["id"]): s for g in rez for s in g["sobe"]}
            ocek = {}
            isklj = {}
            for g in raspolozivo:
                for s in g["sobe"]:
                    gt = ground_truth(conn, g["smestaj_id"], s, d_od, d_do, adl, chd, sop)
                    if gt is None:
                        isklj[g["smestaj_id"]] = isklj.get(g["smestaj_id"], 0) + 1
                    else:
                        ocek[(g["smestaj_id"], s["id"])] = gt
            tag = f"{adl} ADL/{chd} CHD, {prevoz}"
            proveri(f"[{tag}] skup soba == ground truth (pravilo 2)", set(po_sobi) == set(ocek),
                    f"api-only={set(po_sobi) - set(ocek)}, gt-only={set(ocek) - set(po_sobi)}")
            for k, gt in ocek.items():
                s = po_sobi.get(k)
                if not s:
                    continue
                if gt == ("nema",):
                    ok = s["cena_osnovna"] is None and s["nema_cene"]
                else:
                    osnova, gt_var = gt
                    api_var = [(v["popust_redni"], v["cena_snizena"]) for v in s["varijante"] if v["cena_snizena"] is not None]
                    ok = s["cena_osnovna"] == osnova and api_var == gt_var and s["cena_snizena"] == (gt_var[0][1] if gt_var else None)
                if not ok:
                    proveri(f"[{tag}] cena sobe {k} == gt", False, f"api={s['cena_osnovna']} {s['varijante']} gt={gt}")
            proveri(f"[{tag}] sve cene == ground truth ({len(ocek)} soba)", True)
            proveri(f"[{tag}] svaka soba ima obracun tekst", all(s["obracun"] for s in po_sobi.values()))
            for g in rez:
                proveri(f"[{tag}] {g['smestaj_naziv']} iskljuceno_putnici == {isklj.get(g['smestaj_id'], 0)}",
                        g["iskljuceno_putnici"] == isklj.get(g["smestaj_id"], 0), f"api={g['iskljuceno_putnici']}")
            if adl == 1 and sop:
                s = next((s for s in po_sobi.values() if s.get("varijante")), None)
                ob = s["varijante"][0]["obracun"] if s else []
                proveri("[sopstveni] obracun pominje umanjenje jednom (ne po terminu)",
                        s is not None and sum("Sopstveni prevoz" in l for l in ob) == 1)
                proveri("[lanac] obracun pokazuje zbir termina",
                        s is not None and any("lanac od 2 termina" in l for l in ob))
            # varijante: jedna po važećem popustu, redni rastući, svaka sa sopstvenom cenom
            for k, s in po_sobi.items():
                if s.get("cena_osnovna") is None:
                    continue
                vz = [v for v in s["varijante"] if v["cena_snizena"] is not None]
                proveri(f"[{tag}] soba {k}: varijante ⊇ važeći popusti, redni rastući",
                        [v["popust_redni"] for v in vz] == sorted(v["popust_redni"] for v in vz)
                        and all(v["vazi"] for v in vz))

    # ── UI ──
    rez = api.get("/slobodne-sobe", params={"mesto_id": 1, "datum_od": OD, "datum_do": DO,
                                            "odrasli": 2, "deca": "", "prevoz": "autobuski"}).json()
    vazece = lambda s: [v for v in (s.get("varijante") or []) if v["cena_snizena"] is not None]
    prva_g, prva_soba = next(((g, s) for g in rez for s in g["sobe"] if vazece(s)), (None, None))
    # UI: jedan Rezerviši po važećem popustu (bez popusta → jedan Rezerviši sa osnovnom cenom)
    ocekivano_rezervisi = sum(max(1, len(vazece(s))) for g in rez for s in g["sobe"])
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
        plusevi = page.get_by_role("button", name=re.compile(r"^Prikaži obračun"))
        plusevi.first.wait_for(timeout=30000)
        proveri("obračun je sakriven dok se ne klikne +", page.locator("[data-testid=obracun]").count() == 0)
        proveri("dugme + kod svake sobe sa obračunom",
                plusevi.count() == sum(len(g["sobe"]) for g in rez))
        plusevi.first.click()
        page.locator("[data-testid=obracun]").first.wait_for(timeout=5000)
        proveri("klik na + otvara obračun samo te sobe", page.locator("[data-testid=obracun]").count() == 1)
        page.get_by_role("button", name=re.compile(r"^Sakrij obračun")).first.click()
        proveri("klik na − sakriva obračun", page.locator("[data-testid=obracun]").count() == 0)
        if prva_g:
            def eur(n): return (str(int(n)) if float(n).is_integer() else f"{n:.2f}") + " €"
            for v in vazece(prva_soba):
                proveri(f"snižena cena prikazana (popust {v['popust_redni']})",
                        page.get_by_text(eur(v["cena_snizena"]), exact=True).count() >= 1)
            proveri("osnovna cena precrtana", page.locator(".line-through", has_text=eur(prva_soba["cena_osnovna"])).count() >= 1)
            proveri("jedan Rezerviši po važećem popustu (bez popusta: jedan)",
                    page.get_by_role("button", name="Rezerviši").count() == ocekivano_rezervisi,
                    f"ui={page.get_by_role('button', name='Rezerviši').count()} očekivano={ocekivano_rezervisi}")
            proveri("kartica prikazuje oznaku popusta i tip plaćanja",
                    all(page.get_by_text(f"Popust {v['popust_redni']}", exact=False).count() >= 1 for v in vazece(prva_soba)))
        # Rezerviši prve sobe sa važećim popustom → forma rezervacije sa prebačenim podacima
        page.locator("button", has_text="Rezerviši").nth(0).click()
        page.wait_for_url(re.compile(r"/prodaja/rezervacije\?"), timeout=10000)
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(page.url).query)
        # klik na prvi Rezerviši → soba iz URL-a; očekivana varijanta = prvi važeći popust te sobe
        klik_g, prva_soba = next(((g, s) for g in rez for s in g["sobe"] if qs.get("soba") == [str(s["id"])]), (None, None))
        v0 = vazece(prva_soba)[0] if prva_soba and vazece(prva_soba) else None
        proveri("link rezervacije nosi novi=1, soba, smestaj, mesto, datume",
                prva_soba is not None and qs.get("novi") == ["1"]
                and qs.get("smestaj") == [str(klik_g["smestaj_id"])] and qs.get("mesto") == ["1"]
                and qs.get("datumod") == [OD] and qs.get("datumdo") == [DO])
        proveri("link nosi strukturu, cenu, popust, putnike i prevoz",
                prva_soba is not None and qs.get("struktura") == [prva_soba["struktura"]]
                and float(qs["cena"][0]) == float(prva_soba["cena_osnovna"])
                and (v0 is None or abs(float(qs["popust"][0]) - (prva_soba["cena_osnovna"] - v0["cena_snizena"])) < 0.01)
                and qs.get("odrasli") == ["2"] and qs.get("prevoz") == ["autobuski"])
        page.get_by_placeholder("npr. 1/2 + 1/2").wait_for(timeout=15000)
        page.wait_for_timeout(1500)
        proveri("forma: struktura popunjena",
                page.get_by_placeholder("npr. 1/2 + 1/2").input_value() == prva_soba["struktura"])
        proveri("forma: 1 saputnik (2 odrasla)",
                page.get_by_text("Saputnik 1", exact=True).count() == 1 and page.get_by_text("Saputnik 2", exact=True).count() == 0)
        page.get_by_role("tab", name="Obračun").click()
        cena_inp = page.locator("input[aria-label='Cena smeštaja (EUR)']")
        cena_inp.wait_for(timeout=5000)
        # Forma rastavlja ukupnu cenu iz pretrage po osobama: jedinična = cena / broj osoba, količina = broj osoba
        broj_osoba = int(qs["odrasli"][0]) + len([x for x in (qs.get("deca") or [""])[0].split(",") if x.strip()])
        proveri("forma: cena smeštaja = osnovna / broj osoba",
                abs(float(cena_inp.input_value()) - float(prva_soba["cena_osnovna"]) / broj_osoba) < 0.01,
                f"ui={cena_inp.input_value()} očekivano={float(prva_soba['cena_osnovna']) / broj_osoba}")
        proveri("forma: količina = broj osoba",
                page.locator("input[aria-label='Količina za cenu smeštaja (EUR)']").input_value() == str(broj_osoba))
        # Popust card je prvi ProcenatRed sa naslovom Smeštaj (Provizija je drugi) → .first
        pop_inp = page.locator("input[aria-label='Smeštaj — iznos (EUR)']").first
        ocekivani_popust = (prva_soba["cena_osnovna"] - v0["cena_snizena"]) if v0 else 0
        proveri("forma: popust smeštaja popunjen (iznos EUR)",
                abs(float(pop_inp.input_value() or 0) - ocekivani_popust) < 0.01)
        ctx.close(); browser.close()

    print()
    if not all(okovi):
        sys.exit(1)
    print(f"OK — pretraga obračun cene: {len(okovi)}/{len(okovi)}")

if __name__ == "__main__":
    main()
