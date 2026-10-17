"""Test: Notifikacije API (POST/GET) — upis, autor snimak, validacija, najnovija.

Pokretanje: uv run python test_notifikacije_api.py (backend na :3158 ili BACKEND_URL).
"""
import os
import sys

import httpx

BASE = os.environ.get("BACKEND_URL", "http://localhost:3158/api")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from routes import create_access_token  # noqa: E402

TOKEN = create_access_token({"sub": "1"})
H = {"Authorization": f"Bearer {TOKEN}"}
rezultati = []


def provera(naziv, uslov):
    rezultati.append((naziv, bool(uslov)))
    print(("PASS" if uslov else "FAIL"), naziv)


def main():
    with httpx.Client(timeout=20) as c:
        provera("GET bez tokena → 401", c.get(f"{BASE}/notifikacije").status_code == 401)

        r = c.post(f"{BASE}/notifikacije", headers=H, json={"poruka": "   "})
        provera("prazna poruka → 422", r.status_code == 422)

        r = c.post(f"{BASE}/notifikacije", headers=H, json={"poruka": "x" * 1001})
        provera("1001 znak → 422", r.status_code == 422)

        r = c.post(f"{BASE}/notifikacije", headers=H, json={"poruka": "  Test poruka 1  "})
        provera("POST → 201", r.status_code == 201)
        novi = r.json()
        provera("poruka trimovana", novi.get("poruka") == "Test poruka 1")
        provera("autor_id = 1", novi.get("autor_id") == 1)
        provera("autor_ime snimljen", bool(novi.get("autor_ime")) or bool(novi.get("autor_username")))
        provera("created_at postavljen", bool(novi.get("created_at")))

        r = c.post(f"{BASE}/notifikacije", headers=H, json={"poruka": "Test poruka 2"})
        drugi = r.json()

        d = c.get(f"{BASE}/notifikacije?limit=5", headers=H).json()
        provera("najnovija = poslednja poslata", d["najnovija"] and d["najnovija"]["id"] == drugi["id"])
        ids = [x["id"] for x in d["rows"]]
        provera("lista sortirana najnovije prvo", ids.index(drugi["id"]) < ids.index(novi["id"]))

        d1 = c.get(f"{BASE}/notifikacije?limit=1", headers=H).json()
        provera("limit=1 vraća jedan red", len(d1["rows"]) == 1)
        provera("ukupno >= 2", d1["ukupno"] >= 2)

        dq = c.get(f"{BASE}/notifikacije?q=poruka%201", headers=H).json()
        provera("q filter nalazi test poruku", any(x["id"] == novi["id"] for x in dq["rows"]))
        provera("q filter vraća samo pogodke", all(
            "poruka 1" in (x["poruka"] + " " + x["autor_ime"] + " " + x["autor_username"]).lower()
            for x in dq["rows"]))
        dn = c.get(f"{BASE}/notifikacije?q=%25", headers=H).json()
        provera("q='%' se traži doslovno (0 rezultata)", dn["ukupno"] == 0)
        dd = c.get(f"{BASE}/notifikacije", headers=H).json()
        provera("default limit ≥ 2 redova", len(dd["rows"]) >= 2)

    print(f"\n{sum(ok for _, ok in rezultati)}/{len(rezultati)} provera prošlo")
    sys.exit(0 if all(ok for _, ok in rezultati) else 1)


if __name__ == "__main__":
    main()
