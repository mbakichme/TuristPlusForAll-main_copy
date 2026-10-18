"""API test — smestaj.granica_chd (default 6.99, CRUD).

Flow:
  1. Postojeći smeštaji svi imaju granica_chd (default 6.99 posle ALTER-a).
  2. POST bez granica_chd → 6.99; POST sa 5.5 → 5.5.
  3. PUT menja na 7.25; GET vraća 7.25.
  4. Cleanup: DELETE test smeštaja.
Pokretanje: uv run python test_smestaj_granica_chd.py (backend na 3158).
"""
import os

import httpx

from routes import create_access_token

API = os.environ.get("TEST_API_URL", "http://localhost:3158/api")


def main():
    token = create_access_token({"sub": "1"})
    api = httpx.Client(base_url=API, headers={"Authorization": "Bearer " + token}, timeout=30)
    ids = []
    try:
        lista = api.get("/smestaj").json()
        assert lista, "nema smeštaja"
        assert all("granica_chd" in s for s in lista), "polje nedostaje u listi"
        assert all(float(s["granica_chd"]) == 6.99 for s in lista), [s["granica_chd"] for s in lista if float(s["granica_chd"]) != 6.99]
        print(f"OK 1: {len(lista)} postojećih smeštaja ima granica_chd=6.99")

        base = {"naziv": "TEST-CHD", "status": 1, "grafik": 0}
        r = api.post("/smestaj", json=base)
        assert r.status_code == 200, r.text
        s1 = r.json(); ids.append(s1["id"])
        assert float(s1["granica_chd"]) == 6.99, s1
        print("OK 2a: POST bez granice → 6.99")

        r = api.post("/smestaj", json={**base, "naziv": "TEST-CHD2", "granica_chd": 5.5})
        assert r.status_code == 200, r.text
        s2 = r.json(); ids.append(s2["id"])
        assert float(s2["granica_chd"]) == 5.5, s2
        print("OK 2b: POST sa 5.5 → 5.5")

        r = api.put(f"/smestaj/{s1['id']}", json={"granica_chd": 7.25})
        assert r.status_code == 200, r.text
        assert float(r.json()["granica_chd"]) == 7.25, r.text
        back = [s for s in api.get("/smestaj").json() if s["id"] == s1["id"]][0]
        assert float(back["granica_chd"]) == 7.25, back
        print("OK 3: PUT 7.25 → GET 7.25")
    finally:
        for i in ids:
            api.delete(f"/smestaj/{i}")
        print("cleanup: obrisani test smeštaji", ids)


if __name__ == "__main__":
    main()
