"""API test: zaduzenje partner + uslovi placanja (po rezervaciji).

Pokretanje: uv run python test_zaduzenje_api.py
Koristi prvi postojeci aranzman; na kraju brise samo redove koje je test upisao
(pre testa proverava da za taj aranzman nema zapisa).
"""

import os
import sys

import httpx
from sqlalchemy import text

from db_config import get_engine
from routes import create_access_token

API = os.environ.get("TEST_API_URL", "http://localhost:3158/api")
engine = get_engine()
token = create_access_token({"sub": "1"})
api = httpx.Client(base_url=API, headers={"Authorization": "Bearer " + token}, timeout=60)

fails = 0


def check(naziv, uslov):
    global fails
    print(("OK   " if uslov else "FAIL ") + naziv)
    if not uslov:
        fails += 1


with engine.connect() as c:
    row = c.execute(text("SELECT id, kljuc FROM aranzman ORDER BY id LIMIT 1")).fetchone()
    sub = c.execute(text("SELECT id FROM subagenti WHERE naziv <> '' ORDER BY id LIMIT 1")).fetchone()
    pre = c.execute(text(
        "SELECT (SELECT count(*) FROM zaduzenje_po_aranzmanu WHERE aranzman_id=:a),"
        " (SELECT count(*) FROM uslovi_placanja_po_aranzmanu WHERE aranzman_id=:a)"
    ), {"a": row.id}).fetchone()

KLJUC = row.kljuc
SUB_ID = sub.id
check("preduslov: aranzman nema prethodne zapise", pre[0] == 0 and pre[1] == 0)

try:
    check("bez tokena 401", httpx.get(f"{API}/zaduzenje/{KLJUC}").status_code == 401)
    check("nepostojeci ugovor 404", api.get("/zaduzenje/NEPOSTOJI-99999").status_code == 404)

    g = api.get(f"/zaduzenje/{KLJUC}").json()
    check("GET bez zapisa: postoji=False i nule", g["postoji"] is False and g["hotel_eur"] == 0)

    body = {"subagent_id": SUB_ID, "hotel_eur": 1234.5, "hotel_rsd": 0,
            "hf_eur": 0, "hf_rsd": 50000, "transfer_eur": 80, "transfer_rsd": 0,
            "prevoz_eur": 0, "prevoz_rsd": 9000}
    r = api.put(f"/zaduzenje/{KLJUC}", json=body)
    check("PUT zaduzenje 200", r.status_code == 200)
    g = api.get(f"/zaduzenje/{KLJUC}").json()
    check("GET vraca subagenta i iznose", g["postoji"] and g["subagent_id"] == SUB_ID
          and g["hotel_eur"] == 1234.5 and g["hf_rsd"] == 50000 and g["prevoz_rsd"] == 9000
          and g["subagent_naziv"])

    body["subagent_id"] = None
    api.put(f"/zaduzenje/{KLJUC}", json=body)
    check("PUT bez partnera (null) prihvacen", api.get(f"/zaduzenje/{KLJUC}").json()["subagent_id"] is None)

    check("PUT nepoznat subagent 400",
          api.put(f"/zaduzenje/{KLJUC}", json={**body, "subagent_id": 999999}).status_code == 400)
    check("PUT negativan iznos 422",
          api.put(f"/zaduzenje/{KLJUC}", json={**body, "hotel_eur": -5}).status_code == 422)

    redovi = [
        {"naziv": "Avans", "iznos_eur": 300, "iznos_rsd": None, "iznos_procenat": 20,
         "datum_placanja": "2026-11-01", "placeno": True},
        {"naziv": "Ostatak", "iznos_eur": None, "iznos_rsd": 40000, "iznos_procenat": None,
         "datum_placanja": None, "placeno": False},
        {"naziv": "Napomena", "iznos_eur": None, "iznos_rsd": None, "iznos_procenat": None,
         "datum_placanja": None, "placeno": False},
    ]
    r = api.put(f"/uslovi-placanja/{KLJUC}", json={"redovi": redovi})
    check("PUT uslovi 200 i broj=3", r.status_code == 200 and r.json()["broj"] == 3)
    u = api.get(f"/uslovi-placanja/{KLJUC}").json()["redovi"]
    check("GET uslovi: 3 reda, redosled ocuvan",
          [x["naziv"] for x in u] == ["Avans", "Ostatak", "Napomena"])
    check("GET uslovi: placeno, datum, procenat",
          u[0]["placeno"] is True and u[0]["datum_placanja"] == "2026-11-01"
          and u[0]["iznos_procenat"] == 20 and u[1]["iznos_rsd"] == 40000)

    check("PUT uslovi procenat 101 -> 422",
          api.put(f"/uslovi-placanja/{KLJUC}", json={"redovi": [
              {"naziv": "x", "iznos_procenat": 101}]}).status_code == 422)

    api.put(f"/uslovi-placanja/{KLJUC}", json={"redovi": redovi[:1]})
    check("PUT uslovi replace-all (ostaje 1 red)",
          len(api.get(f"/uslovi-placanja/{KLJUC}").json()["redovi"]) == 1)
finally:
    with engine.begin() as c:
        c.execute(text("DELETE FROM uslovi_placanja_po_aranzmanu WHERE aranzman_id = :a"), {"a": row.id})
        c.execute(text("DELETE FROM zaduzenje_po_aranzmanu WHERE aranzman_id = :a"), {"a": row.id})

print(f"\n{'SVE PROLAZI' if fails == 0 else f'PADA: {fails}'}")
sys.exit(1 if fails else 0)
