import db_config

import os, time
from sqlalchemy import create_engine, text

engine = db_config.get_engine()

SQL = text("""
INSERT INTO aranzman (
    kljuc, danas, putnik, adresa, telefon, destinacija, mesto, naziv,
    datumod, datumdo, datumoddo, cenaaranz, uplaceno, obradio,
    organizator, poslovnica, tiprezervacije, napomena, soba, obrok
)
SELECT
    (100000 + i)::text,
    (DATE '2026-01-05' + i % 250)::timestamp,
    ime[1 + i % 25] || ' ' || prz[1 + i % 30],
    adr[1 + i % 12],
    '06' || lpad(((i * 7919) % 900000000 + 100000000)::text, 9, '0'),
    mst[1 + i % 8] || ' - AVIO ' || grad[1 + i % 8] || ' / BEG BJV',
    mst[1 + i % 8] || '-' || grad[1 + i % 8],
    hotel[1 + i % 20] || ' ' || (3 + (i % 3))::text || '*',
    (DATE '2026-05-01' + i % 300)::timestamp,
    (DATE '2026-05-01' + (i % 300) + 7 + (i % 5) * 3)::timestamp,
    to_char(DATE '2026-05-01' + i % 300, 'DD.MM.YYYY') || '-' ||
        to_char(DATE '2026-05-01' + (i % 300) + 7 + (i % 5) * 3, 'DD.MM.YYYY'),
    round((499 + (i * 37 % 2500))::numeric, 1),
    CASE WHEN i % 4 = 0 THEN 0
         ELSE round((499 + (i * 37 % 2500))::numeric * (0.3 + (i % 5) * 0.175), 1) END,
    obr[1 + i % 6],
    'OKTOPOD TRAVEL',
    'OKTOPOD ' || pos[1 + i % 3],
    CASE i % 3 WHEN 0 THEN 'ARANZMAN' WHEN 1 THEN 'SMESTAJ' ELSE 'PREVOZ' END,
    CASE WHEN i % 7 = 0 THEN ' Napomena: poslat dokaz o uplati' ELSE '' END,
    CASE WHEN i % 2 = 0 THEN 'STANDARD ROOM' ELSE 'DELUXE ROOM' END,
    CASE i % 3 WHEN 0 THEN 'AI' WHEN 1 THEN 'HB' ELSE 'BB' END
FROM generate_series(1, 40000) i
CROSS JOIN LATERAL (SELECT
    ARRAY['MARKO','JOVAN','NIKOLA','PETAR','MILOS','STEFAN','ALEKSANDAR','DRAGAN','ZORAN','DEJAN','IVAN','VLADAN','GORAN','BRANISLAV','RADOSLAV','MILAN','LJUBISA','SLOBODAN','MIROSLAV','VLADIMIR','MARIA','ANNA','ELENA','KOVALSKA','DIMITROVA']::text[] AS ime,
    ARRAY['MARKOVIC','JOVANOVIC','NIKOLIC','PETROVIC','MILOSEVIC','STEFANOVIC','ALEKSIC','DRAGICEVIC','ZORIC','DEJANOVIC','IVANOVIC','VLADICIN','GORANOVIC','BRANKOVIC','RADIC','MILIC','LJUBICIC','SLOBODOV','MIROSLAVLJEVIC','VLADIMIROV','IVANOVA','KOWALSKA','PETROVA','NOVAK','MARKOV']::text[] AS prz,
    ARRAY['TURSKA','GRCKA','EGIPAT','TUNIS','SPANIJA','ITALIJA','BUGARSKA','CRNA GORA']::text[] AS mst,
    ARRAY['ANTALIJA','BODRUM','SALONIKA','HURGADA','MONASTIR','KOSTA BRAVA','RIM','BUDVA']::text[] AS grad,
    ARRAY['CHARM BEACH','GRAND PARADISE','BLUE LAGOON','SUNNY RESORT','ROYAL PALACE','DELUX SEA VIEW','MARINA BAY','GOLDEN SAND','PANORAMA','OLYMPIC STAR','SEA PEARL','LUX GARDEN','BELLEVUE','TITANIC','CRYSTAL','EMPEROR','AZURE','DOLPHIN','MIRAGE','ATLANTIC']::text[] AS hotel,
    ARRAY['16.OKTOBRA 28','KNEZA MILOSA 15','BULEVAR ZORANA DJINDJICA 64','JUZEFOVA 3','TAKOVSKA 11','CARA DUANA 5','VLAJKOVICEVA 9','MITROPOLITA PETRA 7','RIGE OF FMROGA 22','DELIGRADSKA 4','KRALJA PETRA 31','CVIJICEVA 18']::text[] AS adr,
    ARRAY['Yubc','Nikola Jovicic','Marko Admin','Katarina','Slavica','Reception']::text[] AS obr,
    ARRAY['YUBC','SLAVIJA','NOVI BEOGRAD']::text[] AS pos
) x
ON CONFLICT (kljuc) DO NOTHING
""")

t0 = time.time()
with engine.begin() as conn:
    conn.execute(text("SET statement_timeout = 300000"))
    res = conn.execute(SQL)
    print("inserted:", res.rowcount)
    print("ukupno:", conn.execute(text("SELECT count(*) FROM aranzman")).scalar())
    print(f"trajanje: {time.time()-t0:.1f}s")
