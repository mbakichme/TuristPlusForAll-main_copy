"""API test administrativne zabrane sa proizvoljnim brojem rata (broj_rata).

Pokretanje: uv run python test_zabrana_brojrata_api.py (dev backend na TEST_API_URL, podrazumevano :3158).
Čisti svoje redove (zabrana + ratazab) direktno iz baze.
"""

import os
import uuid
from datetime import date

import httpx
from sqlalchemy import text

from routes import create_access_token, get_engine

API = os.environ.get("TEST_API_URL", "http://localhost:3158/api")


def main() -> None:
    engine = get_engine()
    tok = create_access_token({"sub": "1"})  # token se ne ispisuje
    client = httpx.Client(base_url=API, headers={"Authorization": "Bearer " + tok}, timeout=30)
    provere = 0

    def ok(cond, opis):
        nonlocal provere
        assert cond, opis
        provere += 1
        print("  OK", opis)

    with engine.connect() as conn:
        kljuc = conn.execute(text(
            "SELECT kljuc FROM aranzman WHERE kljuc LIKE '%/26' AND COALESCE(kljuc,'') <> '' "
            "ORDER BY id DESC LIMIT 1"
        )).scalar()
    ok(kljuc is not None, f"postoji ugovor za test ({kljuc})")
    sub = client.get("/subagenti-izbor").json()[0]

    broj = f"TST{uuid.uuid4().hex[:8]}/1"
    telo = {
        "kljuc": kljuc,
        "subagent_id": sub["id"],
        "mesto_obracuna": "TEST MESTO",
        "datum": date.today().isoformat(),
        "broj_zabrane": broj,
        "prva_rata": "2027-01-01",
        "prva_polurata": "2027-01-15",
        "iznos_eur": 1000.0,
        "broj_rata": 20,
    }
    print("kreiranje sa 20 rata")
    try:
        r = client.post("/zabrane", json=telo)
        ok(r.status_code == 201, f"POST 201 (dobijeno {r.status_code})")
        ok(r.json().get("broj_rata") == 20, "odgovor broj_rata = 20")

        with engine.connect() as conn:
            z = conn.execute(text("SELECT brojrata, valuta FROM zabrana WHERE brojzabrane = :b"),
                             {"b": broj}).mappings().one()
            ok(z["brojrata"] == 20, "zabrana.brojrata = 20")
            z_valuta = z["valuta"]
            rate = conn.execute(text(
                "SELECT rb, datum, rata FROM ratazab WHERE id_zabrane = :b ORDER BY rb"
            ), {"b": broj}).mappings().all()
        ok(len(rate) == 20, f"20 redova u ratazab (dobijeno {len(rate)})")
        ok(round(sum(x["rata"] for x in rate), 2) == r.json()["iznos_rsd"], "zbir rata = iznos u RSD")
        ok(z_valuta == "RSD", "valuta zabrane = RSD")
        ok(rate[0]["datum"] == date(2027, 1, 15), "prva rata 15.01.2027")
        ok(rate[-1]["datum"] == date(2028, 8, 15), "poslednja rata 15.08.2028 (19 meseci posle prve)")
        ok(all(x["datum"].day == 15 for x in rate), "sve rate na 15. dan")

        print("validacija broja rata")
        r0 = client.post("/zabrane", json={**telo, "broj_zabrane": broj + "x", "broj_rata": 0})
        ok(r0.status_code == 422, f"broj_rata 0 → 422 (dobijeno {r0.status_code})")
        r121 = client.post("/zabrane", json={**telo, "broj_zabrane": broj + "y", "broj_rata": 121})
        ok(r121.status_code == 422, f"broj_rata 121 → 422 (dobijeno {r121.status_code})")
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM ratazab WHERE id_zabrane = :b"), {"b": broj})
            conn.execute(text("DELETE FROM zabrana WHERE brojzabrane = :b"), {"b": broj})

    print(f"REZULTAT: PROŠLO ({provere} provera)")


if __name__ == "__main__":
    main()
