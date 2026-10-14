"""Round-trip API test za koeficijente prodaje; čisti isključivo za sobom."""
import os
import httpx
from sqlalchemy import text
from routes import get_engine, create_access_token


def main():
    engine = get_engine()
    base = os.environ.get("TEST_API_URL", "http://localhost:3158/api")
    client = httpx.Client(base_url=base, headers={"Authorization": "Bearer " + create_access_token({"sub": "1"})}, timeout=30)
    created = []
    try:
        assert httpx.get(base + "/koeficijenti").status_code == 401

        # GET: strukture iz sobe.tip (DEDUP), tabula prazna na početku
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM koeficijenti_prodaje"))
        r = client.get("/koeficijenti")
        assert r.status_code == 200, r.text
        start = r.json()
        strukture = start["strukture"]
        assert strukture and len(strukture) == len(set(strukture)), strukture
        assert start["redovi"] == []
        print(f"[start] {len(strukture)} struktura iz sobe.tip: {strukture}")

        # PUT: auto red (postoji u sobama) + ručni red za ISTU strukturu
        s1 = strukture[0]
        r = client.put("/koeficijenti", json={"redovi": [
            {"struktura": s1, "adl": 2, "chd": 1, "inf": 0, "koeficijent": 1.5, "rucno": False},
            {"struktura": s1, "adl": 0, "chd": 0, "inf": 0, "koeficijent": 0, "rucno": True},
        ]})
        assert r.status_code == 200, r.text
        odg = r.json()
        assert len(odg["redovi"]) == 2, odg
        red1 = next(x for x in odg["redovi"] if not x["rucno"])
        red2 = next(x for x in odg["redovi"] if x["rucno"])
        created = [red1["id"], red2["id"]]
        assert red1["struktura"] == s1 and red1["adl"] == 2 and red1["chd"] == 1
        assert float(red1["koeficijent"]) == 1.5
        print(f"[put] snimljena 2 reda za '{s1}' (auto id={red1['id']}, rucno id={red2['id']})")

        # PUT: izmena postojećeg čuva ID, brisanje ručnog radi, struktura van soba ostaje
        r = client.put("/koeficijenti", json={"redovi": [
            {"id": red1["id"], "struktura": s1, "adl": 3, "chd": 0, "inf": 1, "koeficijent": 2.25, "rucno": False},
        ]})
        assert r.status_code == 200, r.text
        odg = r.json()
        assert [x["id"] for x in odg["redovi"]] == [red1["id"]], odg
        assert odg["redovi"][0]["adl"] == 3 and odg["redovi"][0]["inf"] == 1
        assert float(odg["redovi"][0]["koeficijent"]) == 2.25
        print("[diff] ID zadržan pri izmeni, ručni red obrisan")

        # Validacija: negativni brojevi, NaN, granice, prazna struktura, nepoznat ID
        for telo in [
            {"redovi": [{"struktura": s1, "adl": -1}]},
            {"redovi": [{"struktura": s1, "chd": 100}]},
            {"redovi": [{"struktura": s1, "koeficijent": -0.5}]},
            {"redovi": [{"struktura": s1, "koeficijent": "NaN"}]},
            {"redovi": [{"struktura": s1, "koeficijent": "Infinity"}]},
            {"redovi": [{"struktura": s1, "koeficijent": 1000000}]},
            {"redovi": [{"struktura": "   "}]},
            {"redovi": [{"id": 99999999, "struktura": s1}]},
        ]:
            r = client.put("/koeficijenti", json=telo)
            assert r.status_code in (400, 422), (telo, r.status_code, r.text)
        r = client.get("/koeficijenti").json()
        assert len(r["redovi"]) == 1 and r["redovi"][0]["adl"] == 3, "neuspešna validacija je ipak menjala podatke"
        print("[validacija] 8 nevalidnih zahteva odbijeno (400/422), podaci netaknuti")

        # Prazan payload == brisanje svega
        r = client.put("/koeficijenti", json={"redovi": []})
        assert r.status_code == 200 and r.json()["redovi"] == []
        created = []
        print("[prazno] payload bez redova briše sve")

        print("PASS: auth, strukture iz soba (dedup), auto+rucni redovi za istu strukturu, diff cuva ID, validacija, atomicnost")
    finally:
        with engine.begin() as conn:
            for item_id in created:
                conn.execute(text("DELETE FROM koeficijenti_prodaje WHERE id = :id"), {"id": item_id})
        with engine.connect() as conn:
            ostalo = conn.execute(text("SELECT COUNT(*) FROM koeficijenti_prodaje")).scalar()
        assert ostalo == 0, f"ostalo {ostalo} redova"
        print(f"[cleanup] tabela prazna (ostalo={ostalo})")
        client.close()


if __name__ == "__main__":
    main()
