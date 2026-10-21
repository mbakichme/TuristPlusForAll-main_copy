import db_config

"""Jednokratna migracija: split aranzman saputnik polja u aranzman_dopuna.

Faza 1 (ovo): kreira aranzman_dopuna, dodaje aranzman.smer, prenosi
saputnik1-4 redove. Stare kolone se NE brisu ovde (faza 2, nakon sto
routes.py prestane da ih koristi).
"""
import os

from sqlalchemy import create_engine, text

engine = db_config.get_engine()

# uslov: red saputnika ima bar jedno popunjeno polje
ANY_DATA = (
    "COALESCE(TRIM(saputnik{i}),'') <> '' "
    "OR COALESCE(TRIM(uzrast{i}),'') <> '' "
    "OR COALESCE(prevoz{i}ow,0) <> 0 "
    "OR COALESCE(prevoz{i}rt,0) <> 0 "
    "OR COALESCE(viza{i},0) <> 0 "
    "OR COALESCE(TRIM(ulazak{i}),'') <> ''"
)

with engine.begin() as conn:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS aranzman_dopuna (
            id SERIAL PRIMARY KEY,
            aranzman_id INTEGER NOT NULL REFERENCES aranzman(id) ON DELETE CASCADE,
            saputnik VARCHAR(200) DEFAULT '',
            uzrast VARCHAR(20) DEFAULT '',
            prevozow SMALLINT DEFAULT NULL,
            prevozrt SMALLINT DEFAULT NULL,
            viza SMALLINT DEFAULT NULL,
            ulazak VARCHAR(200) DEFAULT NULL,
            smer VARCHAR(50) DEFAULT NULL
        )
    """))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_aranzman_dopuna_aranzman_id "
        "ON aranzman_dopuna(aranzman_id)"
    ))
    conn.execute(text(
        "ALTER TABLE aranzman ADD COLUMN IF NOT EXISTS smer VARCHAR(50) DEFAULT NULL"
    ))

    existing = conn.execute(text("SELECT COUNT(*) FROM aranzman_dopuna")).scalar_one()
    if existing > 0:
        print(f"aranzman_dopuna vec ima {existing} redova — preskacem fazu 1 prenosa")
    else:
        selects = []
        for i in range(1, 5):
            selects.append(f"""
                SELECT id AS aranzman_id,
                       saputnik{i} AS saputnik,
                       uzrast{i} AS uzrast,
                       prevoz{i}ow AS prevozow,
                       prevoz{i}rt AS prevozrt,
                       viza{i} AS viza,
                       ulazak{i} AS ulazak
                FROM aranzman
                WHERE {ANY_DATA.format(i=i)}
            """)
        union = " UNION ALL ".join(selects)
        conn.execute(text(
            f"INSERT INTO aranzman_dopuna "
            f"(aranzman_id, saputnik, uzrast, prevozow, prevozrt, viza, ulazak) {union}"
        ))

        n = conn.execute(text("SELECT COUNT(*) FROM aranzman_dopuna")).scalar_one()
        per = {}
        for i in range(1, 5):
            per[i] = conn.execute(text(
                f"SELECT COUNT(*) FROM aranzman WHERE {ANY_DATA.format(i=i)}"
            )).scalar_one()
        print(f"migrirano redova u aranzman_dopuna: {n}")
        print(f"ocekivano po kolonama: {per} (zbir {sum(per.values())})")
        assert n == sum(per.values()), "broj redova se ne poklapa!"

        # provera: svaki aranzman_id mora postojati u aranzman
        orf = conn.execute(text("""
            SELECT COUNT(*) FROM aranzman_dopuna d
            LEFT JOIN aranzman a ON a.id = d.aranzman_id WHERE a.id IS NULL
        """)).scalar_one()
        print(f"sirocinskih redova (bez aranzman): {orf}")
        assert orf == 0
print("faza 1 OK")

# ── Faza 2: brisanje starih kolona (pozovi Tek nakon što routes.py ne koristi) ──
import sys

if "--drop" not in sys.argv:
    print("faza 2 (DROP kolona) preskočena — pokreni sa --drop")
    raise SystemExit(0)

STARE_KOLONE = []
for i in range(1, 5):
    STARE_KOLONE += [
        f"saputnik{i}", f"uzrast{i}", f"prevoz{i}ow", f"prevoz{i}rt",
        f"viza{i}", f"ulazak{i}",
    ]

with engine.begin() as conn:
    postojece = {
        r[0] for r in conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='aranzman'"
        )).fetchall()
    }
    for c in STARE_KOLONE:
        if c in postojece:
            conn.execute(text(f"ALTER TABLE aranzman DROP COLUMN {c}"))
            print(f"obrisana kolona aranzman.{c}")
    ostatak = {
        r[0] for r in conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='aranzman'"
        )).fetchall()
    }
    for c in STARE_KOLONE:
        assert c not in ostatak, f"kolona {c} jos uvek postoji!"
    assert "smer" in ostatak
print("faza 2 OK")
