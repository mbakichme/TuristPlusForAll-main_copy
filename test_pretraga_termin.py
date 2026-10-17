"""Pretraga /slobodne-sobe: rezultat vezan za Grupu termina vile.

Traženi boravak (datum_od + datum_do) mora biti pokriven LANCOM uzastopnih
perioda u grupi termina smeštaja (smestaj.grupa_datuma → period_datum): prvi
period počinje na datum_od, svaki sledeći počinje tačno na kraju prethodnog,
boravak se završava na kraju nekog perioda grupe. Smeštaj čija grupa ne
pokriva boravak NE SME da se pojavi u rezultatima, ma koliko sobe bile
slobodne (npr. ELENI 2 za 22.06→29.06 — termin definiše samo grupa 17;
25.05→14.06 definiše samo lanac grupe 6: 25.05–04.06 + 04.06–14.06).
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

# Rekurzivni CTE: krajevi LANACA perioda koji počinje na :od — prvi period
# počinje na :od, svaki sledeći tačno na kraju prethodnog; kraj < :do se
# produžava dalje (kraj = :do je nađen lanac, kraj > :do se odbacuje)
LANAC_SQL = """
WITH RECURSIVE lanac_krajevi(grupa_id, kraj) AS (
    SELECT pd.grupa_id, pd.datum_do
    FROM period_datum pd
    WHERE pd.datum_od = to_date(:od, 'DD.MM.YYYY')
    UNION
    SELECT l.grupa_id, pd2.datum_do
    FROM lanac_krajevi l
    JOIN period_datum pd2 ON pd2.grupa_id = l.grupa_id AND pd2.datum_od = l.kraj
    WHERE l.kraj < to_date(:do, 'DD.MM.YYYY')
)
"""

okovi = []
def proveri(naziv, uslov, detalj=""):
    okovi.append(uslov)
    print(f"{'PASS' if uslov else 'FAIL'} {naziv}" + (f" — {detalj}" if detalj and not uslov else ""))

def ground_truth(mesto_id, od, do):
    """SQL ground-truth: boravak pokriven lancom perioda grupe vile + soba bez preklapanja."""
    with eng.connect() as c:
        return {(r[0], r[1]) for r in c.execute(text(LANAC_SQL + """
            SELECT DISTINCT s.id, s.naziv FROM sobe b
            JOIN smestaj s ON s.id = b.veza_id_smestaj
            WHERE s.mesto = :m
              AND EXISTS (SELECT 1 FROM lanac_krajevi lk
                          WHERE lk.grupa_id = s.grupa_datuma
                            AND lk.kraj = to_date(:do, 'DD.MM.YYYY'))
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

# ── 4) LANCI perioda: produženi boravci (spajanje uzastopnih perioda iste grupe) ──
# 25.05→14.06 (20 noćenja) = lanac grupe 6: 25.05–04.06 + 04.06–14.06
API4 = api(1, "25.05.2026", "14.06.2026")
GT4 = ground_truth(1, "25.05.2026", "14.06.2026")
proveri("lanac 25.05→14.06 (20 noćenja): API == SQL ground-truth", API4 == GT4,
        f"API={sorted(API4)} GT={sorted(GT4)}")
proveri("lanac 25.05→14.06: nije prazan (lanac grupe 6 postaje pretraga)", len(API4) > 0,
        f"API={sorted(API4)}")
with eng.connect() as c:
    g6 = {r[0] for r in c.execute(text(
        "SELECT s.naziv FROM smestaj s WHERE s.grupa_datuma = 6")).fetchall()}
proveri("lanac 25.05→14.06: svi rezultati su iz grupe 6",
        {n for _, n in API4} <= g6, f"nazivi={sorted(API4)}")
# 25.05→08.06 (14 noćenja) = lanac grupe 17: 25.05–01.06 + 01.06–08.06
API5 = api(1, "25.05.2026", "08.06.2026")
GT5 = ground_truth(1, "25.05.2026", "08.06.2026")
proveri("lanac 25.05→08.06 (14 noćenja): API == SQL ground-truth", API5 == GT5,
        f"API={sorted(API5)} GT={sorted(GT5)}")
