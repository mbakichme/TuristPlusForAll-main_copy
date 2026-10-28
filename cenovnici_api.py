"""Cenovnici: trajni snimak soba/termina i cene za ceo termin."""
import json
from datetime import date
from decimal import Decimal
from uuid import uuid4

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import text


class CenaIn(BaseModel):
    soba_id: int
    period_id: int
    cena: Decimal

    @field_validator("cena")
    @classmethod
    def validna_cena(cls, value):
        if not value.is_finite() or value < 0 or value >= Decimal("1000000000000"):
            raise ValueError("Cena mora biti konačan, nenegativan iznos manji od 1000000000000")
        if value != value.quantize(Decimal("0.01")):
            raise ValueError("Cena može imati najviše dve decimale")
        return value


class CenovnikIzmena(BaseModel):
    datumod: date
    datumdo: date
    cene: list[CenaIn] = Field(default_factory=list, max_length=100000)
    opis: str | None = None  # None = ne menjaj postojeći opis (stari klijenti)

    @model_validator(mode="after")
    def validni_datumi(self):
        if self.datumod > self.datumdo:
            raise ValueError("Aktivan od mora biti pre ili isti kao Aktivan do")
        return self

    @field_validator("opis")
    @classmethod
    def validan_opis(cls, v):
        if v is None:
            return None
        v = v.strip()
        if len(v) > 500:
            raise ValueError("Opis cenovnika može imati najviše 500 znakova")
        return v


class CenovnikNovi(CenovnikIzmena):
    mesto_id: int
    grupa_id: int
    smestaj_id: int
    opis: str = ""  # novi cenovnik uvek dobija opis (prazan ako nije unet)


# ── Opcije i popusti po sobi cenovnika (opcije_soba / popust_soba) ──────────

PREVOZ_VREDNOSTI = ("opciono", "obavezan", "nemoguc")
TIP_ARANZMANA_VREDNOSTI = ("sa_prevozom", "bez_prevoza")
TIP_CENE_VREDNOSTI = ("po_osobi", "po_sobi")
TIP_POPUSTA_VREDNOSTI = ("last_minute", "first_minute", "specijalna_ponuda", "ultra_last_minute")
TIP_PLACANJA_VREDNOSTI = ("delimicno", "u_celosti")


def _enum_ili_none(vrednost: str | None, dozvoljene: tuple[str, ...], naziv: str) -> str | None:
    if vrednost is None:
        return None
    vrednost = vrednost.strip().lower()
    if vrednost == "":
        return None
    if vrednost not in dozvoljene:
        raise ValueError(f"{naziv} mora biti jedno od: {', '.join(dozvoljene)}")
    return vrednost


def _iznos_ili_none(vrednost: Decimal | None, naziv: str) -> Decimal | None:
    if vrednost is None:
        return None
    if not vrednost.is_finite() or vrednost < 0 or vrednost >= Decimal("1000000000000"):
        raise ValueError(f"{naziv} mora biti konačan, nenegativan iznos manji od 1000000000000")
    if vrednost != vrednost.quantize(Decimal("0.01")):
        raise ValueError(f"{naziv} može imati najviše dve decimale")
    return vrednost


class OpcijeSobaIn(BaseModel):
    blokirano: bool = False
    istaknuto: bool = False
    blokirano_subagenci: bool = False
    blokirano_sajt: bool = False
    prevoz: str | None = None
    tip_aranzmana: str | None = None
    tip_cene: str | None = None
    popust_sopstveni_prevoz: Decimal | None = None

    @field_validator("prevoz")
    @classmethod
    def _prevoz(cls, v):
        return _enum_ili_none(v, PREVOZ_VREDNOSTI, "Prevoz")

    @field_validator("tip_aranzmana")
    @classmethod
    def _aranzman(cls, v):
        return _enum_ili_none(v, TIP_ARANZMANA_VREDNOSTI, "Tip aranžmana")

    @field_validator("tip_cene")
    @classmethod
    def _tip_cene(cls, v):
        return _enum_ili_none(v, TIP_CENE_VREDNOSTI, "Tip cene")

    @field_validator("popust_sopstveni_prevoz")
    @classmethod
    def _iznos(cls, v):
        return _iznos_ili_none(v, "Popust za sopstveni prevoz")


class BlokadaIn(BaseModel):
    sobe: list[int]    # soba_id-jevi iz snimka (realne i virtuelne)
    periodi: list[int]  # period_id-jevi iz snimka
    blokirano: bool


class PopustSobaIn(BaseModel):
    umanjenje_vrsta: str  # 'iznos' | 'procenat'
    umanjenje: Decimal
    tip_popusta: str
    tip_placanja: str | None = None
    vazi_od: date | None = None
    vazi_do: date | None = None
    tip_aranzmana: str | None = None
    tip_cene: str | None = None
    popust_sopstveni_prevoz: Decimal | None = None

    @field_validator("umanjenje_vrsta")
    @classmethod
    def _vrsta(cls, v):
        v = (v or "").strip().lower()
        if v not in ("iznos", "procenat"):
            raise ValueError("Umanjenje mora biti 'iznos' ili 'procenat'")
        return v

    @field_validator("umanjenje")
    @classmethod
    def _umanjenje(cls, v):
        if not v.is_finite() or v <= 0 or v >= Decimal("1000000000000"):
            raise ValueError("Umanjenje mora biti konačan broj veći od 0")
        if v != v.quantize(Decimal("0.01")):
            raise ValueError("Umanjenje može imati najviše dve decimale")
        return v

    @field_validator("tip_popusta")
    @classmethod
    def _tip_popusta(cls, v):
        v = (v or "").strip().lower()
        if v not in TIP_POPUSTA_VREDNOSTI:
            raise ValueError(f"Tip popusta mora biti jedno od: {', '.join(TIP_POPUSTA_VREDNOSTI)}")
        return v

    @field_validator("tip_placanja")
    @classmethod
    def _placanja(cls, v):
        return _enum_ili_none(v, TIP_PLACANJA_VREDNOSTI, "Tip plaćanja")

    @field_validator("tip_aranzmana")
    @classmethod
    def _aranzman(cls, v):
        return _enum_ili_none(v, TIP_ARANZMANA_VREDNOSTI, "Tip aranžmana")

    @field_validator("tip_cene")
    @classmethod
    def _tip_cene(cls, v):
        return _enum_ili_none(v, TIP_CENE_VREDNOSTI, "Tip cene")

    @field_validator("popust_sopstveni_prevoz")
    @classmethod
    def _iznos(cls, v):
        return _iznos_ili_none(v, "Popust za sopstveni prevoz")

    @model_validator(mode="after")
    def _validno(self):
        if self.umanjenje_vrsta == "procenat" and self.umanjenje > 100:
            raise ValueError("Procenat može biti najviše 100")
        if self.vazi_od and self.vazi_do and self.vazi_od > self.vazi_do:
            raise ValueError("'Važi od' mora biti pre ili isti kao 'Važi do'")
        return self


