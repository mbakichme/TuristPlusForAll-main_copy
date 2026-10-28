"""Uzrast putnika (ADL / CHD / INF) — offline prema dev serveru na 3158.

Provere:
1. POST: nosilac uzrast=ADL → aranzman.uzrast; saputnici CHD i INF → aranzman_dopuna.uzrast po redu
2. GET /ugovori vraća uzrast nosioca i saputnika (prefill forme)
3. PUT: promena uzrasta saputnika (INF → ADL) i poništavanje nosioca (prazno)
4. čišćenje test redova (aranzman + aranzman_dopuna)
"""
import json
import os
import subprocess
import urllib.parse
import urllib.request

from routes import create_access_token

BASE = "http://127.0.0.1:3158/api"
tok = create_access_token({"sub": "1"})
hdr = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}

SME = "TEST UZRAST SMEŠTAJ"
SOBA = "TU901"
IME_NOSIOCA = "TEST UZRAST NOSILAC"
SAP1 = "TEST UZRAST SAPUTNIK 1"
SAP2 = "TEST UZRAST SAPUTNIK 2"
kljucevi: list[str] = []
ok = True


def req(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(f"{BASE}{path}", data=data, headers=hdr, method=method)
    with urllib.request.urlopen(r, timeout=30) as resp:
        return json.load(resp)


def provera(naziv, dobijeno, ocekivano):
    global ok
    if dobijeno != ocekivano:
        ok = False
        print(f"  FAIL {naziv}: dobijeno={dobijeno!r} očekivano={ocekivano!r}")
    else:
        print(f"  OK {naziv}: {dobijeno!r}")


def osoba(ime, uzrast):
    return {"ime": ime, "datumRodjenja": "1990-01-01", "pasos": "", "uzrast": uzrast,
            "ow": False, "rt": False, "sp": False, "smer": "",
            "adresa": "", "telefon": "", "email": "",
            "mestoSedenja": "", "placeno": False, "zelja": False,
            "datumOw": "", "destinacijaOw": "", "datumPolaska": "", "destinacijaPolaska": "",
            "datumPovratka": "", "destinacijaPovratka": ""}


def payload(uzrast_nosioca, uzrast_s1, uzrast_s2):
    return {
        "tiprezervacije": "Klasična rezervacija", "timelimit": None,
        "nosilac": osoba(IME_NOSIOCA, uzrast_nosioca),
        "saputnici": [osoba(SAP1, uzrast_s1), osoba(SAP2, uzrast_s2)],
        "boravak": {"datumOd": "2026-12-01", "datumDo": "2026-12-08", "smestajId": None,
                    "sobaId": None, "mestoId": None, "smestajNaziv": SME, "sobaBroj": SOBA,
                    "mestoNaziv": "TEST MESTO", "struktura": "1/2",
                    "napomena": "", "napomenaInterna": ""},
        "destinacijaId": None, "destinacijaNaziv": None,
        "ulazak": "Hanioti", "izlazak": "",
        "napomenaPrevoz": "",
        "cene": {"cenaSmestajEUR": 100, "kolSmestajEUR": 1, "cenaSmestajRSD": 0,
                 "kolSmestajRSD": 0, "popustSmestaj": {}, "cenaPrevozEUR": 0,
                 "kolPrevozEUR": 0, "cenaPrevozRSD": 0, "kolPrevozRSD": 0,
                 "popustPrevoz": {}, "osiguranjeEUR": 0, "osiguranjeRSD": 0,
                 "provizijaSmestaj": {}, "provizijaPrevoz": {}, "uplaceno": {}},
    }


def proveri(kljuc, u_nosilac, u_s1, u_s2, oznaka):
    d = req(f"/ugovori/{urllib.parse.quote(kljuc, safe='')}")
    provera(f"{oznaka} nosilac uzrast", d.get("uzrast"), u_nosilac)
    sap = {p["saputnik"]: p for p in d["putnici_detalji"]}
    provera(f"{oznaka} saputnik 1 uzrast", (sap.get(SAP1) or {}).get("uzrast"), u_s1)
    provera(f"{oznaka} saputnik 2 uzrast", (sap.get(SAP2) or {}).get("uzrast"), u_s2)


try:
    # 1. POST
    r = req("/rezervacije", "POST", payload("ADL", "CHD", "INF"))
    kljuc = r["kljuc"]
    kljucevi.append(kljuc)
    print("1. POST →", kljuc)
    proveri(kljuc, "ADL", "CHD", "INF", "POST")

    # 2. PUT: nosilac ADL → INF, saputnik 2 INF → ADL
    req("/rezervacije/" + urllib.parse.quote(kljuc, safe=""), "PUT",
        payload("INF", "CHD", "ADL"))
    print("2. PUT")
    proveri(kljuc, "INF", "CHD", "ADL", "PUT")

    # 3. PUT: nosilac poništen (prazno → NULL)
    req("/rezervacije/" + urllib.parse.quote(kljuc, safe=""), "PUT",
        payload("", "CHD", "ADL"))
    print("3. PUT prazan uzrast nosioca")
    proveri(kljuc, None, "CHD", "ADL", "PRAZAN")
except Exception as e:
    ok = False
    print("  FAIL:", repr(e))

print("\nREZULTAT:", "SVE PROVERE PROŠLE" if ok else "IMA GREŠAKA")

# ── čišćenje (samo test redovi) ──
klj_list = ", ".join(f"'{k}'" for k in kljucevi) or "''"
_sql_cleanup = r'''
import db_config
from sqlalchemy import text
engine = db_config.get_engine()
with engine.begin() as conn:
    r = conn.execute(text("DELETE FROM aranzman WHERE putnik LIKE 'TEST UZRAST%' AND kljuc IN (''' + klj_list + r''') RETURNING id"))
    ids = [row[0] for row in r.fetchall()]
    n = 0
    for aid in ids:
        n += conn.execute(text("DELETE FROM aranzman_dopuna WHERE aranzman_id = :i"), {"i": aid}).rowcount
    print(f"obrisano: aranzman redova={len(ids)}, dopuna redova={n}")
'''
subprocess.run(["uv", "run", "python", "-c", _sql_cleanup],
               capture_output=True, text=True,
               cwd=os.path.dirname(os.path.abspath(__file__)))
print("Čišćenje završeno.")
