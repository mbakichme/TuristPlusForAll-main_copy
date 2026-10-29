"""API test — parametri_obracuna (singleton, GET/PUT).

Flow:
  1. GET vraća sva polja; čuva originalno stanje za restore.
  2. PUT punih vrednosti → GET potvrđuje (datumi ISO, koeficijenti double).
  3. PUT null-ova (datumi/koef obrisani) → GET vraća null.
  4. Validacija: popust 101/-1, datumod > datumdo, koef -1 → 400.
  5. Restore originalnih vrednosti.
Pokretanje: uv run python test_parametri_obracuna.py (backend na 3158).
"""
import os

import httpx

from routes import create_access_token

API = os.environ.get("TEST_API_URL", "http://localhost:3158/api")

PUN = {
    "visina_popusta": 12,
    "datumod1": "2026-05-01", "datumdo1": "2026-06-30", "koeficijent1": 1.25,
    "datumod2": "2026-07-01", "datumdo2": "2026-09-30", "koeficijent2": 0.9,
}


def main():
    token = create_access_token({"sub": "1"})
    api = httpx.Client(base_url=API, headers={"Authorization": "Bearer " + token}, timeout=30)
    original = api.get("/parametri-obracuna").json()
    try:
        assert set(original) == set(PUN), original
        print("OK 1: GET vraća sva polja")

        r = api.put("/parametri-obracuna", json=PUN)
        assert r.status_code == 200, r.text
        back = api.get("/parametri-obracuna").json()
        assert back == PUN, back
        print("OK 2: PUT punih vrednosti → GET identičan")

        prazno = {k: None for k in PUN} | {"visina_popusta": 0}
        r = api.put("/parametri-obracuna", json=prazno)
        assert r.status_code == 200, r.text
        assert api.get("/parametri-obracuna").json() == prazno
        print("OK 3: null datumi/koeficijenti se čuvaju kao null")

        for bad, opis in (
            ({"visina_popusta": 101}, "popust 101"),
            ({"visina_popusta": -1}, "popust -1"),
            ({"visina_popusta": 5, "datumod1": "2026-06-10", "datumdo1": "2026-06-01"}, "datumod1 > datumdo1"),
            ({"visina_popusta": 5, "koeficijent2": -1}, "koeficijent2 < 0"),
        ):
            r = api.put("/parametri-obracuna", json=bad)
            assert r.status_code == 400, f"{opis}: očekivano 400, ima {r.status_code} {r.text}"
        print("OK 4: validacija (popust, datumi, koeficijent) → 400")
    finally:
        r = api.put("/parametri-obracuna", json={k: original[k] for k in PUN})
        assert r.status_code == 200, r.text
        print("cleanup: vraćene originalne vrednosti")


if __name__ == "__main__":
    main()