class PopustiIn(BaseModel):
    """Skup popusta jednog opsega (soba / termin / cenovnik / polje): do 3, svaki zaseban red.
    Redni se dodeljuje po poziciji (1..3). Prazna lista = nema popusta (briše opseg)."""
    model_config = ConfigDict(extra="forbid")
    popusti: list[PopustSobaIn] = Field(default_factory=list, max_length=3)


def init_cenovnici(engine):
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS cenovnici (
                id SERIAL PRIMARY KEY, uuid UUID NOT NULL UNIQUE,
                naziv TEXT NOT NULL, opis TEXT NOT NULL DEFAULT '',
                mesto_id INTEGER NOT NULL,
                grupa_id INTEGER NOT NULL, smestaj_id INTEGER NOT NULL,
                sobe JSONB NOT NULL, periodi JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        conn.execute(text(
            "ALTER TABLE cenovnici ADD COLUMN IF NOT EXISTS opis TEXT NOT NULL DEFAULT ''"
        ))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS cenovnik_opcije (
                cenovnik_id INTEGER PRIMARY KEY REFERENCES cenovnici(id) ON DELETE CASCADE,
                datumod DATE NOT NULL, datumdo DATE NOT NULL,
                CHECK (datumod <= datumdo)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS cenovnik_cene (
                cenovnik_id INTEGER NOT NULL REFERENCES cenovnici(id) ON DELETE CASCADE,
                soba_id INTEGER NOT NULL, period_id INTEGER NOT NULL,
                cena NUMERIC(14,2) NOT NULL CHECK (cena >= 0),
                PRIMARY KEY (cenovnik_id, soba_id, period_id)
            )
        """))
        # Opcije po sobi cenovnika (soba_id = id iz JSONB snimka cenovnika, može biti
        # negativan za virtuelne sobe — zato BEZ FK ka tabeli sobe, po odluci za cenovnike).
        # period_id = 0 znači „SVI TERMINI“; konkretan id perioda iz snimka = override za taj termin.
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS opcije_soba (
                id SERIAL PRIMARY KEY,
                cenovnik_id INTEGER NOT NULL REFERENCES cenovnici(id) ON DELETE CASCADE,
                soba_id INTEGER NOT NULL,
                period_id INTEGER NOT NULL DEFAULT 0,
                blokirano BOOLEAN NOT NULL DEFAULT FALSE,
                istaknuto BOOLEAN NOT NULL DEFAULT FALSE,
                blokirano_subagenci BOOLEAN NOT NULL DEFAULT FALSE,
                blokirano_sajt BOOLEAN NOT NULL DEFAULT FALSE,
                prevoz TEXT, tip_aranzmana TEXT, tip_cene TEXT,
                popust_sopstveni_prevoz NUMERIC(14,2),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT opcije_soba_unique_csp UNIQUE (cenovnik_id, soba_id, period_id)
            )
        """))
        # Migracija postojeće baze: period_id + zamena starog UNIQUE(cenovnik_id, soba_id)
        conn.execute(text(
            "ALTER TABLE opcije_soba ADD COLUMN IF NOT EXISTS period_id INTEGER NOT NULL DEFAULT 0"
        ))
        conn.execute(text(
            "ALTER TABLE opcije_soba DROP CONSTRAINT IF EXISTS opcije_soba_cenovnik_id_soba_id_key"
        ))
        conn.execute(text("""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_constraint
                               WHERE conname = 'opcije_soba_unique_csp') THEN
                    ALTER TABLE opcije_soba
                        ADD CONSTRAINT opcije_soba_unique_csp
                        UNIQUE (cenovnik_id, soba_id, period_id);
                END IF;
            END $$;
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS popust_soba (
                id SERIAL PRIMARY KEY,
                cenovnik_id INTEGER NOT NULL REFERENCES cenovnici(id) ON DELETE CASCADE,
                soba_id INTEGER NOT NULL,
                period_id INTEGER NOT NULL DEFAULT 0,
                redni SMALLINT NOT NULL DEFAULT 1,
                umanjenje_vrsta TEXT NOT NULL CHECK (umanjenje_vrsta IN ('iznos', 'procenat')),
                umanjenje NUMERIC(14,2) NOT NULL CHECK (umanjenje > 0),
                tip_popusta TEXT NOT NULL,
                tip_placanja TEXT,
                vazi_od DATE, vazi_do DATE,
                tip_aranzmana TEXT, tip_cene TEXT,
                popust_sopstveni_prevoz NUMERIC(14,2),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT popust_soba_unique_cspr UNIQUE (cenovnik_id, soba_id, period_id, redni),
                CONSTRAINT popust_soba_redni_chk CHECK (redni BETWEEN 1 AND 3),
                CHECK (umanjenje_vrsta <> 'procenat' OR umanjenje <= 100),
                CHECK (vazi_od IS NULL OR vazi_do IS NULL OR vazi_od <= vazi_do)
            )
        """))
        conn.execute(text(
            "ALTER TABLE popust_soba ADD COLUMN IF NOT EXISTS period_id INTEGER NOT NULL DEFAULT 0"
        ))
        conn.execute(text(
            "ALTER TABLE popust_soba DROP CONSTRAINT IF EXISTS popust_soba_cenovnik_id_soba_id_key"
        ))
        # Do 3 popusta po opsegu (soba × termin): redni 1–3, svaki zaseban red.
        conn.execute(text(
            "ALTER TABLE popust_soba ADD COLUMN IF NOT EXISTS redni SMALLINT NOT NULL DEFAULT 1"
        ))
        conn.execute(text(
            "ALTER TABLE popust_soba DROP CONSTRAINT IF EXISTS popust_soba_redni_chk"
        ))
        conn.execute(text(
            "ALTER TABLE popust_soba ADD CONSTRAINT popust_soba_redni_chk CHECK (redni BETWEEN 1 AND 3)"
        ))
        conn.execute(text(
            "ALTER TABLE popust_soba DROP CONSTRAINT IF EXISTS popust_soba_unique_csp"
        ))
        conn.execute(text("""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_constraint
                               WHERE conname = 'popust_soba_unique_cspr') THEN
                    ALTER TABLE popust_soba
                        ADD CONSTRAINT popust_soba_unique_cspr
                        UNIQUE (cenovnik_id, soba_id, period_id, redni);
                END IF;
            END $$;
        """))


