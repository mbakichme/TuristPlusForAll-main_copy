"""API test: /dodatne-usluge — GET lista, POST kreiranje, validacija i zaokruživanje iznosa."""
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
TEST_PREFIX = "TEST-DU-"


def check(name, cond):
    print(("OK  " if cond else "FAIL") + " " + name)
    if not cond:
        fails.append(name)


with httpx.Client(base_url=BASE, headers=H, timeout=30) as c:
    r = c.get("/dodatne-usluge")
    check("GET 200 i lista", r.status_code == 200 and isinstance(r.json(), list))
    pre = len(r.json())

    r = c.post("/dodatne-usluge", json={"naziv": f"{TEST_PREFIX}Transfer", "iznos_eur": 25, "iznos_din": 2950})
    check("POST 201", r.status_code == 201)
    body = r.json() if r.status_code == 201 else {}
    check("POST vraća naziv/iznose", body.get("naziv") == f"{TEST_PREFIX}Transfer"
          and body.get("iznos_eur") == 25.0 and body.get("iznos_din") == 2950.0)

    r = c.post("/dodatne-usluge", json={"naziv": f"  {TEST_PREFIX}Trim  ", "iznos_eur": 12.345, "iznos_din": 0})
    check("naziv se trimuje, iznos se zaokružuje na 2 dec (12.345 → 12.35)",
          r.status_code == 201 and r.json()["naziv"] == f"{TEST_PREFIX}Trim" and r.json()["iznos_eur"] == 12.35)

    r = c.post("/dodatne-usluge", json={"naziv": f"{TEST_PREFIX}Bez iznosa"})
    check("iznosi su opcioni (default 0)", r.status_code == 201 and r.json()["iznos_eur"] == 0.0 and r.json()["iznos_din"] == 0.0)

    r = c.post("/dodatne-usluge", json={"naziv": "   ", "iznos_eur": 1, "iznos_din": 1})
    check("prazan naziv → 422", r.status_code == 422)

    r = c.post("/dodatne-usluge", json={"iznos_eur": 1, "iznos_din": 1})
    check("naziv obavezan → 422", r.status_code == 422)

    r = c.post("/dodatne-usluge", json={"naziv": f"{TEST_PREFIX}Minus", "iznos_eur": -1, "iznos_din": 0})
    check("negativan EUR → 422", r.status_code == 422)

    r = c.post("/dodatne-usluge", json={"naziv": f"{TEST_PREFIX}Minus", "iznos_eur": 0, "iznos_din": -5})
    check("negativan DIN → 422", r.status_code == 422)

    r = c.post("/dodatne-usluge", json={"naziv": f"{TEST_PREFIX}Velik", "iznos_eur": 1e13, "iznos_din": 0})
    check("prevelik iznos → 422", r.status_code == 422)

    lista = c.get("/dodatne-usluge").json()
    check("lista uvećana za 3 (uspešna POST-a)", len(lista) == pre + 3)
    check("lista sortirana po nazivu", [u["naziv"] for u in lista] == sorted(u["naziv"] for u in lista))

r = httpx.get(BASE + "/dodatne-usluge", timeout=30)
check("GET bez tokena → 401", r.status_code == 401)

with eng.begin() as conn:
    deleted = conn.execute(text("DELETE FROM dodatne_usluge WHERE naziv LIKE :p"), {"p": TEST_PREFIX + "%"}).rowcount
print(f"cleanup: obrisano test redova = {deleted}")

print("\nREZULTAT:", "SVE PROŠLO" if not fails else f"PAO {len(fails)}: {fails}")
sys.exit(1 if fails else 0)
