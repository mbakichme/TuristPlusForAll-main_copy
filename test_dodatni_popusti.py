"""Dodatni popusti na smeštaj — API test prema dev serveru (APP_PORT+100, default 3162).

Tok: nađe poslednji aranžman → POST → PATCH → GET ugovora (lista) → DELETE → provera.
Briše samo redove koje sam kreirao.
"""
import json
import os
import sys
import urllib.error
import urllib.request

from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from routes import create_access_token, get_engine  # noqa: E402

PORT = os.environ.get("TEST_PORT", "3162")
BASE = f"http://127.0.0.1:{PORT}/api"
TOK = create_access_token({"sub": "1"})
FAILS = []


def req(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    hdr = {"Authorization": f"Bearer {TOK}", "Content-Type": "application/json"}
    r = urllib.request.Request(f"{BASE}{path}", data=data, headers=hdr, method=method)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except json.JSONDecodeError:
            return e.code, None


def check(ime, uslov):
    print(("OK   " if uslov else "FAIL ") + ime)
    if not uslov:
        FAILS.append(ime)


def main():
    with get_engine().connect() as c:
        kljuc = c.execute(text("SELECT kljuc FROM aranzman ORDER BY id DESC LIMIT 1")).scalar_one()
    print("ugovor:", kljuc)
    enc = kljuc.replace("/", "%2F")

    st, d = req(f"/ugovori/{enc}/dodatni-popusti", "POST", {"naziv": "TEST POPUST", "eur": 15, "rsd": 1500})
    check("POST 201", st == 201)
    pid = d.get("id") if isinstance(d, dict) else None
    check("POST vraća id/naziv/eur/rsd", pid and d["naziv"] == "TEST POPUST" and d["eur"] == 15)

    st, d = req(f"/ugovori/{enc}/dodatni-popusti", "POST", {"naziv": "BEZ IZNOSA"})
    check("POST bez iznosa → 400", st == 400)
    st, d = req(f"/ugovori/{enc}/dodatni-popusti", "POST", {"naziv": "NEG", "eur": -5})
    check("POST negativan iznos → 400", st == 400)
    st, d = req(f"/ugovori/{enc}/dodatni-popusti", "POST", {"naziv": "  ", "eur": 5})
    check("POST prazan naziv → 400", st == 400)

    if pid:
        st, d = req(f"/ugovori/{enc}/dodatni-popusti/{pid}", "PATCH", {"naziv": "TEST IZMENA", "eur": 20})
        check("PATCH 200 + izmena", st == 200 and d["naziv"] == "TEST IZMENA" and d["eur"] == 20 and d["rsd"] is None)

        st, d = req(f"/ugovori/{enc}")
        lista = (d or {}).get("dodatni_popusti", [])
        check("GET ugovora vraća dodatni_popusti", any(p["id"] == pid for p in lista))

        st, _ = req(f"/ugovori/{enc}/dodatni-popusti/{pid}", "DELETE")
        check("DELETE 200", st == 200)
        st, d = req(f"/ugovori/{enc}")
        check("posle DELETE nema popusta", not any(p["id"] == pid for p in (d or {}).get("dodatni_popusti", [])))
        st, _ = req(f"/ugovori/{enc}/dodatni-popusti/{pid}", "DELETE")
        check("DELETE ponovo → 404", st == 404)

    # procenat: iznos se računa od bruto smeštaja; obračun (ukupna_vrednost) mora reagovati isto kao za fiksni iznos
    with get_engine().connect() as c:
        b = c.execute(text("SELECT kolaranz, cenaaranz, kolchd, cenachd FROM aranzman WHERE kljuc = :k"),
                      {"k": kljuc}).mappings().one()
    base_eur = float(b["kolaranz"] or 0) * float(b["cenaaranz"] or 0) + float(b["kolchd"] or 0) * float(b["cenachd"] or 0)
    st, d0 = req(f"/ugovori/{enc}")
    u0 = d0["ukupna_vrednost"]
    st, d = req(f"/ugovori/{enc}/dodatni-popusti", "POST", {"naziv": "FIX", "eur": 15})
    fix_pid = d["id"]
    st, d1 = req(f"/ugovori/{enc}")
    ratio = (u0 - d1["ukupna_vrednost"]) / 15 if u0 and d1.get("ukupna_vrednost") is not None else None
    req(f"/ugovori/{enc}/dodatni-popusti/{fix_pid}", "DELETE")
    check("fiksni iznos menja ukupnu vrednost (kurs)", ratio is not None and ratio > 0)

    st, d = req(f"/ugovori/{enc}/dodatni-popusti", "POST", {"naziv": "PCT", "procenat": 10})
    check("POST procenat 201", st == 201 and d.get("procenat") == 10 and d.get("eur") is None)
    pct_pid = d.get("id")
    check("procenat: eur_iznos = 10% bruto smeštaja", st == 201 and abs(d["eur_iznos"] - round(base_eur * 0.10, 2)) < 0.02)
    st, d2 = req(f"/ugovori/{enc}")
    if ratio is not None and d2.get("ukupna_vrednost") is not None:
        delta = u0 - d2["ukupna_vrednost"]
        check("procenat menja ukupnu vrednost istom logikom kao iznos",
              abs(delta - (round(base_eur * 0.10, 2)) * ratio) < 0.05)
    st, d = req(f"/ugovori/{enc}/dodatni-popusti/{pct_pid}", "PATCH", {"naziv": "PCT2", "procenat": 20})
    check("PATCH procenat 200 + eur_iznos = 2×", st == 200 and abs(d["eur_iznos"] - round(base_eur * 0.20, 2)) < 0.02)
    req(f"/ugovori/{enc}/dodatni-popusti/{pct_pid}", "DELETE")
    st, _ = req(f"/ugovori/{enc}/dodatni-popusti", "POST", {"naziv": "BOTH", "procenat": 10, "eur": 5})
    check("procenat + iznos zajedno → 400", st == 400)
    st, _ = req(f"/ugovori/{enc}/dodatni-popusti", "POST", {"naziv": "BIG", "procenat": 150})
    check("procenat 150 → 400", st == 400)

    st, _ = req("/ugovori/99999999%2F00/dodatni-popusti", "POST", {"naziv": "X", "eur": 1})
    check("POST nepostojeći ugovor → 404", st == 404)

    if FAILS:
        print(f"\n{len(FAILS)} FAIL")
        sys.exit(1)
    print("\nSVE OK")


if __name__ == "__main__":
    main()
