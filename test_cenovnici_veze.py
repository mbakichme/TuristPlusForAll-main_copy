"""FK veze cenovnika: cenovnik ↔ mesto / grupa termina / smeštaj, cene ↔ soba."""
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


def fk_rule(table, col):
    with engine.connect() as conn:
        r = conn.execute(text("""
            SELECT ccu.table_name, rc.delete_rule
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
              ON tc.constraint_name = ccu.constraint_name
            LEFT JOIN information_schema.referential_constraints rc
              ON tc.constraint_name = rc.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_name = :t
              AND kcu.column_name = :c
        """), {"t": table, "c": col}).first()
        return r


# 1) FK postoji i pokazuje na pravu tabelu
check("FK cenovnici.mesto_id → mesto (RESTRICT)",
      fk_rule("cenovnici", "mesto_id") == ("mesto", "RESTRICT"))
check("FK cenovnici.grupa_id → period_grupa (RESTRICT)",
      fk_rule("cenovnici", "grupa_id") == ("period_grupa", "RESTRICT"))
check("FK cenovnici.smestaj_id → smestaj (RESTRICT)",
      fk_rule("cenovnici", "smestaj_id") == ("smestaj", "RESTRICT"))
check("FK cenovnik_cene.soba_id → sobe (RESTRICT)",
      fk_rule("cenovnik_cene", "soba_id") == ("sobe", "RESTRICT"))

with engine.connect() as conn:
    cid = conn.execute(text(
        "SELECT id FROM cenovnici ORDER BY id LIMIT 1")).scalar()
    row = conn.execute(text(
        "SELECT mesto_id, grupa_id, smestaj_id FROM cenovnici WHERE id = :i"),
        {"i": cid}).one()
    mesto_id, grupa_id, smestaj_id = row
    soba_id = conn.execute(text(
        "SELECT soba_id FROM cenovnik_cene WHERE cenovnik_id = :i LIMIT 1"),
        {"i": cid}).scalar_one()
    # sva upisana vezivanja ciljaju postojeće redove
    check("postojeći cenovnik ima ispravne veze (mesto/grupa/smeštaj/sobe)",
          conn.execute(text("""
            SELECT COUNT(*) FROM cenovnici c
            LEFT JOIN mesto m ON m.id = c.mesto_id
            LEFT JOIN period_grupa g ON g.id = c.grupa_id
            LEFT JOIN smestaj s ON s.id = c.smestaj_id
            WHERE m.id IS NULL OR g.id IS NULL OR s.id IS NULL
          """)).scalar() == 0 and
          conn.execute(text("""
            SELECT COUNT(*) FROM cenovnik_cene cc
            LEFT JOIN cenovnici c ON c.id = cc.cenovnik_id
            LEFT JOIN sobe s ON s.id = cc.soba_id
            WHERE c.id IS NULL OR s.id IS NULL
          """)).scalar() == 0)

# 2) lažan podatak se ne može upisati
with engine.connect() as conn:
    for label, sql in [
        ("lažan mesto_id blokiran", "UPDATE cenovnici SET mesto_id=99999 WHERE id=:i"),
        ("lažan grupa_id blokiran", "UPDATE cenovnici SET grupa_id=99999 WHERE id=:i"),
        ("lažan smestaj_id blokiran", "UPDATE cenovnici SET smestaj_id=99999 WHERE id=:i"),
        ("lažan soba_id (cene) blokiran", "UPDATE cenovnik_cene SET soba_id=99999 WHERE cenovnik_id=:i"),
    ]:
        try:
            conn.execute(text("BEGIN"))
            conn.execute(text(sql), {"i": cid})
            conn.execute(text("ROLLBACK"))
            check(label, False)
        except Exception:
            conn.rollback()
            check(label, True)

# 3) brisanje referenciranog podatka kroz API → 409
check("DELETE soba u cenovniku → 409",
      c.delete(f"/api/sobe/{soba_id}", headers=H).status_code == 409)
check("DELETE grupa termina u cenovniku → 409",
      c.delete(f"/api/period-grupa/{grupa_id}", headers=H).status_code == 409)
check("DELETE mesto u cenovniku → 409",
      c.delete(f"/api/mesto/{mesto_id}", headers=H).status_code == 409)
check("DELETE smeštaj u cenovniku → 409",
      c.delete(f"/api/smestaj/{smestaj_id}", headers=H).status_code == 409)

# 4) nepovezani red se briše normalno (slobodna soba)
with engine.begin() as conn:
    tmp = conn.execute(text(
        "INSERT INTO sobe (veza_id_smestaj, broj_sobe, tip) "
        "VALUES (:s, 'TST-FK-CV', '1/2') RETURNING id"),
        {"s": smestaj_id}).scalar_one()
check("DELETE nepovezana soba → 200",
      c.delete(f"/api/sobe/{tmp}", headers=H).status_code == 200)
with engine.connect() as conn:
    check("privremena soba obrisana iz baze",
          conn.execute(text("SELECT COUNT(*) FROM sobe WHERE id=:i"),
                       {"i": tmp}).scalar() == 0)

print(f"\n{sum(OK)}/{len(OK)} PASS")
sys.exit(0 if all(OK) else 1)
