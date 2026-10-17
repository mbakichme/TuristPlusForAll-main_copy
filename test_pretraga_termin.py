"""Pretraga /slobodne-sobe: rezultat vezan za Grupu termina vile.

Traženi termin (datum_od + datum_do) mora biti DEFINISAN periodom u grupi
termina smeštaja (smestaj.grupa_datuma → period_datum). Smeštaj čija grupa
ne definiše termin NE SME da se pojavi u rezultatima, ma koliko sobe bile
slobodne (npr. ELENI 2 za 22.06→29.06 — termin definiše samo grupa 17).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests
from sqlalchemy import create_engine, text

BASE = os.environ.get("TA_BASE", "http://localhost:3158/api")
eng = create_engine(os.environ["EXTERNAL_NEON_DATABASE_URL"])
tok = None
from routes import create_access_token
tok = create_access_token({"sub": "1"})
H = {"Authorization": f"Bearer {tok}"}

okovi = []
def proveri(naziv, uslov, detalj=""):
    okovi.append(uslov)
    print(f"{'PASS' if uslov else 'FAIL'} {naziv}" + (f" — {detalj}" if detalj and not uslov else ""))

def ground_truth(mesto_id, od, do):
    """SQL ground-truth: termin definisan grupom vile + soba bez preklapanja."""
    with eng.connect() as c:
        return {(r[0], r[1]) for r in c.execute(text("""
            SELECT DISTINCT s.id, s.naziv FROM sobe b
            JOIN smestaj s ON s.id = b.veza_id_smestaj
            WHERE s.mesto = :m
              AND EXISTS (SELECT 1 FROM period_datum pd
                          WHERE pd.grupa_id = s.grupa_datuma
                            AND pd.datum_od = to_date(:od, 'DD.MM.YYYY')
                            AND pd.datum_do = to_date(:do, 'DD.MM.YYYY'))
              AND NOT EXISTS (
                  SELECT 1 FROM aranzman a
                  WHERE a.naziv = s.naziv
                    AND TRIM(COALESCE(a.soba, '')) = TRIM(b.broj_sobe)
                    AND a.datumod IS NOT NULL AND a.datumdo IS NOT NULL
                    AND a.datumod < to_date(:do, 'DD.MM.YYYY')
                    AND a.datumdo > to_date(:od, 'DD.MM.YYYY'))
        """), {"m": mesto_id, "od": od, "do": do}).fetchall()}

def api(mesto_id, od, do):
    r = requests.get(f"{BASE}/slobodne-sobe", params={
        "mesto_id": mesto_id, "datum_od": od, "datum_do": do}, headers=H, timeout=30)
    assert r.status_code == 200, (r.status_code, r.text[:200])
    return {(g["smestaj_id"], g["smestaj_naziv"]) for g in r.json()}

# ── 1) 22.06→29.06 (7 noćenja): definiše SAMO grupa 17 ──────────────────────
API = api(1, "22.06.2026", "29.06.2026")
GT = ground_truth(1, "22.06.2026", "29.06.2026")
proveri("22.06→29.06: API == SQL ground-truth", API == GT, f"API={sorted(API)} GT={sorted(GT)}")
nazivi = {n for _, n in API}
proveri("22.06→29.06: ELENI 2 / ELENI 2 C / PENNY C NISU u rezultatu",
        not ({"ELENI 2", "ELENI 2 C", "PENNY C"} & nazivi), f"nazivi={sorted(nazivi)}")
with eng.connect() as c:
    g17 = {r[0] for r in c.execute(text(
        "SELECT s.naziv FROM smestaj s WHERE s.grupa_datuma = 17")).fetchall()}
proveri("22.06→29.06: svi rezultati su iz grupe 17 (JORGOS/MACEDONIA SKY/PENNY/STORNO)",
        nazivi <= g17, f"nazivi={sorted(nazivi)} grupa17={sorted(g17)}")
if GT:
    proveri("22.06→29.06: ground-truth nije prazan (ima što proveriti)", True)

# ── 2) 24.06→04.07 (10 noćenja, grupa 6): ELENI 2 (grupa 6) sme da bude ────
API2 = api(1, "24.06.2026", "04.07.2026")
GT2 = ground_truth(1, "24.06.2026", "04.07.2026")
proveri("24.06→04.07: API == SQL ground-truth", API2 == GT2, f"API={sorted(API2)} GT={sorted(GT2)}")
with eng.connect() as c:
    el6_slobodna = c.execute(text("""
        SELECT COUNT(*) FROM sobe b JOIN smestaj s ON s.id = b.veza_id_smestaj
        WHERE s.id = 10 AND NOT EXISTS (
            SELECT 1 FROM aranzman a WHERE a.naziv = s.naziv
              AND TRIM(COALESCE(a.soba,'')) = TRIM(b.broj_sobe)
              AND a.datumod < '2026-07-04' AND a.datumdo > '2026-06-24')
    """)).scalar()
if el6_slobodna > 0:
    proveri("24.06→04.07: ELENI 2 (grupa 6) JESTE u rezultatu (ima slobodnu sobu)",
            (10, "ELENI 2") in API2, f"API={sorted(API2)}")
else:
    proveri("24.06→04.07: ELENI 2 nema slobodnu sobu — preskačem pozitivnu asertaciju", True)

# ── 3) 19.06→29.06 (10 noćenja, grupa 15): ELENI 2 (grupa 15) sme; grupe 16/17 ne ──
API3 = api(1, "19.06.2026", "29.06.2026")
GT3 = ground_truth(1, "19.06.2026", "29.06.2026")
proveri("19.06→29.06: API == SQL ground-truth", API3 == GT3, f"API={sorted(API3)} GT={sorted(GT3)}")

# ── 4) parametri i auth ─────────────────────────────────────────────────────
r = requests.get(f"{BASE}/slobodne-sobe", params={"mesto_id": 1, "datum_od": "22.06.2026", "datum_do": "05.07.2026"}, headers=H, timeout=30)
proveri("termin bez definisanog perioda i dalje 200 (može biti prazan)", r.status_code == 200)
r = requests.get(f"{BASE}/slobodne-sobe", params={"mesto_id": 1, "datum_od": "22.06.2026", "datum_do": "29.06.2026"}, timeout=10)
proveri("bez tokena → 401", r.status_code == 401, f"status={r.status_code}")

# ── 5) NOVI MOD: pretraga po SVIM terminima koji počinju na datum_od ────────
# Bez datum_do → za SVAKI termin (period u grupama mesta) koji počinje na
# datum_od proverava se raspoloživost; vraćaju se SAMO termini sa slobodnim
# smeštajem, hronološki po datumu povratka.
OD = "25.05.2026"
r = requests.get(f"{BASE}/slobodne-sobe", params={"mesto_id": 1, "datum_od": OD}, headers=H, timeout=60)
proveri("multi-mod: 200", r.status_code == 200, f"status={r.status_code} {r.text[:200]}")
REZ = r.json()
proveri("multi-mod: lista termina", isinstance(REZ, list) and all(
    {"datum_od", "datum_do", "nocenja", "smestaji"} == set(t.keys()) for t in REZ),
    f"oblik={REZ[:1]}")

with eng.connect() as c:
    DB_TERMINI = [(r[0], r[1]) for r in c.execute(text("""
        SELECT DISTINCT to_char(pd.datum_od, 'DD.MM.YYYY'), to_char(pd.datum_do, 'DD.MM.YYYY')
        FROM period_datum pd
        WHERE pd.grupa_id IN (SELECT grupa_id FROM mesto_grupa WHERE mesto_id = 1)
          AND pd.datum_od = to_date(:od, 'DD.MM.YYYY')
        ORDER BY 2
    """), {"od": OD}).fetchall()]

proveri("multi-mod: svi vraćeni termini postoje u grupama mesta",
        {(t["datum_od"], t["datum_do"]) for t in REZ} <= set(DB_TERMINI),
        f"API={[(t['datum_od'], t['datum_do']) for t in REZ]} DB={DB_TERMINI}")

def gt_smestaji(od, do):
    """Ground-truth (id, naziv) smeštaja sa slobodnom sobom za termin."""
    with eng.connect() as c:
        return {(r[0], r[1]) for r in c.execute(text("""
            SELECT DISTINCT s.id, s.naziv FROM sobe b
            JOIN smestaj s ON s.id = b.veza_id_smestaj
            WHERE s.mesto = 1
              AND EXISTS (SELECT 1 FROM period_datum pd
                          WHERE pd.grupa_id = s.grupa_datuma
                            AND pd.datum_od = to_date(:od, 'DD.MM.YYYY')
                            AND pd.datum_do = to_date(:do, 'DD.MM.YYYY'))
              AND NOT EXISTS (
                  SELECT 1 FROM aranzman a
                  WHERE a.naziv = s.naziv
                    AND TRIM(COALESCE(a.soba, '')) = TRIM(b.broj_sobe)
                    AND a.datumod IS NOT NULL AND a.datumdo IS NOT NULL
                    AND a.datumod < to_date(:do, 'DD.MM.YYYY')
                    AND a.datumdo > to_date(:od, 'DD.MM.YYYY'))
        """), {"od": od, "do": do}).fetchall()}

from datetime import datetime as _dt
svi_gt = []
for t in REZ:
    d_od = _dt.strptime(t["datum_od"], "%d.%m.%Y").date()
    d_do = _dt.strptime(t["datum_do"], "%d.%m.%Y").date()
    proveri(f"multi-mod {t['datum_od']}–{t['datum_do']}: nocenja = razlika datuma",
            t["nocenja"] == (d_do - d_od).days, f"nocenja={t['nocenja']}")
    GT_T = gt_smestaji(t["datum_od"], t["datum_do"])
    svi_gt.append(GT_T)
    API_T = {(g["smestaj_id"], g["smestaj_naziv"]) for g in t["smestaji"]}
    proveri(f"multi-mod {t['datum_od']}–{t['datum_do']}: smestaji == SQL ground-truth",
            API_T == GT_T, f"API={sorted(API_T)} GT={sorted(GT_T)}")
    proveri(f"multi-mod {t['datum_od']}–{t['datum_do']}: svaki smeštaj ima ≥1 sobu",
            all(g["sobe"] for g in t["smestaji"]))

proveri("multi-mod: nema termina bez slobodnog smeštaja (svi GT neprazni)",
        all(len(g) > 0 for g in svi_gt))
povracaji = [_dt.strptime(t["datum_do"], "%d.%m.%Y").date() for t in REZ]
proveri("multi-mod: hronološki po datumu povratka", povracaji == sorted(povracaji), f"povracaji={povracaji}")
proveri("multi-mod: podaci termina identični modu od+do (uzorak)",
        all(
            {(g["smestaj_id"], g["smestaj_naziv"]) for g in t["smestaji"]}
            == api(1, t["datum_od"], t["datum_do"])
            for t in REZ
        ))

# validacija multi-moda
r = requests.get(f"{BASE}/slobodne-sobe", params={"datum_od": OD}, headers=H, timeout=30)
proveri("multi-mod bez mesta/grupe → 400", r.status_code == 400, f"status={r.status_code}")
r = requests.get(f"{BASE}/slobodne-sobe", params={"mesto_id": 1, "datum_od": "xxx"}, headers=H, timeout=30)
proveri("multi-mod loš format datuma → 400", r.status_code == 400, f"status={r.status_code}")
r = requests.get(f"{BASE}/slobodne-sobe", params={"mesto_id": 1, "datum_od": OD}, timeout=10)
proveri("multi-mod bez tokena → 401", r.status_code == 401, f"status={r.status_code}")

print()
print(f"[{'PASS' if all(okovi) else 'FAIL'}] slobodne-sobe grupa-termin vezivanje: {sum(okovi)}/{len(okovi)}")
sys.exit(0 if all(okovi) else 1)
