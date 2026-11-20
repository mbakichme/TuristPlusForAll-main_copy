"""Test Rezervacije (Sačuvaj/Izmeni) API-ja — offline prema dev serveru na 3158.

Provere:
1. POST /rezervacije → novi broj = MAX(broj) godine iz Datuma od + 1
2. GET /ugovori/{kljuc} → round-trip sačuvanih polja
3. PUT /rezervacije/{kljuc} → izmena polja, saputnici, konverzija iznosa u procenat
4. čišćenje test redova iz baze
"""
import json
import os
import urllib.parse
import urllib.request

from routes import create_access_token

BASE = "http://127.0.0.1:3158/api"
tok = create_access_token({"sub": "1"})
hdr = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def req(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(f"{BASE}{path}", data=data, headers=hdr, method=method)
    with urllib.request.urlopen(r, timeout=30) as resp:
        return json.load(resp)


# očekivani broj: MAX preko split_part u bazi
import subprocess
sql_probe = r'''
import db_config
from sqlalchemy import text
engine = db_config.get_engine()
with engine.connect() as conn:
    m = conn.execute(text("SELECT COALESCE(MAX(split_part(kljuc,'/',1)::bigint),0) FROM aranzman "
                          "WHERE split_part(kljuc,'/',1) ~ '^[0-9]+$' AND split_part(kljuc,'/',2)='26'")).scalar_one()
    print(m)
'''
ocekivani_broj = int(subprocess.run(
    ["uv", "run", "python", "-c", sql_probe], capture_output=True, text=True).stdout.strip()) + 1

payload = {
    "tiprezervacije": "Klasična rezervacija",
    "timelimit": None,
    "nosilac": {
        "ime": "TEST TESTIC", "datumRodjenja": "1990-01-01", "pasos": "T1234567",
        "ow": True, "rt": False, "sp": False, "smer": "Polazak",
        "adresa": "Test adresa 1", "telefon": "0601234567", "email": "test@example.com",
    },
    "saputnici": [{
        "ime": "TEST SAPUTNIK", "datumRodjenja": "1992-03-04", "pasos": "T7654321",
        "ow": True, "rt": False, "sp": False, "smer": "Polazak",
        "adresa": "", "telefon": "", "email": "", "ulazak": "BEOGRAD Test ulaz",
    }],
    "boravak": {
        "datumOd": "2026-10-20", "datumDo": "2026-10-27",
        "smestajId": None, "sobaId": None, "mestoId": None,
        "smestajNaziv": "TEST SMEŠTAJ", "sobaBroj": "999", "mestoNaziv": "TEST MESTO",
        "struktura": "1/2", "napomena": "Test napomena", "napomenaInterna": "Interna napomena",
    },
    "destinacijaId": None, "destinacijaNaziv": "TEST DESTINACIJA",
    "ulazak": "BEOGRAD Test ulaz",
    "cene": {
        "cenaSmestajEUR": 100, "kolSmestajEUR": 2, "cenaSmestajRSD": 0, "kolSmestajRSD": 1,
        "popustSmestaj": {"pct": 10},
        "cenaPrevozEUR": 55, "kolPrevozEUR": 2, "cenaPrevozRSD": 0, "kolPrevozRSD": 1,
        "popustPrevoz": {},
        "osiguranjeEUR": 5.5, "osiguranjeRSD": 0,
        "provizijaSmestaj": {"pct": 5},
        "provizijaPrevoz": {"eur": 10},
    },
}

print("Očekivani broj:", f"{ocekivani_broj}/26")
r = req("/rezervacije", "POST", payload)
kljuc = r["kljuc"]
print("POST →", r)
assert kljuc == f"{ocekivani_broj}/26", f"BAD broj: {kljuc} != {ocekivani_broj}/26"

d = req(f"/ugovori/{urllib.parse.quote(kljuc, safe='')}")
print("GET → kljuc:", d["kljuc"])
provere = [
    ("putnik", d["putnik"], "TEST TESTIC"),
    ("rodjen", d["rodjen"], "01.01.1990"),
    ("pasos", d["pasos"], "T1234567"),
    ("adresa", d["adresa"], "Test adresa 1"),
    ("refno(email)", d["refno"], "test@example.com"),
    ("prevozow", d["prevozow"], 1),
    ("smer", d["smer"], "Polazak"),
    ("mesto", d["mesto"], "TEST MESTO"),
    ("naziv", d["naziv"], "TEST SMEŠTAJ"),
    ("soba", d["soba"], "999"),
    ("destinacija", d["destinacija"], "TEST DESTINACIJA"),
    ("apartman", d["apartman"], "1/2"),
    ("datumod", d["datumod"], "20.10.2026"),
    ("datumdo", d["datumdo"], "27.10.2026"),
    ("cenaaranz", d["cenaaranz"], 100.0),
    ("kolaranz", d["kolaranz"], 2.0),
    ("popustar", d["popustar"], 10.0),
    ("procenatar", d["procenatar"], 5.0),
    ("cenaow", d["cenaow"], 55.0),
    ("kolow", d["kolow"], 2),
    ("osiguranje1", d["osiguranje1"], 5.5),
    ("tiprezervacije", d["tiprezervacije"], "Klasična rezervacija"),
]
ok = True
for naziv_, stvarno, ocekivano in provere:
    if stvarno != ocekivano:
        print(f"  FAIL {naziv_}: {stvarno!r} != {ocekivano!r}")
        ok = False

# kolone koje API ne vraća → direktno iz baze
_sql_col = r'''
import os, json
import db_config
from sqlalchemy import text
engine = db_config.get_engine()
with engine.connect() as conn:
    row = conn.execute(text("SELECT procenatpr, popustpr, obradio, cenaaranzd, cenadrt, cenadow, datumoddo FROM aranzman WHERE kljuc = :k"),
                       {"k": "''' + kljuc + r'''"}).fetchone()
    print(json.dumps({"procenatpr": row.procenatpr, "obradio": row.obradio, "cenaaranzd": row.cenaaranzd,
                      "cenadrt": row.cenadrt, "cenadow": row.cenadow, "datumoddo": row.datumoddo}))
'''
def db_kolone():
    _p = subprocess.run(["uv", "run", "python", "-c", _sql_col], capture_output=True, text=True)
    return json.loads(_p.stdout)

_db = db_kolone()
for naziv_, stvarno, ocekivano in [
    ("procenatpr(DB)", _db["procenatpr"], 5.0),
    ("obradio(DB)", _db["obradio"], "Super Admin"),
]:
    if stvarno != ocekivano:
        print(f"  FAIL {naziv_}: {stvarno!r} != {ocekivano!r}")
        ok = False
print(f"procenatpr (DB) = {_db['procenatpr']} (očekivano 5.0 — iznos 10 EUR / 2 osobe); obradio = {_db['obradio']!r}")
assert len(d["putnici_detalji"]) == 1 and d["putnici_detalji"][0]["saputnik"] == "TEST SAPUTNIK", d["putnici_detalji"]
assert d["putnici_detalji"][0]["ulazak"] == "BEOGRAD Test ulaz"
print("putnici_detalji: OK (saputnik + ulazak)")

# ── PUT: izmena imena + popust kao IZNOS (20 EUR od 200 → 10%), novi saputnik ──
payload["nosilac"]["ime"] = "TEST TESTIC IZMENJEN"
payload["nosilac"]["ow"] = False
payload["nosilac"]["rt"] = True
payload["nosilac"]["smer"] = ""
payload["saputnici"].append({
    "ime": "TEST SAPUTNIK 2", "datumRodjenja": None, "pasos": "",
    "ow": False, "rt": True, "sp": False, "smer": "",
    "adresa": "", "telefon": "", "email": "", "ulazak": "NOVI SAD Test",
})
payload["cene"]["popustSmestaj"] = {"eur": 20}
payload["cene"]["provizijaPrevoz"] = {"rsd": 2400}  # 2400/2 = 1200 po osobi (RSD kol)
payload["boravak"]["struktura"] = "1/1"
req(f"/rezervacije/{urllib.parse.quote(kljuc, safe='')}", "PUT", payload)
print("PUT → ok")

d2 = req(f"/ugovori/{urllib.parse.quote(kljuc, safe='')}")
provere2 = [
    ("putnik", d2["putnik"], "TEST TESTIC IZMENJEN"),
    ("prevozrt", d2["prevozrt"], 1),
    ("cenart", d2["cenart"], 55.0),
    ("cenaow", d2["cenaow"], 0.0),
    ("popustar(20/200)", d2["popustar"], 10.0),
    ("apartman", d2["apartman"], "1/1"),
]
for naziv_, stvarno, ocekivano in provere2:
    if stvarno != ocekivano:
        print(f"  FAIL {naziv_}: {stvarno!r} != {ocekivano!r}")
        ok = False
imena = [p["saputnik"] for p in d2["putnici_detalji"]]
assert imena == ["TEST SAPUTNIK", "TEST SAPUTNIK 2"], imena
print("saputnici posle PUT:", imena)

# procenatpr posle PUT: iznos je RSD → deli se sa RSD količinom (1) = 2400 po osobi
_db2 = db_kolone()
if _db2["procenatpr"] != 2400.0:
    print(f"  FAIL procenatpr posle PUT (DB): {_db2['procenatpr']!r} != 2400.0")
    ok = False
print(f"procenatpr posle PUT (DB) = {_db2['procenatpr']} (očekivano 2400.0 — 2400 RSD / RSD količina 1)")
if _db2["datumoddo"] != "20.10.2026-27.10.2026":
    print(f"  FAIL datumoddo (DB): {_db2['datumoddo']!r}")
    ok = False
print(f"datumoddo (DB) = {_db2['datumoddo']!r}")

print("\nREZULTAT:", "SVE PROVERE PROŠLE" if ok else "IMA GREŠAKA")

# ── čišćenje test redova ──
sql_cleanup = r'''
import db_config
from sqlalchemy import text
engine = db_config.get_engine()
with engine.begin() as conn:
    r = conn.execute(text("DELETE FROM aranzman WHERE putnik LIKE 'TEST TESTIC%' AND kljuc = :k RETURNING id"),
                     {"k": "''' + kljuc + r'''"})
    aid = r.scalar()
    n = conn.execute(text("DELETE FROM aranzman_dopuna WHERE aranzman_id = :i"), {"i": aid}).rowcount
    print(f"obrisano: aranzman id={aid}, dopuna redova={n}")
'''
subprocess.run(["uv", "run", "python", "-c", sql_cleanup], capture_output=True, text=True)
print("Test redovi su obrisani iz baze.")
