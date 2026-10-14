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

        # ── Integracija sa sobama: auto koeficijent pri dodavanju sobe ──
        with engine.connect() as conn:
            smestaj_id = conn.execute(text("SELECT id FROM smestaj ORDER BY id LIMIT 1")).scalar()
        assert smestaj_id
        test_tip = "TST/9"
        r = client.post("/sobe", json={"veza_id_smestaj": smestaj_id, "broj_sobe": "TEST-KOEF",
                                       "tip": test_tip, "status": 0})
        assert r.status_code in (200, 201), r.text
        soba_id = r.json()["id"]
        r = client.get("/koeficijenti")
        assert r.status_code == 200
        assert test_tip in r.json()["strukture"], "tip nove sobe nije u strukturama"
        auto = [x for x in r.json()["redovi"] if x["struktura"] == test_tip]
        assert len(auto) == 1 and auto[0]["rucno"] is False and auto[0]["id"] is not None, auto
        assert auto[0]["adl"] == 0 and float(auto[0]["koeficijent"]) == 0
        auto_id = auto[0]["id"]
        print(f"[soba] soba id={soba_id} sa tipom '{test_tip}' auto-kreira koeficijent (id={auto_id}, nule)")

        # druga soba sa istim tipom NE duplira auto red
        r = client.post("/sobe", json={"veza_id_smestaj": smestaj_id, "broj_sobe": "TEST-KOEF-2",
                                       "tip": test_tip, "status": 0})
        assert r.status_code in (200, 201), r.text
        soba2_id = r.json()["id"]
        dupl = [x for x in client.get("/koeficijenti").json()["redovi"] if x["struktura"] == test_tip]
        assert len(dupl) == 1, dupl
        print("[soba] druga soba istog tipa ne duplira auto red")

        # GET /sobe: mesto_naziv + koeficijenti kao NAZIVI (osnovni = tip sobe)
        r = client.get("/sobe", params={"q": "TEST-KOEF"})
        assert r.status_code == 200, r.text
        pronadjene = [x for x in r.json() if x["id"] in (soba_id, soba2_id)]
        assert len(pronadjene) == 2, pronadjene
        for x in pronadjene:
            assert x["mesto_naziv"], x
            assert x["koeficijenti"] == [test_tip], x
        print(f"[sobe] mesto_naziv='{pronadjene[0]['mesto_naziv']}' + koeficijenti kao nazivi {[test_tip]}")

        # ručni zapis sa vrednostima (POST /koeficijenti/red) — i dalje deo API-ja
        r = client.post("/koeficijenti/red", json={"struktura": test_tip, "adl": 2, "chd": 1, "inf": 0,
                                                   "koeficijent": 1.25})
        assert r.status_code == 201, r.text
        rucni = r.json()
        assert rucni["rucno"] is True and rucni["id"]
        assert client.post("/koeficijenti/red", json={"struktura": test_tip, "adl": -1}).status_code == 422
        assert client.delete(f'/koeficijenti/red/{auto_id}').status_code == 400
        assert client.delete("/koeficijenti/red/999999999").status_code == 404
        assert client.delete(f'/koeficijenti/red/{rucni["id"]}').status_code == 200
        print("[red] rucni zapis sa vrednostima: 201, validacija 422, auto zasticen (400)")

        # više koeficijenata za jednu sobu: soba 1/3 dobija dodatni koeficijent (naziv) 1/2
        s1 = strukture[0]
        r = client.post(f"/sobe/{soba_id}/koeficijenti", json={"struktura": s1})
        assert r.status_code == 200, r.text
        assert r.json() == {"tip": test_tip, "dodati": [s1]}, r.json()
        assert client.post(f"/sobe/{soba_id}/koeficijenti", json={"struktura": s1}).status_code == 400
        assert client.post(f"/sobe/{soba_id}/koeficijenti", json={"struktura": test_tip}).status_code == 400
        assert client.post(f"/sobe/{soba_id}/koeficijenti", json={"struktura": "   "}).status_code == 422
        assert client.post(f"/sobe/{soba_id}/koeficijenti", json={"struktura": "NEPOSTOJI/XX"}).status_code == 400
        assert client.get(f"/sobe/{soba_id}/koeficijenti").json() == {"tip": test_tip, "dodati": [s1]}
        soba1 = next(x for x in client.get("/sobe", params={"q": "TEST-KOEF"}).json() if x["id"] == soba_id)
        assert soba1["koeficijenti"] == [test_tip, s1], soba1
        print(f"[soba-koef] soba '{test_tip}' dobila dodatni koeficijent (naziv) '{s1}'; dupliran/osnovni/nedefinisan → 400")

        # brisanje dodatnog koeficijenta: osnovni → 400, dodatni → 200, nepoznat → 404
        assert client.delete(f"/sobe/{soba_id}/koeficijenti", params={"struktura": test_tip}).status_code == 400
        assert client.delete(f"/sobe/{soba_id}/koeficijenti", params={"struktura": "NEPOSTOJI/XX"}).status_code == 404
        r = client.delete(f"/sobe/{soba_id}/koeficijenti", params={"struktura": s1})
        assert r.status_code == 200 and r.json() == {"tip": test_tip, "dodati": []}
        soba1 = next(x for x in client.get("/sobe", params={"q": "TEST-KOEF"}).json() if x["id"] == soba_id)
        assert soba1["koeficijenti"] == [test_tip], soba1
        print("[soba-koef] dodatni koeficijent uklonjen, osnovni zaštićen (400)")

        print("PASS: auth, strukture iz soba (dedup), auto+rucni redovi za istu strukturu, diff cuva ID, validacija, atomicnost, auto-koef pri dodavanju sobe, veza soba↔koeficijent po nazivu")
    finally:
        with engine.begin() as conn:
            for item_id in created:
                conn.execute(text("DELETE FROM koeficijenti_prodaje WHERE id = :id"), {"id": item_id})
            conn.execute(text("DELETE FROM sobe WHERE broj_sobe IN ('TEST-KOEF', 'TEST-KOEF-2') AND tip = 'TST/9'"))
            conn.execute(text("DELETE FROM koeficijenti_prodaje WHERE struktura = 'TST/9'"))
        with engine.connect() as conn:
            ostalo = conn.execute(text("SELECT COUNT(*) FROM koeficijenti_prodaje")).scalar()
        assert ostalo == 0, f"ostalo {ostalo} redova"
        print(f"[cleanup] tabela prazna (ostalo={ostalo})")
        client.close()


if __name__ == "__main__":
    main()
