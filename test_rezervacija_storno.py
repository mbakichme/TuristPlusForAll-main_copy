"""Provera STORNO na privremenim zapisima; postojeći ugovori se ne menjaju."""
import os
from uuid import uuid4
import httpx
from sqlalchemy import create_engine, text
from routes import create_access_token


def main():
    engine = create_engine(os.environ.get("EXTERNAL_NEON_DATABASE_URL"))
    kljuc = f"TEST-STORNO-{uuid4().hex[:12]}/26"
    headers = {"Authorization": "Bearer " + create_access_token({"sub": "1"})}
    base = "http://127.0.0.1:3158/api"
    with engine.begin() as c:
        c.execute(text("INSERT INTO aranzman (kljuc, putnik, naziv, soba, tiprezervacije, napomena, cenaaranz, uplaceno) VALUES (:k, 'TEST STORNO', 'TEST VILA', 'T9', 'Predrezervacija', 'Postojeća napomena', 123, 45)"), {"k": kljuc})
    try:
        with httpx.Client(base_url=base, headers=headers, timeout=30) as client:
            path = f"/rezervacije/{kljuc}/storno"
            assert client.post(path).status_code == 200
            with engine.connect() as c:
                row = c.execute(text("SELECT tiprezervacije, naziv, soba, smestaj_id, napomena, cenaaranz, uplaceno, putnik FROM aranzman WHERE kljuc=:k"), {"k": kljuc}).mappings().one()
            assert row['tiprezervacije'] == row['naziv'] == 'STORNO'
            assert row['soba'] == '' and row['smestaj_id'] is None
            assert row['napomena'].startswith('Postojeća napomena\n') and 'TEST VILA' in row['napomena'] and 'T9' in row['napomena']
            assert row['putnik'] == 'TEST STORNO - (STORNO)'
            assert row['cenaaranz'] == 123 and row['uplaceno'] == 45
            assert client.post(path).status_code == 200
            with engine.connect() as c:
                assert c.execute(text('SELECT napomena FROM aranzman WHERE kljuc=:k'), {'k':kljuc}).scalar_one() == row['napomena']
                assert c.execute(text('SELECT putnik FROM aranzman WHERE kljuc=:k'), {'k':kljuc}).scalar_one() == row['putnik']
            assert client.post('/rezervacije/NEPOSTOJECI-STORNO/26/storno').status_code == 404
            assert httpx.post(base + path, timeout=30).status_code == 401
            with engine.begin() as c:
                c.execute(text("UPDATE aranzman SET tiprezervacije='Predrezervacija', naziv='TEST VILA', soba='T9', napomena=:n WHERE kljuc=:k"), {'n':'x'*1024,'k':kljuc})
            assert client.post(path).status_code == 400
            with engine.connect() as c:
                assert c.execute(text('SELECT soba FROM aranzman WHERE kljuc=:k'), {'k':kljuc}).scalar_one() == 'T9'
        print('OK: storno, očuvana napomena i cene, idempotentnost, 404/401, rollback preduge napomene')
    finally:
        with engine.begin() as c:
            c.execute(text('DELETE FROM rezervacija_log WHERE kljuc=:k'), {'k':kljuc})
            c.execute(text('DELETE FROM aranzman WHERE kljuc=:k'), {'k':kljuc})
        engine.dispose()

if __name__ == '__main__':
    main()