def _osvezi_sobe(conn, smestaj_id, stari_sobe=None, taguj_nove=False):
    """Spisak soba za cenovnik: realne sobe smeštaja iz žive baze + virtuelne sobe
    po dodatnim koeficijentima (soba_koeficijenti) — v{broj} (jedan dodatni
    koeficijent), odnosno v{broj}-1, v{broj}-2… (više njih), redom ispod izvorne sobe.

    Ako je dat stari snimak (stari_sobe), virtuelna soba ZADRŽAVA stari id dok se
    i dalje poklapa kombinacija (izvor_soba_id, struktura) — tako postojeće cene
    ostaju vezane za ispravan red — a nove virtuelne sobe dobijaju id ispod
    najnižeg starog. Sobe/koeficijenti koji više ne postoje nestaju iz spiska.
    Id je negativan i važi SAMO u okviru cenovnika; ne upisuju se u tabelu sobe —
    žive u JSONB snimku cenovnika."""
    sobe = [dict(r) for r in conn.execute(text("""
        SELECT id, broj_sobe, tip, opis, opis_dodatno FROM sobe
        WHERE veza_id_smestaj = :s ORDER BY broj_sobe, id
    """), {"s": smestaj_id}).mappings()]
    dodatni: dict[int, list[str]] = {}
    for r in conn.execute(text("""
        SELECT k.soba_id, k.struktura FROM soba_koeficijenti k
        JOIN sobe s ON s.id = k.soba_id
        WHERE s.veza_id_smestaj = :s ORDER BY k.soba_id, k.id
    """), {"s": smestaj_id}).fetchall():
        dodatni.setdefault(r.soba_id, []).append(r.struktura)
    stari_virt: dict[tuple[int, str], int] = {}
    for s in (stari_sobe or []):
        if s.get("virtuelna"):
            stari_virt[(s.get("izvor_soba_id"), s.get("tip"))] = s["id"]
    najnizi = min((s["id"] for s in (stari_sobe or []) if s.get("virtuelna")), default=0)
    stari_idjevi = {s["id"] for s in (stari_sobe or [])}
    sa_virtuelnim: list[dict] = []
    for sob in sobe:
        sa_virtuelnim.append(sob)
        strukture = dodatni.get(sob["id"], [])
        broj = sob["broj_sobe"] or str(sob["id"])
        for i, struktura in enumerate(strukture, start=1):
            kljuc = (sob["id"], struktura)
            if kljuc in stari_virt:
                vid = stari_virt.pop(kljuc)
            else:
                najnizi -= 1
                vid = najnizi
            sa_virtuelnim.append({
                "id": vid,
                "broj_sobe": f"v{broj}" if len(strukture) == 1 else f"v{broj}-{i}",
                "tip": struktura,
                "opis": sob["opis"] or "",
                "opis_dodatno": sob["opis_dodatno"] or "",
                "izvor_soba_id": sob["id"],
                "virtuelna": True,
            })
    if taguj_nove:
        for s in sa_virtuelnim:
            if s["id"] not in stari_idjevi:
                s["nova"] = True
    return sa_virtuelnim


def _sablon(conn, mesto_id, grupa_id, smestaj_id):
    ref = conn.execute(text("""
        SELECT m.naziv AS mesto_naziv, s.naziv AS smestaj_naziv, g.naziv AS grupa_naziv
        FROM smestaj s JOIN mesto m ON m.id = s.mesto
        JOIN period_grupa g ON g.id = s.grupa_datuma
        WHERE m.id = :m AND s.id = :s AND g.id = :g
        AND (m.grupa_datuma = :g OR EXISTS (
            SELECT 1 FROM mesto_grupa mg WHERE mg.mesto_id = m.id AND mg.grupa_id = :g
        ))
    """), {"m": mesto_id, "g": grupa_id, "s": smestaj_id}).mappings().first()
    if not ref:
        raise HTTPException(400, "Mesto, grupa termina i smeštaj nisu povezani")
    sobe = [dict(r) for r in conn.execute(text("""
        SELECT id, broj_sobe, tip, opis, opis_dodatno FROM sobe
        WHERE veza_id_smestaj = :s ORDER BY broj_sobe, id
    """), {"s": smestaj_id}).mappings()]
    periodi = []
    for r in conn.execute(text("""
        SELECT id, datum_od, datum_do FROM period_datum
        WHERE grupa_id = :g ORDER BY datum_od, datum_do, id
    """), {"g": grupa_id}).mappings():
        nocenja = (r["datum_do"] - r["datum_od"]).days
        if nocenja <= 0:
            raise HTTPException(400, "Grupa sadrži termin bez pozitivnog broja noćenja")
        periodi.append({"id": r["id"], "datum_od": r["datum_od"].isoformat(),
                        "datum_do": r["datum_do"].isoformat(), "nocenja": nocenja})
    if not sobe or not periodi:
        raise HTTPException(400, "Smeštaj mora imati sobe, a grupa definisane termine")
    # Virtuelne sobe po dodatnim koeficijentima — novi cenovnik nema stari snimak,
    # pa su id-jevi deterministički (-1, -2…), identični preview-u i POST payload-u.
    sobe = _osvezi_sobe(conn, smestaj_id)
    return {"naziv": f'{ref["mesto_naziv"]}-{ref["smestaj_naziv"]}-{ref["grupa_naziv"]}',
            "mesto_id": mesto_id, "grupa_id": grupa_id, "smestaj_id": smestaj_id,
            "sobe": sobe, "periodi": periodi, "cene": [], "datumod": None, "datumdo": None,
            "opis": ""}


def _detail(conn, item_id, lock=False):
    r = conn.execute(text("""
        SELECT c.*, o.datumod, o.datumdo FROM cenovnici c
        JOIN cenovnik_opcije o ON o.cenovnik_id = c.id WHERE c.id = :id
    """ + (" FOR UPDATE OF c" if lock else "")), {"id": item_id}).mappings().first()
    if not r:
        raise HTTPException(404, "Cenovnik nije pronađen")
    result = dict(r)
    result["uuid"] = str(result["uuid"])
    # Osveži spisak soba prema živom stanju (dodato/obrisano u Sobe, dodatni/
    # uklonjeni koeficijenti → virtuelne sobe). Virtuelne sobe koje se i dalje
    # poklapaju zadržavaju id pa cene ostaju vezane za ispravan red; nove sobe
    # nose oznaku "nova". Cene za nestale sobe se brišu pri snimanju (PUT).
    result["sobe"] = _osvezi_sobe(conn, result["smestaj_id"], result.get("sobe"),
                                  taguj_nove=True)
    result["cene"] = [{"soba_id": x.soba_id, "period_id": x.period_id, "cena": str(x.cena)}
                      for x in conn.execute(text("""
                          SELECT soba_id, period_id, cena FROM cenovnik_cene
                          WHERE cenovnik_id = :id ORDER BY soba_id, period_id
                      """), {"id": item_id})]
    return result


def _save_values(conn, item_id, body, snapshot):
    rooms = {x["id"] for x in snapshot["sobe"]}
    periods = {x["id"] for x in snapshot["periodi"]}
    seen = set()
    for cell in body.cene:
        key = (cell.soba_id, cell.period_id)
        if cell.soba_id not in rooms or cell.period_id not in periods:
            raise HTTPException(400, "Cena ne pripada sobi/terminu ovog cenovnika")
        if key in seen:
            raise HTTPException(400, "Duplirana cena za istu sobu i termin")
        seen.add(key)
    conn.execute(text("""
        INSERT INTO cenovnik_opcije (cenovnik_id, datumod, datumdo) VALUES (:id, :od, :do)
        ON CONFLICT (cenovnik_id) DO UPDATE SET datumod = EXCLUDED.datumod, datumdo = EXCLUDED.datumdo
    """), {"id": item_id, "od": body.datumod, "do": body.datumdo})
    if body.opis is not None:
        conn.execute(text("UPDATE cenovnici SET opis = :opis WHERE id = :id"),
                     {"id": item_id, "opis": body.opis})
    conn.execute(text("DELETE FROM cenovnik_cene WHERE cenovnik_id = :id"), {"id": item_id})
    if body.cene:
        conn.execute(text("""
            INSERT INTO cenovnik_cene (cenovnik_id, soba_id, period_id, cena)
            VALUES (:id, :soba_id, :period_id, :cena)
        """), [{"id": item_id, **x.model_dump()} for x in body.cene])
    conn.execute(text("UPDATE cenovnici SET updated_at = NOW() WHERE id = :id"), {"id": item_id})


