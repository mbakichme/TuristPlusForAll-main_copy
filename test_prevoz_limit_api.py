"""Limiti prevoz — API tok (offline prema dev serveru na 3158).

Provere:
1. POST sa postojećim destinacija/mesto/grupa ID-jevima → 201, GET vraća spojene nazive
2. POST sa nepostojećim mestom → 400
3. POST sa negativnim limitom / nepoznatim smerom / praznim nazivom → 422
4. POST sa negativnim dodatnim mestima (−2) → 201, ukupno = limit + dodatna
5. GET ?q= pretraga po nazivu mesta (ne samo po nazivu limita)
6. PUT menja vrednosti; PUT nepostojećeg → 404
7. DELETE → 200, ponovni DELETE → 404
8. čišćenje test redova
"""
import json
import urllib.error
import urllib.parse
import urllib.request

from routes import create_access_token

BASE = "http://127.0.0.1:3158/api"
tok = create_access_token({"sub": "1"})  # token se ne ispisuje
hdr = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
TEST_NAZIV = "TEST PREVOZ LIMIT"


def req(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(f"{BASE}{path}", data=data, headers=hdr, method=method)
    with urllib.request.urlopen(r, timeout=30) as resp:
        return json.load(resp)


def ocekuj_kod(path, method, body, kod):
    try:
        req(path, method, body)
    except urllib.error.HTTPError as e:
        assert e.code == kod, f"kod {e.code} != {kod}: {e.read().decode()[:200]}"
        return
    raise AssertionError(f"očekivan kod {kod}, zahtev je prošao")


def body(**izmene):
    b = {
        "naziv": TEST_NAZIV, "destinacija_id": None, "mesto_id": MESTO_ID,
        "grupa_datuma_id": GRUPA_ID, "smer": "Polazak", "limit": 40, "dodatna_mesta": 0,
    }
    b.update(izmene)
    return b


mesta = req("/mesto")
MESTO_ID = mesta[0]["id"]
MESTO_NAZIV = mesta[0]["naziv"]
grupe = req("/period-grupa")
GRUPA_ID = grupe[0]["id"] if grupe else None
dest = req("/destinacija")
DEST_ID = dest[0]["id"] if dest else None

kljucevi = []
ok = True
try:
    r = req("/prevoz-limit", "POST", body(destinacija_id=DEST_ID))
    idA = r["id"]; kljucevi.append(idA)
    lista = req("/prevoz-limit")
    a = next(x for x in lista if x["id"] == idA)
    assert a["mesto_naziv"] == MESTO_NAZIV, a
    assert a["grupa_datuma_naziv"] is not None or GRUPA_ID is None
    assert a["ukupno"] == 40
    print("1. POST → GET sa spojenim nazivima OK", idA)

    ocekuj_kod("/prevoz-limit", "POST", body(mesto_id=999999999), 400)
    print("2. nepostojeće mesto → 400 OK")

    ocekuj_kod("/prevoz-limit", "POST", body(limit=-1), 422)
    ocekuj_kod("/prevoz-limit", "POST", body(smer="Negde"), 422)
    ocekuj_kod("/prevoz-limit", "POST", body(naziv="   "), 422)
    print("3. negativan limit / loš smer / prazan naziv → 422 OK")

    rB = req("/prevoz-limit", "POST", body(naziv=TEST_NAZIV + " B", smer="Povratak", dodatna_mesta=-2))
    idB = rB["id"]; kljucevi.append(idB)
    b = next(x for x in req("/prevoz-limit") if x["id"] == idB)
    assert b["dodatna_mesta"] == -2 and b["ukupno"] == 38, b
    print("4. dodatna mesta −2 → ukupno 38 OK")

    pronadjeni = req("/prevoz-limit?q=" + urllib.parse.quote(MESTO_NAZIV))
    assert any(x["id"] == idA for x in pronadjeni), "pretraga po mestu ne vraća zapis"
    print("5. pretraga po nazivu mesta OK")

    req(f"/prevoz-limit/{idA}", "PUT", body(naziv=TEST_NAZIV + " izmenjen", limit=50, dodatna_mesta=3))
    a2 = next(x for x in req("/prevoz-limit") if x["id"] == idA)
    assert a2["naziv"].endswith("izmenjen") and a2["limit"] == 50 and a2["ukupno"] == 53, a2
    print("6. PUT menja vrednosti OK")
    ocekuj_kod("/prevoz-limit/999999999", "PUT", body(), 404)

    req(f"/prevoz-limit/{idB}", "DELETE")
    assert not any(x["id"] == idB for x in req("/prevoz-limit"))
    ocekuj_kod(f"/prevoz-limit/{idB}", "DELETE", None, 404)
    kljucevi.remove(idB)
    print("7. DELETE → 200, ponovni → 404 OK")
except Exception as e:
    ok = False
    print("  FAIL:", e)

# ── čišćenje ──
for i in kljucevi:
    try:
        req(f"/prevoz-limit/{i}", "DELETE")
    except Exception:
        pass
ostalo = [x for x in req("/prevoz-limit") if x["naziv"].startswith(TEST_NAZIV)]
print("ostalo test redova:", len(ostalo))
print("\nREZULTAT:", "SVE PROVERE PROŠLE" if ok and not ostalo else "IMA GREŠAKA")
