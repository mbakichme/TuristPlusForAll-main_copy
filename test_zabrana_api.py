"""API test administrativne zabrane: predlog, kreiranje (12 rata, zbir, polurata), 409, 400, pregled.

Pokretanje: uv run python test_zabrana_api.py (dev backend na TEST_API_URL, podrazumevano :3158).
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

    subs = client.get("/subagenti-izbor").json()
    ok(len(subs) > 0, "postoji subagent")
    sub = subs[0]

    print("predlog")
    p = client.get("/zabrane/predlog", params={"kljuc": kljuc})
    ok(p.status_code == 200, "predlog 200")
    pj = p.json()
    ok(pj["broj_zabrane"].endswith("/1") or pj["broj_zabrane"].split("/")[-1].isdigit(),
       f"broj zabrane u formatu brojUgovora/N ({pj['broj_zabrane']})")

    print("kreiranje")
    broj = f"TST{uuid.uuid4().hex[:8]}/1"
    telo = {
        "kljuc": kljuc,
        "subagent_id": sub["id"],
        "mesto_obracuna": "TEST MESTO",
        "datum": date.today().isoformat(),
        "broj_zabrane": broj,
        "prva_rata": "2027-01-01",
        "prva_polurata": "2027-01-15",
        "iznos_eur": 1000.05,
    }
    try:
        r = client.post("/zabrane", json=telo)
        ok(r.status_code == 201, f"POST 201 (dobijeno {r.status_code} {r.text[:200]})")

        with engine.connect() as conn:
            z = conn.execute(text(
                "SELECT id_aranzmana, preduzece, idsub, ukupno, valuta, brojrata, polurata, mestoobracuna "
                "FROM zabrana WHERE brojzabrane = :b"), {"b": broj}).mappings().fetchone()
            rate = conn.execute(text(
                "SELECT rb, datum, rata, rasknjizeno FROM ratazab WHERE id_zabrane = :b ORDER BY rb"),
                {"b": broj}).mappings().all()
        ok(z is not None, "red u tabeli zabrana")
        ok(z["id_aranzmana"] == kljuc and z["idsub"] == sub["id"] and z["preduzece"] == sub["naziv"],
           "ugovor, subagent (idsub + preduzece) upisani")
        iznos_rsd = r.json()["iznos_rsd"]
        kurs_zab = r.json()["kurs"]
        ok(abs(z["ukupno"] - iznos_rsd) < 1e-9 and z["valuta"] == "RSD" and z["brojrata"] == 12,
           "ukupno = iznos u RSD (EUR × kurs), valuta RSD, brojrata 12")
        ok(abs(iznos_rsd - round(1000.05 * kurs_zab, 2)) < 1e-9, "iznos_rsd = 1000.05 × kurs na dan")
        ok(z["mestoobracuna"] == "TEST MESTO", "mesto obračuna upisano")
        ok(len(rate) == 12, "12 rata u ratazab")
        ok(abs(round(sum(x["rata"] for x in rate), 2) - iznos_rsd) < 1e-9, "zbir rata = iznos RSD (bez gubitka centi)")
        ok(all(x["datum"].day == 15 for x in rate), "sve rate na 15. dan (polurata)")
        ok(rate[0]["datum"] == date(2027, 1, 15) and rate[-1]["datum"] == date(2027, 12, 15),
           "rate od 15.01.2027 do 15.12.2027")
        ok(all(x["rasknjizeno"] is False for x in rate), "rasknjizeno = false")

        print("duplikat i validacija")
        ok(client.post("/zabrane", json=telo).status_code == 409, "isti broj zabrane → 409")
        bad = dict(telo, broj_zabrane=broj + "X", subagent_id=-999)
        ok(client.post("/zabrane", json=bad).status_code == 400, "nepostojeći subagent → 400")
        bad2 = dict(telo, broj_zabrane=broj + "Y", iznos_eur=0)
        ok(client.post("/zabrane", json=bad2).status_code == 422, "iznos 0 → 422")
        bad3 = dict(telo, broj_zabrane=broj + "Z", kljuc="NEPOSTOJI/99")
        ok(client.post("/zabrane", json=bad3).status_code == 404, "nepoznat ugovor → 404")

        print("pregled")
        lista = client.get("/zabrane", params={"q": broj}).json()
        ok(any(x["brojzabrane"] == broj for x in lista["rows"]), "pregled nalazi zabranu pretragom")
        p2 = client.get("/zabrane/predlog", params={"kljuc": kljuc}).json()
        ok(p2["broj_zabrane"] != broj, "predlog sledećeg broja ne vraća postojeći")
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM ratazab WHERE id_zabrane = :b"), {"b": broj})
            conn.execute(text("DELETE FROM zabrana WHERE brojzabrane = :b"), {"b": broj})

    print(f"REZULTAT: PROŠLO ({provere} provera)")


if __name__ == "__main__":
    main()
