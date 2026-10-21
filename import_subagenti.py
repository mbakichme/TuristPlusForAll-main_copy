import db_config

"""Import subagenti records from MariaDB dump into Postgres subagenti table."""
import os, io, csv, sys
from sqlalchemy import create_engine, text

DUMP = "/data/users/Ynxr51Wm2KaiRlwUvADMwZ6Atva2/uploads/subagenti.sql"

engine = db_config.get_engine()

# ── kreiraj tabelu ako ne postoji (ista DDL kao u init_db) ─────────────────
with engine.begin() as conn:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS subagenti (
            id SERIAL PRIMARY KEY,
            naziv VARCHAR(200) DEFAULT '',
            adresa VARCHAR(200) DEFAULT '',
            mesto VARCHAR(100) DEFAULT '',
            osoba VARCHAR(200) DEFAULT '',
            tel VARCHAR(100) DEFAULT '',
            tel1 VARCHAR(100) DEFAULT '',
            tel2 VARCHAR(200) DEFAULT '',
            fax VARCHAR(100) DEFAULT '',
            racun VARCHAR(200) DEFAULT '',
            provizija DOUBLE PRECISION DEFAULT 0,
            provizija1 DOUBLE PRECISION DEFAULT 0,
            provizija1a DOUBLE PRECISION DEFAULT 0,
            provizija2 DOUBLE PRECISION DEFAULT 0,
            punnaziv VARCHAR(300) DEFAULT '',
            kontakt VARCHAR(300) DEFAULT ''
        )
    """))

# ── kolone ─────────────────────────────────────────────────────────────────
with engine.connect() as conn:
    pg_cols = [r[0] for r in conn.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='subagenti' ORDER BY ordinal_position")).fetchall()]
print(f"Postgres subagenti kolona: {len(pg_cols)}")

# ── parser (isti kao za aranzman dump) ─────────────────────────────────────
def unescape_mysql(s: str) -> str:
    out = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            n = s[i + 1]
            mapping = {"n": "\n", "r": "\r", "0": "\0", "Z": "\x1a",
                       "b": "\b", "t": "\t", "\\": "\\", "'": "'", '"': '"', "%": "\\%", "_": "\\_"}
            out.append(mapping.get(n, n))
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)

def split_tuples(blob: str):
    tuples = []
    i = 0
    n = len(blob)
    while i < n:
        c = blob[i]
        if c not in "(,":
            i += 1
            continue
        if c == ",":
            i += 1
            continue
        i += 1
        vals = []
        cur = []
        in_str = False
        while i < n:
            c = blob[i]
            if in_str:
                if c == "\\":
                    cur.append(c)
                    if i + 1 < n:
                        cur.append(blob[i + 1])
                    i += 2
                    continue
                if c == "'":
                    if i + 1 < n and blob[i + 1] == "'":
                        cur.append("''")
                        i += 2
                        continue
                    in_str = False
                    cur.append(c)
                    i += 1
                    continue
                cur.append(c)
                i += 1
                continue
            if c == "'":
                in_str = True
                cur.append(c)
                i += 1
                continue
            if c == ",":
                vals.append("".join(cur).strip())
                cur = []
                i += 1
                continue
            if c == ")":
                vals.append("".join(cur).strip())
                tuples.append(vals)
                i += 1
                break
            cur.append(c)
            i += 1
        else:
            break
    return tuples

def conv(tok: str):
    if tok.upper() == "NULL":
        return None
    if tok.startswith("b'") and tok.endswith("'"):
        return int(tok[2:-1])
    if tok.startswith("'") and tok.endswith("'") and len(tok) >= 2:
        return unescape_mysql(tok[1:-1])
    return tok

data = open(DUMP, encoding="utf-8", errors="replace").read()

marker = "INSERT INTO `subagenti` ("
pos = 0
rows = []
insert_cols = None
while True:
    p = data.find(marker, pos)
    if p < 0:
        break
    cl_end = data.find(") VALUES", p)
    if cl_end < 0:
        break
    collist = [c.strip().strip("`") for c in data[p + len(marker):cl_end].split(",")]
    if insert_cols is None:
        insert_cols = collist
        missing = [c for c in collist if c not in pg_cols]
        if missing:
            print("!!! Kolone u dumpu koje ne postoje u tabeli:", missing)
            sys.exit(1)
        print(f"INSERT kolona: {len(collist)}")
    else:
        assert collist == insert_cols, "Kolone se razlikuju između INSERT naredbi!"
    blob_start = data.find("\n", cl_end) + 1
    nxt = data.find(marker, cl_end)
    blob = data[blob_start:nxt if nxt > 0 else len(data)]
    end_idx = blob.find(";\n\nCOMMIT")
    if end_idx < 0:
        end_idx = blob.find(";\n\n/*!")
    if end_idx < 0:
        end_idx = len(blob)
    blob = blob[:end_idx]
    for t in split_tuples(blob):
        if len(t) != len(collist):
            print("!!! Red sa pogrešnim brojem vrednosti:", len(t), "!=", len(collist))
            continue
        rows.append({col: conv(tok) for col, tok in zip(collist, t)})
    pos = cl_end

print(f"INSERT naredbi: 9, redova: {len(rows)}")

# ── uvoz ───────────────────────────────────────────────────────────────────
imp_cols = [c for c in pg_cols if c != "id"]
with engine.begin() as conn:
    conn.execute(text("DROP TABLE IF EXISTS _subagenti_staging"))
    conn.execute(text(
        f"CREATE TABLE _subagenti_staging AS SELECT {', '.join(imp_cols)} FROM subagenti WITH NO DATA"
    ))
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    for r in rows:
        w.writerow(["\\N" if r.get(c) is None else str(r.get(c)) for c in imp_cols])
    buf.seek(0)
    cur = conn.connection.cursor()
    cur.copy_expert(
        f"COPY _subagenti_staging ({', '.join(imp_cols)}) FROM STDIN WITH (FORMAT csv, NULL '\\N')",
        buf,
    )
    cur.close()
    print("staging redova:", conn.execute(text("SELECT count(*) FROM _subagenti_staging")).scalar())

    conn.execute(text("DELETE FROM subagenti"))
    conn.execute(text(f"""
        INSERT INTO subagenti ({', '.join(imp_cols)})
        SELECT {', '.join(imp_cols)} FROM _subagenti_staging
    """))
    conn.execute(text("DROP TABLE _subagenti_staging"))

with engine.connect() as conn:
    total = conn.execute(text("SELECT count(*) FROM subagenti")).scalar()
    print("ukupno u subagenti:", total)
    for r in conn.execute(text(
        "SELECT naziv, mesto, provizija FROM subagenti ORDER BY naziv LIMIT 5"
    )).fetchall():
        print(r)
