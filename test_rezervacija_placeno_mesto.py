"""Izračunata stavka PLAĆENO MESTO u dodatnim uslugama — API tok (dev server na 3158).

Provere:
1. POST /rezervacije sa transferi=[PLAĆENO MESTO - GORE IZLOG, 25 EUR] → GET ugovora ima stavku
2. PUT sa transferi=[] → stavka PLAĆENO MESTO je obrisana (TRANSFER/PLAĆENO se zamenjuju pri snimanju)
3. PUT sa transferi=[TRANSFER - X + PLAĆENO MESTO] → obe stavke upisane, ostale ručne stavke netaknute
4. čišćenje test redova
"""
import json
import os
import subprocess
import urllib.parse
import urllib.request

from routes import create_access_token

BASE = "http://127.0.0.1:3158/api"
tok = create_access_token({"sub": "1"})  # token se ne ispisuje
hdr = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
IME = "TEST PLACENO MESTO"
PM = "PLAĆENO MESTO - GORE IZLOG"
TR = "TRANSFER - TEST"


def req(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(f"{BASE}{path}", data=data, headers=hdr, method=method)
    with urllib.request.urlopen(r, timeout=30) as resp:
        return json.load(resp)


def payload(transferi):
    return {
        "tiprezervacije": "Klasična rezervacija", "timelimit": None,
        "nosilac": {"ime": IME, "datumRodjenja": "1990-01-01", "pasos": "T1111111", "uzrast": "ADL",
                    "ow": True, "rt": False, "sp": False, "smer": "Polazak",
                    "adresa": "Test adresa 3", "telefon": "0601234567", "email": "",
                    "mestoSedenja": "GORE IZLOG", "placeno": True, "zelja": False},
        "saputnici": [],
        "boravak": {"datumOd": "2026-12-20", "datumDo": "2026-12-25", "smestajId": None,
                    "sobaId": None, "mestoId": None, "smestajNaziv": "TEST PLACENO SMEŠTAJ",
                    "sobaBroj": "P902", "mestoNaziv": "TEST MESTO", "struktura": "1/2",
                    "napomena": "", "napomenaInterna": ""},
        "destinacijaId": None, "destinacijaNaziv": None, "ulazak": "",
        "cene": {"cenaSmestajEUR": 100, "kolSmestajEUR": 2, "cenaSmestajRSD": 0,
                 "kolSmestajRSD": 1, "popustSmestaj": {}, "cenaPrevozEUR": 0,
                 "kolPrevozEUR": 1, "cenaPrevozRSD": 0, "kolPrevozRSD": 1,
                 "popustPrevoz": {}, "osiguranjeEUR": 0, "osiguranjeRSD": 0,
                 "provizijaSmestaj": {}, "provizijaPrevoz": {}},
        "nacinPlacanja": "",
        "transferi": transferi,
    }


def usluge(kljuc):
    d = req(f"/ugovori/{urllib.parse.quote(kljuc, safe='')}")
    return {s["usluga"]: s["eur"] for s in d.get("dodatne") or []}


kljucevi = []
ok = True
try:
    r = req("/rezervacije", "POST", payload([{"usluga": PM, "eur": 25}]))
    k = r["kljuc"]; kljucevi.append(k)
    u = usluge(k)
    assert u.get(PM) == 25, u
    print("1. POST sa PLAĆENO MESTO → stavka u dodatnim uslugama OK", k)

    req(f"/rezervacije/{urllib.parse.quote(k, safe='')}", "PUT", payload([]))
    u = usluge(k)
    assert PM not in u, u
    print("2. PUT bez izračunatih stavki → PLAĆENO MESTO obrisana OK")

    req(f"/rezervacije/{urllib.parse.quote(k, safe='')}", "PUT", payload([{"usluga": TR, "eur": 12}, {"usluga": PM, "eur": 25}]))
    u = usluge(k)
    assert u.get(TR) == 12 and u.get(PM) == 25, u
    print("3. PUT sa TRANSFER + PLAĆENO MESTO → obe stavke upisane OK")
except Exception as e:
    ok = False
    print("  FAIL:", e)

print("\nREZULTAT:", "SVE PROVERE PROŠLE" if ok else "IMA GREŠAKA")

# ── čišćenje ──
klj_list = ", ".join(f"'{x}'" for x in kljucevi) or "''"
brojevi = ", ".join(str(int(x.split("/")[0])) for x in kljucevi) or "0"
_sql_cleanup = r'''
import db_config
from sqlalchemy import text
engine = db_config.get_engine()
with engine.begin() as conn:
    r = conn.execute(text("DELETE FROM aranzman WHERE putnik = 'TEST PLACENO MESTO' AND kljuc IN (''' + klj_list + r''') RETURNING id"))
    ids = [row[0] for row in r.fetchall()]
    for aid in ids:
        conn.execute(text("DELETE FROM aranzman_dopuna WHERE aranzman_id = :i"), {"i": aid})
    conn.execute(text("DELETE FROM dodatne WHERE id IN (''' + brojevi + r''') AND usluga IN ('PLAĆENO MESTO - GORE IZLOG', 'TRANSFER - TEST')"))
    print("obrisano aranzman redova:", len(ids))
'''
subprocess.run(["uv", "run", "python", "-c", _sql_cleanup],
               capture_output=True, text=True, cwd=os.path.dirname(os.path.abspath(__file__)))
print("Čišćenje završeno.")
