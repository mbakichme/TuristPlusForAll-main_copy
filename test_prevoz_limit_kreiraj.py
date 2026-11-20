"""API test: POST /prevoz-limit/kreiraj kreira limite za sve datume destinacije prevoza bez duplikata."""
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


def check(name, cond):
    print(("OK  " if cond else "FAIL") + " " + name)
    if not cond:
        fails.append(name)


with eng.connect() as c:
    par = c.execute(text("""
        SELECT m.destinacija AS d, array_agg(DISTINCT pg.id ORDER BY pg.id) AS grupe
        FROM mesto_grupa mg
        JOIN mesto m ON m.id = mg.mesto_id
        JOIN period_grupa pg ON pg.id = mg.grupa_id
        WHERE m.destinacija IS NOT NULL
          AND pg.id NOT IN (SELECT id_grupe_termina FROM destinacija_prevoz_grupa)
        GROUP BY m.destinacija
        ORDER BY m.destinacija
        LIMIT 1
    """)).first()
    assert par, "nema destinacije sa slobodnom grupom termina"
    ocekivano = c.execute(text("""
        SELECT count(*) FROM (
            SELECT pd.datum_od AS datum, 'Odlazak' AS smer FROM period_datum pd WHERE pd.grupa_id = ANY(:g)
            UNION SELECT pd.datum_do, 'Povratak' FROM period_datum pd WHERE pd.grupa_id = ANY(:g)
        ) t
    """), {"g": list(par.grupe)}).scalar_one()

dp_id = None
with httpx.Client(timeout=60) as cl:
    r = cl.post(f"{BASE}/destinacija-prevoz", headers=H, json={"id_destinacije": par.d, "grupe": list(par.grupe)})
    check("kreiranje destinacije prevoza 201", r.status_code == 201)
    dp_id = r.json().get("id")
    try:
        r1 = cl.post(f"{BASE}/prevoz-limit/kreiraj", headers=H, json={"id_destinacije_prevoza": dp_id})
        check("prvi poziv 200/201", r1.status_code in (200, 201))
        j1 = r1.json()
        check(f"dodato == unique datumi ({ocekivano})", j1.get("dodato") == ocekivano)
        check("postojalo == 0 na prvom pozivu", j1.get("postojalo") == 0)

        r2 = cl.post(f"{BASE}/prevoz-limit/kreiraj", headers=H, json={"id_destinacije_prevoza": dp_id})
        j2 = r2.json()
        check("drugi poziv: dodato 0", j2.get("dodato") == 0)
        check("drugi poziv: postojalo == ukupno", j2.get("postojalo") == ocekivano)

        lst = cl.get(f"{BASE}/prevoz-limit", headers=H).json()
        mine = [i for i in lst if i["id_destinacije_prevoza"] == dp_id]
        check("u tabeli tačno jedan red po (datum, smer)",
              len({(i["datum"], i["smer"]) for i in mine}) == len(mine) == ocekivano)
        check("svi limiti kreću od 0", all(i["limit"] == 0 and i["dodatna_mesta"] == 0 for i in mine))

        r3 = cl.post(f"{BASE}/prevoz-limit/kreiraj", headers=H, json={"id_destinacije_prevoza": 999999})
        check("nepoznata destinacija prevoza → 400", r3.status_code == 400)
    finally:
        if dp_id:
            cl.delete(f"{BASE}/destinacija-prevoz/{dp_id}", headers=H)

with eng.connect() as c:
    left = c.execute(text("SELECT count(*) FROM prevoz_limit WHERE id_destinacije_prevoza = :i"),
                     {"i": dp_id or -1}).scalar()
check("cleanup: nema zaostalih limita", left == 0)

print("FAILS:", fails if fails else "none")
sys.exit(1 if fails else 0)