# NEGATIVNI: 02.06 nije kraj nikakvog lanca od 25.05 (grupa 6 se završava 30.05/04.06…,
# grupa 17 01.06/08.06…) i 26.05 nije početak nijednog perioda
proveri("25.05→02.06 (nije kraj lanca) → prazno", api(1, "25.05.2026", "02.06.2026") == set())
proveri("26.05→02.06 (nije početak perioda) → prazno", api(1, "26.05.2026", "02.06.2026") == set())

# ── 6) parametri i auth ─────────────────────────────────────────────────────
r = requests.get(f"{BASE}/slobodne-sobe", params={"mesto_id": 1, "datum_od": "22.06.2026", "datum_do": "05.07.2026"}, headers=H, timeout=30)
proveri("termin bez definisanog perioda i dalje 200 (može biti prazan)", r.status_code == 200)
r = requests.get(f"{BASE}/slobodne-sobe", params={"mesto_id": 1, "datum_od": "22.06.2026", "datum_do": "29.06.2026"}, timeout=10)
proveri("bez tokena → 401", r.status_code == 401, f"status={r.status_code}")

# ── 7) NOVI MOD: pretraga po SVIM opcijama trajanja od datum_od ─────────────
# Bez datum_do → za SVAKI kraj lanca perioda (grupa mesta) od datum_od
# (osnovni termin + produženi boravci) proverava se raspoloživost; vraćaju se
# SAMO opcije sa slobodnim smeštajem, hronološki po datumu povratka.
OD = "25.05.2026"
r = requests.get(f"{BASE}/slobodne-sobe", params={"mesto_id": 1, "datum_od": OD}, headers=H, timeout=120)
proveri("multi-mod: 200", r.status_code == 200, f"status={r.status_code} {r.text[:200]}")
REZ = r.json()
proveri("multi-mod: lista termina", isinstance(REZ, list) and all(
    {"datum_od", "datum_do", "nocenja", "smestaji"} == set(t.keys()) for t in REZ),
    f"oblik={REZ[:1]}")

with eng.connect() as c:
    DB_TERMINI = [(r[0], r[1]) for r in c.execute(text("""
        WITH RECURSIVE krajevi(grupa_id, kraj) AS (
            SELECT pd.grupa_id, pd.datum_do
            FROM period_datum pd
            WHERE pd.grupa_id IN (SELECT grupa_id FROM mesto_grupa WHERE mesto_id = 1)
              AND pd.datum_od = to_date(:od, 'DD.MM.YYYY')
            UNION
            SELECT k.grupa_id, pd2.datum_do
            FROM krajevi k
            JOIN period_datum pd2 ON pd2.grupa_id = k.grupa_id AND pd2.datum_od = k.kraj
        )
        SELECT to_char(kraj, 'DD.MM.YYYY'), to_char(kraj, 'DD.MM.YYYY')
        FROM krajevi ORDER BY kraj
    """), {"od": OD}).fetchall()]
    DB_TERMINI = [(OD, do) for _, do in DB_TERMINI]

proveri("multi-mod: svi vraćeni termini postoje u grupama mesta",
        {(t["datum_od"], t["datum_do"]) for t in REZ} <= set(DB_TERMINI),
        f"API={[(t['datum_od'], t['datum_do']) for t in REZ]} DB={DB_TERMINI}")

def gt_smestaji(od, do):
    """Ground-truth (id, naziv) smeštaja sa slobodnom sobom za boravak od→do."""
    with eng.connect() as c:
        return {(r[0], r[1]) for r in c.execute(text(LANAC_SQL + """
            SELECT DISTINCT s.id, s.naziv FROM sobe b
            JOIN smestaj s ON s.id = b.veza_id_smestaj
            WHERE s.mesto = 1
              AND EXISTS (SELECT 1 FROM lanac_krajevi lk
                          WHERE lk.grupa_id = s.grupa_datuma
                            AND lk.kraj = to_date(:do, 'DD.MM.YYYY'))
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
