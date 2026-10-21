import db_config

"""Import rod.sql u postojeće ugovore; dry-run je podrazumevan, --apply snima."""
import argparse
from datetime import date, datetime
import os
from pathlib import Path
import re

from sqlalchemy import create_engine, text
from psycopg2.extras import execute_values

COLUMNS = ('id', 'rodjen', 'pasos', 'rodjen1', 'pasos1', 'rodjen2', 'pasos2',
           'rodjen3', 'pasos3', 'rodjen4', 'pasos4')


def split_values(value):
    tokens, buf, quoted, i = [], [], False, 0
    while i < len(value):
        ch = value[i]
        if quoted and ch == '\\' and i + 1 < len(value):
            buf.extend((ch, value[i + 1]))
            i += 2
            continue
        if ch == "'":
            if quoted and i + 1 < len(value) and value[i + 1] == "'":
                buf.extend((ch, ch))
                i += 2
                continue
            quoted = not quoted
        if ch == ',' and not quoted:
            tokens.append(''.join(buf).strip())
            buf = []
        else:
            buf.append(ch)
        i += 1
    if quoted:
        raise ValueError('Nezatvoren navodnik u SQL redu')
    tokens.append(''.join(buf).strip())
    return tokens


def decode_value(token):
    if token.upper() == 'NULL':
        return None
    if token.startswith("'") and token.endswith("'"):
        return re.sub(r"\\(.)", lambda m: {'0': '\0', 'n': '\n', 'r': '\r', 't': '\t'}.get(m[1], m[1]),
                      token[1:-1].replace("''", "'"))
    return token


def parse_rows(path):
    rows = []
    in_insert = False
    for number, line in enumerate(Path(path).read_text(encoding='utf-8-sig').splitlines(), 1):
        line = line.strip()
        if line.startswith('INSERT INTO'):
            header = re.fullmatch(r'INSERT INTO `rod` \((.+)\) VALUES', line)
            if not header or tuple(re.findall(r'`([^`]+)`', header[1])) != COLUMNS:
                raise ValueError(f'Zaglavlje INSERT-a nije očekivano na liniji {number}')
            in_insert = True
            continue
        if not in_insert:
            continue
        match = re.fullmatch(r'\((.*)\)([,;])', line)
        if not match:
            raise ValueError(f'Neispravan SQL red na liniji {number}')
        values = [decode_value(t) for t in split_values(match[1])]
        if len(values) != len(COLUMNS):
            raise ValueError(f'Pogrešan broj polja na liniji {number}')
        pk = int(values[0])
        if pk <= 0:
            raise ValueError(f'Neispravan id na liniji {number}')
        normalized = []
        for slot in range(5):
            born, passport = values[1 + 2 * slot:3 + 2 * slot]
            born = datetime.strptime(born, '%Y-%m-%d %H:%M:%S').date() if born else None
            passport = passport.strip() if passport else None
            if passport and len(passport) > 50:
                raise ValueError(f'Predugačak pasoš na liniji {number}')
            normalized.extend((born, passport or None))
        rows.append((pk, *normalized))
        in_insert = match[2] != ';'
    if in_insert or not rows:
        raise ValueError('SQL izvor je nepotpun ili prazan')
    return rows


def merge_rows(rows):
    """Popunjene vrednosti spajamo; svaki konflikt izuzima ceo ugovor."""
    merged, conflicts = {}, set()
    for pk, *values in rows:
        if pk in conflicts:
            continue
        if pk not in merged:
            merged[pk] = values
            continue
        previous = merged[pk]
        if any(a is not None and b is not None and a != b for a, b in zip(previous, values)):
            conflicts.add(pk)
            del merged[pk]
            continue
        merged[pk] = [a if a is not None else b for a, b in zip(previous, values)]
    return merged, sorted(conflicts)


def stage_rows(merged):
    return [{'broj': str(pk), 'slot': slot, 'rodjen': values[2 * slot], 'pasos': values[2 * slot + 1]}
            for pk, values in merged.items() for slot in range(5)]


