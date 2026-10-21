import db_config

"""Import tabele `uplate` (sva plaćanja iz starog sistema) iz phpMyAdmin dumpa.

Struktura po dumpu uplate.sql:
  - kljuc  = broj uplate → SERIAL PRIMARY KEY (sekvenca za nove uplate)
  - id     = veza na ugovor/fakturu → običan INTEGER (NIJE jedinstven —
             više uplata može ići na isti ugovor)
  - broj   = broj dokumenta kao VARCHAR(10)

Kreira tabelu ako ne postoji, poravnava tipove na starijim verzijama i puni
podatke iz dumpa (idempotentno: ON CONFLICT (kljuc) DO NOTHING).

Upotreba: uv run python import_uplate.py [putanja_do_uplate.sql]
"""
import os
import sys
from datetime import datetime

from sqlalchemy import create_engine, text

SQL_PATH = sys.argv[1] if len(sys.argv) > 1 else "/data/users/Ynxr51Wm2KaiRlwUvADMwZ6Atva2/uploads/uplate_extract/uplate.sql"

engine = db_config.get_engine()

COLUMNS = ("danas", "ime", "adresa", "nacin", "din", "evro", "uevro", "svrha",
           "obradio", "vrsta", "kljuc", "broj", "faktura", "destinacija",
           "mesto", "subagent", "organizator", "poslovnica", "id")
INT_COLS = {"kljuc", "id"}
FLOAT_COLS = {"din", "evro", "uevro"}
DATE_COLS = {"danas"}
# Širine iz dumpa (MariaDB); po potrebi se automatski šire na dužinu podataka
VARCHAR_WIDTHS = {
    "ime": 60, "adresa": 70, "nacin": 50, "svrha": 50, "obradio": 60,
    "vrsta": 10, "broj": 10, "faktura": 10, "destinacija": 50,
    "mesto": 50, "subagent": 50, "organizator": 50, "poslovnica": 50,
}


def split_fields(s: str):
    """Split po zapetama van navodnika; podržava \\' i \\\\: escape-ove."""
    out, buf, in_q, i = [], [], False, 0
    while i < len(s):
        ch = s[i]
        if in_q:
            if ch == "\\" and i + 1 < len(s):
                buf.append(ch)
                buf.append(s[i + 1])
                i += 2
                continue
            if ch == "'":
                in_q = False
            buf.append(ch)
        else:
            if ch == "'":
                in_q = True
                buf.append(ch)
            elif ch == ",":
                out.append("".join(buf).strip())
                buf = []
            else:
                buf.append(ch)
        i += 1
    out.append("".join(buf).strip())
    return out


def unquote(tok: str):
    if tok.upper() == "NULL":
        return None
    if tok.startswith("'") and tok.endswith("'"):
        body = tok[1:-1]
        return body.replace("\\'", "'").replace('\\"', '"').replace("\\\\", "\\")
    return tok


def convert(col: str, v):
    if v is None:
        return None
    if col in DATE_COLS:
        return datetime.strptime(v, "%Y-%m-%d %H:%M:%S")
    if col in INT_COLS:
        return int(float(v))
    if col in FLOAT_COLS:
        return float(v)
    return v


def parse_rows(path: str):
    raw = open(path, "r", encoding="utf-8").read()
    rows, str_max = [], {c: 0 for c in VARCHAR_WIDTHS}
    for line in raw.splitlines():
        s = line.strip()
        if not s.startswith("("):
            continue
        if s.endswith("),") or s.endswith(");"):
            s = s[:-2]
        elif s.endswith(")"):
            s = s[:-1]
        vals = [unquote(t) for t in split_fields(s[1:])]
        if len(vals) != len(COLUMNS):
            raise RuntimeError(f"Ocekivano {len(COLUMNS)} polja, dobijeno {len(vals)}: {s[:120]}...")
        row = tuple(convert(c, v) for c, v in zip(COLUMNS, vals))
        for c in VARCHAR_WIDTHS:
            v = row[COLUMNS.index(c)]
            if isinstance(v, str):
                str_max[c] = max(str_max[c], len(v))
        rows.append(row)
    return rows, str_max


