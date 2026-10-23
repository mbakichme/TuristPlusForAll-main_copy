"""Cenovnici — blokada polja (soba × termin): PUT /cenovnici/{id}/blokada.

Menja SAMO kolonu blokirano. Blokirano=TRUE upisuje/menja red za svako polje (ostale opcije
se kopiraju iz globalnog period_id=0 reda ako postoji, inače ostaju kakve jesu). Blokirano=FALSE
menja postojeći red; bez reda upisuje odblokirano samo kad polje nasleđuje globalnu blokadu.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient
from sqlalchemy import text
import db_config
import routes

engine = db_config.get_engine()
app = routes.create_app("dist")
c = TestClient(app)
tok = routes.create_access_token({"sub": "1"})
H = {"Authorization": f"Bearer {tok}"}
OK = []


def check(label, cond):
    OK.append(cond)
    print(("PASS " if cond else "FAIL ") + label)


def red(cid, soba, period):
    with engine.connect() as conn:
        r = conn.execute(text(
            "SELECT blokirano, istaknuto, prevoz FROM opcije_soba "
            "WHERE cenovnik_id=:c AND soba_id=:s AND period_id=:p"),
            {"c": cid, "s": soba, "p": period}).mappings().first()
        return dict(r) if r else None


def blokirane(cid):
    r = c.get(f"/api/cenovnici/{cid}/opcije-celije", headers=H)
    assert r.status_code == 200, r.text
    return {(x["soba_id"], x["period_id"]) for x in r.json()["blokirane"]}


# cenovnik: ELENI 2 (realne + virtuelne sobe)
r = c.post("/api/cenovnici", headers=H, json={
    "mesto_id": 1, "grupa_id": 6, "smestaj_id": 10,
    "datumod": "2026-05-25", "datumdo": "2026-10-02", "cene": []})
assert r.status_code == 201, r.text
d = r.json()
cid = d["id"]
sobe = d["sobe"]
periodi = [p["id"] for p in d["periodi"]]
realne = [s["id"] for s in sobe if not s.get("virtuelna")]
virtuelne = [s["id"] for s in sobe if s.get("virtuelna")]
s1 = realne[0]                 # realna soba sa virtuelnom (prvi red)
s2 = realne[1]                 # druga realna soba — nezavisna od s1 i virt
virt = virtuelne[0]            # virtuelna soba (nastala iz neke realne)
assert len({s1, s2, virt}) == 3, "test traži tri različite sobe"
p1, p2 = periodi[0], periodi[1]

try:
    # 1) prethodna opcija na (s1,p1): istaknuto + obavezan prevoz — mora ostati nakon blokade
    r = c.put(f"/api/cenovnici/{cid}/opcije-soba-termin/{p1}?soba_id={s1}", headers=H,
              json={"istaknuto": True, "prevoz": "obavezan"})
    check("priprema: opcija na (s1,p1) upisana", r.status_code == 200)

    # 2) blokiraj s1 + virt × p1 + p2
    r = c.put(f"/api/cenovnici/{cid}/blokada", headers=H,
              json={"sobe": [s1, virt], "periodi": [p1, p2], "blokirano": True})
    check("blokada TRUE → 200", r.status_code == 200)
    check("broj_polja = 4", r.json().get("broj_polja") == 4)
    check("(s1,p1) blokirano u bazi", red(cid, s1, p1)["blokirano"] is True)
    check("(s1,p1) zadržao istaknuto", red(cid, s1, p1)["istaknuto"] is True)
    check("(s1,p1) zadržao prevoz obavezan", red(cid, s1, p1)["prevoz"] == "obavezan")
    check("(virt,p2) blokirano u bazi", red(cid, virt, p2)["blokirano"] is True)
    check("(s2,p1) NIJE blokirano", red(cid, s2, p1) is None)
    bl = blokirane(cid)
    check("opcije-celije: crvena polja = 4", {(s1, p1), (s1, p2), (virt, p1), (virt, p2)} <= bl)
    check("opcije-celije: s2 nije u blokiranima", (s2, p1) not in bl)

    # 3) odblokiraj isti izbor — skida blokadu, ostale opcije ostaju
    r = c.put(f"/api/cenovnici/{cid}/blokada", headers=H,
              json={"sobe": [s1, virt], "periodi": [p1, p2], "blokirano": False})
    check("blokada FALSE → 200", r.status_code == 200)
    check("(s1,p1) odblokirano", red(cid, s1, p1)["blokirano"] is False)
    check("(s1,p1) istaknuto ostaje", red(cid, s1, p1)["istaknuto"] is True)
    check("(virt,p2) odblokirano", red(cid, virt, p2)["blokirano"] is False)
    check("(virt,p2) bez reda ostaje bez reda (nije blokirano ranije)", red(cid, virt, p2) is not None)
    bl = blokirane(cid)
    check("opcije-celije: nijedno od 4 polja nije crveno", not ({(s1, p1), (s1, p2), (virt, p1), (virt, p2)} & bl))

    # 4) odblokiraj polje koje nikad nije blokirano → nema novog reda
    r = c.put(f"/api/cenovnici/{cid}/blokada", headers=H,
              json={"sobe": [s2], "periodi": [p2], "blokirano": False})
    check("odblokiraj nikad blokirano → 200", r.status_code == 200)
    check("(s2,p2) bez novog reda", red(cid, s2, p2) is None)

    # 5) nasleđena globalna (period_id=0) blokada: odblokiranje jednog polja
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO opcije_soba (cenovnik_id, soba_id, period_id, blokirano) "
            "VALUES (:c, :s, 0, TRUE)"), {"c": cid, "s": s2})
    bl = blokirane(cid)
    check("globalna blokada s2 važi za sve periode", {(s2, p1), (s2, p2)} <= bl)
    r = c.put(f"/api/cenovnici/{cid}/blokada", headers=H,
              json={"sobe": [s2], "periodi": [p1], "blokirano": False})
    check("odblokiraj nasleđeno polje → 200", r.status_code == 200)
    check("(s2,p1) eksplicitno odblokirano", red(cid, s2, p1)["blokirano"] is False)
    bl = blokirane(cid)
    check("(s2,p1) nije crveno, (s2,p2) i dalje crveno", (s2, p1) not in bl and (s2, p2) in bl)

    # 6) validacija
    r = c.put(f"/api/cenovnici/{cid}/blokada", headers=H,
              json={"sobe": [999999], "periodi": [p1], "blokirano": True})
    check("nepoznata soba → 400", r.status_code == 400)
    r = c.put(f"/api/cenovnici/{cid}/blokada", headers=H,
              json={"sobe": [s1], "periodi": [999999], "blokirano": True})
    check("nepoznat period → 400", r.status_code == 400)
    r = c.put(f"/api/cenovnici/{cid}/blokada", headers=H,
              json={"sobe": [], "periodi": [p1], "blokirano": True})
    check("prazan izbor sobe → 400", r.status_code == 400)
    r = c.put("/api/cenovnici/999999999/blokada", headers=H,
              json={"sobe": [s1], "periodi": [p1], "blokirano": True})
    check("nepoznat cenovnik → 404", r.status_code == 404)
    r = c.put(f"/api/cenovnici/{cid}/blokada", json={"sobe": [s1], "periodi": [p1], "blokirano": True})
    check("bez tokena → 401/403", r.status_code in (401, 403))
finally:
    c.delete(f"/api/cenovnici/{cid}", headers=H)

print(f"\n{sum(OK)}/{len(OK)} provera prošlo")
sys.exit(0 if all(OK) else 1)
