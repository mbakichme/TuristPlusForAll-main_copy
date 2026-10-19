"""API test — polazak.cena_transfera (EUR, NULL = nije uneta) + mesto_id/grupa_id (obavezno).

Flow:
  1. POST sa cena_transfera=25.5 → vraća 25.5; GET je vraća; nazivi mesto/grupe.
  2. POST bez cena_transfera → null (postojeći klijenti ne lome).
  3. PUT menja na 30; PUT sa null briše vrednost.
  4. POST/PUT bez mesto_id ili grupa_id → 400.
  5. Cleanup: DELETE test redova.
Pokretanje: uv run python test_polazak_cena_transfera.py (backend na 3158).
"""
import os

import httpx

from routes import create_access_token

API = os.environ.get("TEST_API_URL", "http://localhost:3158/api")


def main():
    token = create_access_token({"sub": "1"})
    api = httpx.Client(base_url=API, headers={"Authorization": "Bearer " + token}, timeout=30)

    mesta = api.get("/mesto").json()
    grupe = api.get("/period-grupa").json()
    destinacije = api.get("/destinacija").json()
    assert mesta and grupe and destinacije, "šifarnici su prazni"
    mesto, grupa, destinacija = mesta[0], grupe[0], destinacije[0]
    BASE = {
        "polazak": "TEST polazak", "sat": "00:00", "valuta": "EUR",
        "destinacija_id": destinacija["id"], "mesto_id": mesto["id"], "grupa_id": grupa["id"],
    }

    ids = []
    try:
        r = api.post("/polazak", json={**BASE, "cena_transfera": 25.5})
        assert r.status_code == 200, r.text
        p1 = r.json(); ids.append(p1["id"])
        assert p1["cena_transfera"] == 25.5, p1
        assert p1["destinacija_id"] == destinacija["id"] and p1["destinacija"] == destinacija["naziv"], p1
        assert p1["mesto_id"] == mesto["id"] and p1["grupa_id"] == grupa["id"], p1
        assert p1["mesto_naziv"] == mesto["naziv"] and p1["grupa_naziv"] == grupa["naziv"], p1
        lista = [x for x in api.get("/polazak").json() if x["id"] == p1["id"]]
        assert lista and lista[0]["cena_transfera"] == 25.5, lista
        assert lista[0]["mesto_naziv"] == mesta[0]["naziv"], lista
        print("OK 1: POST 25.5 → GET 25.5 + destinacija/mesto/grupa nazivi")

        r = api.post("/polazak", json=BASE)
        assert r.status_code == 200, r.text
        p2 = r.json(); ids.append(p2["id"])
        assert p2["cena_transfera"] is None, p2
        print("OK 2: POST bez cene → null")

        r = api.put(f"/polazak/{p1['id']}", json={**BASE, "cena_transfera": 30})
        assert r.status_code == 200 and r.json()["cena_transfera"] == 30, r.text
        print("OK 3a: PUT 30")

        r = api.put(f"/polazak/{p1['id']}", json={**BASE, "cena_transfera": None})
        assert r.status_code == 200 and r.json()["cena_transfera"] is None, r.text
        print("OK 3b: PUT null briše vrednost")

        r = api.post("/polazak", json={**BASE, "destinacija_id": None})
        assert r.status_code == 400, r.status_code
        r = api.post("/polazak", json={**BASE, "mesto_id": None})
        assert r.status_code == 400, r.status_code
        r = api.post("/polazak", json={**BASE, "grupa_id": None})
        assert r.status_code == 400, r.status_code
        r = api.put(f"/polazak/{p1['id']}", json={**BASE, "destinacija_id": None})
        assert r.status_code == 400, r.status_code
        r = api.put(f"/polazak/{p1['id']}", json={**BASE, "destinacija_id": 999999})
        assert r.status_code == 400, r.status_code
        print("OK 4: POST/PUT bez destinacije/mesta/grupe ili nepostojeća destinacija → 400")
    finally:
        for i in ids:
            api.delete(f"/polazak/{i}")
        print("cleanup: obrisani test redovi", ids)


if __name__ == "__main__":
    main()
