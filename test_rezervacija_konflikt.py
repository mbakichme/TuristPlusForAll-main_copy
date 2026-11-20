"""Test zauzeća termina (sudar rezervacija) — offline prema dev serveru na 3158.

Provere:
1. POST /rezervacije → upis prvog boravka (201)
2. POST preklapajućeg boravka (ista soba) → 409 + zapis NIJE upisan
3. POST naslonjenog boravka (dolazak na dan odjave) → 201 (ista konvencija kao /slobodne-sobe)
4. PUT prvog boravka u period drugog → 409
5. PUT istog ugovora bez promene perioda → prolazi (izuzima sebe)
6. POST iste sobe u istom periodu ALI druga soba → 201 (bez lažnih sudara)
7. čišćenje test redova
"""
import json
import urllib.error
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


def ocekuj_gresku(path, method, body, ocekivani_kod, frasa):
    try:
        req(path, method, body)
    except urllib.error.HTTPError as e:
        detail = json.loads(e.read().decode()).get("detail", "")
        assert e.code == ocekivani_kod, f"kod {e.code} != {ocekivani_kod}: {detail}"
        assert frasa in detail, f"u poruci fali {frasa!r}: {detail}"
        print(f"  OK {method} {ocekivani_kod}: {detail}")
        return detail
    raise AssertionError(f"{method} je prošao, a očekivana greška {ocekivani_kod}")


SME = "TEST KONFLIK SMEŠTAJ"


def payload(ime, od, do, soba):
    return {
        "tiprezervacije": "Klasična rezervacija", "timelimit": None,
        "nosilac": {"ime": ime, "datumRodjenja": "1990-01-01", "pasos": "T1234567",
                    "ow": True, "rt": False, "sp": False, "smer": "Polazak",
                    "adresa": "Test adresa 1", "telefon": "0601234567", "email": ""},
        "saputnici": [],
        "boravak": {"datumOd": od, "datumDo": do, "smestajId": None, "sobaId": None,
                    "mestoId": None, "smestajNaziv": SME, "sobaBroj": soba,
                    "mestoNaziv": "TEST MESTO", "struktura": "1/2",
                    "napomena": "", "napomenaInterna": ""},
        "destinacijaId": None, "destinacijaNaziv": None, "ulazak": "",
        "cene": {"cenaSmestajEUR": 100, "kolSmestajEUR": 2, "cenaSmestajRSD": 0,
                 "kolSmestajRSD": 1, "popustSmestaj": {}, "cenaPrevozEUR": 0,
                 "kolPrevozEUR": 1, "cenaPrevozRSD": 0, "kolPrevozRSD": 1,
                 "popustPrevoz": {}, "osiguranjeEUR": 0, "osiguranjeRSD": 0,
                 "provizijaSmestaj": {}, "provizijaPrevoz": {}},
    }


kljucevi = []
ok = True
try:
    # 1. prvi boravak: 10.11. → 15.11. (soba T901)
    rA = req("/rezervacije", "POST", payload("TEST KONFLIK A", "2026-11-10", "2026-11-15", "T901"))
    kljucA = rA["kljuc"]; kljucevi.append(kljucA)
    print("1. POST A →", kljucA)

    # 2. preklapajući boravak istom sobom → 409, NE upisuje se
    ocekuj_gresku("/rezervacije", "POST",
                  payload("TEST KONFLIK B", "2026-11-13", "2026-11-18", "T901"),
                  409, "zauzet")
    d = req(f"/ugovori/{urllib.parse.quote(kljucA, safe='')}")
    print("2. POST preklapanje → 409, upis blokiran")
except Exception as e:
    ok = False
    print("  FAIL:", e)

# broj zapisa B u bazi (mora 0) — direktna SQL provera
import os
import subprocess
_sql_broj_b = r'''
import db_config
from sqlalchemy import text
engine = db_config.get_engine()
with engine.connect() as conn:
    print(conn.execute(text("SELECT count(*) FROM aranzman WHERE putnik = 'TEST KONFLIK B'")).scalar_one())
'''
n_b = int(subprocess.run(["uv", "run", "python", "-c", _sql_broj_b],
                         capture_output=True, text=True, cwd=os.path.dirname(os.path.abspath(__file__))).stdout.strip() or -1)
if n_b != 0:
    ok = False
    print(f"  FAIL: zapis B je upisan u bazu ({n_b})!")
else:
    print("  OK zapis B NEMA u bazi (0 redova)")

try:
    # 3. naslonjeni boravak (dolazak na dan odjave A) → dozvoljen
    rC = req("/rezervacije", "POST", payload("TEST KONFLIK C", "2026-11-15", "2026-11-18", "T901"))
    kljucC = rC["kljuc"]; kljucevi.append(kljucC)
    print("3. POST naslonjeni →", kljucC)

    # 4. PUT A u period C-a → 409
    pA = payload("TEST KONFLIK A", "2026-11-14", "2026-11-20", "T901")
    ocekuj_gresku(f"/rezervacije/{urllib.parse.quote(kljucA, safe='')}", "PUT", pA, 409, kljucC.split("/")[0])

    # 5. PUT A bez promene perioda → prolazi (izuzima sebe)
    pA2 = payload("TEST KONFLIK A", "2026-11-10", "2026-11-15", "T901")
    pA2["boravak"]["napomena"] = "izmena bez promene termina"
    req(f"/rezervacije/{urllib.parse.quote(kljucA, safe='')}", "PUT", pA2)
    dA = req(f"/ugovori/{urllib.parse.quote(kljucA, safe='')}")
    assert dA["napomena"] == "izmena bez promene termina"
    print("5. PUT A bez promene termina → OK (self-exclusion)")

    # 6. ista soba-naziv ali druga soba (T902) u istom periodu → dozvoljeno
    rD = req("/rezervacije", "POST", payload("TEST KONFLIK D", "2026-11-12", "2026-11-16", "T902"))
    kljucevi.append(rD["kljuc"])
    print("6. POST druga soba isti period →", rD["kljuc"])
except Exception as e:
    ok = False
    print("  FAIL:", e)

print("\nREZULTAT:", "SVE PROVERE PROŠLE" if ok else "IMA GREŠAKA")

# ── čišćenje ──
klj_list = ", ".join(f"'{k}'" for k in kljucevi)
_sql_cleanup = r'''
import db_config
from sqlalchemy import text
engine = db_config.get_engine()
with engine.begin() as conn:
    r = conn.execute(text("DELETE FROM aranzman WHERE putnik LIKE 'TEST KONFLIK%' AND kljuc IN (''' + klj_list + r''') RETURNING id"))
    ids = [row[0] for row in r.fetchall()]
    n = 0
    for aid in ids:
        n += conn.execute(text("DELETE FROM aranzman_dopuna WHERE aranzman_id = :i"), {"i": aid}).rowcount
    print(f"obrisano: aranzman redova={len(ids)}, dopuna redova={n}")
    ostalo = conn.execute(text("SELECT count(*) FROM aranzman WHERE putnik LIKE 'TEST KONFLIK%'")).scalar_one()
    print("ostalo test redova:", ostalo)
'''
subprocess.run(["uv", "run", "python", "-c", _sql_cleanup],
               capture_output=True, text=True, cwd=os.path.dirname(os.path.abspath(__file__)))
print("Test redovi su obrisani iz baze.")
