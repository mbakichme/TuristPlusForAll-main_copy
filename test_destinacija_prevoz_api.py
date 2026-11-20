"""API test: više destinacija prevoza za istu destinaciju; grupa termina samo jednom."""
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

with eng.connect() as c:
    par = c.execute(text("""
        SELECT m.destinacija AS d, array_agg(DISTINCT pg.id ORDER BY pg.id) AS grupe
        FROM mesto_grupa mg
        JOIN mesto m ON m.id = mg.mesto_id
        JOIN period_grupa pg ON pg.id = mg.grupa_id
        WHERE m.destinacija IS NOT NULL
        GROUP BY m.destinacija
        HAVING count(DISTINCT pg.id) >= 2
        ORDER BY m.destinacija
        LIMIT 1
    """)).first()
assert par, "nema destinacije sa bar 2 grupe"
dest, grupe = par.d, list(par.grupe)
g1, g2 = grupe[0], grupe[1]
print("destinacija", dest, "grupe", g1, g2)

fails = []


def check(name, cond):
    print(("OK  " if cond else "FAIL") + " " + name)
    if not cond:
        fails.append(name)


created = []
with httpx.Client(timeout=30) as cl:
    r1 = cl.post(f"{BASE}/destinacija-prevoz", headers=H, json={"id_destinacije": dest, "grupe": [g1]})
    check("prvi POST 201", r1.status_code == 201)
    dp1 = r1.json().get("id") if r1.status_code == 201 else None
    if dp1:
        created.append(dp1)
    r2 = cl.post(f"{BASE}/destinacija-prevoz", headers=H, json={"id_destinacije": dest, "grupe": [g2]})
    check("drugi POST za istu destinaciju 201 (druge grupe)", r2.status_code == 201)
    dp2 = r2.json().get("id") if r2.status_code == 201 else None
    if dp2:
        created.append(dp2)
    r3 = cl.post(f"{BASE}/destinacija-prevoz", headers=H, json={"id_destinacije": dest, "grupe": [g1]})
    check("POST sa zauzetom grupom g1 → 409", r3.status_code == 409)
    if dp2:
        r4 = cl.put(f"{BASE}/destinacija-prevoz/{dp2}", headers=H, json={"grupe": [g1]})
        check("PUT dp2 na zauzetu g1 → 409", r4.status_code == 409)
    lst = cl.get(f"{BASE}/destinacija-prevoz", headers=H).json()
    mine = [i for i in lst if i["id"] in created]
    check("lista vraća obe destinacije prevoza", len(mine) == len(created))
    for dp in created:
        cl.delete(f"{BASE}/destinacija-prevoz/{dp}", headers=H)

with eng.connect() as c:
    left = c.execute(text("SELECT count(*) FROM destinacija_prevoz WHERE id = ANY(:ids)"),
                     {"ids": created or [-1]}).scalar()
check("cleanup: test zapisi obrisani", left == 0)

print("FAILS:", fails if fails else "none")
sys.exit(1 if fails else 0)
