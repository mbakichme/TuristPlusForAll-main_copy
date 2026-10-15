"""Virtuelne sobe u cenovniku: redovi v{broj} / v{broj}-N po dodatnim koeficijentima sobe."""
import os
import sys

import routes
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
engine = create_engine(os.environ["EXTERNAL_NEON_DATABASE_URL"])
app = routes.create_app("dist")
c = TestClient(app)
tok = routes.create_access_token({"sub": "1"})
H = {"Authorization": f"Bearer {tok}"}

OK = []


def check(label, cond):
    OK.append(cond)
    print(("PASS " if cond else "FAIL ") + label)


# ── priprema: privremene sobe sa 2 / 1 / 0 dodatnih koeficijenata ──────────
with engine.begin() as conn:
    # idempotentno: obriši eventualne zaostatke iz prethodnog run-a
    conn.execute(text(
        "DELETE FROM sobe WHERE veza_id_smestaj = 8 AND broj_sobe IN ('901','902','903')"))
    ids = {}
    for broj, koef in [("901", ["1/2", "1/4"]), ("902", ["1/2"]), ("903", [])]:
        sid = conn.execute(text(
            "INSERT INTO sobe (veza_id_smestaj, broj_sobe, tip, opis) "
            "VALUES (8, :b, '1/3', 'STD') RETURNING id"), {"b": broj}).scalar_one()
        for k in koef:
            conn.execute(text(
                "INSERT INTO soba_koeficijenti (soba_id, struktura) VALUES (:s, :k)"),
                {"s": sid, "k": k})
        ids[broj] = sid
print(f"[setup] privremene sobe: {ids}")
TEMP_IDS = tuple(ids.values())

# ── 1) GET /cenovnici/sablon ────────────────────────────────────────────────
r = c.get("/api/cenovnici/sablon?mesto_id=1&grupa_id=6&smestaj_id=8", headers=H)
check("GET sablon → 200", r.status_code == 200)
sobe = r.json()["sobe"]
poz = {s["broj_sobe"]: i for i, s in enumerate(sobe)}
i901, i903 = poz["901"], poz["903"]
v = [s for s in sobe if s.get("virtuelna")]

v901 = [s for s in v if s["izvor_soba_id"] == ids["901"]]
v902 = [s for s in v if s["izvor_soba_id"] == ids["902"]]
v903 = [s for s in v if s["izvor_soba_id"] == ids["903"]]
check("soba sa 2 dodatna koeficijenta → v901-1 (1/2) i v901-2 (1/4), odmah ispod",
      [s["broj_sobe"] for s in v901] == ["v901-1", "v901-2"]
      and v901[0]["tip"] == "1/2" and v901[1]["tip"] == "1/4"
      and poz["v901-1"] == i901 + 1 and poz["v901-2"] == i901 + 2)
check("soba sa 1 dodatnim koeficijentom → v902 (bez sufiksa)",
      [s["broj_sobe"] for s in v902] == ["v902"] and v902[0]["tip"] == "1/2"
      and poz["v902"] == poz["902"] + 1)
check("soba bez dodatnih koeficijenata → nema virtuelnih redova", v903 == [])
check("virtuelna soba: opis preuzet iz sobe (STD), id negativan, veza izvor_soba_id",
      all(s["opis"] == "STD" and s["id"] < 0 and s["izvor_soba_id"] > 0 for s in v))
check("stvarna soba nema virtuelna/izvor_soba_id polja",
      all("virtuelna" not in s and "izvor_soba_id" not in s for s in sobe if not s.get("virtuelna")))

# ── 2) POST cenovnika sa cenom na virtuelnoj sobi ──────────────────────────
per = r.json()["periodi"][0]
cene = [
    {"soba_id": ids["901"], "period_id": per["id"], "cena": "100"},
    {"soba_id": v901[0]["id"], "period_id": per["id"], "cena": "80"},
    {"soba_id": v901[1]["id"], "period_id": per["id"], "cena": "90"},
]
r2 = c.post("/api/cenovnici", headers=H, json={
    "mesto_id": 1, "grupa_id": 6, "smestaj_id": 8,
    "datumod": "2026-11-01", "datumdo": "2026-11-30", "cene": cene})
