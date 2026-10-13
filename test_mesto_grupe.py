"""Test: mesto moze imati vise grupa perioda (mesto_grupa).
Kreira test mesto, proverava POST/GET/PUT grupe, /slobodne-sobe mesto_id, brise za sobom.
Pokretanje: uv run python test_mesto_grupe.py  (dev backend na 127.0.0.1:3158)
"""
import json
import urllib.request

BASE = "http://127.0.0.1:3158/api"

from routes import create_access_token  # noqa: E402

TOKEN = create_access_token({"sub": "1"})
OK = True


def call(method: str, path: str, body: dict | None = None):
    req = urllib.request.Request(
        BASE + path,
        method=method,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
        data=json.dumps(body).encode() if body is not None else None,
    )
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def proveri(naziv: str, uslov: bool, detalj: str = ""):
    global OK
    mark = "OK " if uslov else "FAIL"
    print(f"  {mark}: {naziv}" + (f" — {detalj}" if detalj else ""))
    if not uslov:
        OK = False


# 0) dve postojece grupe
st, grupe = call("GET", "/period-grupa")
proveri("GET /period-grupa", st == 200 and len(grupe) >= 2, f"status={st}, n={len(grupe)}")
g1, g2 = grupe[0]["id"], grupe[1]["id"]
print(f"  grupe: g1={g1} ({grupe[0]['naziv']}), g2={g2} ({grupe[1]['naziv']})")

# 1) POST sa dve grupe
st, m = call("POST", "/mesto", {"naziv": "TEST MESTO GRUPE", "grupe": [g1, g2], "status": 1, "grafik": 0})
proveri("POST /mesto grupe=[g1,g2]", st == 200 and m.get("grupa_datuma") == g1, f"status={st}, grupa_datuma={m.get('grupa_datuma')}")
mid = m["id"]

# 2) GET — grupe iz baze
st, lst = call("GET", "/mesto")
mm = next((x for x in lst if x["id"] == mid), None)
proveri("GET /mesto grupe==[g1,g2]", mm is not None and mm.get("grupe") == [g1, g2], f"grupe={mm.get('grupe') if mm else None}")
proveri("GET /mesto grupe_nazivi", mm is not None and len(mm.get("grupe_nazivi") or []) == 2, f"nazivi={mm.get('grupe_nazivi') if mm else None}")
proveri("GET /mesto grupa_datuma==g1", mm is not None and mm.get("grupa_datuma") == g1)

# 3) PUT — nova lista grupa
st, m2 = call("PUT", f"/mesto/{mid}", {"grupe": [g2, g1]})
proveri("PUT grupe=[g2,g1]", st == 200, f"status={st}")
st, lst = call("GET", "/mesto")
mm = next((x for x in lst if x["id"] == mid), None)
proveri("GET posle PUT grupe==[g2,g1] (primarna prva)", mm is not None and mm.get("grupe") == [g2, g1], f"grupe={mm.get('grupe') if mm else None}")
proveri("GET posle PUT grupa_datuma==prva poslata (g2)", mm is not None and mm.get("grupa_datuma") == g2, f"grupa_datuma={mm.get('grupa_datuma') if mm else None}")

# 4) /slobodne-sobe sa mesto_id (ne sme da baca)
st, sobe = call("GET", f"/slobodne-sobe?mesto_id={mid}&datum_od=01.07.2026&datum_do=08.07.2026")
proveri("/slobodne-sobe?mesto_id=", st == 200, f"status={st}, n_sobnih_grupa={len(sobe)}")

# 5) PUT prazna lista — brise sve grupe
st, m3 = call("PUT", f"/mesto/{mid}", {"grupe": []})
proveri("PUT grupe=[]", st == 200 and m3.get("grupa_datuma") is None, f"status={st}, grupa_datuma={m3.get('grupa_datuma')}")
st, lst = call("GET", "/mesto")
mm = next((x for x in lst if x["id"] == mid), None)
proveri("GET posle brisanja grupe==[]", mm is not None and mm.get("grupe") == [], f"grupe={mm.get('grupe') if mm else None}")

# 6) DELETE — cleanup (CASCADE brise i mesto_grupa)
st, _ = call("DELETE", f"/mesto/{mid}")
proveri("DELETE test mesto", st == 200, f"status={st}")

# 7) DB provera: nema zaostalih redova u mesto_grupa
import os  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
_eng = create_engine(os.environ["EXTERNAL_NEON_DATABASE_URL"])
with _eng.connect() as conn:
    n = conn.execute(text("SELECT COUNT(*) FROM mesto_grupa WHERE mesto_id = :i"), {"i": mid}).scalar()
proveri("DB: mesto_grupa ocisceno (CASCADE)", n == 0, f"ostalo={n}")

print()
print("REZULTAT:", "SVE PROVERE PROSLE" if OK else "IMA GRESAKA")