def ensure_table(conn, str_max):
    """Kreira tabelu po strukturi dumpa ako ne postoji i širi varchar kolone po potrebi."""
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS uplate (
            id INTEGER DEFAULT NULL,
            danas TIMESTAMP DEFAULT NULL,
            ime VARCHAR(60) DEFAULT '',
            adresa VARCHAR(70) DEFAULT '',
            nacin VARCHAR(50) DEFAULT '',
            din DOUBLE PRECISION DEFAULT 0,
            evro DOUBLE PRECISION DEFAULT 0,
            uevro DOUBLE PRECISION DEFAULT 0,
            svrha VARCHAR(50) DEFAULT '',
            obradio VARCHAR(60) DEFAULT '',
            vrsta VARCHAR(10) DEFAULT '',
            kljuc SERIAL PRIMARY KEY,
            broj VARCHAR(10) DEFAULT NULL,
            faktura VARCHAR(10) DEFAULT '',
            destinacija VARCHAR(50) DEFAULT '',
            mesto VARCHAR(50) DEFAULT '',
            subagent VARCHAR(50) DEFAULT '',
            organizator VARCHAR(50) DEFAULT '',
            poslovnica VARCHAR(50) DEFAULT ''
        )
    """))

    def col_type(col: str):
        return conn.execute(text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'uplate' AND column_name = :c"
        ), {"c": col}).scalar_one()

    # starije verzije tabele: kljuc je bio VARCHAR, broj INTEGER, id PK — poravnaj
    if col_type("kljuc") != "integer":
        conn.execute(text("ALTER TABLE uplate DROP CONSTRAINT IF EXISTS uplate_pkey"))
        conn.execute(text("ALTER TABLE uplate ALTER COLUMN kljuc DROP DEFAULT"))
        conn.execute(text(
            "ALTER TABLE uplate ALTER COLUMN kljuc TYPE INTEGER "
            "USING NULLIF(TRIM(kljuc), '')::integer"
        ))
    if col_type("broj") != "character varying":
        conn.execute(text(
            "ALTER TABLE uplate ALTER COLUMN broj TYPE VARCHAR(10) USING broj::text"
        ))
    # id nije jedinstven po dumpu — skini PK/not-null ako postoji iz stare verzije
    has_pk = conn.execute(text(
        "SELECT 1 FROM pg_constraint WHERE conrelid = 'uplate'::regclass "
        "AND contype = 'p' AND pg_get_constraintdef(oid) LIKE '%(id)%'"
    )).first()
    if has_pk:
        conn.execute(text("ALTER TABLE uplate DROP CONSTRAINT IF EXISTS uplate_pkey"))
        conn.execute(text("ALTER TABLE uplate ALTER COLUMN id DROP NOT NULL"))
    # kljuc mora biti PK sa sekvencom
    has_kljuc_pk = conn.execute(text(
        "SELECT 1 FROM pg_constraint WHERE conrelid = 'uplate'::regclass "
        "AND contype = 'p' AND pg_get_constraintdef(oid) LIKE '%(kljuc)%'"
    )).first()
    if not has_kljuc_pk:
        conn.execute(text("DELETE FROM uplate WHERE kljuc IS NULL OR TRIM(kljuc::text) = ''"))
        conn.execute(text("ALTER TABLE uplate ALTER COLUMN kljuc SET NOT NULL"))
        conn.execute(text(
            "ALTER TABLE uplate ADD CONSTRAINT uplate_kljuc_pkey PRIMARY KEY (kljuc)"
        ))
    conn.execute(text("CREATE SEQUENCE IF NOT EXISTS uplate_kljuc_seq OWNED BY uplate.kljuc"))
    conn.execute(text(
        "ALTER TABLE uplate ALTER COLUMN kljuc SET DEFAULT nextval('uplate_kljuc_seq')"
    ))

    # auto-širenje varchar kolona ako podaci ne stanu u širinu iz dumpa
    for col, data_max in str_max.items():
        if data_max <= VARCHAR_WIDTHS[col]:
            continue
        cur = conn.execute(text(
            "SELECT character_maximum_length FROM information_schema.columns "
            "WHERE table_name = 'uplate' AND column_name = :c"
        ), {"c": col}).scalar_one()
        if cur is not None and cur < data_max:
            conn.execute(text(
                f"ALTER TABLE uplate ALTER COLUMN {col} TYPE VARCHAR({data_max})"
            ))
            print(f"Kolona {col} proširena na VARCHAR({data_max})")

    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_uplate_danas ON uplate(danas)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_uplate_faktura ON uplate(faktura)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_uplate_id ON uplate(id)"))


def main():
    rows, str_max = parse_rows(SQL_PATH)
    if not rows:
        raise RuntimeError("Nije pronadjen ni jedan red u dumpu")
    print(f"Parsirano {len(rows)} redova iz {SQL_PATH}")

    with engine.begin() as conn:
        ensure_table(conn, str_max)
        existing = conn.execute(text("SELECT COUNT(*) FROM uplate")).scalar_one()
        print(f"Tabela uplate trenutno ima {existing} redova")

        inserted = 0
        for chunk_start in range(0, len(rows), 200):
            chunk = rows[chunk_start:chunk_start + 200]
            values_sql = ", ".join(
                "(" + ", ".join(f":{c}{i}" for c in COLUMNS) + ")"
                for i in range(len(chunk))
            )
            bind = {}
            for i, row in enumerate(chunk):
                for col, val in zip(COLUMNS, row):
                    bind[f"{col}{i}"] = val
            res = conn.execute(text(
                f"INSERT INTO uplate ({', '.join(COLUMNS)}) VALUES {values_sql} "
                "ON CONFLICT (kljuc) DO NOTHING"
            ), bind)
            inserted += res.rowcount

        print(f"Dodato {inserted} novih redova")
        total = conn.execute(text("SELECT COUNT(*) FROM uplate")).scalar_one()
        max_kljuc = conn.execute(text("SELECT COALESCE(MAX(kljuc), 0) FROM uplate")).scalar_one()
        conn.execute(text(
            "SELECT setval(pg_get_serial_sequence('uplate', 'kljuc'), :m)"
        ), {"m": max_kljuc})
        print(f"Ukupno u tabeli: {total}, sekvenca kljuca na {max_kljuc}")


if __name__ == "__main__":
    main()