def run_import(engine, rows, apply=False):
    merged, conflicts = merge_rows(rows)
    staged = stage_rows(merged)
    stats = {'izvorni_redovi': len(rows), 'jedinstveni_bez_konflikta': len(merged),
             'konfliktni_ugovori': conflicts}
    with engine.connect() as conn:
        with conn.begin() as transaction:
            conn.execute(text("SELECT pg_advisory_xact_lock(749102640)"))
            for table in ('aranzman', 'aranzman_dopuna'):
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS rodjen DATE'))
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS pasos VARCHAR(50)'))
            conn.execute(text('CREATE TEMP TABLE rod_stage (broj TEXT, slot INTEGER, rodjen DATE, pasos VARCHAR(50), PRIMARY KEY (broj, slot)) ON COMMIT DROP'))
            # Batch VALUES umesto mrežnog zahteva za svaki pojedinačni red.
            with conn.connection.driver_connection.cursor() as cursor:
                execute_values(cursor,
                    'INSERT INTO rod_stage (broj, slot, rodjen, pasos) VALUES %s',
                    [(r['broj'], r['slot'], r['rodjen'], r['pasos']) for r in staged],
                    page_size=1000)
            conn.execute(text("""
                CREATE TEMP TABLE rod_contract_keys ON COMMIT DROP AS
                SELECT id, (split_part(kljuc, '/', 1)::numeric)::text AS broj
                FROM aranzman WHERE split_part(kljuc, '/', 1) ~ '^[0-9]+$'
            """))
            duplicates = conn.execute(text("""
                SELECT count(*) FROM (
                    SELECT a.broj FROM rod_contract_keys a
                    JOIN rod_stage r ON r.broj = a.broj AND r.slot = 0
                    GROUP BY a.broj HAVING count(*) > 1
                ) t
            """)).scalar_one()
            if duplicates:
                raise ValueError('Više ugovora ima isti numerički ključ; import zaustavljen')
            conn.execute(text("""
                CREATE TEMP TABLE rod_targets ON COMMIT DROP AS
                SELECT a.id AS target_id, r.* FROM rod_stage r
                JOIN rod_contract_keys a ON a.broj = r.broj WHERE r.slot = 0
            """))
            conn.execute(text("""
                CREATE TEMP TABLE rod_dopuna_targets ON COMMIT DROP AS
                SELECT d.id AS target_id, r.* FROM rod_stage r
                JOIN rod_contract_keys a ON a.broj = r.broj
                JOIN (SELECT id, aranzman_id, row_number() OVER (PARTITION BY aranzman_id ORDER BY id) AS slot
                      FROM aranzman_dopuna) d ON d.aranzman_id = a.id AND d.slot = r.slot
                WHERE r.slot BETWEEN 1 AND 4
            """))
            stats['povezani_ugovori'] = conn.execute(text('SELECT count(*) FROM rod_targets')).scalar_one()
            stats['nepovezani_ugovori'] = len(merged) - stats['povezani_ugovori']
            stats['povezani_saputnici'] = conn.execute(text('SELECT count(*) FROM rod_dopuna_targets')).scalar_one()
            stats['nedostajuci_saputnici_sa_podacima'] = conn.execute(text("""
                SELECT count(*) FROM rod_stage r JOIN rod_targets a ON a.broj = r.broj
                WHERE r.slot > 0 AND (r.rodjen IS NOT NULL OR r.pasos IS NOT NULL)
                AND NOT EXISTS (SELECT 1 FROM rod_dopuna_targets d WHERE d.broj=r.broj AND d.slot=r.slot)
            """)).scalar_one()
            for table, targets in (('aranzman', 'rod_targets'), ('aranzman_dopuna', 'rod_dopuna_targets')):
                result = conn.execute(text(f"""
                    UPDATE {table} a SET rodjen = COALESCE(r.rodjen, a.rodjen), pasos = COALESCE(r.pasos, a.pasos)
                    FROM {targets} r WHERE a.id = r.target_id
                    AND (a.rodjen IS DISTINCT FROM COALESCE(r.rodjen, a.rodjen)
                         OR a.pasos IS DISTINCT FROM COALESCE(r.pasos, a.pasos))
                """))
                stats[f'izmenjeni_{table}'] = result.rowcount
                mismatch = conn.execute(text(f"""
                    SELECT count(*) FROM {targets} r JOIN {table} a ON a.id=r.target_id
                    WHERE (r.rodjen IS NOT NULL AND a.rodjen IS DISTINCT FROM r.rodjen)
                       OR (r.pasos IS NOT NULL AND a.pasos IS DISTINCT FROM r.pasos)
                """ )).scalar_one()
                if mismatch:
                    raise ValueError(f'Provera prenosa nije prošla za {table}')
            if not apply:
                transaction.rollback()
    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sql_path')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    rows = parse_rows(args.sql_path)
    engine = db_config.get_engine()
    try:
        stats = run_import(engine, rows, apply=args.apply)
        print('SNIMLJENO' if args.apply else 'PROVERA — sve promene vraćene rollback-om')
        for key, value in stats.items():
            print(f'{key}: {value}')
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
