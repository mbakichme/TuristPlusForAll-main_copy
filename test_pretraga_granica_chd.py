"""API test — /slobodne-sobe: CHD = starost <= smestaj.granica_chd, starije deca = ADL.

Ground: mesto 1, boravak 25.05.2026–14.06.2026 (grupa 6 lanac), ELENI 2 (smestaj 10).
Provere:
  A. deca=12 (iznad granice 6.99) ≡ jedan odrasli više (odrasli=3, bez dece)
  B. deca=5 (ispod granice) ≠ odrasli=3 (računa se kao CHD)
  C. privremeno granica_chd smestaja 10 = 12 → deca=12 postaje CHD (≠ odrasli=3)
     i vraća se na 6.99 (cleanup, uvek)
Pokretanje: uv run python test_pretraga_granica_chd.py (backend 3158).
"""
import os

import httpx

from routes import create_access_token

API = os.environ.get("TEST_API_URL", "http://localhost:3158/api")
SMESTAJ_ID = 10
BASE_Q = {"mesto_id": 1, "datum_od": "25.05.2026", "datum_do": "14.06.2026", "prevoz": "autobuski"}


def main():
    token = create_access_token({"sub": "1"})
    api = httpx.Client(base_url=API, headers={"Authorization": "Bearer " + token}, timeout=60)
    original = None
    try:
        smestaj = [s for s in api.get("/smestaj").json() if s["id"] == SMESTAJ_ID][0]
        original = smestaj["granica_chd"]
        assert float(original) == 6.99, f"očekivano 6.99, ima {original}"

        def pretraga(**extra):
            r = api.get("/slobodne-sobe", params={**BASE_Q, **extra})
            assert r.status_code == 200, r.text
            return r.json()

        def po_smestaju(rez, sid):
            return [g for g in rez if g["smestaj_id"] == sid]

        def cene(rez, sid):
            return [(s["broj_sobe"], s.get("koeficijent"), s.get("struktura"), s.get("cena_osnovna"))
                    for g in po_smestaju(rez, sid) for s in g["sobe"]]

        # A
        dete12 = pretraga(odrasli="2", deca="12")
        odr3 = pretraga(odrasli="3")
        assert cene(dete12, SMESTAJ_ID) == cene(odr3, SMESTAJ_ID), "A: deca=12 treba da bude ADL"
        print("OK A: deca=12 ≡ odrasli=3")

        # B
        dete5 = pretraga(odrasli="2", deca="5")
        assert cene(dete5, SMESTAJ_ID) != cene(odr3, SMESTAJ_ID), "B: deca=5 treba da bude CHD (ne ADL)"
        print("OK B: deca=5 je CHD (≠ odrasli=3)")

        # C
        api.put(f"/smestaj/{SMESTAJ_ID}", json={"granica_chd": 12})
        dete12_c = pretraga(odrasli="2", deca="12")
        assert cene(dete12_c, SMESTAJ_ID) != cene(odr3, SMESTAJ_ID), "C: sa granicom 12, deca=12 treba CHD"
        print("OK C: sa granicom 12, deca=12 je CHD")

        # D — prima_decu: NE ispod 5 → dete 3 isključuje smeštaj, dete 6 ne
        api.put(f"/smestaj/{SMESTAJ_ID}", json={"prima_decu": False, "ne_prima_ispod_godina": 5})
        d3 = pretraga(odrasli="2", deca="3")
        assert po_smestaju(d3, SMESTAJ_ID) == [], "D: dete 3 < 5 — smeštaj mora nestati"
        d6 = pretraga(odrasli="2", deca="6")
        assert po_smestaju(d6, SMESTAJ_ID) != [], "D: dete 6 >= 5 — smeštaj mora ostati"
        print("OK D: NE ispod 5 → dete 3 isključuje, dete 6 prolazi")

        # E — DA (godine nedefinisane) ne utiče na pretragu
        api.put(f"/smestaj/{SMESTAJ_ID}", json={"prima_decu": True})
        e3 = pretraga(odrasli="2", deca="3")
        assert po_smestaju(e3, SMESTAJ_ID) != [], "E: DA — dete 3 ne sme isključiti smeštaj"
        print("OK E: DA → pretraga ne zavisi od godina")
    finally:
        if original is not None:
            api.put(f"/smestaj/{SMESTAJ_ID}", json={"granica_chd": float(original), "prima_decu": True})
            print("cleanup: granica_chd vraćena na", original, "; prima_decu=DA")


if __name__ == "__main__":
    main()
