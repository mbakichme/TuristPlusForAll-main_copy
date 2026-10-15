"""Osvežavanje spiska soba pri izmeni cenovnika: dodate/obrisane sobe i koeficijenti.

Editor (GET /cenovnici/{id}) uvek vraća spisak soba usklađen sa živim stanjem —
nove sobe/virtuelne sobe (po dodatnim koeficijentima) se pojavljuju sa oznakom
"nova", nestale nestaju, a virtuelne sobe koje se i dalje poklapaju zadržavaju
id pa cene ostaju vezane za ispravan red. PUT upisuje osvežen snimak u cenovnik,
a cene za nestale sobe briše (DELETE-all + reinsert samo soba iz payload-a).
"""
import json
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


# ── priprema: privremene sobe 901 (2 koefa), 902 (1 koef), 903 (0) ──────────
with engine.begin() as conn:
    conn.execute(text(
        "DELETE FROM sobe WHERE veza_id_smestaj = 8 AND broj_sobe IN ('901','902','903','904','905')"))
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


def postavi_cene(cene_po_sobi, per_id):
    return [{"soba_id": s, "period_id": per_id, "cena": v} for s, v in cene_po_sobi.items()]


def db_sobe(cid):
    with engine.connect() as conn:
        return conn.execute(text("SELECT sobe FROM cenovnici WHERE id = :i"), {"i": cid}).scalar_one()


def db_cene(cid):
    with engine.connect() as conn:
        return {(x.soba_id, x.period_id): str(x.cena) for x in conn.execute(text(
            "SELECT soba_id, period_id, cena FROM cenovnik_cene WHERE cenovnik_id = :i"),
            {"i": cid})}


# ── 0) POST baznog cenovnika ────────────────────────────────────────────────
r = c.get("/api/cenovnici/sablon?mesto_id=1&grupa_id=6&smestaj_id=8", headers=H)
per = r.json()["periodi"][0]
r2 = c.post("/api/cenovnici", headers=H, json={
    "mesto_id": 1, "grupa_id": 6, "smestaj_id": 8,
    "datumod": "2026-11-01", "datumdo": "2026-11-30",
    "cene": postavi_cene({ids["901"]: "100"}, per["id"])})
check("POST baznog cenovnika → 201", r2.status_code == 201)
cid = r2.json()["id"]
d0 = c.get(f"/api/cenovnici/{cid}", headers=H).json()
stari_virt = {s["tip"]: s["id"] for s in d0["sobe"] if s.get("virtuelna") and s["izvor_soba_id"] == ids["902"]}
check("bazno stanje: 901 ima v901-1/v901-2, 902 ima v902, 903 nema virtuelnu",
      stari_virt.get("1/2") is not None
      and sum(1 for s in d0["sobe"] if s.get("virtuelna") and s["izvor_soba_id"] == ids["901"]) == 2
      and not any(s.get("virtuelna") and s["izvor_soba_id"] == ids["903"] for s in d0["sobe"]))
check("bez 'nova' oznaka na osveženom detail-u bez promena",
      not any(s.get("nova") for s in d0["sobe"]))
vid_902_1_2 = stari_virt["1/2"]

# ── 1) DODAT koeficijent (902 + 1/3) → nova virtuelna soba, stari id ostaje ─
with engine.begin() as conn:
    conn.execute(text("INSERT INTO soba_koeficijenti (soba_id, struktura) VALUES (:s, '1/3')"),
                 {"s": ids["902"]})
d1 = c.get(f"/api/cenovnici/{cid}", headers=H).json()
v902 = [s for s in d1["sobe"] if s.get("virtuelna") and s["izvor_soba_id"] == ids["902"]]
check("dodat koeficijent → 902 sada ima 2 virtuelne sobe (v902-1 1/2, v902-2 1/3)",
      [s["broj_sobe"] for s in v902] == ["v902-1", "v902-2"]
      and v902[0]["tip"] == "1/2" and v902[1]["tip"] == "1/3")
check("stara virtuelna (1/2) ZADRŽAVA id — postojeće cene ostaju vezane",
      v902[0]["id"] == vid_902_1_2)
check("nova virtuelna soba: nov id (ispod najnižeg starog) + oznaka 'nova'",
      v902[1]["id"] < vid_902_1_2 and v902[1].get("nova") is True
      and not v902[0].get("nova"))
r3 = c.put(f"/api/cenovnici/{cid}", headers=H, json={
    "datumod": "2026-11-01", "datumdo": "2026-11-30",
    "cene": postavi_cene({ids["901"]: "100", v902[0]["id"]: "55"}, per["id"])})
check("PUT sa cenom na starijoj virtuelnoj → 200", r3.status_code == 200)
check("PUT upisao osvežen snimak: nova virtuelna sada u cenovnici.sobe (bez 'nova' taga)",
      any(s.get("virtuelna") and s["tip"] == "1/3" and s["izvor_soba_id"] == ids["902"]
          and not s.get("nova") for s in r3.json()["sobe"]))
