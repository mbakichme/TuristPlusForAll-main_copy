"""Prenos dodatne.sql; čuva i identična ponavljanja. Bez --apply radi rollback."""
import argparse
from collections import Counter
import math
import os
from pathlib import Path
import re

from psycopg2.extras import execute_values
from sqlalchemy import create_engine, text
from import_rod import split_values, decode_value

COLUMNS = ('usluga', 'eur', 'din', 'id')
SCHEMA = '''CREATE TABLE IF NOT EXISTS dodatne (
    usluga VARCHAR(150) DEFAULT NULL,
    eur DOUBLE PRECISION DEFAULT NULL,
    din DOUBLE PRECISION DEFAULT NULL,
    id INTEGER DEFAULT NULL
)'''


def parse_rows(path):
    rows, active = [], False
    for number, line in enumerate(Path(path).read_text(encoding='utf-8-sig').splitlines(), 1):
        line = line.strip()
        if line.startswith('INSERT INTO'):
            header = re.fullmatch(r'INSERT INTO `dodatne` \((.+)\) VALUES', line)
            if not header or tuple(re.findall(r'`([^`]+)`', header[1])) != COLUMNS:
                raise ValueError(f'Neispravno INSERT zaglavlje: linija {number}')
            active = True
            continue
        if not active:
            continue
        match = re.fullmatch(r'\((.*)\)([,;])', line)
        if not match:
            raise ValueError(f'Neispravan SQL red: linija {number}')
        values = [decode_value(t) for t in split_values(match[1])]
        if len(values) != 4:
            raise ValueError(f'Neispravan broj polja: linija {number}')
        usluga, eur, din, pk = values
        if usluga is not None and len(usluga) > 150:
            raise ValueError(f'Predugačka usluga: linija {number}')
        eur = float(eur) if eur is not None else None
        din = float(din) if din is not None else None
        if any(v is not None and not math.isfinite(v) for v in (eur, din)):
            raise ValueError(f'Neispravan iznos: linija {number}')
        pk = int(pk) if pk is not None else None
        if pk is not None and not -(2**31) <= pk < 2**31:
            raise ValueError(f'Neispravan id: linija {number}')
        rows.append((usluga, eur, din, pk))
        active = match[2] != ';'
    if active or not rows:
        raise ValueError('Izvor je prazan ili nepotpun')
    return rows


def missing_rows(source, existing):
    """Multiset: import ne udvostručava podatke, ali čuva ponavljanja iz izvora."""
    counts = Counter(existing)
    missing = []
    for row in source:
        if counts[row]:
            counts[row] -= 1
        else:
            missing.append(row)
    return missing


def run_import(engine, rows, apply=False):
    with engine.connect() as conn:
        with conn.begin() as transaction:
            conn.execute(text('SELECT pg_advisory_xact_lock(749102641)'))
            conn.execute(text(SCHEMA))
            conn.execute(text('CREATE INDEX IF NOT EXISTS idx_dodatne_id ON dodatne(id)'))
            conn.execute(text('LOCK TABLE dodatne IN SHARE ROW EXCLUSIVE MODE'))
            existing = [tuple(r) for r in conn.execute(text('SELECT usluga, eur, din, id FROM dodatne'))]
            additions = missing_rows(rows, existing)
            if additions:
                with conn.connection.driver_connection.cursor() as cursor:
                    execute_values(cursor, 'INSERT INTO dodatne (usluga, eur, din, id) VALUES %s',
                                   additions, page_size=1000)
            after = [tuple(r) for r in conn.execute(text('SELECT usluga, eur, din, id FROM dodatne'))]
            if Counter(after) != Counter(existing) + Counter(additions) or missing_rows(rows, after):
                raise ValueError('Provera prenosa nije prošla')
            stats = {'izvorni_redovi': len(rows), 'dodato': len(additions), 'ukupno': len(after)}
            if not apply:
                transaction.rollback()
    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sql_path')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    rows = parse_rows(args.sql_path)
    url = os.environ.get('EXTERNAL_NEON_DATABASE_URL')
    if not url:
        raise RuntimeError('EXTERNAL_NEON_DATABASE_URL nije definisan')
    engine = create_engine(url)
    try:
        stats = run_import(engine, rows, args.apply)
        print('SNIMLJENO' if args.apply else 'PROVERA — rollback')
        print(stats)
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
