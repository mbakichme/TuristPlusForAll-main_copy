import db_config

"""Import aranzman records from MariaDB SQL dump into Postgres aranzman table.

- Clears the aranzman table first
- Appends "/26" to every kljuc value
- Converts MySQL literals: b'0'/b'1' -> 0/1, NULL -> None, MySQL escapes unescaped
"""
import os, io, csv, sys
from sqlalchemy import create_engine, text

DUMP = "/tmp/aranzman_x/aranzman (3).sql"
SUFFIX = "/26"

data = open(DUMP, encoding="utf-8", errors="replace").read()

engine = db_config.get_engine()

# ── 1. kolone iz naše Postgres tabele ──────────────────────────────────────
with engine.connect() as conn:
    pg_cols = [r[0] for r in conn.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='aranzman' ORDER BY ordinal_position")).fetchall()]
print(f"Postgres aranzman kolona: {len(pg_cols)}")

# ── 2. parsuj dump ─────────────────────────────────────────────────────────
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
    """Split VALUES blob into tuple value-lists. Returns list of lists of raw token strings."""
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
        # start of tuple
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
                    # possible escaped '' or end
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
            # not in string
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
    """Convert a raw token to a Python value."""
    if tok.upper() == "NULL":
        return None
    if tok.startswith("b'") and tok.endswith("'"):
        return int(tok[2:-1])
    if tok.startswith("'") and tok.endswith("'") and len(tok) >= 2:
        return unescape_mysql(tok[1:-1])
    return tok  # number as string; Postgres casts via staging types

TS_COLS = {"danas", "datumod", "datumdo", "spajanje1od", "spajanje1do",
           "spajanje2od", "spajanje2do", "timelimit", "datumkeptp",
           "datumfiskalni"}

marker = "INSERT INTO `aranzman` ("
pos = 0
rows = []
insert_cols = None
count_stmt = 0
while True:
    p = data.find(marker, pos)
    if p < 0:
        break
    count_stmt += 1
    # column list
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
    # find end of this INSERT: the ");" that terminates — tuples scanner stops per tuple;
    # we rely on next INSERT marker: take slice up to next marker or end
    nxt = data.find(marker, cl_end)
    blob = data[blob_start:nxt if nxt > 0 else len(data)]
    # trim trailing COMMIT/semicolons section
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
        row = {}
        for col, tok in zip(collist, t):
            v = conv(tok)
            if col in TS_COLS and (v == "" or v is None):
                v = None
            row[col] = v
        if row.get("kljuc") is None:
            continue
        row["kljuc"] = str(row["kljuc"]) + SUFFIX
        rows.append(row)
    pos = cl_end

print(f"INSERT naredbi: {count_stmt}, redova: {len(rows)}")

# duplikati kljuc
kl = [r["kljuc"] for r in rows]
dupes = len(kl) - len(set(kl))
print(f"duplikata kljuc: {dupes}")

# ── 3. uvoz: staging tabelu, pa transfer ───────────────────────────────────
all_cols = pg_cols
with engine.begin() as conn:
    imp_cols = [c for c in all_cols if c != "id"]
    conn.execute(text("DROP TABLE IF EXISTS _aranzman_staging"))
    conn.execute(text(
        f"CREATE TABLE _aranzman_staging AS SELECT {', '.join(imp_cols)} FROM aranzman WITH NO DATA"
    ))

    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    for r in rows:
        w.writerow(["\\N" if r.get(c) is None else str(r.get(c)) for c in imp_cols])
    buf.seek(0)
    raw = conn.connection  # DBAPI connection
    cur = raw.cursor()
    cur.copy_expert(
        f"COPY _aranzman_staging ({', '.join(imp_cols)}) FROM STDIN WITH (FORMAT csv, NULL '\\N')",
        buf,
    )
    cur.close()

    n_stag = conn.execute(text("SELECT count(*) FROM _aranzman_staging")).scalar()
    print("staging redova:", n_stag)

    # očisti ciljnu tabelu i prebaci (id generiše serial)
    conn.execute(text("DELETE FROM aranzman"))
    conn.execute(text(f"""
        INSERT INTO aranzman ({', '.join(imp_cols)})
        SELECT {', '.join(imp_cols)} FROM _aranzman_staging
        ON CONFLICT (kljuc) DO NOTHING
    """))
    conn.execute(text("DROP TABLE _aranzman_staging"))

with engine.connect() as conn:
    total = conn.execute(text("SELECT count(*) FROM aranzman")).scalar()
    print("ukupno u aranzman:", total)
    for r in conn.execute(text(
        "SELECT kljuc, putnik, mesto, naziv, to_char(datumod,'DD.MM.YYYY') FROM aranzman ORDER BY kljuc LIMIT 5"
    )).fetchall():
        print(r)
