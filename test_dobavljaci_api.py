"""API test: dobavljaci CRUD.

Pokretanje: uv run python test_dobavljaci_api.py
Kreira i menja samo sopstveni test red (naziv 'TEST-DOB-...'), na kraju ga brise.
Kopirani redovi se ne diraju.
"""

import os
import sys

import httpx
from sqlalchemy import text

from db_config import get_engine
from routes import create_access_token

API = os.environ.get("TEST_API_URL", "http://localhost:3158/api")
engine = get_engine()
token = create_access_token({"sub": "1"})
api = httpx.Client(base_url=API, headers={"Authorization": "Bearer " + token}, timeout=60)

fails = 0
TEST_NAZIV = "TEST-DOB-ZZ"


def check(naziv, uslov):
    global fails
    print(("OK   " if uslov else "FAIL ") + naziv)
    if not uslov:
        fails += 1


def obrisi_test_redove():
    with engine.begin() as c:
        c.execute(text("DELETE FROM dobavljaci WHERE naziv = :n"), {"n": TEST_NAZIV})


obrisi_test_redove()

with engine.connect() as c:
    pre_count = c.execute(text("SELECT COUNT(*) FROM dobavljaci")).scalar()

# 1. Kreiranje
r = api.post("/dobavljaci", json={"naziv": TEST_NAZIV, "mesto": "Beograd", "pib": "123456789"})
check("POST 201", r.status_code == 201)
new_id = r.json().get("id") if r.status_code == 201 else None
check("POST vraca id", isinstance(new_id, int))

# 2. Lista i pretraga
r = api.get("/dobavljaci", params={"q": TEST_NAZIV})
rows = r.json()["rows"]
check("GET q nalazi novi red", any(x["id"] == new_id for x in rows))
check("GET q=novi red ima mesto", next((x["mesto"] for x in rows if x["id"] == new_id), None) == "Beograd")

# 3. Izmena
r = api.put(f"/dobavljaci/{new_id}", json={"naziv": TEST_NAZIV + "-IZM", "mesto": "Novi Sad", "email": "a@b.rs"})
check("PUT 200", r.status_code == 200)
r = api.get("/dobavljaci", params={"q": TEST_NAZIV + "-IZM"})
izmenjen = next((x for x in r.json()["rows"] if x["id"] == new_id), None)
check("PUT menja naziv", izmenjen is not None)
check("PUT menja mesto", izmenjen is not None and izmenjen["mesto"] == "Novi Sad")
check("PUT menja email", izmenjen is not None and izmenjen["email"] == "a@b.rs")
check("PUT brise pib kad je prazan", izmenjen is not None and izmenjen["pib"] == "")

# 4. Validacija
r = api.post("/dobavljaci", json={"naziv": ""})
check("POST prazan naziv -> 422", r.status_code == 422)
r = api.put(f"/dobavljaci/{new_id}", json={"naziv": ""})
check("PUT prazan naziv -> 422", r.status_code == 422)

# 5. 404
r = api.put("/dobavljaci/999999999", json={"naziv": "x"})
check("PUT nepostojeci -> 404", r.status_code == 404)
r = api.delete("/dobavljaci/999999999")
check("DELETE nepostojeci -> 404", r.status_code == 404)

# 6. Brisanje
r = api.delete(f"/dobavljaci/{new_id}")
check("DELETE 200", r.status_code == 200)
r = api.get("/dobavljaci", params={"q": TEST_NAZIV})
check("posle DELETE red nestao", not any(x["id"] == new_id for x in r.json()["rows"]))

# 7. Kopirani redovi netaknuti
with engine.connect() as c:
    post_count = c.execute(text("SELECT COUNT(*) FROM dobavljaci")).scalar()
check("broj redova isti posle testa", post_count == pre_count)

obrisi_test_redove()
print(f"\n{'SVE PROLAZI' if fails == 0 else f'PADLO: {fails}'}")
sys.exit(1 if fails else 0)
