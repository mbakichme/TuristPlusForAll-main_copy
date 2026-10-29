"""Provera izuzetka za 1 osobu (parametri_obracuna period 1/2 × koeficijent).

Ne menja podatke: čita parametre, bira boravak čiji početak pada u period 1 ili 2,
i proverava da su cene 1 ADL = osnova × koeficijent perioda (pre umanjenja/popusta).
Pokretanje: uv run python check_izuzetak_1osoba.py (backend na 3158).
"""
import os
from datetime import date

import httpx
from sqlalchemy import text

import db_config
from routes import create_access_token

API = os.environ.get("TEST_API_URL", "http://localhost:3158/api")


def main():
    engine = db_config.get_engine()
    with engine.connect() as conn:
        par = conn.execute(text("""
            SELECT datumod1, datumdo1, koeficijent1, datumod2, datumdo2, koeficijent2
            FROM parametri_obracuna WHERE id = 1
        """)).mappings().first()
    print("parametri:", dict(par))
    kandidati = []
    for n in ("1", "2"):
        od, do, k = par[f"datumod{n}"], par[f"datumdo{n}"], par[f"koeficijent{n}"]
        if od and do and k is not None:
            kandidati.append((od, do, k))
    if not kandidati:
        print("SKIP: parametri nemaju period sa koeficijentom")
        return
    od, do, k = kandidati[0]
    token = create_access_token({"sub": "1"})
    api = httpx.Client(base_url=API, headers={"Authorization": "Bearer " + token}, timeout=180)
    d_od = od.strftime("%d.%m.%Y")
    d_do = os.environ.get("DO") or date.fromordinal(od.toordinal() + 7).strftime("%d.%m.%Y")
    r = api.get("/slobodne-sobe", params={"mesto_id": 1, "datum_od": d_od, "datum_do": d_do,
                                          "odrasli": 1, "prevoz": "autobuski"}).json()
    sobe = [(g, s) for g in r for s in g["sobe"] if s.get("cena_osnovna") is not None]
    print(f"boravak {d_od} – {d_do}, koeficijent perioda {k}: {len(sobe)} soba sa cenom")
    for g, s in sobe[:5]:
        print(f"  {g['smestaj_naziv']} soba {s['broj_sobe']} [{s['struktura']}] osnovna={s['cena_osnovna']} "
              f"tip={s['tip_cene']}")
        for line in s["obracun"]:
            print("     ", line)
    if not sobe:
        print("SKIP: nema soba sa cenom za 1 ADL u ovom boravku")


if __name__ == "__main__":
    main()
