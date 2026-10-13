"""Jednokratni import: tabela `polazak` (cena i mesto polaska agencijskog prevoza).

Kreira tabelu (ako ne postoji) i puni je iz phpMyAdmin dumpa polazak.sql
(idempotentno: ON CONFLICT (id) DO NOTHING). Na kraju postavlja sekvencu
iza najveceg postojeceg id-ja.
"""
import os
import re
import sys

from sqlalchemy import create_engine, text

SQL_PATH = sys.argv[1] if len(sys.argv) > 1 else "/data/users/Ynxr51Wm2KaiRlwUvADMwZ6Atva2/uploads/polazak.sql"

engine = create_engine(os.environ["EXTERNAL_NEON_DATABASE_URL"])

COLUMNS = ("destinacija", "polazak", "sat", "valuta",
           "adlrt", "chdrt", "infrt", "adlow", "chdow", "infow")

ROW_RE = re.compile(r"^\((\d+), (.+)\)[,;]\s*$")


def split_fields(s: str):
    """Split po zapetama van navodnika; tokeni su 'str', broj ili prazan."""
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


def parse_rows(path: str):
    raw = open(path, "r", encoding="utf-8").read()
    rows = []
    for line in raw.splitlines():
        m = ROW_RE.match(line.strip())
        if not m:
            continue
        pk = int(m.group(1))
        vals = [unquote(t) for t in split_fields(m.group(2))]
        if len(vals) != len(COLUMNS):
            raise RuntimeError(f"Red {pk}: ocekivano {len(COLUMNS)} polja, dobijeno {len(vals)}")
        rows.append((pk, *vals))
    return rows


def main():
    rows = parse_rows(SQL_PATH)
    if not rows:
        raise RuntimeError("Nije pronadjen ni jedan red u dumpu")
    print(f"Parsirano {len(rows)} redova iz {SQL_PATH}")

    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS polazak (
                id SERIAL PRIMARY KEY,
                destinacija VARCHAR(60) DEFAULT NULL,
                polazak VARCHAR(60) DEFAULT NULL,
                sat VARCHAR(10) DEFAULT NULL,
                valuta VARCHAR(3) DEFAULT NULL,
                adlrt DOUBLE PRECISION DEFAULT NULL,
                chdrt DOUBLE PRECISION DEFAULT NULL,
                infrt DOUBLE PRECISION DEFAULT NULL,
                adlow DOUBLE PRECISION DEFAULT NULL,
                chdow DOUBLE PRECISION DEFAULT NULL,
                infow DOUBLE PRECISION DEFAULT NULL
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_polazak_destinacija ON polazak(destinacija)"
        ))

        existing = conn.execute(text("SELECT COUNT(*) FROM polazak")).scalar_one()
        print(f"Tabela polazak trenutno ima {existing} redova")

        inserted = 0
        for chunk_start in range(0, len(rows), 200):
            chunk = rows[chunk_start:chunk_start + 200]
            values_sql = ", ".join(
                f"(:id{i}, :destinacija{i}, :polazak{i}, :sat{i}, :valuta{i}, "
                f":adlrt{i}, :chdrt{i}, :infrt{i}, :adlow{i}, :chdow{i}, :infow{i})"
                for i in range(len(chunk))
            )
            bind = {}
            for i, (pk, *vals) in enumerate(chunk):
                bind[f"id{i}"] = pk
                for col, val in zip(COLUMNS, vals):
                    bind[f"{col}{i}"] = val
            res = conn.execute(text(
                f"INSERT INTO polazak (id, {', '.join(COLUMNS)}) VALUES {values_sql} "
                "ON CONFLICT (id) DO NOTHING"
            ), bind)
            inserted += res.rowcount

        print(f"Dodato {inserted} novih redova")
        total = conn.execute(text("SELECT COUNT(*) FROM polazak")).scalar_one()
        max_id = conn.execute(text("SELECT COALESCE(MAX(id), 0) FROM polazak")).scalar_one()
        conn.execute(text(
            "SELECT setval(pg_get_serial_sequence('polazak', 'id'), :max_id)"
        ), {"max_id": max_id})
        print(f"Ukupno u tabeli: {total}, sekvenca postavljena na {max_id}")


if __name__ == "__main__":
    main()
