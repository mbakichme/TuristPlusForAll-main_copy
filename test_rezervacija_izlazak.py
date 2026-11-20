"""Mesto izlaska (tab Prevoz) — offline prema dev serveru na 3158.

Provere:
1. POST bez izlaska → nosilac i saputnik dobijaju mesto izlaska = mesto ulaska (podrazumevano)
2. POST sa izabranim izlaskom → čuva se izlazak (različit od ulaska)
3. PUT sa praznim izlaskom → ponovo podrazumevano = mesto ulaska
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

SME = "TEST IZLAZAK SMEŠTAJ"
SOBA = "TI901"
IME_NOSIOCA = "TEST IZLAZAK NOSILAC"
IME_SAPUTNIKA = "TEST IZLAZAK SAPUTNIK"
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


def payload(ulazak, izlazak_nosilac, saputnik_ulazak, saputnik_izlazak):
    nosilac = {"ime": IME_NOSIOCA, "datumRodjenja": "1990-01-01", "pasos": "T1234567",
               "ow": False, "rt": False, "sp": False, "smer": "",
               "adresa": "", "telefon": "", "email": "",
               "mestoSedenja": "", "placeno": False, "zelja": False,
               "datumOw": "", "destinacijaOw": "", "datumPolaska": "", "destinacijaPolaska": "",
               "datumPovratka": "", "destinacijaPovratka": ""}
    saputnik = {"ime": IME_SAPUTNIKA, "datumRodjenja": "1992-02-02", "pasos": "",
                "ow": False, "rt": False, "sp": False, "smer": "",
                "adresa": "", "telefon": "", "email": "",
                "ulazak": saputnik_ulazak, "mestoIzlaska": saputnik_izlazak,
                "mestoSedenja": "", "placeno": False, "zelja": False,
                "datumOw": "", "destinacijaOw": "", "datumPolaska": "", "destinacijaPolaska": "",
                "datumPovratka": "", "destinacijaPovratka": ""}
    return {
        "tiprezervacije": "Klasična rezervacija", "timelimit": None,
        "nosilac": {**nosilac, "mestoIzlaska": izlazak_nosilac},
        "saputnici": [saputnik],
        "boravak": {"datumOd": "2026-12-01", "datumDo": "2026-12-08", "smestajId": None,
                    "sobaId": None, "mestoId": None, "smestajNaziv": SME, "sobaBroj": SOBA,
                    "mestoNaziv": "TEST MESTO", "struktura": "1/2",
                    "napomena": "", "napomenaInterna": ""},
        "destinacijaId": None, "destinacijaNaziv": None,
        "ulazak": ulazak, "izlazak": izlazak_nosilac,
        "napomenaPrevoz": "",
        "cene": {"cenaSmestajEUR": 100, "kolSmestajEUR": 1, "cenaSmestajRSD": 0,
                 "kolSmestajRSD": 0, "popustSmestaj": {}, "cenaPrevozEUR": 0,
                 "kolPrevozEUR": 0, "cenaPrevozRSD": 0, "kolPrevozRSD": 0,
                 "popustPrevoz": {}, "osiguranjeEUR": 0, "osiguranjeRSD": 0,
                 "provizijaSmestaj": {}, "provizijaPrevoz": {}, "uplaceno": {}},
    }


def proveri(kljuc, ocekivano_nosilac, ocekivano_saputnik, oznaka):
    d = req(f"/ugovori/{urllib.parse.quote(kljuc, safe='')}")
    provera(f"{oznaka} nosilac mesto_izlaska", d.get("mesto_izlaska"), ocekivano_nosilac)
    sap = [p for p in d["putnici_detalji"] if p["saputnik"] == IME_SAPUTNIKA]
    provera(f"{oznaka} saputnik nađen", len(sap), 1)
    provera(f"{oznaka} saputnik mesto_izlaska", sap[0]["mesto_izlaska"], ocekivano_saputnik)


try:
    # 1. podrazumevano = ulaz
    r = req("/rezervacije", "POST", payload("Hanioti", "", "Hanioti", ""))
    kljuc = r["kljuc"]
    kljucevi.append(kljuc)
    print("1. POST bez izlaska →", kljuc)
    proveri(kljuc, "Hanioti", "Hanioti", "podrazumevano")

    # 2. izabran izlaz različit od ulaza
    r = req("/rezervacije/" + urllib.parse.quote(kljuc, safe=""), "PUT",
            payload("Hanioti", "Solun", "Hanioti", "Solun"))
    print("2. PUT sa izlazom Solun")
    proveri(kljuc, "Solun", "Solun", "izabran")

    # 3. prazan izlaz → ponovo podrazumevano
    req("/rezervacije/" + urllib.parse.quote(kljuc, safe=""), "PUT",
        payload("Hanioti", "", "Hanioti", ""))
    print("3. PUT sa praznim izlazom")
    proveri(kljuc, "Hanioti", "Hanioti", "prazan")
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
    r = conn.execute(text("DELETE FROM aranzman WHERE putnik LIKE 'TEST IZLAZAK%' AND kljuc IN (''' + klj_list + r''') RETURNING id"))
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
