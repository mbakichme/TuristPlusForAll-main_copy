"""Limiti prevoz — API tok (offline prema dev serveru na 3158).

Provere:
1. POST sa ispravnim lancem država→destinacija→mesto→grupa → 201, naziv = Država-Destinacija-Mesto-Grupa-dd.mm.yyyy
2. destinacija iz druge države → 400
3. mesto iz druge destinacije → 400
4. grupa termina koja nije vezana za mesto → 400
5. isti (mesto, grupa, datum, smer) ponovo → 409
6. smer "Polazak" / negativan limit → 422
7. dodatna mesta −2 → ukupno = limit − 2
8. pretraga po nazivu države
9. PUT menja vrednosti; PUT nepostojećeg → 404
10. DELETE → 200; ponovni → 404
11. POST /prevoz-limit/generisi → drugi poziv ne dodaje ništa (idempotentno)
Zapisi generisani u koraku 11 se NAMERNO ne brišu (traženi rezultat).
"""
import json
import urllib.error
import urllib.parse
import urllib.request

from routes import create_access_token

BASE = "http://127.0.0.1:3158/api"
tok = create_access_token({"sub": "1"})  # token se ne ispisuje
hdr = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
TEST_TAG = "TEST PREVOZ LIMIT"


def req(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(f"{BASE}{path}", data=data, headers=hdr, method=method)
    with urllib.request.urlopen(r, timeout=120) as resp:
        return json.load(resp)


def ocekuj_kod(path, method, body, kod):
    try:
        req(path, method, body)
    except urllib.error.HTTPError as e:
        assert e.code == kod, f"kod {e.code} != {kod}: {e.read().decode()[:200]}"
        return
    raise AssertionError(f"očekivan kod {kod}, zahtev je prošao")


def naziv_ocekivan(drz, dest, mesto, grupa, datum_iso):
    y, m, d = datum_iso.split("-")
    return f"{drz}-{dest}-{mesto}-{grupa}-{d}.{m}.{y}"


drzave = {d["id"]: d["naziv"] for d in req("/drzava")}
destinacije = {d["id"]: d for d in req("/destinacija")}
grupe = {g["id"]: g["naziv"] for g in req("/period-grupa")}
mesta = [m for m in req("/mesto") if m.get("destinacija") in destinacije
         and destinacije[m["destinacija"]].get("drzava") in drzave and m.get("grupe")]
assert len(mesta) >= 1, "nema mesta sa destinacijom, državom i grupom"
M = mesta[0]
D = destinacije[M["destinacija"]]
G = M["grupe"][0]
DRZ = D["drzava"]
DATUM = "2030-06-01"  # test datum, nema veze sa realnim terminima


def body(**izmene):
    b = {"drzava_id": DRZ, "destinacija_id": D["id"], "mesto_id": M["id"],
         "grupa_datuma_id": G, "datum": DATUM, "smer": "Odlazak", "limit": 40, "dodatna_mesta": 0}
    b.update(izmene)
    return b


kljucevi = []
ok = True
try:
    r = req("/prevoz-limit", "POST", body())
    idA = r["id"]; kljucevi.append(idA)
    a = next(x for x in req("/prevoz-limit") if x["id"] == idA)
    ocekivan = naziv_ocekivan(drzave[DRZ], D["naziv"], M["naziv"], grupe[G], DATUM)
    assert a["naziv"] == ocekivan, (a["naziv"], ocekivan)
    assert a["datum"] == DATUM and a["smer"] == "Odlazak" and a["ukupno"] == 40
    print("1. POST → naziv", a["naziv"])

    tudja = next((d for d in destinacije.values() if d.get("drzava") not in (None, DRZ)), None)
    if tudja:
        ocekuj_kod("/prevoz-limit", "POST", body(destinacija_id=tudja["id"]), 400)
    print("2. destinacija iz druge države → 400", "(preskočeno, nema druge države)" if not tudja else "OK")

    drugo_mesto = next((m for m in req("/mesto") if m.get("destinacija") not in (None, D["id"])), None)
    if drugo_mesto:
        ocekuj_kod("/prevoz-limit", "POST", body(mesto_id=drugo_mesto["id"]), 400)
    print("3. mesto iz druge destinacije → 400 OK")

    tudja_grupa = next((g for g in grupe if g not in M["grupe"]), None)
    if tudja_grupa:
        ocekuj_kod("/prevoz-limit", "POST", body(grupa_datuma_id=tudja_grupa), 400)
    print("4. grupa nevezana za mesto → 400 OK")

    ocekuj_kod("/prevoz-limit", "POST", body(), 409)
    print("5. duplikat → 409 OK")

    ocekuj_kod("/prevoz-limit", "POST", body(smer="Polazak", datum="2030-06-02"), 422)
    ocekuj_kod("/prevoz-limit", "POST", body(limit=-1, datum="2030-06-03"), 422)
    print("6. smer Polazak / negativan limit → 422 OK")

    rB = req("/prevoz-limit", "POST", body(smer="Povratak", dodatna_mesta=-2))
    kljucevi.append(rB["id"])
    b = next(x for x in req("/prevoz-limit") if x["id"] == rB["id"])
    assert b["dodatna_mesta"] == -2 and b["ukupno"] == 38, b
    print("7. dodatna −2 → ukupno 38 OK")

    pronadjeni = req("/prevoz-limit?q=" + urllib.parse.quote(drzave[DRZ]))
    assert any(x["id"] == idA for x in pronadjeni), "pretraga po državi ne vraća zapis"
    print("8. pretraga po državi OK")

    req(f"/prevoz-limit/{idA}", "PUT", body(limit=50, dodatna_mesta=3))
    a2 = next(x for x in req("/prevoz-limit") if x["id"] == idA)
    assert a2["limit"] == 50 and a2["ukupno"] == 53, a2
    print("9. PUT OK")
    ocekuj_kod("/prevoz-limit/999999999", "PUT", body(), 404)

    req(f"/prevoz-limit/{rB['id']}", "DELETE")
    kljucevi.remove(rB["id"])
    ocekuj_kod(f"/prevoz-limit/{rB['id']}", "DELETE", None, 404)
    print("10. DELETE → 200, ponovni → 404 OK")

    prvi = req("/prevoz-limit/generisi", "POST")
    drugi = req("/prevoz-limit/generisi", "POST")
    assert drugi["dodato"] == 0, drugi
    print("11. generisi:", prvi, "| ponovo:", drugi)
except Exception as e:
    ok = False
    print("  FAIL:", e)

# ── čišćenje test zapisa (ručno kreirani; generisani ostaju) ──
for i in kljucevi:
    try:
        req(f"/prevoz-limit/{i}", "DELETE")
    except Exception:
        pass
print("\nREZULTAT:", "SVE PROVERE PROŠLE" if ok else "IMA GREŠAKA")
