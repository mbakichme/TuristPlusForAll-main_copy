"""Naslovna: ugovori kreirani danas (po vremenu kreiranja, Europe/Belgrade).

Jedan red po ugovoru (kljuc). `soba` i ostalo su sa prvog reda ugovora.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import Depends
from sqlalchemy import text

BELGRADE = ZoneInfo("Europe/Belgrade")


def register_dashboard(api, engine, get_current_user) -> None:

    @api.get("/ugovori-danas")
    def ugovori_danas(current_user: dict = Depends(get_current_user)):
        danas = datetime.now(BELGRADE).date()
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT DISTINCT ON (a.kljuc)
                       a.kljuc,
                       a.putnik AS nosioc,
                       a.mesto,
                       a.naziv AS smestaj,
                       to_char(a.datumod, 'DD.MM.YYYY') AS datumod,
                       to_char(a.datumdo, 'DD.MM.YYYY') AS datumdo,
                       a.soba,
                       COALESCE(NULLIF(TRIM(a.apartman), ''), (
                           SELECT b.tip FROM sobe b
                           WHERE b.veza_id_smestaj = a.smestaj_id
                             AND TRIM(b.broj_sobe) = TRIM(a.soba)
                           LIMIT 1
                       )) AS struktura,
                       a.obradio,
                       a.danas
                FROM aranzman a
                WHERE a.danas::date = :d
                  AND a.kljuc IS NOT NULL AND a.kljuc <> ''
                ORDER BY a.kljuc, a.danas DESC NULLS LAST, a.id DESC
            """), {"d": danas}).mappings().fetchall()
        rows = sorted(rows, key=lambda r: r["danas"] or datetime.min, reverse=True)
        out = [{k: r[k] for k in ("kljuc", "nosioc", "mesto", "smestaj",
                                  "datumod", "datumdo", "soba", "struktura", "obradio")} for r in rows]
        return {"datum": danas.strftime("%d.%m.%Y"), "ukupno": len(out), "rows": out}

    @api.get("/predrezervacije-istekle")
    def predrezervacije_istekle(current_user: dict = Depends(get_current_user)):
        """Predrezervacije i rezervacije kojima je istekao timelimit (timelimit <= sada).
        Tip: sve osim STORNO (PREDREZERVACIJA, LAST MINUTE, rezervacije). Ugovori sa
        nacin_placanja = 'delimicno' se prikazuju. Jedan red po ugovoru."""
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT DISTINCT ON (a.kljuc)
                       a.kljuc,
                       a.putnik AS nosioc,
                       a.mesto,
                       a.naziv AS smestaj,
                       a.tiprezervacije,
                       to_char(a.datumod, 'DD.MM.YYYY') AS datumod,
                       to_char(a.datumdo, 'DD.MM.YYYY') AS datumdo,
                       to_char(a.timelimit, 'DD.MM.YYYY HH24:MI') AS timelimit,
                       a.timelimit AS timelimit_ts,
                       a.obradio
                FROM aranzman a
                WHERE UPPER(TRIM(COALESCE(a.tiprezervacije, ''))) <> 'STORNO'
                  AND a.timelimit IS NOT NULL
                  AND a.timelimit <= :sada
                  AND a.kljuc IS NOT NULL AND a.kljuc <> ''
                ORDER BY a.kljuc, a.id
            """), {"sada": datetime.now(BELGRADE).replace(tzinfo=None)}).mappings().fetchall()
        rows = sorted(rows, key=lambda r: r["timelimit_ts"])
        out = [{k: r[k] for k in ("kljuc", "nosioc", "mesto", "smestaj", "tiprezervacije",
                                  "datumod", "datumdo", "timelimit", "obradio")} for r in rows]
        return {"ukupno": len(out), "rows": out}
