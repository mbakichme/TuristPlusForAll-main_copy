"""API test: naziv destinacije prevoza može da se zada pri kreiranju i menja pri izmeni.

Nema slobodnih grupa termina, pa se test ne kreira novi zapis: validacija se proverava
bez upisa (422 pre baze), a promena naziva radi se na postojećem zapisu uz vraćanje originalnog.
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


def check(name, cond):
    print(("OK  " if cond else "FAIL") + " " + name)
    if not cond:
        fails.append(name)


def naziv_u_bazi(dp_id: int) -> str | None:
    with eng.connect() as c:
        return c.execute(text("SELECT naziv FROM destinacija_prevoz WHERE id = :i"), {"i": dp_id}).scalar()


with eng.connect() as c:
    red = c.execute(text("""
        SELECT dp.id, array_agg(dpg.id_grupe_termina ORDER BY dpg.id_grupe_termina) AS grupe
        FROM destinacija_prevoz dp
        JOIN destinacija_prevoz_grupa dpg ON dpg.destinacija_prevoz_id = dp.id
        GROUP BY dp.id ORDER BY dp.id LIMIT 1
    """)).first()
assert red, "nema postojeće destinacije prevoza"
dp_id, grupe = red.id, list(red.grupe)
original = naziv_u_bazi(dp_id)
print("dp", dp_id, "grupe", grupe, "naziv", original)

with httpx.Client(timeout=30) as cl:
    try:
        r = cl.put(f"{BASE}/destinacija-prevoz/{dp_id}", headers=H,
                   json={"grupe": grupe, "naziv": "   "})
        check("PUT sa praznim nazivom → 422", r.status_code == 422)
        check("prazan naziv nije upisan", naziv_u_bazi(dp_id) == original)

        r = cl.post(f"{BASE}/destinacija-prevoz", headers=H,
                    json={"id_destinacije": 1, "grupe": [grupe[0]], "naziv": ""})
        check("POST sa praznim nazivom → 422", r.status_code == 422)

        r = cl.put(f"{BASE}/destinacija-prevoz/{dp_id}", headers=H,
                   json={"grupe": grupe, "naziv": "  TEST izmenjen  "})
        check("PUT menja naziv 200", r.status_code == 200)
        check("naziv u bazi promenjen i očišćen (trim)", naziv_u_bazi(dp_id) == "TEST izmenjen")

        r = cl.put(f"{BASE}/destinacija-prevoz/{dp_id}", headers=H, json={"grupe": grupe})
        check("PUT bez naziva zadržava naziv", r.status_code == 200 and naziv_u_bazi(dp_id) == "TEST izmenjen")
    finally:
        with eng.begin() as c:
            c.execute(text("UPDATE destinacija_prevoz SET naziv = :n WHERE id = :i"),
                      {"n": original, "i": dp_id})

check("originalni naziv vraćen", naziv_u_bazi(dp_id) == original)
print("FAILS:", fails if fails else "none")
sys.exit(1 if fails else 0)
