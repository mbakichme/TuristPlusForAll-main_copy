"""Smoke test: do 3 popusta po opsegu (soba / termin / ceo cenovnik / polje).

Kreira privremeni cenovnik (ELENI 2), proverava PUT/GET sa listom popusta, odbijanje 4. popusta,
pražnjenje liste i brisanje cenovnika na kraju (cleanup).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient
import routes

app = routes.create_app("dist")
c = TestClient(app)
tok = routes.create_access_token({"sub": "1"})
H = {"Authorization": f"Bearer {tok}"}
OK = []


def check(label, cond):
    OK.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + label)


def popust(umanjenje, tip="last_minute", placanje="delimicno"):
    return {
        "umanjenje_vrsta": "iznos", "umanjenje": umanjenje, "tip_popusta": tip,
        "tip_placanja": placanje, "vazi_od": "2026-05-01", "vazi_do": "2026-10-01",
        "tip_aranzmana": "sa_prevozom", "tip_cene": "po_osobi", "popust_sopstveni_prevoz": None,
    }


r = c.post("/api/cenovnici", headers=H, json={
    "mesto_id": 1, "grupa_id": 6, "smestaj_id": 10,
    "datumod": "2026-05-25", "datumdo": "2026-10-02", "cene": []})
check("POST privremenog cenovnika → 201", r.status_code == 201)
d = r.json()
cid = d["id"]
try:
    P = len(d["periodi"])
    S = len(d["sobe"])
    soba = next(s for s in d["sobe"] if not s.get("virtuelna"))
    pid = d["periodi"][0]["id"]

    # 1) ceo cenovnik — 3 popusta, zapisi = S × P × 3
    r = c.put(f"/api/cenovnici/{cid}/popust-soba-sve", headers=H,
              json={"popusti": [popust(10), popust(20, "first_minute"), popust(5, "specijalna_ponuda", "u_celosti")]})
    check("PUT -sve sa 3 popusta → 200", r.status_code == 200)
    check(f"PUT -sve broj_zapisa = S×P×3 ({S}×{P}×3)", r.status_code == 200 and r.json()["broj_zapisa"] == S * P * 3)
    g = c.get(f"/api/cenovnici/{cid}/popust-soba-sve", headers=H).json()
    redni = sorted({z["redni"] for z in g["zapisi"]})
    check("GET -sve vraća redni 1,2,3", redni == [1, 2, 3])
    check("GET -sve: redni 2 je first_minute",
          all(z["tip_popusta"] == "first_minute" for z in g["zapisi"] if z["redni"] == 2))

    # 2) soba — 2 popusta, zatim GET spaja po rednom broju
    r = c.put(f"/api/cenovnici/{cid}/popust-soba/{soba['id']}", headers=H,
              json={"popusti": [popust(7), popust(8, "ultra_last_minute")]})
    check("PUT soba sa 2 popusta → 200", r.status_code == 200)
    g = c.get(f"/api/cenovnici/{cid}/popust-soba/{soba['id']}", headers=H).json()
    check("GET soba vraća 2 popusta", len(g.get("popusti", [])) == 2)
    check("GET soba: prvi umanjenje 7 (redni 1)",
          g.get("popusti") and float(g["popusti"][0]["umanjenje"]) == 7)

    # 3) termin — 1 popust, override samo tog termina
    r = c.put(f"/api/cenovnici/{cid}/popust-soba-termin/{pid}", headers=H, json={"popusti": [popust(3)]})
    check("PUT termin sa 1 popustom → 200", r.status_code == 200)
    g = c.get(f"/api/cenovnici/{cid}/popust-soba-termin/{pid}", headers=H).json()
    check("GET termin vraća samo redni 1", {z["redni"] for z in g["zapisi"]} == {1})

    # 4) polje — soba × termin, pa pražnjenje liste (prazan skup briše opseg)
    r = c.put(f"/api/cenovnici/{cid}/popust-soba-termin/{pid}?soba_id={soba['id']}", headers=H,
              json={"popusti": [popust(4), popust(6, "first_minute")]})
    check("PUT polje sa 2 popusta → 200", r.status_code == 200)
    g = c.get(f"/api/cenovnici/{cid}/popust-soba-termin/{pid}?soba_id={soba['id']}", headers=H).json()
    check("GET polje vraća 2 popusta", len({z["redni"] for z in g["zapisi"]}) == 2)
    r = c.put(f"/api/cenovnici/{cid}/popust-soba-termin/{pid}?soba_id={soba['id']}", headers=H,
              json={"popusti": []})
    check("PUT polje sa praznom listom → 200", r.status_code == 200)
    g = c.get(f"/api/cenovnici/{cid}/popust-soba-termin/{pid}?soba_id={soba['id']}", headers=H).json()
    check("GET polje posle pražnjenja → postoji False", g.get("postoji") is False)

    # 5) 4 popusta → odbijeno (max_length=3)
    r = c.put(f"/api/cenovnici/{cid}/popust-soba-sve", headers=H,
              json={"popusti": [popust(1), popust(2), popust(3), popust(4)]})
    check("PUT sa 4 popusta → 422", r.status_code == 422)
finally:
    rd = c.delete(f"/api/cenovnici/{cid}", headers=H)
    print(f"cleanup DELETE cenovnik {cid} → {rd.status_code}")

print(f"\n{sum(OK)}/{len(OK)} provera prošlo")
sys.exit(0 if all(OK) else 1)
