"""Test profila (profil_api) — offline prema dev serveru na 3158.

Koristi PRIVREMENOG korisnika (ne diramo pravog). Na kraju ga briše.
1. GET /profil vraća statistiku (ukupno_ugovora, danas_ugovora)
2. PUT /profil: validan telefon + JMBG se upisuju
3. PUT /profil: loš JMBG (12 cifara) → 422; prazan body → 400
4. POST /profil/lozinka: pogrešna trenutna → 400
5. POST /profil/lozinka: ista kao stara → 400
6. POST /profil/lozinka: ispravna → 200 i novi hash verifikuje
7. čišćenje: brisanje privremenog korisnika
"""
import json
import os
import urllib.error
import urllib.request

from sqlalchemy import create_engine, text

from routes import create_access_token, hash_password, verify_password

BASE = "http://127.0.0.1:3158/api"
engine = create_engine(os.environ.get("EXTERNAL_NEON_DATABASE_URL"))
STARA = "stara-lozinka-1"
NOVA = "nova-lozinka-2"
EMAIL = "profil.test@example.invalid"


def req(path, uid, method="GET", body=None):
    tok = create_access_token({"sub": str(uid)})
    hdr = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(f"{BASE}{path}", data=data, headers=hdr, method=method)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def provera(uslov, opis):
    assert uslov, f"FAIL: {opis}"
    print(f"  OK {opis}")


with engine.begin() as c:
    c.execute(text("DELETE FROM users WHERE email = :e"), {"e": EMAIL})
    uid = c.execute(text("""
        INSERT INTO users (first_name, last_name, email, username, password_hash, status)
        VALUES ('Profil', 'Test', :e, 'profil_test', :h, 'aktivan')
        RETURNING id
    """), {"e": EMAIL, "h": hash_password(STARA)}).scalar_one()

try:
    print("1. GET /profil")
    st, p = req("/profil", uid)
    provera(st == 200, "200")
    provera(p["statistika"]["ukupno_ugovora"] == 0, "bez ugovora → 0")
    provera(p["statistika"]["danas_ugovora"] == 0, "danas bez ugovora → 0")

    print("2. PUT /profil validno")
    st, p = req("/profil", uid, "PUT", {"phone": " +381 64 123 4567 ", "jmbg": "0101990710006"})
    provera(st == 200, "200")
    provera(p["phone"] == "+381 64 123 4567", "telefon trim + upisan")
    provera(p["jmbg"] == "0101990710006", "jmbg upisan")

    print("3. PUT /profil nevalidno")
    st, _ = req("/profil", uid, "PUT", {"jmbg": "123456789012"})
    provera(st == 422, "JMBG 12 cifara → 422")
    st, _ = req("/profil", uid, "PUT", {})
    provera(st == 400, "prazan body → 400")

    print("4. Lozinka")
    st, _ = req("/profil/lozinka", uid, "POST", {"trenutna": "pogresna-xx", "nova": NOVA})
    provera(st == 400, "pogrešna trenutna → 400")
    st, _ = req("/profil/lozinka", uid, "POST", {"trenutna": STARA, "nova": STARA})
    provera(st == 400, "ista kao stara → 400")
    st, _ = req("/profil/lozinka", uid, "POST", {"trenutna": STARA, "nova": "kratka"})
    provera(st == 422, "nova < 8 karaktera → 422")
    st, _ = req("/profil/lozinka", uid, "POST", {"trenutna": STARA, "nova": NOVA})
    provera(st == 200, "ispravna promena → 200")
    with engine.connect() as c:
        h = c.execute(text("SELECT password_hash FROM users WHERE id = :i"), {"i": uid}).scalar_one()
    provera(verify_password(NOVA, h), "novi hash verifikuje novu lozinku")
    provera(not verify_password(STARA, h), "stara lozinka više ne važi")
    print("SVE PROVERE PROŠLE")
finally:
    with engine.begin() as c:
        c.execute(text("DELETE FROM users WHERE id = :i"), {"i": uid})
    print("  očišćen privremeni korisnik")
