"""API test — smestaj.popular (bool, default false) i smestaj.provizija (int 0-100, default 10).

Flow:
  1. Postojeći smeštaji imaju popular/provizija (provizija=10 posle ALTER-a).
  2. POST bez polja → popular=False, provizija=10; POST sa popular=True, provizija=15 → sačuvano.
  3. PUT menja provizija=0 (validno, ne sme biti tretirano kao prazno) i popular=False; GET vraća.
  4. Validacija: provizija 101 / -1 → 422.
  5. Cleanup: DELETE test smeštaja.
Pokretanje: uv run python test_smestaj_popular_provizija.py (backend na 3158).
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
        assert all("popular" in s and "provizija" in s for s in lista), "polja nedostaju u listi"
        assert all(s["popular"] is False for s in lista if s["id"] not in ids), "očekivano popular=false za postojeće"
        print(f"OK 1: {len(lista)} postojećih smeštaja ima popular/provizija")

        base = {"naziv": "TEST-POP", "status": 1, "grafik": 0}
        r = api.post("/smestaj", json=base)
        assert r.status_code == 200, r.text
        s1 = r.json(); ids.append(s1["id"])
        assert s1["popular"] is False and s1["provizija"] == 10, s1
        print("OK 2a: POST bez polja → popular=False, provizija=10")

        r = api.post("/smestaj", json={**base, "naziv": "TEST-POP2", "popular": True, "provizija": 15})
        assert r.status_code == 200, r.text
        s2 = r.json(); ids.append(s2["id"])
        assert s2["popular"] is True and s2["provizija"] == 15, s2
        print("OK 2b: POST popular=True, provizija=15 → sačuvano")

        r = api.put(f"/smestaj/{s1['id']}", json={"provizija": 0, "popular": True})
        assert r.status_code == 200, r.text
        assert r.json()["provizija"] == 0 and r.json()["popular"] is True, r.text
        back = [s for s in api.get("/smestaj").json() if s["id"] == s1["id"]][0]
        assert back["provizija"] == 0 and back["popular"] is True, back
        r = api.put(f"/smestaj/{s1['id']}", json={"popular": False})
        assert r.status_code == 200 and r.json()["popular"] is False and r.json()["provizija"] == 0, r.text
        print("OK 3: PUT provizija=0 i popular toggle → GET potvrđuje")

        for bad in (101, -1):
            r = api.put(f"/smestaj/{s1['id']}", json={"provizija": bad})
            assert r.status_code == 422, f"provizija={bad} treba 422, ima {r.status_code}"
            r = api.post("/smestaj", json={**base, "naziv": "TEST-BAD", "provizija": bad})
            assert r.status_code == 422, f"POST provizija={bad} treba 422, ima {r.status_code}"
        print("OK 4: provizija 101 / -1 → 422 (PUT i POST)")
    finally:
        for i in ids:
            api.delete(f"/smestaj/{i}")
        print(f"cleanup: obrisano {len(ids)} test smeštaja")


if __name__ == "__main__":
    main()
