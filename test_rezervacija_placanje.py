"""Način plaćanja rezervacije — API tok (offline prema dev serveru na 3158).

Provere:
1. POST /rezervacije sa nacinPlacanja="delimicno" → GET ugovora vraća "delimicno"
2. PUT istog ugovora sa "u_celosti" → GET vraća "u_celosti" (izmena postojećeg ugovora)
3. PUT sa "" (bez izbora) → GET vraća null
4. Nepoznata vrednost ("xyz") → upisuje se kao null (whitelist)
5. čišćenje test redova
"""
import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request

from routes import create_access_token

BASE = "http://127.0.0.1:3158/api"
tok = create_access_token({"sub": "1"})  # token se ne ispisuje
hdr = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
IME = "TEST PLACANJE"


def req(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(f"{BASE}{path}", data=data, headers=hdr, method=method)
    with urllib.request.urlopen(r, timeout=30) as resp:
        return json.load(resp)


def payload(placanje):
    return {
        "tiprezervacije": "Klasična rezervacija", "timelimit": None,
        "nosilac": {"ime": IME, "datumRodjenja": "1990-01-01", "pasos": "T7654321", "uzrast": "ADL",
                    "ow": True, "rt": False, "sp": False, "smer": "Polazak",
                    "adresa": "Test adresa 2", "telefon": "0601234567", "email": ""},
        "saputnici": [],
        "boravak": {"datumOd": "2026-12-10", "datumDo": "2026-12-15", "smestajId": None,
                    "sobaId": None, "mestoId": None, "smestajNaziv": "TEST PLACANJE SMEŠTAJ",
                    "sobaBroj": "P901", "mestoNaziv": "TEST MESTO", "struktura": "1/2",
                    "napomena": "", "napomenaInterna": ""},
        "destinacijaId": None, "destinacijaNaziv": None, "ulazak": "",
        "cene": {"cenaSmestajEUR": 100, "kolSmestajEUR": 2, "cenaSmestajRSD": 0,
                 "kolSmestajRSD": 1, "popustSmestaj": {}, "cenaPrevozEUR": 0,
                 "kolPrevozEUR": 1, "cenaPrevozRSD": 0, "kolPrevozRSD": 1,
                 "popustPrevoz": {}, "osiguranjeEUR": 0, "osiguranjeRSD": 0,
                 "provizijaSmestaj": {}, "provizijaPrevoz": {}},
        "nacinPlacanja": placanje,
    }


def nacin(kljuc):
    return req(f"/ugovori/{urllib.parse.quote(kljuc, safe='')}").get("nacin_placanja")


kljucevi = []
ok = True
try:
    r = req("/rezervacije", "POST", payload("delimicno"))
    k = r["kljuc"]; kljucevi.append(k)
    assert nacin(k) == "delimicno", nacin(k)
    print("1. POST delimicno → GET delimicno OK", k)

    req(f"/rezervacije/{urllib.parse.quote(k, safe='')}", "PUT", payload("u_celosti"))
    assert nacin(k) == "u_celosti", nacin(k)
    print("2. PUT u_celosti → GET u_celosti OK")

    req(f"/rezervacije/{urllib.parse.quote(k, safe='')}", "PUT", payload(""))
    assert nacin(k) is None, nacin(k)
    print("3. PUT bez izbora → GET null OK")

    req(f"/rezervacije/{urllib.parse.quote(k, safe='')}", "PUT", payload("xyz"))
    assert nacin(k) is None, nacin(k)
    print("4. PUT nepoznata vrednost → null OK (whitelist)")
except Exception as e:
    ok = False
    print("  FAIL:", e)

print("\nREZULTAT:", "SVE PROVERE PROŠLE" if ok else "IMA GREŠAKA")

# ── čišćenje ──
klj_list = ", ".join(f"'{x}'" for x in kljucevi) or "''"
_sql_cleanup = r'''
import db_config
from sqlalchemy import text
engine = db_config.get_engine()
with engine.begin() as conn:
    r = conn.execute(text("DELETE FROM aranzman WHERE putnik = 'TEST PLACANJE' AND kljuc IN (''' + klj_list + r''') RETURNING id"))
    ids = [row[0] for row in r.fetchall()]
    for aid in ids:
        conn.execute(text("DELETE FROM aranzman_dopuna WHERE aranzman_id = :i"), {"i": aid})
    print("obrisano aranzman redova:", len(ids))
'''
subprocess.run(["uv", "run", "python", "-c", _sql_cleanup],
               capture_output=True, text=True, cwd=os.path.dirname(os.path.abspath(__file__)))
print("Čišćenje završeno.")