r3b = c.put(f"/api/cenovnici/{cid}", headers=H, json={
    "datumod": "2026-11-01", "datumdo": "2026-11-30",
    "cene": postavi_cene({ids["901"]: "100", v902[0]["id"]: "55", v902[1]["id"]: "66"}, per["id"])})
check("PUT sa cenom na NOVOJ virtuelnoj → 200 i sačuvana",
      r3b.status_code == 200
      and db_cene(cid).get((v902[1]["id"], per["id"])) == "66.00")

# ── 2) UKLONJEN koeficijent (902 − 1/2) → virtuelna nestaje, njena cena se briše
with engine.begin() as conn:
    conn.execute(text("DELETE FROM soba_koeficijenti WHERE soba_id = :s AND struktura = '1/2'"),
                 {"s": ids["902"]})
d2 = c.get(f"/api/cenovnici/{cid}", headers=H).json()
v902n = [s for s in d2["sobe"] if s.get("virtuelna") and s["izvor_soba_id"] == ids["902"]]
check("uklonjen koeficijent → za 902 ostaje samo virtuelna 1/3 (isti id, labela v902)",
      len(v902n) == 1 and v902n[0]["id"] == v902[1]["id"]
      and v902n[0]["tip"] == "1/3" and v902n[0]["broj_sobe"] == "v902"
      and v902n[0].get("nova") is None)
r4 = c.put(f"/api/cenovnici/{cid}", headers=H, json={
    "datumod": "2026-11-01", "datumdo": "2026-11-30",
    "cene": postavi_cene({ids["901"]: "100", v902n[0]["id"]: "66"}, per["id"])})
check("PUT nakon uklanjanja koeficijenta → 200", r4.status_code == 200)
check("cena uklonjene virtuelne sobe obrisana iz cenovnik_cene",
      (vid_902_1_2, per["id"]) not in db_cene(cid))
check("snimak u bazi bez uklonjene virtuelne sobe",
      not any(s.get("virtuelna") and s["tip"] == "1/2" and s["izvor_soba_id"] == ids["902"]
              for s in db_sobe(cid)))
check("cene preživelih soba zadržane", db_cene(cid).get((ids["901"], per["id"])) == "100.00"
      and db_cene(cid).get((v902n[0]["id"], per["id"])) == "66.00")

# ── 3) DODATA prava soba (904) → pojavljuje se sa 'nova', PUT je upisuje ────
with engine.begin() as conn:
    ids["904"] = conn.execute(text(
        "INSERT INTO sobe (veza_id_smestaj, broj_sobe, tip, opis) "
        "VALUES (8, '904', '1/3', 'STD') RETURNING id")).scalar_one()
d3 = c.get(f"/api/cenovnici/{cid}", headers=H).json()
s904 = [s for s in d3["sobe"] if s["id"] == ids["904"]]
check("dodata prava soba 904 → u detail-u sa oznakom 'nova'",
      len(s904) == 1 and s904[0].get("nova") is True and s904[0]["broj_sobe"] == "904")
r5 = c.put(f"/api/cenovnici/{cid}", headers=H, json={
    "datumod": "2026-11-01", "datumdo": "2026-11-30",
    "cene": postavi_cene({ids["901"]: "100", v902n[0]["id"]: "66", ids["904"]: "123"}, per["id"])})
check("PUT sa cenom za novu sobu → 200, snimak i cena upisani",
      r5.status_code == 200
      and any(s["id"] == ids["904"] and not s.get("nova") for s in r5.json()["sobe"])
      and db_cene(cid).get((ids["904"], per["id"])) == "123.00")

# ── 4) OBRISANA prava soba (904) → nestaje, njena cena se briše ─────────────
with engine.begin() as conn:
    conn.execute(text("DELETE FROM sobe WHERE id = :i"), {"i": ids["904"]})
d4 = c.get(f"/api/cenovnici/{cid}", headers=H).json()
check("obrisana soba 904 → više je u detail-u", not any(s["id"] == ids["904"] for s in d4["sobe"]))
r6 = c.put(f"/api/cenovnici/{cid}", headers=H, json={
    "datumod": "2026-11-01", "datumdo": "2026-11-30",
    "cene": postavi_cene({ids["901"]: "100", v902n[0]["id"]: "66"}, per["id"])})
check("PUT nakon brisanja sobe → 200", r6.status_code == 200)
check("cena obrisane sobe uklonjena iz cenovnik_cene",
      (ids["904"], per["id"]) not in db_cene(cid))
check("snimak u bazi bez obrisane sobe", not any(s["id"] == ids["904"] for s in db_sobe(cid)))
check("cene preživelih i dalje na mestu", db_cene(cid).get((ids["901"], per["id"])) == "100.00")

