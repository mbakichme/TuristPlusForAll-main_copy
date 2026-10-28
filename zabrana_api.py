"""Administrativna zabrana (tabele zabrana + ratazab).

- zabrana: jedna zabrana po kreiranju (popup na Rezervacijama). Broj zabrane
  je `brojUgovora/N` (N = redni broj zabrane za taj ugovor), polje je izmenljivo
  ali mora biti jedinstveno.
- ratazab: 12 rata, iznos/12 (ostatak centi na prvim ratama). Datumi: mesečno
  od prve rate; ako je zadata prva polurata, rate padaju na njen dan u mesecu
  (npr. 15. u svakom mesecu počev od meseca prve rate).

Iznosi obračuna (smestaj, prevoz, dod, procs, ukupno) se računaju na serveru
iz reda aranzmana; klijent šalje samo iznos EUR (može se korigovati).
"""

import calendar
from datetime import date, datetime
from typing import Callable, Optional

from fastapi import Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text

BROJ_RATA = 12


def init_zabrana(engine):
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS zabrana (
                id SERIAL PRIMARY KEY,
                id_aranzmana VARCHAR(512) NOT NULL DEFAULT '',
                zabrana VARCHAR(512) NOT NULL DEFAULT '',
                preduzece VARCHAR(512) NOT NULL DEFAULT '',
                datum DATE,
                procs DOUBLE PRECISION,
                smestaje DOUBLE PRECISION,
                smestaj DOUBLE PRECISION,
                prevoz DOUBLE PRECISION,
                dod DOUBLE PRECISION,
                kurs DOUBLE PRECISION,
                prvarata TIMESTAMP,
                brojrata SMALLINT,
                idsub INTEGER,
                brojzabrane VARCHAR(512) NOT NULL,
                preuzeta TIMESTAMP,
                operater VARCHAR(512) NOT NULL DEFAULT '',
                ukupno DOUBLE PRECISION,
                valuta VARCHAR(512) NOT NULL DEFAULT '',
                polurata TIMESTAMP,
                mestoobracuna VARCHAR(512) NOT NULL DEFAULT ''
            )
        """))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS zabrana_brojzabrane_uq ON zabrana (brojzabrane)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS zabrana_aranzman_idx ON zabrana (id_aranzmana)"
        ))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ratazab (
                id VARCHAR(512) PRIMARY KEY,
                id_zabrane VARCHAR(512) NOT NULL,
                datum DATE,
                rata DOUBLE PRECISION,
                rb SMALLINT,
                rasknjizeno BOOLEAN NOT NULL DEFAULT FALSE,
                datumizvod DATE,
                nacinplacanja VARCHAR(512)
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ratazab_zabrana_idx ON ratazab (id_zabrane)"
        ))


def _dodaj_mesece(d: date, meseci: int, dan: Optional[int] = None) -> date:
    """Pomera datum za `meseci`; `dan` (ako je zadat) zamenjuje dan u mesecu."""
    ukupno = d.month - 1 + meseci
    god = d.year + ukupno // 12
    mes = ukupno % 12 + 1
    poslednji = calendar.monthrange(god, mes)[1]
    dan_u_mesecu = dan if dan is not None else d.day
    return date(god, mes, min(dan_u_mesecu, poslednji))


def podeli_na_rate(iznos: float, prva_rata: date, prva_polurata: Optional[date],
                   broj_rata: int = BROJ_RATA) -> list[tuple[date, float]]:
    """`broj_rata` rata; iznos u centima, ostatak centi raspodeljen na prve rate."""
    cents = round(iznos * 100)
    base, ostatak = divmod(cents, broj_rata)
    dan = prva_polurata.day if prva_polurata else None
    out = []
    for k in range(broj_rata):
        datum = _dodaj_mesece(prva_rata, k, dan)
        c = base + (1 if k < ostatak else 0)
        out.append((datum, c / 100))
    return out


class ZabranaNova(BaseModel):
    kljuc: str = Field(min_length=1, max_length=512)
    subagent_id: int
    mesto_obracuna: str = Field(default="", max_length=512)
    datum: date
    broj_zabrane: str = Field(min_length=1, max_length=512)
    prva_rata: date
    prva_polurata: Optional[date] = None
    iznos_eur: float = Field(gt=0)
    broj_rata: int = Field(default=BROJ_RATA, ge=1, le=120)

    @field_validator("kljuc", "broj_zabrane", "mesto_obracuna")
    @classmethod
    def _strip(cls, v: str) -> str:
        return (v or "").strip()

    @field_validator("iznos_eur")
    @classmethod
    def _dve_decimale(cls, v: float) -> float:
        if round(v, 2) != v:
            raise ValueError("Iznos može imati najviše dve decimale")
        return v


def _d(v) -> str:
    return v.strftime("%d.%m.%Y.") if v else ""


def _zabrana_detalj(conn, broj: str) -> dict:
    """Sve što treba za pregled i PDF zabrane (iznosi u RSD)."""
    z = conn.execute(text("SELECT * FROM zabrana WHERE brojzabrane = :b"),
                     {"b": broj}).mappings().fetchone()
    if not z:
        raise HTTPException(status_code=404, detail="Zabrana nije pronađena")
    ar = conn.execute(text(
        "SELECT * FROM aranzman WHERE kljuc = :k ORDER BY id DESC LIMIT 1"
    ), {"k": z["id_aranzmana"]}).mappings().fetchone()
    ag = conn.execute(text("SELECT * FROM agencija WHERE id = 1")).mappings().first() or {}
    rate = conn.execute(text(
        "SELECT rb, datum, rata, rasknjizeno FROM ratazab WHERE id_zabrane = :b ORDER BY rb"
    ), {"b": broj}).mappings().all()

    nosilac = {"ime": "", "rodjen": "", "adresa": "", "telefon": ""}
    putnici = []
    aranzman = {"mesto": "", "naziv": "", "termin": "", "apartman": ""}
    if ar:
        nosilac = {"ime": ar["putnik"] or "", "rodjen": _d(ar["rodjen"]),
                   "adresa": ar["adresa"] or "", "telefon": ar["telefon"] or ""}
        putnici.append({"ime": nosilac["ime"], "rodjen": nosilac["rodjen"]})
        for s in conn.execute(text(
            "SELECT saputnik, rodjen FROM aranzman_dopuna WHERE aranzman_id = :a ORDER BY id"
        ), {"a": ar["id"]}).mappings().all():
            if (s["saputnik"] or "").strip():
                putnici.append({"ime": s["saputnik"], "rodjen": _d(s["rodjen"])})
        termin = " - ".join(x for x in [_d(ar["datumod"]), _d(ar["datumdo"])] if x)
        aranzman = {"mesto": ar["mesto"] or "", "naziv": ar["naziv"] or "",
                    "termin": termin, "apartman": ar.get("apartman") or ""}

    return {
        "broj": z["brojzabrane"],
        "preduzece": z["preduzece"],
        "mesto_obracuna": z["mestoobracuna"] or "",
        "datum": _d(z["datum"]),
        "broj_rata": z["brojrata"] or len(rate),
        "smestaj": z["smestaj"] or 0,
        "prevoz": z["prevoz"] or 0,
        "dod": z["dod"] or 0,
        "ukupno": z["ukupno"] or 0,
        "valuta": "RSD",
        "kurs": z["kurs"],
        "nosilac": nosilac,
        "putnici": putnici,
        "aranzman": aranzman,
        "rate": [{"rb": r["rb"], "datum": _d(r["datum"]), "iznos": r["rata"] or 0,
                  "rasknjizeno": bool(r["rasknjizeno"])} for r in rate],
        "agencija": {
            "naziv": ag.get("naziv") or "",
            "mesto": ag.get("mesto") or "",
            "adresa": " ".join(x for x in [ag.get("ulica_naziv") or "",
                                           str(ag.get("ulica_broj") or "")] if x).strip(),
            "telefon": ag.get("telefon1") or "",
            "email": ag.get("email1") or "",
            "racun": ag.get("tekuci_racun1") or "",
            "banka": ag.get("banka1") or "",
        },
    }


def _broj_ugovora(kljuc: str) -> str:
    return kljuc.strip().strip("/").split("/")[0]


def register_zabrana(api, engine, get_current_user, get_kurs: Callable[[], float],
                     calc_obracun: Callable[[dict], dict]):

    def _aranzman(conn, kljuc: str):
        row = conn.execute(text(
            "SELECT * FROM aranzman WHERE kljuc = :k ORDER BY id DESC LIMIT 1"
        ), {"k": kljuc}).mappings().fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Ugovor nije pronađen")
        return row

    def _sledeci_broj(conn, kljuc: str) -> str:
        base = _broj_ugovora(kljuc)
        n = conn.execute(text(
            "SELECT COUNT(*) FROM zabrana WHERE id_aranzmana = :k"
        ), {"k": kljuc}).scalar() or 0
        n += 1
        while conn.execute(text("SELECT 1 FROM zabrana WHERE brojzabrane = :b"),
                           {"b": f"{base}/{n}"}).fetchone():
            n += 1
        return f"{base}/{n}"

    @api.get("/zabrane/predlog")
    def zabrana_predlog(kljuc: str, _: dict = Depends(get_current_user)):
        """Predlog za popup: sledeći broj zabrane, iznos iz obračuna (EUR), kurs."""
        kljuc = kljuc.strip().strip("/")
        with engine.connect() as conn:
            ar = _aranzman(conn, kljuc)
            broj = _sledeci_broj(conn, kljuc)
        obracun = calc_obracun(dict(ar))
        kurs = get_kurs()
        return {
            "broj_zabrane": broj,
            "iznos_eur": obracun["naplata"],
            "kurs": kurs,
            "iznos_rsd": round(obracun["naplata"] * kurs, 2),
        }

    @api.get("/zabrane")
    def zabrane_lista(q: str = "", limit: int = 500, _: dict = Depends(get_current_user)):
        limit = max(1, min(int(limit), 2000))
        sql = ("SELECT id, id_aranzmana, brojzabrane, preduzece, datum, mestoobracuna, "
               "prvarata, polurata, brojrata, ukupno, valuta, operater, preuzeta "
               "FROM zabrana")
        bind: dict = {"lim": limit}
        pojam = (q or "").strip()
        if pojam:
            sql += (" WHERE brojzabrane ILIKE :q OR id_aranzmana ILIKE :q OR preduzece ILIKE :q"
                    " OR mestoobracuna ILIKE :q OR operater ILIKE :q")
            bind["q"] = f"%{pojam}%"
        sql += " ORDER BY preuzeta DESC NULLS LAST, id DESC LIMIT :lim"
        with engine.connect() as conn:
            rows = conn.execute(text(sql), bind).mappings().all()
        out = []
        for r in rows:
            d = dict(r)
            for k in ("datum",):
                d[k] = d[k].isoformat() if d.get(k) else None
            for k in ("prvarata", "polurata", "preuzeta"):
                d[k] = d[k].strftime("%d.%m.%Y.") if d.get(k) else None
            out.append(d)
        return {"rows": out, "total": len(out)}

    @api.get("/zabrane/detalj")
    def zabrana_detalj(broj: str, _: dict = Depends(get_current_user)):
        """Detalj zabrane + sve rate (za dijalog na pregledu)."""
        with engine.connect() as conn:
            return _zabrana_detalj(conn, broj.strip())

    @api.get("/zabrane/pdf")
    def zabrana_pdf(broj: str, _: dict = Depends(get_current_user)):
        """PDF „Prijava aranžmana / administrativna zabrana“ (iznosi u RSD)."""
        from zabrana_pdf import build_zabrana_pdf

        with engine.connect() as conn:
            d = _zabrana_detalj(conn, broj.strip())
        pdf = build_zabrana_pdf(d)
        ime = d["broj"].replace("/", "-")
        return Response(content=pdf, media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="zabrana_{ime}.pdf"'})

    @api.post("/zabrane", status_code=201)
    def zabrana_kreiraj(body: ZabranaNova, current_user: dict = Depends(get_current_user)):
        try:
            user_id = int(current_user["sub"])
        except (KeyError, TypeError, ValueError):
            raise HTTPException(status_code=401, detail="Neautorizovan pristup")

        kurs = get_kurs()
        with engine.begin() as conn:
            urow = conn.execute(text(
                "SELECT first_name, last_name FROM users WHERE id = :id"
            ), {"id": user_id}).fetchone()
            operater = (f"{(urow.first_name or '').strip()} {(urow.last_name or '').strip()}".strip()
                        if urow else "")

            ar = _aranzman(conn, body.kljuc)
            subagent = conn.execute(text(
                "SELECT naziv FROM subagenti WHERE id = :s AND naziv <> '' AND ta = false"
            ), {"s": body.subagent_id}).fetchone()
            if not subagent:
                raise HTTPException(status_code=400, detail="Izaberite firmu")

            if conn.execute(text("SELECT 1 FROM zabrana WHERE brojzabrane = :b"),
                            {"b": body.broj_zabrane}).fetchone():
                raise HTTPException(status_code=409, detail=f"Zabrana {body.broj_zabrane} već postoji")

            ob = calc_obracun(dict(ar))
            # sve zapisi u RSD: EUR iznosi × kurs na dan kreiranja (kurs se čuva uz zabranu)
            def rsd(v: float) -> float:
                return round(float(v or 0) * kurs, 2)
            iznos_rsd = rsd(body.iznos_eur)
            zid = conn.execute(text("""
                INSERT INTO zabrana
                  (id_aranzmana, zabrana, preduzece, datum, procs, smestaje, smestaj, prevoz, dod,
                   kurs, prvarata, brojrata, idsub, brojzabrane, preuzeta, operater, ukupno,
                   valuta, polurata, mestoobracuna)
                VALUES
                  (:ida, :zab, :pred, :datum, :procs, :smestaje, :smestaj, :prevoz, :dod,
                   :kurs, :prva, :brrata, :idsub, :broj, NOW(), :oper, :ukupno,
                   :valuta, :polurata, :mesto)
                RETURNING id
            """), {
                "ida": body.kljuc,
                "zab": "Administrativna zabrana",
                "pred": subagent.naziv,
                "datum": body.datum,
                # procs = provizija iz obračuna; smeštaj/prevoz/dod iz obračuna ugovora (RSD)
                "procs": rsd(ob["provizija"]),
                "smestaje": rsd(ob["smestaj"]),
                "smestaj": rsd(ob["smestaj"]),
                "prevoz": rsd(ob["prevoz"]),
                "dod": rsd(ar.get("cenadod")),
                "kurs": kurs,
                "prva": datetime.combine(body.prva_rata, datetime.min.time()),
                "brrata": body.broj_rata,
                "idsub": body.subagent_id,
                "broj": body.broj_zabrane,
                "oper": operater,
                "ukupno": iznos_rsd,
                "valuta": "RSD",
                "polurata": (datetime.combine(body.prva_polurata, datetime.min.time())
                             if body.prva_polurata else None),
                "mesto": body.mesto_obracuna,
            }).scalar()

            for rb, (datum, iznos) in enumerate(podeli_na_rate(iznos_rsd, body.prva_rata,
                                                              body.prva_polurata,
                                                              body.broj_rata), start=1):
                conn.execute(text("""
                    INSERT INTO ratazab
                      (id, id_zabrane, datum, rata, rb, rasknjizeno, datumizvod, nacinplacanja)
                    VALUES (:id, :zab, :datum, :rata, :rb, FALSE, NULL, NULL)
                """), {"id": f"{body.broj_zabrane}#{rb}", "zab": body.broj_zabrane,
                       "datum": datum, "rata": iznos, "rb": rb})
        return {"status": "kreirano", "id": zid, "broj_zabrane": body.broj_zabrane,
                "broj_rata": body.broj_rata, "iznos_rsd": iznos_rsd, "kurs": kurs}

