"""API test — smestaj.napomena (TEXT, nullable).

Flow:
  1. POST bez napomene → napomena=None; POST sa napomenom → sačuvano.
  2. GET liste vraća napomenu.
  3. PUT menja napomenu; PUT sa null je briše.
  4. Cleanup: DELETE test smeštaja.
Pokretanje: uv run python test_smestaj_napomena.py (backend na 3158).
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
        base = {"naziv": "TEST-NAPOMENA", "mesto": None}
        r = api.post("/smestaj", json=base)
        assert r.status_code == 200, r.text
        s1 = r.json()
        ids.append(s1["id"])
        assert s1.get("napomena") is None, s1
        print("OK 1: POST bez napomene → null")

        r = api.post("/smestaj", json={**base, "naziv": "TEST-NAPOMENA2", "napomena": "Blizu plaže"})
        assert r.status_code == 200, r.text
        s2 = r.json()
        ids.append(s2["id"])
        assert s2["napomena"] == "Blizu plaže", s2
        print("OK 2: POST sa napomenom → sačuvano")

        lista = api.get("/smestaj").json()
        back = [s for s in lista if s["id"] == s2["id"]][0]
        assert back["napomena"] == "Blizu plaže", back
        print("OK 3: GET liste vraća napomenu")

        r = api.put(f"/smestaj/{s1['id']}", json={"napomena": "Ulaz sa zadnje strane"})
        assert r.status_code == 200, r.text
        assert r.json()["napomena"] == "Ulaz sa zadnje strane"
        print("OK 4: PUT menja napomenu")

        r = api.put(f"/smestaj/{s1['id']}", json={"napomena": None})
        assert r.status_code == 200, r.text
        assert r.json()["napomena"] is None, r.json()
        back = [s for s in api.get("/smestaj").json() if s["id"] == s1["id"]][0]
        assert back["napomena"] is None, back
        print("OK 5: PUT sa null briše napomenu")
    finally:
        for i in ids:
            api.delete(f"/smestaj/{i}")
        print("cleanup OK")


if __name__ == "__main__":
    main()
