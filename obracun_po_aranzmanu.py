"""Tabela obracun_po_aranzmanu — jedan red po ugovoru (aranzman).

Red se upisuje/ažurira pri snimanju ugovora (upsert po aranzman_id) i menja se pri izmeni.
koeficijent = broj kojim se množi cena sobe/virtuelne sobe (iz koeficijenti prodaje za strukturu).
soba_cenovnik = broj sobe za navedeni cenovnik.
prevoz = true ako obračun uključuje prevoz (autobuski), false za sopstveni.
"""
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo
import json
import re

from sqlalchemy import text


def init_obracun_po_aranzmanu(engine):
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS obracun_po_aranzmanu (
                id SERIAL PRIMARY KEY,
                aranzman_id INTEGER NOT NULL UNIQUE REFERENCES aranzman(id) ON DELETE CASCADE,
                koeficijent NUMERIC(8, 4),
                adl INTEGER NOT NULL DEFAULT 0,
                chd INTEGER NOT NULL DEFAULT 0,
                inf INTEGER NOT NULL DEFAULT 0,
                mesto_id INTEGER,
                smestaj_id INTEGER,
                grupa_perioda_id INTEGER,
                cenovnik_id INTEGER REFERENCES cenovnici(id) ON DELETE SET NULL,
                soba_cenovnik VARCHAR(50),
                struktura VARCHAR(50),
                iznos_eur NUMERIC(12, 2),
                datumod DATE,
                datumdo DATE,
                prevoz BOOLEAN NOT NULL DEFAULT FALSE
            )
        """))
        # struktura po kojoj je računat koeficijent (varijanta iz PROVERI OBRAČUN); stari redovi = NULL
        conn.execute(text(
            "ALTER TABLE obracun_po_aranzmanu ADD COLUMN IF NOT EXISTS struktura VARCHAR(50)"
        ))


OBRACUN_KOLONE = (
    "koeficijent", "adl", "chd", "inf", "mesto_id", "smestaj_id", "grupa_perioda_id",
    "cenovnik_id", "soba_cenovnik", "struktura", "iznos_eur", "datumod", "datumdo", "prevoz",
)


def upsert_obracun(conn, aranzman_id: int, vals: dict) -> None:
    """Upisuje ili ažurira jedini red ugovora. Nepoznate ključeve ignoriše."""
    data = {k: vals.get(k) for k in OBRACUN_KOLONE}
    data["prevoz"] = bool(data["prevoz"])
    for k in ("adl", "chd", "inf"):
        data[k] = int(data[k] or 0)
    cols = ", ".join(OBRACUN_KOLONE)
    ph = ", ".join(f":{k}" for k in OBRACUN_KOLONE)
    sets = ", ".join(f"{k} = EXCLUDED.{k}" for k in OBRACUN_KOLONE)
    conn.execute(text(
        f"INSERT INTO obracun_po_aranzmanu (aranzman_id, {cols}) VALUES (:aid, {ph}) "
        f"ON CONFLICT (aranzman_id) DO UPDATE SET {sets}"
    ), {"aid": aranzman_id, **data})


def _norm(v: str) -> str:
    return re.sub(r"\s+", "", v or "").upper()


KARTA_ADL = Decimal("80")  # privremene fiksne cene karata (isto kao u pretrazi, routes.py)
KARTA_CHD = Decimal("70")


def _q2(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"))


def lanac_termina(periodi: list, datumod: date, datumdo: date) -> list:
    """Lanac perioda cenovnika od datumod do datumdo (isto kao BFS u pretrazi). Prazno ako ne postoji."""
    poceci: dict = {}
    for p in periodi:
        poceci.setdefault(str(p["datum_od"]), []).append(p)
    cilj = datumdo.isoformat()
    front = [(datumod.isoformat(), [])]
    videno = set()
    while front:
        sledeci = []
        for cur, put in front:
            if cur in videno:
                continue
            videno.add(cur)
            for p in poceci.get(cur, []):
                novi = put + [p]
                if str(p["datum_do"]) == cilj:
                    return novi
                if str(p["datum_do"]) < cilj:
                    sledeci.append((str(p["datum_do"]), novi))
        front = sledeci
    return []


def izracun_ponude(*, lanac: list, red_id: int, struktura: str, koef: Decimal | None, izuz_koef: Decimal | None,
                   cene: dict, opcije: dict, popusti: dict, adl: int, chd: int, inf: int,
                   sopstveni: bool, danas: date) -> dict:
    """Cena jedne sobe/varijante za jednu opciju prevoza — pravila kao _obracun_sobe u pretrazi.

    - osnova = zbir cena po terminima lanca (bez blokirane smene)
    - po osobi: osnova × koeficijent; sopstveni prevoz minus umanjenje × broj osoba × smena
      (autobuski: × (smena − 1)); po sobi: autobuski + karte, sopstveni bez korekcije
    - popust: opcije PRVOG termina lanca (važi danas); važeći popust = konačna cena
    """
    def po_opsegu(mapa: dict, pid: int):
        return mapa.get((red_id, pid)) or mapa.get((red_id, 0))

    nema = lambda razlog: {"dostupno": False, "razlog": razlog}  # noqa: E731
    if not lanac:
        return nema("Cenovnik ne pokriva traženi boravak lancem termina")
    for p in lanac:
        opc_p = po_opsegu(opcije, p["id"])
        if opc_p and opc_p["blokirano"]:
            return nema(f"Blokirano u cenovniku za termin {p['datum_od']} – {p['datum_do']}")
    osnova = Decimal("0")
    termini = []
    for p in lanac:
        cena_p = cene.get((red_id, p["id"]))
        if cena_p is None or cena_p <= 0:
            return nema(f"Nema unete cene za termin {p['datum_od']} – {p['datum_do']}")
        osnova += cena_p
        termini.append({"datum_od": str(p["datum_od"]), "datum_do": str(p["datum_do"]), "cena": float(cena_p)})

    osnova_cenovnika = osnova  # zbir cena iz tabele po terminima, pre koeficijenta
    if izuz_koef is not None:
        # izuzetak za 1 osobu: osnova × koeficijent perioda; važi samo za strukture 1/2
        if not re.match(r"^1/2(?:[\s+]|$)", struktura):
            return nema("Izuzetak za 1 osobu važi samo za strukture 1/2")
        if izuz_koef <= 0:
            return nema("Izuzetak za 1 osobu: koeficijent perioda u parametrima obračuna je 0")
        koef = izuz_koef
        osnova = osnova * koef
        koef_mnozi = Decimal("1")
    else:
        if koef is None:
            return nema(f"U koeficijenti_prodaje nema reda za strukturu {struktura} sa {adl} ADL / {chd} CHD")
        koef_mnozi = koef

    prvi = lanac[0]["id"]
    opc = po_opsegu(opcije, prvi)
    tip_cene = (opc["tip_cene"] if opc and opc["tip_cene"] else "po_osobi")
    umanj_sp = Decimal(str(opc["popust_sopstveni_prevoz"])) if opc and opc["popust_sopstveni_prevoz"] else Decimal("0")
    osnova_eur = osnova
    if tip_cene == "po_sobi":
        cena = osnova
        if not sopstveni:
            cena += KARTA_ADL * adl + KARTA_CHD * chd
    else:
        if koef_mnozi <= 0:
            return nema(f"Tip cene po osobi, ali koeficijent za {adl} ADL / {chd} CHD / {inf} INF "
                        f"(struktura {struktura}) je 0")
        osnova_eur = osnova * koef_mnozi
        cena = osnova_eur
        n_smena = len(lanac)
        puta = n_smena if sopstveni else n_smena - 1
        if umanj_sp > 0 and puta > 0:
            # umanjenje po jedinici × koeficijent × smene (ne × broj osoba)
            cena -= umanj_sp * koef_mnozi * puta
    korekcija = _q2(cena - osnova_eur)
    osnovna = _q2(max(Decimal("0"), cena))
    # jedinična cena za formu: sopstveni prevoz = osnova − umanjenje × smene (umanjenje po jedinici, jednom po terminu)
    cena_jedinicna = osnova_cenovnika
    if tip_cene != "po_sobi" and sopstveni and umanj_sp > 0 and lanac:
        cena_jedinicna = osnova_cenovnika - umanj_sp * len(lanac)
    cena_jedinicna = _q2(max(Decimal("0"), cena_jedinicna))

    popusti_out = []
    for pop in (po_opsegu(popusti, prvi) or []):
        vazi = ((pop["vazi_od"] is None or pop["vazi_od"] <= danas)
                and (pop["vazi_do"] is None or pop["vazi_do"] >= danas))
        um = Decimal(str(pop["umanjenje"]))
        snizena = None
        if vazi:
            if pop["umanjenje_vrsta"] == "procenat":
                snizena = _q2(osnovna * (Decimal("100") - um) / Decimal("100"))
            else:
                snizena = _q2(max(Decimal("0"), osnovna - um))
        popusti_out.append({
            "redni": int(pop["redni"]), "tip_popusta": pop["tip_popusta"], "vazi": vazi,
            "vrsta": pop["umanjenje_vrsta"], "umanjenje": float(um),
            "vazi_od": str(pop["vazi_od"]) if pop["vazi_od"] else None,
            "vazi_do": str(pop["vazi_do"]) if pop["vazi_do"] else None,
            "cena_snizena": float(snizena) if snizena is not None else None,
        })
    prvi_vazeci = next((p for p in popusti_out if p["cena_snizena"] is not None), None)
    return {
        "dostupno": True, "razlog": None, "tip_cene": tip_cene,
        "koeficijent": float(koef if izuz_koef is None else izuz_koef),
        "osnova": float(_q2(osnova_eur)), "osnova_cenovnika": float(_q2(osnova_cenovnika)),
        "cena_jedinicna": float(cena_jedinicna),
        "korekcija_prevoza": float(korekcija),
        "cena": float(osnovna), "termini": termini, "popusti": popusti_out,
        "cena_konacna": prvi_vazeci["cena_snizena"] if prvi_vazeci else float(osnovna),
    }


def varijante_cene(conn, smestaj_id: int, soba_id: int, datumod, datumdo,
                   adl: int = 0, chd: int = 0, inf: int = 0) -> dict:
    """Cene izabrane sobe i njenih virtuelnih varijanti (v{broj}, v{broj}-n) iz cenovnika
    koji važi za datum početka boravka. Za svaku varijantu dve ponude: sa prevozom
    (autobuski) i bez prevoza (sopstveni), sa umanjenjem i popustom predviđenim za termin.
    Ne menja bazu."""
    cid = conn.execute(text("""
        SELECT c.id FROM cenovnici c
        JOIN cenovnik_opcije o ON o.cenovnik_id = c.id
        WHERE c.smestaj_id = :s AND o.datumod <= :d AND o.datumdo >= :d
        ORDER BY c.id DESC LIMIT 1
    """), {"s": smestaj_id, "d": datumod}).scalar()
    if cid is None:
        return {"cenovnik_id": None, "naziv": None, "periodi": [], "varijante": []}
    cen = conn.execute(text("SELECT naziv, sobe, periodi FROM cenovnici WHERE id = :c"),
                       {"c": cid}).mappings().one()
    sobe = cen["sobe"] if isinstance(cen["sobe"], list) else json.loads(cen["sobe"])
    periodi = cen["periodi"] if isinstance(cen["periodi"], list) else json.loads(cen["periodi"])
    lanac = lanac_termina(periodi, datumod, datumdo)
    izabrane = [s for s in sobe if s.get("id") == soba_id or s.get("izvor_soba_id") == soba_id]
    izabrane.sort(key=lambda s: (bool(s.get("virtuelna")), str(s.get("broj_sobe"))))
    if not izabrane:
        return {"cenovnik_id": cid, "naziv": cen["naziv"], "periodi": lanac, "varijante": []}
    ids = [s["id"] for s in izabrane]
    danas = datetime.now(ZoneInfo("Europe/Belgrade")).date()

    # koeficijenti za putnike — isti redosled kao u pretrazi (prvi red po strukturi)
    koef_map: dict = {}
    for r in conn.execute(text("""
        SELECT struktura, koeficijent FROM koeficijenti_prodaje
        WHERE adl = :a AND chd = :c AND inf = :i
        ORDER BY (koeficijent > 0) DESC, rucno, id
    """), {"a": adl, "c": chd, "i": inf}):
        koef_map.setdefault((r.struktura or "").strip(), Decimal(str(r.koeficijent or 0)))
    # izuzetak za 1 osobu: početak boravka u periodu parametara obračuna
    izuz_koef = None
    if adl == 1 and chd == 0 and inf == 0:
        par = conn.execute(text("""
            SELECT datumod1, datumdo1, koeficijent1, datumod2, datumdo2, koeficijent2
            FROM parametri_obracuna WHERE id = 1
        """)).mappings().first()
        if par:
            for n in ("1", "2"):
                od_, do_, k_ = par[f"datumod{n}"], par[f"datumdo{n}"], par[f"koeficijent{n}"]
                if od_ and do_ and k_ is not None and od_ <= datumod <= do_:
                    izuz_koef = Decimal(str(k_))
                    break

    cene = {(r.soba_id, r.period_id): Decimal(str(r.cena)) for r in conn.execute(text("""
        SELECT soba_id, period_id, cena FROM cenovnik_cene
        WHERE cenovnik_id = :c AND soba_id = ANY(:ids)
    """), {"c": cid, "ids": ids})}
    opcije = {(r["soba_id"], r["period_id"]): r for r in conn.execute(text(
        "SELECT * FROM opcije_soba WHERE cenovnik_id = :c"), {"c": cid}).mappings()}
    popusti: dict = {}
    for r in conn.execute(text(
        "SELECT * FROM popust_soba WHERE cenovnik_id = :c ORDER BY redni"), {"c": cid}).mappings():
        popusti.setdefault((r["soba_id"], r["period_id"]), []).append(r)

    varijante = []
    for s in izabrane:
        struktura = (s.get("tip") or "").strip()
        zajednicko = dict(lanac=lanac, red_id=s["id"], struktura=struktura,
                          koef=koef_map.get(struktura), izuz_koef=izuz_koef,
                          cene=cene, opcije=opcije, popusti=popusti,
                          adl=adl, chd=chd, inf=inf, danas=danas)
        varijante.append({
            "soba_id": s["id"],
            "broj_sobe": s.get("broj_sobe"),
            "struktura": s.get("tip"),
            "opis": s.get("opis") or "",
            "virtuelna": bool(s.get("virtuelna")),
            "ponude": {
                "sa_prevozom": izracun_ponude(**zajednicko, sopstveni=False),
                "bez_prevoza": izracun_ponude(**zajednicko, sopstveni=True),
            },
        })
    return {"cenovnik_id": cid, "naziv": cen["naziv"], "periodi": lanac, "varijante": varijante}


def obracun_iz_rezervacije(conn, aranzman_id: int, *, smestaj_id, soba_broj, struktura,
                           uzrasti, prevoz: bool, iznos_eur, datumod, datumdo) -> None:
    """Snima red obračuna posle snimanja ugovora.

    - mesto_id, grupa_perioda_id: iz smeštaja (smestaj.mesto, smestaj.grupa_datuma)
    - cenovnik_id: aktivni cenovnik smeštaja za datum početka boravka (cenovnik_opcije)
    - koeficijent: koeficijenti_prodaje za strukturu + ADL/CHD/INF; NULL ako nema reda
    - adl/chd/inf: broj putnika po uzrastu (nosilac + saputnici)
    """
    adl = sum(1 for u in uzrasti if (u or "").strip() == "ADL")
    chd = sum(1 for u in uzrasti if (u or "").strip() == "CHD")
    inf = sum(1 for u in uzrasti if (u or "").strip() == "INF")
    mesto_id = grupa_id = cenovnik_id = None
    if smestaj_id is not None:
        s = conn.execute(text("SELECT mesto, grupa_datuma FROM smestaj WHERE id = :i"),
                         {"i": smestaj_id}).fetchone()
        if s:
            mesto_id, grupa_id = s.mesto, s.grupa_datuma
        cenovnik_id = conn.execute(text("""
            SELECT c.id FROM cenovnici c
            JOIN cenovnik_opcije o ON o.cenovnik_id = c.id
            WHERE c.smestaj_id = :s AND o.datumod <= :d AND o.datumdo >= :d
            ORDER BY c.id DESC LIMIT 1
        """), {"s": smestaj_id, "d": datumod.date() if hasattr(datumod, "date") else datumod}).scalar()
    koef = None
    if struktura:
        koef = conn.execute(text("""
            SELECT koeficijent FROM koeficijenti_prodaje
            WHERE REGEXP_REPLACE(UPPER(struktura), '\\s', '', 'g') = :st
              AND adl = :a AND chd = :c AND inf = :i
            ORDER BY id LIMIT 1
        """), {"st": _norm(struktura), "a": adl, "c": chd, "i": inf}).scalar()
    upsert_obracun(conn, aranzman_id, {
        "koeficijent": koef, "adl": adl, "chd": chd, "inf": inf,
        "mesto_id": mesto_id, "smestaj_id": smestaj_id, "grupa_perioda_id": grupa_id,
        "cenovnik_id": cenovnik_id, "soba_cenovnik": soba_broj, "struktura": struktura,
        "iznos_eur": iznos_eur,
        "datumod": datumod, "datumdo": datumdo, "prevoz": prevoz,
    })
