"""Round-trip test polja taba Prevoz (rezervacija) — offline prema dev serveru na 3158.

Provere:
1. POST: nosilac OW + saputnik RT sa svim novim poljima → 201
2. GET /ugovori: nosilac i saputnik vraćaju polja (ISO datumi, destinacije, bool-ovi)
3. GET: napomena_prevoz vraćena
4. PUT: izmena polja (nosilac prelazi sa OW na RT, saputnik sa RT na OW) → GET potvrđuje
5. Polja smera koji nije uključen se čiste (NULL) — ne ostaju stare vrednosti
6. čišćenje test redova (aranzman + aranzman_dopuna)

Test koristi zaseban naziv smeštaja i sobu, pa ne sudara sa stvarnim podacima.
"""
import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request

from routes import create_access_token

BASE = "http://127.0.0.1:3158/api"
tok = create_access_token({"sub": "1"})
hdr = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}

SME = "TEST PREVOZ SMEŠTAJ"
SOBA = "TP901"
ime_nosioca = "TEST PREVOZ NOSILAC"
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


def payload(nosilac, saputnik, napomena_prevoz):
    return {
        "tiprezervacije": "Klasična rezervacija", "timelimit": None,
        "nosilac": nosilac,
        "saputnici": [saputnik],
        "boravak": {"datumOd": "2026-12-01", "datumDo": "2026-12-08", "smestajId": None,
                    "sobaId": None, "mestoId": None, "smestajNaziv": SME, "sobaBroj": SOBA,
                    "mestoNaziv": "TEST MESTO", "struktura": "1/2",
                    "napomena": "", "napomenaInterna": ""},
        "destinacijaId": None, "destinacijaNaziv": None, "ulazak": "",
        "napomenaPrevoz": napomena_prevoz,
        "cene": {"cenaSmestajEUR": 100, "kolSmestajEUR": 1, "cenaSmestajRSD": 0,
                 "kolSmestajRSD": 0, "popustSmestaj": {}, "cenaPrevozEUR": 0,
                 "kolPrevozEUR": 0, "cenaPrevozRSD": 0, "kolPrevozRSD": 0,
                 "popustPrevoz": {}, "osiguranjeEUR": 0, "osiguranjeRSD": 0,
                 "provizijaSmestaj": {}, "provizijaPrevoz": {}, "uplaceno": {}},
    }


def nosilac_base(**kw):
    base = {"ime": ime_nosioca, "datumRodjenja": "1990-01-01", "pasos": "T1234567",
            "ow": False, "rt": False, "sp": False, "smer": "",
            "adresa": "Test adresa 1", "telefon": "0601234567", "email": "",
            "mestoSedenja": "", "placeno": False, "zelja": False,
            "datumOw": "", "destinacijaOw": "", "datumPolaska": "", "destinacijaPolaska": "",
            "datumPovratka": "", "destinacijaPovratka": ""}
    base.update(kw)
    return base


def saputnik_base(**kw):
    base = {"ime": "TEST PREVOZ SAPUTNIK", "datumRodjenja": "1992-02-02", "pasos": "",
            "ow": False, "rt": False, "sp": False, "smer": "",
            "adresa": "", "telefon": "", "email": "", "ulazak": "",
            "mestoSedenja": "", "placeno": False, "zelja": False,
            "datumOw": "", "destinacijaOw": "", "datumPolaska": "", "destinacijaPolaska": "",
            "datumPovratka": "", "destinacijaPovratka": ""}
    base.update(kw)
    return base