# ── 5) LEGACY snimak (cenovnik pre virtuelnih soba) → refresh ih doda ───────
with engine.begin() as conn:
    stare = db_sobe(cid)
    conn.execute(text("UPDATE cenovnici SET sobe = CAST(:s AS JSONB) WHERE id = :i"),
                 {"s": json.dumps([s for s in stare if not s.get("virtuelna")]), "i": cid})
d5 = c.get(f"/api/cenovnici/{cid}", headers=H).json()
leg_v = [s for s in d5["sobe"] if s.get("virtuelna") and s["izvor_soba_id"] in TEMP_IDS]
check("legacy snimak bez virtuelnih → detail ih regeneriše (v901-1, v901-2, v902) sa 'nova'",
      [s["broj_sobe"] for s in leg_v] == ["v901-1", "v901-2", "v902"]
      and all(s.get("nova") is True for s in leg_v))
leg_v901 = leg_v[0]
r7 = c.put(f"/api/cenovnici/{cid}", headers=H, json={
    "datumod": "2026-11-01", "datumdo": "2026-11-30",
    "cene": postavi_cene({ids["901"]: "100", leg_v901["id"]: "80", leg_v[2]["id"]: "66"}, per["id"])})
check("PUT legacy cenovnika → virtuelne upisane u snimak, cena na virtuelnoj sačuvana",
      r7.status_code == 200
      and len([s for s in db_sobe(cid) if s.get("virtuelna") and s["izvor_soba_id"] in TEMP_IDS]) == 3
      and db_cene(cid).get((leg_v901["id"], per["id"])) == "80.00")

# ── 6) UI: editor u tabu Izmena pokazuje nove sobe/koeficijente i čuva ih ───
with engine.begin() as conn:
    conn.execute(text("INSERT INTO soba_koeficijenti (soba_id, struktura) VALUES (:s, '1/4')"),
                 {"s": ids["902"]})
    ids["905"] = conn.execute(text(
        "INSERT INTO sobe (veza_id_smestaj, broj_sobe, tip, opis) "
        "VALUES (8, '905', '1/3', 'STD') RETURNING id")).scalar_one()
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    pg.goto("http://localhost:3058/agencija/cenovnici")
    pg.evaluate(f"localStorage.setItem('ta_token', '{tok}')")
    pg.goto("http://localhost:3058/agencija/cenovnici")
    pg.wait_for_selector("[role=tablist]")
    pg.get_by_role("tab", name="Izmena").click()
    pg.get_by_role("cell", name=str(cid), exact=True).first.click()
    row905 = pg.get_by_role("row").filter(has=pg.get_by_role("cell", name="905", exact=True))
    row905.first.wait_for(state="visible", timeout=15000)  # matrica se renderuje posle detail fetch-a
    cellv = pg.get_by_role("cell", name="v902-2", exact=True)
    cellv.first.wait_for(state="visible", timeout=15000)
    check("UI: nova soba 905 vidljiva u matrici izmene", row905.count() > 0)
    check("UI: nova soba nosi 'nova' oznaku", row905.get_by_text("nova", exact=True).count() > 0)
    check("UI: novododata virtuelna soba (v902-2) vidljiva", cellv.count() > 0)
    check("UI: virtuelna soba ima violet pill oznaku",
          "bg-violet-500/10" in cellv.first.evaluate(
              "el => [...el.querySelectorAll('span')].map(s => s.className).join(' ')"))
    check("UI: otvoren cenovnik je zaključan u startu",
          row905.get_by_role("textbox").first.is_disabled())
    pg.get_by_role("button", name="Izmeni cenovnik", exact=True).click()
    pg.wait_for_timeout(300)
    row905.get_by_role("textbox").first.fill("123")
    pg.get_by_role("button", name="Sačuvaj izmene").click()
    pg.get_by_text("Izmene cenovnika su sačuvane").wait_for(timeout=10000)
    b.close()
check("posle UI snimanja: soba 905 u snimku i njena cena sačuvana",
      any(s["id"] == ids["905"] for s in db_sobe(cid))
      and db_cene(cid).get((ids["905"], per["id"])) == "123.00")
check("posle UI snimanja: 'nova' oznake nestaju (sinhronizovano)",
      not any(s.get("nova") for s in db_sobe(cid)))

# ── cleanup ─────────────────────────────────────────────────────────────────
check("cleanup cenovnik obrisan", c.delete(f"/api/cenovnici/{cid}", headers=H).status_code == 200)
with engine.begin() as conn:
    conn.execute(text(
        "DELETE FROM sobe WHERE veza_id_smestaj = 8 AND broj_sobe IN ('901','902','903','905')"))
ostalo = engine.connect().execute(text(
    "SELECT count(*) FROM sobe WHERE veza_id_smestaj = 8 AND broj_sobe IN ('901','902','903','905')")).scalar()
check("cleanup privremene sobe obrisane (koeficijenti CASCADE)", ostalo == 0)

print(f"\n{sum(OK)}/{len(OK)} PASS")
sys.exit(0 if all(OK) else 1)
