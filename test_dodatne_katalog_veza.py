"""API test: dodatna stavka ugovora vezana za katalog (dodatna_usluga_id).

Proverava: POST/PATCH sa vezom, 400 za nepostojeći katalog, brisanje kataloga
(FK ON DELETE SET NULL) — stavka ostaje sa svojim iznosima.
"""
import os
import sys

import httpx
from sqlalchemy import create_engine, text

sys.path.insert(0, os.getcwd())
from db_config import DB_URL_ENV  # noqa: E402
from routes import create_access_token  # noqa: E402

BASE = "http://127.0.0.1:3158/api"
H = {"Authorization": f"Bearer {create_access_token({'sub': '1'})}"}
eng = create_engine(os.environ.get(DB_URL_ENV))
fails = []
TEST_PREFIX = "TEST-DU-VEZA-"


def check(name, cond):
    print(("OK  " if cond else "FAIL") + " " + name)
    if not cond:
        fails.append(name)


with eng.connect() as conn:
    kljuc = conn.execute(text(
        "SELECT kljuc FROM aranzman WHERE kljuc ~ '^[0-9]+/[0-9]+$' ORDER BY kljuc LIMIT 1"
    )).scalar()

check("postoji aranzman za test", bool(kljuc))
stavke_ids = []

with httpx.Client(base_url=BASE, headers=H, timeout=30) as c:
    r = c.post("/dodatne-usluge", json={"naziv": f"{TEST_PREFIX}Izlet", "iznos_eur": 40, "iznos_din": 4700})
    check("katalog POST 201", r.status_code == 201)
    kat = r.json()
    kat_id = kat.get("id")

    r = c.post(f"/ugovori/{kljuc}/dodatne", json={"usluga": f"{TEST_PREFIX}Izlet", "eur": 40, "din": 4700, "dodatna_usluga_id": kat_id})
    check("stavka POST sa vezom 201", r.status_code == 201)
    s = r.json()
    stavke_ids.append(s.get("stavka_id"))
    check("POST vraća dodatna_usluga_id", s.get("dodatna_usluga_id") == kat_id)

    r = c.patch(f"/ugovori/{kljuc}/dodatne/{s['stavka_id']}", json={
        "usluga": f"{TEST_PREFIX}Izlet", "eur": 45, "din": 4700, "dodatna_usluga_id": kat_id,
        "original": {"usluga": f"{TEST_PREFIX}Izlet", "eur": 40, "din": 4700},
    })
    check("stavka PATCH zadrži vezu", r.status_code == 200 and r.json().get("dodatna_usluga_id") == kat_id)

    r = c.post(f"/ugovori/{kljuc}/dodatne", json={"usluga": "X", "eur": 1, "din": 1, "dodatna_usluga_id": 999999999})
    check("nepostojeći katalog 400", r.status_code == 400)

    r = c.get(f"/ugovori/{kljuc}")
    dod = (r.json() or {}).get("dodatne") or []
    mine = [d for d in dod if d.get("stavka_id") == s["stavka_id"]]
    check("ugovor detalj vraća dodatna_usluga_id", bool(mine) and mine[0].get("dodatna_usluga_id") == kat_id)

    r = c.delete(f"/dodatne-usluge/{kat_id}")
    check("brisanje kataloga 200", r.status_code == 200)

with eng.connect() as conn:
    row = conn.execute(text(
        "SELECT eur, din, dodatna_usluga_id FROM dodatne WHERE stavka_id = :s"
    ), {"s": s["stavka_id"]}).mappings().first()
    check("stavka ostaje posle brisanja kataloga", row is not None and float(row["eur"]) == 45.0)
    check("veza postaje NULL (SET NULL)", row is not None and row["dodatna_usluga_id"] is None)

with eng.begin() as conn:
    conn.execute(text("DELETE FROM dodatne WHERE stavka_id = ANY(:ids)"), {"ids": [i for i in stavke_ids if i]})
    conn.execute(text("DELETE FROM dodatne_usluge WHERE naziv LIKE :p"), {"p": f"{TEST_PREFIX}%"})

print("\nFAILS:", fails if fails else "none")
sys.exit(1 if fails else 0)
