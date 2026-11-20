"""Test: zauzeće prevoza po destinaciji prevoza i datumu (GET /api/prevoz-limit/zauzece).

Privremeni redovi na datumu 2099-01-01 / 2099-01-08 (ne diraju realne podatke), čiste se na kraju.
Pokretanje: uv run test_prevoz_zauzece.py (backend mora raditi na 3158).
"""
import os
import sys

import httpx
from sqlalchemy import create_engine, text

from routes import create_access_token
import db_config

BASE = "http://127.0.0.1:3158/api"
DATUM_OD = "2099-01-01"
DATUM_DO = "2099-01-08"
KLJ_A = "TSTPV-1/99"   # RT nosilac, placeno, DONJA PLATFORMA
KLJ_B = "TSTPV-2/99"   # bez RT (OW), ne broji se
KLJ_C = "TSTPV-3/99"   # datumod 02.01 — ne ulazi u Odlazak 01.01

rezultati: list[tuple[str, bool]] = []


def provera(naziv: str, uslov: bool) -> None:
    rezultati.append((naziv, bool(uslov)))
    print(("OK   " if uslov else "FAIL ") + naziv)


def main() -> int:
    engine = create_engine(os.environ.get(db_config.DB_URL_ENV))
    token = create_access_token({"sub": "1"})
    h = {"Authorization": f"Bearer {token}"}
    http = httpx.Client(base_url=BASE, timeout=30)

    dp_lista = http.get("/destinacija-prevoz", headers=h).json()
    if not dp_lista:
        print("Nema destinacija prevoza u bazi — test se preskače")
        return 1
    dp = dp_lista[0]["id"]

    def ocisti() -> None:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM aranzman_dopuna WHERE aranzman_id IN "
                              "(SELECT id FROM aranzman WHERE kljuc LIKE 'TSTPV-%')"))
            conn.execute(text("DELETE FROM aranzman WHERE kljuc LIKE 'TSTPV-%'"))
            conn.execute(text("DELETE FROM prevoz_limit WHERE id_destinacije_prevoza = :dp "
                              "AND datum IN (:od, :do)"), {"dp": dp, "od": DATUM_OD, "do": DATUM_DO})

    ocisti()
    try:
        with engine.begin() as conn:
            for klj, od, do, rt, mesto, placeno in (
                (KLJ_A, DATUM_OD, DATUM_DO, 1, "DONJA PLATFORMA", 1),
                (KLJ_B, DATUM_OD, DATUM_DO, 0, None, 0),
                (KLJ_C, "2099-01-02", "2099-01-09", 1, None, 0),
            ):
                conn.execute(text("""
                    INSERT INTO aranzman (kljuc, datumod, datumdo, destinacija_prevoz_id, prevozrt,
                                          mesto_sedenja, placeno_prevoz)
                    VALUES (:k, :od, :do, :dp, :rt, :m, :p)
                """), {"k": klj, "od": od, "do": do, "dp": dp, "rt": rt, "m": mesto, "p": placeno})
            aid = conn.execute(text("SELECT id FROM aranzman WHERE kljuc = :k"), {"k": KLJ_A}).scalar_one()
            # saputnik RT + plaćeno na istom mestu
            conn.execute(text("""
                INSERT INTO aranzman_dopuna (aranzman_id, saputnik, prevozrt, mesto_sedenja, placeno_prevoz)
                VALUES (:a, 'TSTPV SAPUTNIK', 1, 'DONJA PLATFORMA', 1)
            """), {"a": aid})
            # saputnik RT bez plaćanja — broji se u putnike, ne u plaćena mesta
            conn.execute(text("""
                INSERT INTO aranzman_dopuna (aranzman_id, saputnik, prevozrt, mesto_sedenja, placeno_prevoz)
                VALUES (:a, 'TSTPV SAPUTNIK 2', 1, 'GORE STO', 0)
            """), {"a": aid})
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO prevoz_limit (id_destinacije_prevoza, datum, smer, limit_mesta, dodatna_mesta)
                VALUES (:dp, :d, 'Odlazak', 5, 1)
            """), {"dp": dp, "d": DATUM_OD})

        def zauzece(datum: str, smer: str, ex: str = "") -> dict:
            r = http.get("/prevoz-limit/zauzece", headers=h,
                         params={"id_destinacije_prevoza": dp, "datum": datum, "smer": smer, "exclude_kljuc": ex})
            return {"status": r.status_code, "body": r.json() if r.status_code == 200 else {}}

        odl = zauzece(DATUM_OD, "Odlazak")
        provera("Odlazak 01.01 → 200", odl["status"] == 200)
        # A nosilac RT + 2 saputnika RT = 3 (B OW ne ulazi, C je drugi datum)
        provera("putnici RT na Odlazak = 3", odl["body"].get("putnici") == 3)
        provera("placeno: DONJA PLATFORMA = 2 (nosilac + saputnik), GORE STO nije plaćeno",
                odl["body"].get("placeno") == [{"mesto": "DONJA PLATFORMA", "broj": 2}])
        provera("limit_mesta = 5, dodatna = 1", odl["body"].get("limit_mesta") == 5
                and odl["body"].get("dodatna_mesta") == 1)

        pov = zauzece(DATUM_DO, "Povratak")
        provera("Povratak 08.01 (datumdo) = 3 putnika", pov["body"].get("putnici") == 3)
        provera("Povratak nema limit → null", pov["body"].get("limit_mesta") is None)

        pov2 = zauzece("2099-01-09", "Povratak")
        provera("Povratak 09.01 = samo C (1 putnik)", pov2["body"].get("putnici") == 1)

        ex = zauzece(DATUM_OD, "Odlazak", ex=KLJ_A)
        provera("exclude_kljuc tekuće rezervacije → 0 putnika", ex["body"].get("putnici") == 0)
        provera("exclude_kljuc → nema plaćenih mesta", ex["body"].get("placeno") == [])

        bad = http.get("/prevoz-limit/zauzece", headers=h,
                       params={"id_destinacije_prevoza": dp, "datum": DATUM_OD, "smer": "Sredina"})
        provera("loš smer → 400", bad.status_code == 400)
        neauth = http.get("/prevoz-limit/zauzece", params={"id_destinacije_prevoza": dp, "datum": DATUM_OD, "smer": "Odlazak"})
        provera("bez tokena → 401", neauth.status_code == 401)
    finally:
        ocisti()

    prolaz = sum(1 for _, ok in rezultati if ok)
    print(f"\n{prolaz}/{len(rezultati)} provera prošlo")
    return 0 if prolaz == len(rezultati) else 1


if __name__ == "__main__":
    sys.exit(main())
