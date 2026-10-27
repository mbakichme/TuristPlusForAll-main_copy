"""Povraćaj — prebacivanje uplate na drugi ugovor (POST /api/uplate/{kljuc}/prebaci).

Provere:
1. uplata prelazi na novi ugovor (uplate.id + faktura), beleži prebaceno_sa i datum_prebacivanja
2. napomena interna starog ugovora dobija „Prebačena uplata … na novi aranžman …“
3. napomena interna novog ugovora dobija „Prebačena uplata sa starog ugovora …“
4. isti ugovor → 400; nepostojeći ugovor → 404; nepoznata uplata → 404
5. čišćenje test redova

Preduslov: dev server na 127.0.0.1:3158 (start.sh).
"""
import json
import urllib.error
import urllib.request

from sqlalchemy import text

from db_config import get_engine
from routes import create_access_token

engine = get_engine()

BASE = "http://127.0.0.1:3158/api"
tok = create_access_token({"sub": "1"})
hdr = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}

STARI = "99901/26"
NOVI = "99902/26"
ok = True


def provera(naziv, dobijeno, ocekivano):
    global ok
    if dobijeno != ocekivano:
        ok = False
        print(f"  FAIL {naziv}: dobijeno={dobijeno!r} očekivano={ocekivano!r}")
    else:
        print(f"  OK {naziv}: {dobijeno!r}")


def post(path, body):
    r = urllib.request.Request(f"{BASE}{path}", data=json.dumps(body).encode(), headers=hdr, method="POST")
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def ocisti():
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM prebacivanje WHERE uplata_kljuc IN "
                          "(SELECT kljuc FROM uplate WHERE svrha = 'TEST PREBACI')"))
        conn.execute(text("DELETE FROM uplate WHERE faktura IN ('99901', '99902') AND svrha = 'TEST PREBACI'"))
        conn.execute(text("DELETE FROM aranzman WHERE kljuc IN (:a, :b)"), {"a": STARI, "b": NOVI})


def main():
    ocisti()
    with engine.begin() as conn:
        for kljuc, napomena in ((STARI, "Stara napomena"), (NOVI, None)):
            conn.execute(text(
                "INSERT INTO aranzman (kljuc, naziv, mesto, napomena1) VALUES (:k, 'TEST PREBACI', 'TEST', :n)"
            ), {"k": kljuc, "n": napomena})
        kljuc_uplate = conn.execute(text(
            "INSERT INTO uplate (id, danas, ime, nacin, din, svrha, faktura, vrsta) "
            "VALUES (99901, NOW(), 'TEST', 'Gotovina', 1234.5, 'TEST PREBACI', '99901', 'UPLATA') RETURNING kljuc"
        )).scalar_one()

    print("1) prebacivanje")
    status, odg = post(f"/uplate/{kljuc_uplate}/prebaci", {"ugovor": NOVI})
    provera("status HTTP", status, 200)
    provera("odgovor status", odg.get("status"), "prebaceno")

    with engine.connect() as conn:
        u = conn.execute(text(
            "SELECT id, faktura, prebaceno_sa, datum_prebacivanja FROM uplate WHERE kljuc = :k"
        ), {"k": kljuc_uplate}).fetchone()
        provera("uplate.id", u.id, 99902)
        provera("uplate.faktura", u.faktura, "99902")
        provera("prebaceno_sa", u.prebaceno_sa, "99901")
        provera("datum_prebacivanja popunjen", u.datum_prebacivanja is not None, True)

        print("2b) evidencija u tabeli prebacivanje")
        ev = conn.execute(text(
            "SELECT datum, uplata_kljuc, iznos, stari_ugovor, novi_ugovor, operater_id, operater "
            "FROM prebacivanje WHERE uplata_kljuc = :k"
        ), {"k": kljuc_uplate}).fetchall()
        provera("broj evidencija", len(ev), 1)
        if ev:
            provera("iznos", ev[0].iznos, 1234.5)
            provera("stari ugovor", ev[0].stari_ugovor, STARI)
            provera("novi ugovor", ev[0].novi_ugovor, NOVI)
            provera("operater_id", ev[0].operater_id, 1)
            provera("datum popunjen", ev[0].datum is not None, True)

        print("2) napomena starog ugovora")
        n_stari = conn.execute(text("SELECT napomena1 FROM aranzman WHERE kljuc = :k"), {"k": STARI}).scalar()
        provera("napomena starog", n_stari,
                "Stara napomena\nPrebačena uplata 1.234,50 din na novi aranžman 99902/26")

        print("3) napomena novog ugovora")
        n_novi = conn.execute(text("SELECT napomena1 FROM aranzman WHERE kljuc = :k"), {"k": NOVI}).scalar()
        provera("napomena novog", n_novi, "Prebačena uplata sa starog ugovora 99901/26")

    print("4) greške")
    provera("isti ugovor → 400", post(f"/uplate/{kljuc_uplate}/prebaci", {"ugovor": NOVI})[0], 400)
    provera("nepostojeći ugovor → 404", post(f"/uplate/{kljuc_uplate}/prebaci", {"ugovor": "88888888/26"})[0], 404)
    provera("nepoznata uplata → 404", post("/uplate/999999999/prebaci", {"ugovor": STARI})[0], 404)

    print("5) čišćenje")
    ocisti()

    print("\nREZULTAT:", "PROŠLO" if ok else "PAO")


if __name__ == "__main__":
    main()