check("POST cenovnik sa cenama na virtuelnim sobama → 201", r2.status_code == 201)
cid = r2.json()["id"]
cene_ret = {(x["soba_id"], x["period_id"]): x["cena"] for x in r2.json()["cene"]}
check("cena virtuelne sobe (negativan soba_id) sačuvana",
      cene_ret.get((v901[0]["id"], per["id"])) == "80.00"
      and cene_ret.get((v901[1]["id"], per["id"])) == "90.00")
snap_sobe = r2.json()["sobe"]
moje_v = [s for s in snap_sobe if s.get("virtuelna") and s["izvor_soba_id"] in TEMP_IDS]
check("snimak u bazi sadrži virtuelne sobe sa vezom (3 za moje sobe)",
      len(moje_v) == 3
      and {s["izvor_soba_id"] for s in moje_v} == {ids["901"], ids["902"]})

# lažna soba i dalje odbijena
r3 = c.post("/api/cenovnici", headers=H, json={
    "mesto_id": 1, "grupa_id": 6, "smestaj_id": 8,
    "datumod": "2026-11-01", "datumdo": "2026-11-30",
    "cene": [{"soba_id": -999, "period_id": per["id"], "cena": "10"}]})
check("POST sa nepoznatim soba_id → 400", r3.status_code == 400)

# ── 3) PUT: izmena cene virtuelne sobe ─────────────────────────────────────
r4 = c.put(f"/api/cenovnici/{cid}", headers=H, json={
    "datumod": "2026-11-01", "datumdo": "2026-11-30",
    "cene": [{"soba_id": v901[0]["id"], "period_id": per["id"], "cena": "85"}]})
check("PUT menja cenu virtuelne sobe → 85.00",
      r4.status_code == 200
      and {(x["soba_id"]): x["cena"] for x in r4.json()["cene"]}[v901[0]["id"]] == "85.00")

# ── 4) UI: matrica za ELENI 2 pokazuje v12 ispod sobe 12 ───────────────────
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    pg.goto("http://localhost:3058/agencija/cenovnici")
    pg.evaluate(f"localStorage.setItem('ta_token', '{tok}')")
    pg.goto("http://localhost:3058/agencija/cenovnici")
    pg.wait_for_selector("[role=tablist]")
    pg.get_by_role("combobox").nth(0).click()
    pg.get_by_role("option", name="Hanioti").first.click()
    pg.get_by_role("combobox").nth(1).click()
    pg.get_by_role("option").filter(has_text="Kasandra: termini").first.click()
    pg.get_by_role("combobox").nth(2).click()
    pg.get_by_role("option", name="ELENI 2").first.click()
    pg.get_by_role("button", name="Kreiraj cenovnik").click()
    pg.get_by_role("textbox").first.wait_for(state="visible", timeout=15000)
    cell12 = pg.get_by_role("cell", name="12", exact=True)
    cell12.first.wait_for(state="visible", timeout=10000)
    check("UI: kolona sa sobom 12 vidljiva", cell12.count() > 0)
    check("UI: virtuelna soba v12 vidljiva u matrici",
          pg.get_by_role("cell", name="v12", exact=True).count() > 0)
    check("UI: v12 red odmah ispod sobe 12 (y veći)",
          cell12.first.bounding_box()["y"] < pg.get_by_role("cell", name="v12", exact=True).first.bounding_box()["y"])
    check("UI: v12 nosi strukturu iz koeficijenta (1/2 · STD)",
          pg.get_by_role("row").filter(has=pg.get_by_role("cell", name="v12", exact=True))
          .filter(has_text="1/2 · STD").count() > 0)
    b.close()

# ── cleanup ─────────────────────────────────────────────────────────────────
check("cleanup cenovnik obrisan", c.delete(f"/api/cenovnici/{cid}", headers=H).status_code == 200)
with engine.begin() as conn:
    n = conn.execute(text(
        "DELETE FROM sobe WHERE veza_id_smestaj = 8 AND broj_sobe IN ('901','902','903')"
    )).rowcount
check("cleanup privremene sobe obrisane (koeficijenti CASCADE)", n == 3)

print(f"\n{sum(OK)}/{len(OK)} PASS")
sys.exit(0 if all(OK) else 1)