def register_cenovnici(api, engine, get_current_user):
    @api.get("/cenovnici/sablon")
    def sablon(mesto_id: int, grupa_id: int, smestaj_id: int, _: dict = Depends(get_current_user)):
        with engine.connect() as conn:
            return _sablon(conn, mesto_id, grupa_id, smestaj_id)

    @api.get("/cenovnici")
    def lista(q: str = "", _: dict = Depends(get_current_user)):
        with engine.connect() as conn:
            return [dict(r) for r in conn.execute(text("""
                SELECT c.id, c.uuid::text AS uuid, c.naziv, c.opis, c.mesto_id, c.grupa_id, c.smestaj_id,
                       o.datumod, o.datumdo FROM cenovnici c
                JOIN cenovnik_opcije o ON o.cenovnik_id = c.id
                WHERE (:q = '' OR c.naziv ILIKE :like OR c.opis ILIKE :like
                       OR c.uuid::text ILIKE :like OR c.id::text ILIKE :like)
                ORDER BY c.id DESC
            """), {"q": q.strip(), "like": f"%{q.strip()}%"}).mappings()]

    @api.get("/cenovnici/{item_id}")
    def detalj(item_id: int, _: dict = Depends(get_current_user)):
        with engine.connect() as conn:
            return _detail(conn, item_id)

    @api.post("/cenovnici", status_code=201)
    def kreiraj(body: CenovnikNovi, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            snap = _sablon(conn, body.mesto_id, body.grupa_id, body.smestaj_id)
            item_id = conn.execute(text("""
                INSERT INTO cenovnici (uuid, naziv, mesto_id, grupa_id, smestaj_id, sobe, periodi, opis)
                VALUES (:uuid, :naziv, :mesto_id, :grupa_id, :smestaj_id, CAST(:sobe AS JSONB), CAST(:periodi AS JSONB), :opis)
                RETURNING id
            """), {"uuid": str(uuid4()), "naziv": snap["naziv"], "mesto_id": body.mesto_id,
                   "grupa_id": body.grupa_id, "smestaj_id": body.smestaj_id,
                   "sobe": json.dumps(snap["sobe"]), "periodi": json.dumps(snap["periodi"]),
                   "opis": body.opis}).scalar_one()
            _save_values(conn, item_id, body, snap)
            return _detail(conn, item_id)

    @api.put("/cenovnici/{item_id}")
    def izmeni(item_id: int, body: CenovnikIzmena, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            snap = _detail(conn, item_id, lock=True)
            _save_values(conn, item_id, body, snap)
            # Osvežen snimak soba (nove sobe/virtuelne sobe dodate, obrisane/uklonjeni
            # koeficijenti nestali) upisuje se nazad u cenovnik. Cene za nestale sobe
            # je _save_values obrisao (DELETE-all + reinsert samo soba iz payload-a).
            ciste = [{k: v for k, v in s.items() if k != "nova"} for s in snap["sobe"]]
            conn.execute(text("UPDATE cenovnici SET sobe = CAST(:sobe AS JSONB) WHERE id = :id"),
                         {"id": item_id, "sobe": json.dumps(ciste)})
            return _detail(conn, item_id)

    @api.delete("/cenovnici/{item_id}")
    def obrisi(item_id: int, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            row = conn.execute(text("SELECT id FROM cenovnici WHERE id = :i"), {"i": item_id}).first()
            if not row:
                raise HTTPException(status_code=404, detail="Cenovnik nije pronađen")
            # cenovnik_cene / cenovnik_opcije / opcije_soba / popust_soba idu preko ON DELETE CASCADE
            conn.execute(text("DELETE FROM cenovnici WHERE id = :i"), {"i": item_id})
            return {"status": "obrisan", "id": item_id}

    # ── Opcije i popusti po sobi cenovnika ──────────────────────────────────

    def _proveri_sobu_u_cenovniku(conn, item_id: int, soba_id: int) -> None:
        cen = conn.execute(text("SELECT id FROM cenovnici WHERE id = :i"), {"i": item_id}).first()
        if not cen:
            raise HTTPException(status_code=404, detail="Cenovnik nije pronađen")
        sobe = conn.execute(text("SELECT sobe FROM cenovnici WHERE id = :i"), {"i": item_id}).scalar_one()
        if not any(s.get("id") == soba_id for s in (sobe or [])):
            raise HTTPException(status_code=400, detail="Soba ne pripada ovom cenovniku")

    def _bez_meta(r) -> dict:
        d = dict(r)
        for k, v in list(d.items()):
            if isinstance(v, Decimal):
                d[k] = float(v)
        return {k: v for k, v in d.items()
                if k not in ("id", "cenovnik_id", "created_at", "updated_at")}

    def _spoji_redove(redovi: list[dict]) -> dict:
        """Spoji više zapisa istog opsega: vrednost ostaje samo ako je ISTA u svim redovima,
        inače neutralna (False za boolove, None ostalo) — isto kao spojiOpcije/spojiPopust na klijentu."""
        prvi = redovi[0]
        out: dict = {}
        for k in prvi:
            vrednosti = {r[k] for r in redovi}
            if len(vrednosti) == 1:
                out[k] = next(iter(vrednosti))
            else:
                out[k] = False if isinstance(prvi[k], bool) else None
        return out

    def _sobe_ids_u_cenovniku(conn, item_id: int) -> list[int]:
        """Svi soba_id-jevi iz JSONB snimka (realni + virtuelni negativni). 404 ako cenovnik ne postoji."""
        cen = conn.execute(text("SELECT sobe FROM cenovnici WHERE id = :i"), {"i": item_id}).first()
        if not cen:
            raise HTTPException(status_code=404, detail="Cenovnik nije pronađen")
        return [int(s["id"]) for s in (cen.sobe or []) if s.get("id") is not None]

    def _periodi_ids_u_cenovniku(conn, item_id: int) -> list[int]:
        """Svi period_id-jevi iz JSONB snimka perioda cenovnika. 404 ako cenovnik ne postoji."""
        cen = conn.execute(text("SELECT periodi FROM cenovnici WHERE id = :i"), {"i": item_id}).first()
        if not cen:
            raise HTTPException(status_code=404, detail="Cenovnik nije pronađen")
        return [int(p["id"]) for p in (cen.periodi or []) if p.get("id") is not None]

    def _upsert_opcije(conn, item_id: int, soba_id: int, body: OpcijeSobaIn,
                       period_id: int = 0) -> None:
        conn.execute(text("""
            INSERT INTO opcije_soba (cenovnik_id, soba_id, period_id, blokirano, istaknuto,
                blokirano_subagenci, blokirano_sajt, prevoz, tip_aranzmana, tip_cene,
                popust_sopstveni_prevoz)
            VALUES (:c, :s, :p, :blokirano, :istaknuto, :bsub, :bsite, :prevoz, :ta, :tc, :psp)
            ON CONFLICT (cenovnik_id, soba_id, period_id) DO UPDATE SET
                blokirano = EXCLUDED.blokirano, istaknuto = EXCLUDED.istaknuto,
                blokirano_subagenci = EXCLUDED.blokirano_subagenci,
                blokirano_sajt = EXCLUDED.blokirano_sajt, prevoz = EXCLUDED.prevoz,
                tip_aranzmana = EXCLUDED.tip_aranzmana, tip_cene = EXCLUDED.tip_cene,
                popust_sopstveni_prevoz = EXCLUDED.popust_sopstveni_prevoz,
                updated_at = NOW()
        """), {"c": item_id, "s": soba_id, "p": period_id,
               "blokirano": body.blokirano, "istaknuto": body.istaknuto,
               "bsub": body.blokirano_subagenci, "bsite": body.blokirano_sajt,
               "prevoz": body.prevoz, "ta": body.tip_aranzmana, "tc": body.tip_cene,
               "psp": body.popust_sopstveni_prevoz})

    def _upsert_popust(conn, item_id: int, soba_id: int, body: PopustSobaIn,
                       period_id: int = 0, redni: int = 1) -> None:
        conn.execute(text("""
            INSERT INTO popust_soba (cenovnik_id, soba_id, period_id, redni, umanjenje_vrsta, umanjenje,
                tip_popusta, tip_placanja, vazi_od, vazi_do, tip_aranzmana, tip_cene,
                popust_sopstveni_prevoz)
            VALUES (:c, :s, :p, :r, :vrsta, :umanjenje, :tp, :tpl, :od, :do, :ta, :tc, :psp)
            ON CONFLICT (cenovnik_id, soba_id, period_id, redni) DO UPDATE SET
                umanjenje_vrsta = EXCLUDED.umanjenje_vrsta, umanjenje = EXCLUDED.umanjenje,
                tip_popusta = EXCLUDED.tip_popusta, tip_placanja = EXCLUDED.tip_placanja,
                vazi_od = EXCLUDED.vazi_od, vazi_do = EXCLUDED.vazi_do,
                tip_aranzmana = EXCLUDED.tip_aranzmana, tip_cene = EXCLUDED.tip_cene,
                popust_sopstveni_prevoz = EXCLUDED.popust_sopstveni_prevoz,
                updated_at = NOW()
        """), {"c": item_id, "s": soba_id, "p": period_id, "r": redni,
               "vrsta": body.umanjenje_vrsta,
               "umanjenje": body.umanjenje, "tp": body.tip_popusta,
               "tpl": body.tip_placanja, "od": body.vazi_od, "do": body.vazi_do,
               "ta": body.tip_aranzmana, "tc": body.tip_cene,
               "psp": body.popust_sopstveni_prevoz})

    def _upsert_popusti(conn, item_id: int, soba_id: int, popusti: list[PopustSobaIn],
                        period_id: int = 0) -> None:
        """Upis skupa popusta za (soba, termin): svaki popust = zaseban red, redni = pozicija."""
        for i, body in enumerate(popusti, start=1):
            _upsert_popust(conn, item_id, soba_id, body, period_id, redni=i)

    def _popusti_iz_redova(redovi) -> list[dict]:
        """Redovi istog opsega (više soba/termina) → lista popusta po rednom broju.
        Po svakom rednom broju: vrednost ostaje samo ako je ista u svim redovima (spojiPopust)."""
        po_rednom: dict[int, list[dict]] = {}
        for r in redovi:
            po_rednom.setdefault(int(r["redni"]), []).append(_bez_meta(r))
        out = []
        for redni in sorted(po_rednom):
            spojeno = _spoji_redove(po_rednom[redni])
            out.append({"redni": redni, **{k: v for k, v in spojeno.items() if k != "redni"}})
        return out

    def _proveri_period_u_cenovniku(conn, item_id: int, period_id: int) -> None:
        """400 ako period_id nije u JSONB snimku perioda cenovnika (404 ako cenovnik ne postoji)."""
        r = conn.execute(text("SELECT periodi FROM cenovnici WHERE id = :i"), {"i": item_id}).first()
        if not r:
            raise HTTPException(status_code=404, detail="Cenovnik nije pronađen")
        if not any(p.get("id") == period_id for p in (r.periodi or [])):
            raise HTTPException(status_code=400, detail="Period ne pripada ovom cenovniku")

    @api.get("/cenovnici/{item_id}/opcije-soba/{soba_id}")
    def opcije_soba_get(item_id: int, soba_id: int, _: dict = Depends(get_current_user)):
        with engine.connect() as conn:
            _proveri_sobu_u_cenovniku(conn, item_id, soba_id)
            redovi = conn.execute(text("""
                SELECT blokirano, istaknuto, blokirano_subagenci, blokirano_sajt,
                       prevoz, tip_aranzmana, tip_cene, popust_sopstveni_prevoz
                FROM opcije_soba WHERE cenovnik_id = :c AND soba_id = :s
            """), {"c": item_id, "s": soba_id}).mappings().all()
            if not redovi:
                return {"postoji": False, "soba_id": soba_id, "blokirano": False, "istaknuto": False,
                        "blokirano_subagenci": False, "blokirano_sajt": False, "prevoz": None,
                        "tip_aranzmana": None, "tip_cene": None, "popust_sopstveni_prevoz": None}
            return {"postoji": True, "soba_id": soba_id,
                    **_spoji_redove([_bez_meta(r) for r in redovi])}

    @api.put("/cenovnici/{item_id}/opcije-soba/{soba_id}")
    def opcije_soba_put(item_id: int, soba_id: int, body: OpcijeSobaIn,
                        _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            _proveri_sobu_u_cenovniku(conn, item_id, soba_id)
            # opseg ovog endpointa = soba za SVE termine: eksplicitno po polju (soba × period)
            pids = _periodi_ids_u_cenovniku(conn, item_id)
            conn.execute(text("DELETE FROM opcije_soba WHERE cenovnik_id = :c AND soba_id = :s"),
                         {"c": item_id, "s": soba_id})
            for p in pids:
                _upsert_opcije(conn, item_id, soba_id, body, p)
            redovi = conn.execute(text("""
                SELECT blokirano, istaknuto, blokirano_subagenci, blokirano_sajt,
                       prevoz, tip_aranzmana, tip_cene, popust_sopstveni_prevoz
                FROM opcije_soba WHERE cenovnik_id = :c AND soba_id = :s
            """), {"c": item_id, "s": soba_id}).mappings().all()
            return {"postoji": True, "soba_id": soba_id,
                    **_spoji_redove([_bez_meta(r) for r in redovi])}

    @api.delete("/cenovnici/{item_id}/opcije-soba/{soba_id}")
    def opcije_soba_delete(item_id: int, soba_id: int, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            _proveri_sobu_u_cenovniku(conn, item_id, soba_id)
            conn.execute(text("DELETE FROM opcije_soba WHERE cenovnik_id = :c AND soba_id = :s"),
                         {"c": item_id, "s": soba_id})
            return {"status": "obrisano", "soba_id": soba_id}

    @api.get("/cenovnici/{item_id}/popust-soba/{soba_id}")
    def popust_soba_get(item_id: int, soba_id: int, _: dict = Depends(get_current_user)):
        with engine.connect() as conn:
            _proveri_sobu_u_cenovniku(conn, item_id, soba_id)
            redovi = conn.execute(text("""
                SELECT redni, umanjenje_vrsta, umanjenje, tip_popusta, tip_placanja, vazi_od, vazi_do,
                       tip_aranzmana, tip_cene, popust_sopstveni_prevoz
                FROM popust_soba WHERE cenovnik_id = :c AND soba_id = :s
            """), {"c": item_id, "s": soba_id}).mappings().all()
            return {"postoji": bool(redovi), "soba_id": soba_id,
                    "popusti": _popusti_iz_redova(redovi)}

    @api.put("/cenovnici/{item_id}/popust-soba/{soba_id}")
    def popust_soba_put(item_id: int, soba_id: int, body: PopustiIn,
                        _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            _proveri_sobu_u_cenovniku(conn, item_id, soba_id)
            # opseg ovog endpointa = soba za SVE termine: eksplicitno po polju (soba × period)
            pids = _periodi_ids_u_cenovniku(conn, item_id)
            conn.execute(text("DELETE FROM popust_soba WHERE cenovnik_id = :c AND soba_id = :s"),
                         {"c": item_id, "s": soba_id})
            for p in pids:
                _upsert_popusti(conn, item_id, soba_id, body.popusti, p)
            redovi = conn.execute(text("""
                SELECT redni, umanjenje_vrsta, umanjenje, tip_popusta, tip_placanja, vazi_od, vazi_do,
                       tip_aranzmana, tip_cene, popust_sopstveni_prevoz
                FROM popust_soba WHERE cenovnik_id = :c AND soba_id = :s
            """), {"c": item_id, "s": soba_id}).mappings().all()
            return {"postoji": bool(redovi), "soba_id": soba_id,
                    "popusti": _popusti_iz_redova(redovi)}

    @api.delete("/cenovnici/{item_id}/popust-soba/{soba_id}")
    def popust_soba_delete(item_id: int, soba_id: int, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            _proveri_sobu_u_cenovniku(conn, item_id, soba_id)
            conn.execute(text("DELETE FROM popust_soba WHERE cenovnik_id = :c AND soba_id = :s"),
                         {"c": item_id, "s": soba_id})
            return {"status": "obrisano", "soba_id": soba_id}

    # ── Masovne opcije / popusti (na SVE sobe cenovnika — realne i virtuelne) ──
    # Snimanje je EKSPLICITNO po polju: za SVAKU sobu × SVAKI termin cenovnika se upisuje
    # po jedan zapis (bez zbirnih period_id = 0 redova).

    @api.get("/cenovnici/{item_id}/opcije-soba-sve")
    def opcije_sve_get(item_id: int, _: dict = Depends(get_current_user)):
        with engine.connect() as conn:
            ids = _sobe_ids_u_cenovniku(conn, item_id)
            redovi = conn.execute(text("""
                SELECT soba_id, period_id, blokirano, istaknuto, blokirano_subagenci, blokirano_sajt,
                       prevoz, tip_aranzmana, tip_cene, popust_sopstveni_prevoz
                FROM opcije_soba WHERE cenovnik_id = :c
            """), {"c": item_id}).mappings().all()
            red_u_snimku = {s: i for i, s in enumerate(ids)}
            zapisi = [{"soba_id": r["soba_id"], **_bez_meta(r)} for r in sorted(
                (r for r in redovi if r["soba_id"] in red_u_snimku),
                key=lambda r: (red_u_snimku[r["soba_id"]], r["period_id"]))]
            return {"sobe": ids, "postoji": bool(zapisi), "zapisi": zapisi}

    @api.put("/cenovnici/{item_id}/opcije-soba-sve")
    def opcije_sve_put(item_id: int, body: OpcijeSobaIn, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            ids = _sobe_ids_u_cenovniku(conn, item_id)
            pids = _periodi_ids_u_cenovniku(conn, item_id)
            # opseg = ceo cenovnik (svaka soba × svaki termin): briše sve i upisuje eksplicitno po polju
            conn.execute(text("DELETE FROM opcije_soba WHERE cenovnik_id = :c"), {"c": item_id})
            for s in ids:
                for p in pids:
                    _upsert_opcije(conn, item_id, s, body, p)
            return {"status": "sacuvano", "broj_soba": len(ids),
                    "broj_zapisa": len(ids) * len(pids), "soba_id": ids}

    @api.delete("/cenovnici/{item_id}/opcije-soba-sve")
    def opcije_sve_delete(item_id: int, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            _sobe_ids_u_cenovniku(conn, item_id)  # 404 za nepoznat cenovnik
            r = conn.execute(text("DELETE FROM opcije_soba WHERE cenovnik_id = :c"),
                             {"c": item_id})
            return {"status": "obrisano", "broj": r.rowcount}

    @api.get("/cenovnici/{item_id}/popust-soba-sve")
    def popust_sve_get(item_id: int, _: dict = Depends(get_current_user)):
        with engine.connect() as conn:
            ids = _sobe_ids_u_cenovniku(conn, item_id)
            redovi = conn.execute(text("""
                SELECT soba_id, period_id, redni, umanjenje_vrsta, umanjenje, tip_popusta, tip_placanja,
                       vazi_od, vazi_do, tip_aranzmana, tip_cene, popust_sopstveni_prevoz
                FROM popust_soba WHERE cenovnik_id = :c
            """), {"c": item_id}).mappings().all()
            red_u_snimku = {s: i for i, s in enumerate(ids)}
            zapisi = [{"soba_id": r["soba_id"], **_bez_meta(r)} for r in sorted(
                (r for r in redovi if r["soba_id"] in red_u_snimku),
                key=lambda r: (red_u_snimku[r["soba_id"]], r["period_id"], r["redni"]))]
            return {"sobe": ids, "postoji": bool(zapisi), "zapisi": zapisi}

    @api.put("/cenovnici/{item_id}/popust-soba-sve")
    def popust_sve_put(item_id: int, body: PopustiIn, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            ids = _sobe_ids_u_cenovniku(conn, item_id)
            pids = _periodi_ids_u_cenovniku(conn, item_id)
            # opseg = ceo cenovnik (svaka soba × svaki termin): briše sve i upisuje eksplicitno po polju
            conn.execute(text("DELETE FROM popust_soba WHERE cenovnik_id = :c"), {"c": item_id})
            for s in ids:
                for p in pids:
                    _upsert_popusti(conn, item_id, s, body.popusti, p)
            return {"status": "sacuvano", "broj_soba": len(ids),
                    "broj_zapisa": len(ids) * len(pids) * len(body.popusti), "soba_id": ids}

    @api.delete("/cenovnici/{item_id}/popust-soba-sve")
    def popust_sve_delete(item_id: int, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            _sobe_ids_u_cenovniku(conn, item_id)  # 404 za nepoznat cenovnik
            r = conn.execute(text("DELETE FROM popust_soba WHERE cenovnik_id = :c"),
                             {"c": item_id})
            return {"status": "obrisano", "broj": r.rowcount}

    # ── Blokada polja (soba × termin) — menja SAMO kolonu blokirano ──────────────
    # Blokirano=TRUE: za svako polje upisuje/menja red; ako red ne postoji, kopira ostale
    # opcije iz globalnog (period_id=0) reda ako postoji, inače defaulte.
    # Blokirano=FALSE: menja samo postojeći red; bez reda upisuje odblokirano samo ako
    # polje blokira globalni (period_id=0) red — inače nema šta da se skine.

    @api.put("/cenovnici/{item_id}/blokada")
    def blokada_put(item_id: int, body: BlokadaIn, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            sobe_ids = set(_sobe_ids_u_cenovniku(conn, item_id))
            pids = set(_periodi_ids_u_cenovniku(conn, item_id))
            if not body.sobe or not body.periodi:
                raise HTTPException(status_code=400, detail="Izaberite bar jednu sobu i jedan termin")
            if not set(body.sobe) <= sobe_ids:
                raise HTTPException(status_code=400, detail="Soba ne pripada ovom cenovniku")
            if not set(body.periodi) <= pids:
                raise HTTPException(status_code=400, detail="Period ne pripada ovom cenovniku")
            for s in sorted(set(body.sobe)):
                for p in sorted(set(body.periodi)):
                    _postavi_blokadu(conn, item_id, s, p, body.blokirano)
            return {"status": "sacuvano", "blokirano": body.blokirano,
                    "broj_polja": len(set(body.sobe)) * len(set(body.periodi))}

    def _postavi_blokadu(conn, item_id: int, soba_id: int, period_id: int, blokirano: bool) -> None:
        params = {"c": item_id, "s": soba_id, "p": period_id}
        if blokirano:
            conn.execute(text("""
                INSERT INTO opcije_soba (cenovnik_id, soba_id, period_id, blokirano, istaknuto,
                    blokirano_subagenci, blokirano_sajt, prevoz, tip_aranzmana, tip_cene,
                    popust_sopstveni_prevoz)
                SELECT CAST(:c AS INTEGER), CAST(:s AS INTEGER), CAST(:p AS INTEGER), TRUE,
                    COALESCE(g.istaknuto, FALSE), COALESCE(g.blokirano_subagenci, FALSE),
                    COALESCE(g.blokirano_sajt, FALSE), g.prevoz, g.tip_aranzmana, g.tip_cene,
                    g.popust_sopstveni_prevoz
                FROM (SELECT 1) AS x
                LEFT JOIN opcije_soba g
                    ON g.cenovnik_id = CAST(:c AS INTEGER) AND g.soba_id = CAST(:s AS INTEGER)
                    AND g.period_id = 0
                ON CONFLICT (cenovnik_id, soba_id, period_id)
                DO UPDATE SET blokirano = TRUE, updated_at = NOW()
            """), params)
            return
        upd = conn.execute(text("""
            UPDATE opcije_soba SET blokirano = FALSE, updated_at = NOW()
            WHERE cenovnik_id = :c AND soba_id = :s AND period_id = :p
        """), params)
        if upd.rowcount == 0:
            # globalna (period_id=0) blokada se mora poništiti eksplicitnim redom za polje
            conn.execute(text("""
                INSERT INTO opcije_soba (cenovnik_id, soba_id, period_id, blokirano, istaknuto,
                    blokirano_subagenci, blokirano_sajt, prevoz, tip_aranzmana, tip_cene,
                    popust_sopstveni_prevoz)
                SELECT CAST(:c AS INTEGER), CAST(:s AS INTEGER), CAST(:p AS INTEGER), FALSE,
                    g.istaknuto, g.blokirano_subagenci, g.blokirano_sajt, g.prevoz,
                    g.tip_aranzmana, g.tip_cene, g.popust_sopstveni_prevoz
                FROM opcije_soba g
                WHERE g.cenovnik_id = :c AND g.soba_id = :s AND g.period_id = 0 AND g.blokirano = TRUE
                ON CONFLICT (cenovnik_id, soba_id, period_id) DO NOTHING
            """), params)

    # ── Opcije / popusti za JEDAN termin (sve sobe) — O·P dugme u koloni matrice ──
    # period_id = konkretan period iz snimka; za SVAKU sobu × taj termin upisuje se po jedan
    # eksplicitan zapis. Sa ?soba_id= = mod po POLJU (jedna soba × jedan termin).

    @api.get("/cenovnici/{item_id}/opcije-soba-termin/{period_id}")
    def opcije_termin_get(item_id: int, period_id: int, soba_id: int | None = None,
                          _: dict = Depends(get_current_user)):
        with engine.connect() as conn:
            ids = _sobe_ids_u_cenovniku(conn, item_id)
            _proveri_period_u_cenovniku(conn, item_id, period_id)
            if soba_id is not None:
                _proveri_sobu_u_cenovniku(conn, item_id, soba_id)
                ids = [soba_id]
            redovi = conn.execute(text("""
                SELECT soba_id, blokirano, istaknuto, blokirano_subagenci, blokirano_sajt,
                       prevoz, tip_aranzmana, tip_cene, popust_sopstveni_prevoz
                FROM opcije_soba WHERE cenovnik_id = :c AND period_id = :p
            """), {"c": item_id, "p": period_id}).mappings().all()
            po_sobi = {r["soba_id"]: _bez_meta(r) for r in redovi}
            zapisi = [{"soba_id": s, **po_sobi[s]} for s in ids if s in po_sobi]
            return {"sobe": ids, "period_id": period_id, "postoji": bool(zapisi), "zapisi": zapisi}

    @api.put("/cenovnici/{item_id}/opcije-soba-termin/{period_id}")
    def opcije_termin_put(item_id: int, period_id: int, body: OpcijeSobaIn,
                          soba_id: int | None = None, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            ids = _sobe_ids_u_cenovniku(conn, item_id)
            _proveri_period_u_cenovniku(conn, item_id, period_id)
            if soba_id is not None:
                # mod po POLJU (soba × termin) — puni replace samo tog polja
                _proveri_sobu_u_cenovniku(conn, item_id, soba_id)
                conn.execute(text("""DELETE FROM opcije_soba
                    WHERE cenovnik_id = :c AND period_id = :p AND soba_id = :s"""),
                    {"c": item_id, "p": period_id, "s": soba_id})
                _upsert_opcije(conn, item_id, soba_id, body, period_id)
                return {"status": "sacuvano", "broj_soba": 1, "period_id": period_id,
                        "soba_id": [soba_id]}
            conn.execute(text("DELETE FROM opcije_soba WHERE cenovnik_id = :c AND period_id = :p"),
                         {"c": item_id, "p": period_id})
            for s in ids:
                _upsert_opcije(conn, item_id, s, body, period_id)
            return {"status": "sacuvano", "broj_soba": len(ids), "period_id": period_id}

    @api.delete("/cenovnici/{item_id}/opcije-soba-termin/{period_id}")
    def opcije_termin_delete(item_id: int, period_id: int, soba_id: int | None = None,
                             _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            _sobe_ids_u_cenovniku(conn, item_id)  # 404 za nepoznat cenovnik
            _proveri_period_u_cenovniku(conn, item_id, period_id)
            if soba_id is not None:
                _proveri_sobu_u_cenovniku(conn, item_id, soba_id)
                r = conn.execute(text("""DELETE FROM opcije_soba
                    WHERE cenovnik_id = :c AND period_id = :p AND soba_id = :s"""),
                    {"c": item_id, "p": period_id, "s": soba_id})
                return {"status": "obrisano", "broj": r.rowcount}
            r = conn.execute(
                text("DELETE FROM opcije_soba WHERE cenovnik_id = :c AND period_id = :p"),
                {"c": item_id, "p": period_id})
            return {"status": "obrisano", "broj": r.rowcount}

    @api.get("/cenovnici/{item_id}/popust-soba-termin/{period_id}")
    def popust_termin_get(item_id: int, period_id: int, soba_id: int | None = None,
                          _: dict = Depends(get_current_user)):
        with engine.connect() as conn:
            ids = _sobe_ids_u_cenovniku(conn, item_id)
            _proveri_period_u_cenovniku(conn, item_id, period_id)
            if soba_id is not None:
                _proveri_sobu_u_cenovniku(conn, item_id, soba_id)
                ids = [soba_id]
            redovi = conn.execute(text("""
                SELECT soba_id, redni, umanjenje_vrsta, umanjenje, tip_popusta, tip_placanja,
                       vazi_od, vazi_do, tip_aranzmana, tip_cene, popust_sopstveni_prevoz
                FROM popust_soba WHERE cenovnik_id = :c AND period_id = :p
            """), {"c": item_id, "p": period_id}).mappings().all()
            zapisi = [{"soba_id": r["soba_id"], **_bez_meta(r)} for r in sorted(
                (r for r in redovi if r["soba_id"] in ids),
                key=lambda r: (ids.index(r["soba_id"]), r["redni"]))]
            return {"sobe": ids, "period_id": period_id, "postoji": bool(zapisi), "zapisi": zapisi}

    @api.put("/cenovnici/{item_id}/popust-soba-termin/{period_id}")
    def popust_termin_put(item_id: int, period_id: int, body: PopustiIn,
                          soba_id: int | None = None, _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            ids = _sobe_ids_u_cenovniku(conn, item_id)
            _proveri_period_u_cenovniku(conn, item_id, period_id)
            if soba_id is not None:
                _proveri_sobu_u_cenovniku(conn, item_id, soba_id)
                conn.execute(text("""DELETE FROM popust_soba
                    WHERE cenovnik_id = :c AND period_id = :p AND soba_id = :s"""),
                    {"c": item_id, "p": period_id, "s": soba_id})
                _upsert_popusti(conn, item_id, soba_id, body.popusti, period_id)
                return {"status": "sacuvano", "broj_soba": 1, "period_id": period_id,
                        "soba_id": [soba_id]}
            conn.execute(text("DELETE FROM popust_soba WHERE cenovnik_id = :c AND period_id = :p"),
                         {"c": item_id, "p": period_id})
            for s in ids:
                _upsert_popusti(conn, item_id, s, body.popusti, period_id)
            return {"status": "sacuvano", "broj_soba": len(ids), "period_id": period_id}

    @api.delete("/cenovnici/{item_id}/popust-soba-termin/{period_id}")
    def popust_termin_delete(item_id: int, period_id: int, soba_id: int | None = None,
                             _: dict = Depends(get_current_user)):
        with engine.begin() as conn:
            _sobe_ids_u_cenovniku(conn, item_id)  # 404 za nepoznat cenovnik
            _proveri_period_u_cenovniku(conn, item_id, period_id)
            if soba_id is not None:
                _proveri_sobu_u_cenovniku(conn, item_id, soba_id)
                r = conn.execute(text("""DELETE FROM popust_soba
                    WHERE cenovnik_id = :c AND period_id = :p AND soba_id = :s"""),
                    {"c": item_id, "p": period_id, "s": soba_id})
                return {"status": "obrisano", "broj": r.rowcount}
            r = conn.execute(
                text("DELETE FROM popust_soba WHERE cenovnik_id = :c AND period_id = :p"),
                {"c": item_id, "p": period_id})
            return {"status": "obrisano", "broj": r.rowcount}

    @api.get("/cenovnici/{item_id}/opcije-celije")
    def opcije_celije_get(item_id: int, _: dict = Depends(get_current_user)):
        """Polja (soba × termin) koja imaju definisane opcije ILI popuste — za obeležavanje
        ćelija u matrici. Globalni zapisi (period_id = 0, važe za sve termine) šire se na
        SVE periode snimka; termin/polje zapisi idu direktno."""
        with engine.connect() as conn:
            cen = conn.execute(text("SELECT sobe, periodi FROM cenovnici WHERE id = :i"),
                               {"i": item_id}).first()
            if not cen:
                raise HTTPException(status_code=404, detail="Cenovnik nije pronađen")
            soba_ids = {int(s["id"]) for s in (cen.sobe or []) if s.get("id") is not None}
            period_ids = [int(p["id"]) for p in (cen.periodi or []) if p.get("id") is not None]
            redovi = conn.execute(text("""
                SELECT soba_id, period_id, blokirano FROM opcije_soba WHERE cenovnik_id = :c
                UNION
                SELECT soba_id, period_id, FALSE AS blokirano FROM popust_soba WHERE cenovnik_id = :c
            """), {"c": item_id}).all()

            def _razvij(izabrani):
                parovi: set[tuple[int, int]] = set()
                for soba_id, period_id in izabrani:
                    if soba_id not in soba_ids:  # zapisi za sobe van snimka se ne obeležavaju
                        continue
                    if period_id == 0:
                        parovi.update((soba_id, p) for p in period_ids)
                    elif period_id in period_ids:
                        parovi.add((soba_id, period_id))
                return parovi

            svi = _razvij((s, p) for s, p, _ in redovi)
            # efektivno blokirano po polju: eksplicitni red (opcije_soba) ima prednost, inače
            # važi globalni (period_id=0) red te sobe
            blok_redovi = conn.execute(text("""
                SELECT soba_id, period_id, blokirano FROM opcije_soba WHERE cenovnik_id = :c
            """), {"c": item_id}).all()
            globalno = {s for s, p, b in blok_redovi if p == 0 and b}
            eksplicitno = {(s, p): b for s, p, b in blok_redovi if p != 0}
            blok = {(s, p) for s in soba_ids for p in period_ids
                    if eksplicitno.get((s, p), s in globalno)}
            return {
                "celije": [{"soba_id": s, "period_id": p} for s, p in sorted(svi)],
                "blokirane": [{"soba_id": s, "period_id": p} for s, p in sorted(blok)],
            }
