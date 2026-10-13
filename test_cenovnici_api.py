"""Round-trip API test; uklanja isključivo svoje cenovnike."""
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
        assert httpx.get(base + "/cenovnici").status_code == 401
        with engine.connect() as conn:
            combo = conn.execute(text("""
                SELECT m.id AS mesto_id, s.id AS smestaj_id, s.grupa_datuma AS grupa_id
                FROM smestaj s JOIN mesto m ON m.id = s.mesto
                WHERE EXISTS (SELECT 1 FROM sobe b WHERE b.veza_id_smestaj = s.id)
                AND EXISTS (SELECT 1 FROM period_datum p WHERE p.grupa_id = s.grupa_datuma)
                AND (m.grupa_datuma = s.grupa_datuma OR EXISTS (
                    SELECT 1 FROM mesto_grupa mg WHERE mg.mesto_id = m.id AND mg.grupa_id = s.grupa_datuma))
                ORDER BY s.id LIMIT 1
            """)).mappings().first()
        assert combo
        refs = dict(combo)
        r = client.get("/cenovnici/sablon", params=refs)
        assert r.status_code == 200, r.text
        draft = r.json()
        cell = {"soba_id": draft["sobe"][0]["id"], "period_id": draft["periodi"][0]["id"], "cena": "125.50"}
        body = {**refs, "datumod": "2026-01-01", "datumdo": "2026-12-31", "cene": [cell]}
        r = client.post("/cenovnici", json=body)
        assert r.status_code == 201, r.text
        detail = r.json()
        created.append(detail["id"])
        assert detail["cene"][0]["cena"] == "125.50"
        assert client.get(f'/cenovnici/{detail["id"]}').json()["sobe"] == draft["sobe"]
        assert any(x["id"] == detail["id"] for x in client.get("/cenovnici", params={"q": detail["uuid"]}).json())
        r = client.post("/cenovnici", json=body)
        assert r.status_code == 201, r.text
        another = r.json()
        created.append(another["id"])
        assert another["uuid"] != detail["uuid"]
        update = {"datumod": "2026-02-01", "datumdo": "2026-11-30", "cene": [{**cell, "cena": "0"}]}
        r = client.put(f'/cenovnici/{detail["id"]}', json=update)
        assert r.status_code == 200, r.text
        assert r.json()["uuid"] == detail["uuid"] and r.json()["cene"][0]["cena"] == "0.00"
        for invalid in ["-10", "1.234", "NaN", "Infinity"]:
            r = client.put(f'/cenovnici/{detail["id"]}', json={**update, "cene": [{**cell, "cena": invalid}]})
            assert r.status_code == 422, (invalid, r.text)
        assert client.put(f'/cenovnici/{detail["id"]}', json={**update, "datumod": "2027-01-01"}).status_code == 422
        for cells in [[cell, cell], [{**cell, "soba_id": -1}]]:
            assert client.put(f'/cenovnici/{detail["id"]}', json={**update, "cene": cells}).status_code == 400
        assert client.get(f'/cenovnici/{detail["id"]}').json()["cene"][0]["cena"] == "0.00"
        assert client.put(f'/cenovnici/{detail["id"]}', json={**update, "cene": []}).json()["cene"] == []
        print("PASS: auth, template, create/read/search, duplicate combination UUID, edit, zero/blank, validation, atomic rollback")
    finally:
        with engine.begin() as conn:
            for item_id in created:
                conn.execute(text("DELETE FROM cenovnici WHERE id = :id"), {"id": item_id})
        client.close()


if __name__ == "__main__":
    main()