try:
    # 1. POST — nosilac OW, saputnik RT
    n = nosilac_base(ow=True, smer="Polazak", datumOw="2026-11-30",
                     destinacijaOw="TEST DEST OW", mestoSedenja="Prednje",
                     placeno=True, zelja=False)
    s = saputnik_base(rt=True, datumPolaska="2026-11-30", destinacijaPolaska="TEST DEST POL",
                      datumPovratka="2026-12-08", destinacijaPovratka="TEST DEST POV",
                      mestoSedenja="Zadnje", placeno=False, zelja=True)
    r = req("/rezervacije", "POST", payload(n, s, "TEST napomena prevoz"))
    kljuc = r["kljuc"]
    kljucevi.append(kljuc)
    print("1. POST →", kljuc)

    # 2 + 3. GET
    d = req(f"/ugovori/{urllib.parse.quote(kljuc, safe='')}")
    print("2. GET nosilac")
    provera("datum_ow", d["datum_ow"], "2026-11-30")
    provera("destinacija_ow", d["destinacija_ow"], "TEST DEST OW")
    provera("mesto_sedenja", d["mesto_sedenja"], "Prednje")
    provera("placeno_prevoz", d["placeno_prevoz"], True)
    provera("zelja_prevoz", d["zelja_prevoz"], False)
    provera("datum_polaska (nosilac OW → NULL)", d["datum_polaska"], None)
    provera("destinacija_polaska (nosilac OW → NULL)", d["destinacija_polaska"], None)
    print("3. GET napomena_prevoz")
    provera("napomena_prevoz", d["napomena_prevoz"], "TEST napomena prevoz")

    sap = [p for p in d["putnici_detalji"] if p["saputnik"] == "TEST PREVOZ SAPUTNIK"]
    provera("saputnik nađen", len(sap), 1)
    sp = sap[0]
    print("2b. GET saputnik")
    provera("saputnik datum_polaska", sp["datum_polaska"], "2026-11-30")
    provera("saputnik destinacija_polaska", sp["destinacija_polaska"], "TEST DEST POL")
    provera("saputnik datum_povratka", sp["datum_povratka"], "2026-12-08")
    provera("saputnik destinacija_povratka", sp["destinacija_povratka"], "TEST DEST POV")
    provera("saputnik mesto_sedenja", sp["mesto_sedenja"], "Zadnje")
    provera("saputnik zelja_prevoz", sp["zelja_prevoz"], True)
    provera("saputnik datum_ow (RT → NULL)", sp["datum_ow"], None)

    # 4 + 5. PUT — nosilac OW→RT, saputnik RT→OW
    n2 = nosilac_base(rt=True, datumPolaska="2026-12-01", destinacijaPolaska="TEST DEST POL 2",
                      datumPovratka="2026-12-08", destinacijaPovratka="TEST DEST POV 2",
                      mestoSedenja="Sredina", placeno=False, zelja=True,
                      # stari OW podaci ostaju u formi — backend ih mora očistiti
                      datumOw="2026-11-30", destinacijaOw="TEST DEST OW")
    s2 = saputnik_base(ow=True, smer="Polazak", datumOw="2026-12-01", destinacijaOw="TEST DEST OW 2",
                       mestoSedenja="Prednje", placeno=True, zelja=False,
                       datumPolaska="2026-11-30", destinacijaPolaska="TEST DEST POL")
    req(f"/rezervacije/{urllib.parse.quote(kljuc, safe='')}", "PUT",
        payload(n2, s2, "TEST napomena izmenjena"))
    print("4. PUT izmena")
    d2 = req(f"/ugovori/{urllib.parse.quote(kljuc, safe='')}")
    provera("nosilac datum_polaska", d2["datum_polaska"], "2026-12-01")
    provera("nosilac destinacija_povratka", d2["destinacija_povratka"], "TEST DEST POV 2")
    provera("nosilac mesto_sedenja", d2["mesto_sedenja"], "Sredina")
    provera("nosilac placeno_prevoz", d2["placeno_prevoz"], False)
    provera("nosilac zelja_prevoz", d2["zelja_prevoz"], True)
    provera("napomena_prevoz izmenjena", d2["napomena_prevoz"], "TEST napomena izmenjena")
    print("5. Čišćenje neuključenog smera")
    provera("nosilac datum_ow (sada RT → NULL)", d2["datum_ow"], None)
    provera("nosilac destinacija_ow (sada RT → NULL)", d2["destinacija_ow"], None)
    sap2 = [p for p in d2["putnici_detalji"] if p["saputnik"] == "TEST PREVOZ SAPUTNIK"][0]
    provera("saputnik datum_ow", sap2["datum_ow"], "2026-12-01")
    provera("saputnik destinacija_ow", sap2["destinacija_ow"], "TEST DEST OW 2")
    provera("saputnik datum_polaska (sada OW → NULL)", sap2["datum_polaska"], None)
    provera("saputnik destinacija_povratka (NULL)", sap2["destinacija_povratka"], None)
    provera("saputnik placeno_prevoz", sap2["placeno_prevoz"], True)
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
    r = conn.execute(text("DELETE FROM aranzman WHERE putnik LIKE 'TEST PREVOZ%' AND kljuc IN (''' + klj_list + r''') RETURNING id"))
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
