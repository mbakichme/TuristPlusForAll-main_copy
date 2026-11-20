"""Avansni računi: tabela `avansni_racuni`, numeracija, UBL XML i slanje na SEF (eFaktura).

Tipovi su preslikani iz MySQL šeme na PostgreSQL:
int(11) -> INTEGER, tinyint(4) -> SMALLINT, decimal(10,2) -> NUMERIC(10,2).

tipdokumenta: 1-avans, 2-KO, 3-KZ, 4-Uplata, 5-konacni
status_lokalno: 0-nije poslato, 1-poslato
status_efaktura: 0-nije poslato, 1-poslato, 2-prihvacena, 3-odbijeno

Broj avansa (faktura) je `redni/YY`, gde je YY poslednje dve cifre godine `datumod`
aranžmana, a redni broj kreće od 1 za svaku godinu.
"""
import base64
import json
import xml.etree.ElementTree as ET
from datetime import date
from xml.sax.saxutils import escape

import httpx
from sqlalchemy import text

SEF_URL = "https://efaktura.mfin.gov.rs/api/publicApi/sales-invoice/ubl"
SEF_XML_URL = "https://efaktura.mfin.gov.rs/api/publicApi/sales-invoice/xml"
SEF_TIMEOUT_SEC = 30
TIP_AVANS = 1
TIP_FAKTURE_AVANS = "386"
TIP_POREZA = "SS"
OPIS_TIPA_POREZA = "PDV-RS-35-7"
STATUS_NIJE_POSLATO = "0"
STATUS_POSLATO = "1"
STATUS_ODBIJENO = "3"
GRESKA_FIRMA_NIJE_NA_SEF = "ReceiverCompanyNotFound"
GRESKA_DUPLIKAT = "UBLUploadRequestIdDuplicate"
FIRMA_REG_NIJE_NA_SEF = 2


def init_avansni_racuni(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS avansni_racuni (
                id SERIAL PRIMARY KEY,
                tipdokumenta INTEGER NOT NULL,
                profakt VARCHAR(256) NOT NULL,
                ugovor VARCHAR(20) NOT NULL,
                nosilac VARCHAR(512) NOT NULL,
                destinacija VARCHAR(512) NOT NULL,
                period VARCHAR(512) NOT NULL,
                zaduzenje NUMERIC(10,2) NOT NULL,
                saldo NUMERIC(10,2) NOT NULL,
                pib VARCHAR(256) NOT NULL,
                uplaceno NUMERIC(10,2) NOT NULL,
                datumf DATE NOT NULL,
                datump DATE NOT NULL,
                faktura VARCHAR(20) NOT NULL,
                odobrenje VARCHAR(256) NOT NULL,
                subagent VARCHAR(512) NOT NULL,
                adresa VARCHAR(512) NOT NULL,
                mesto VARCHAR(512) NOT NULL,
                status_lokalno INTEGER NOT NULL DEFAULT 0,
                status_efaktura VARCHAR(32) NOT NULL DEFAULT '0',
                id_portal INTEGER NOT NULL,
                "invoiceId" INTEGER NOT NULL,
                "purchaseInvoiceId" INTEGER NOT NULL,
                "salesInvoiceId" INTEGER NOT NULL,
                firma_registracija INTEGER NOT NULL,
                saputnik VARCHAR(512) NOT NULL,
                napomena VARCHAR(1024) NOT NULL,
                jbkjs INTEGER NOT NULL,
                racun VARCHAR(512) NOT NULL,
                crf SMALLINT NOT NULL
            )
        """))
        # broj avansa ne sme da se ponovi
        conn.execute(text("DROP INDEX IF EXISTS avansni_racuni_faktura_idx"))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS avansni_racuni_faktura_uq ON avansni_racuni (faktura)"
        ))


AVANS_KOLONE = (
    "id", "tipdokumenta", "profakt", "ugovor", "nosilac", "destinacija", "period", "zaduzenje",
    "saldo", "pib", "uplaceno", "datumf", "datump", "faktura", "odobrenje", "subagent", "adresa",
    "mesto", "status_lokalno", "status_efaktura", "id_portal", "invoiceId", "purchaseInvoiceId",
    "salesInvoiceId", "firma_registracija", "saputnik", "napomena", "jbkjs", "racun", "crf",
)
STATUSI_POSLATO_NA_SEF = ("1", "2")


def register_avansni_pregled(api, engine, get_current_user):
    """GET /avansni-racuni — pregled izdatih avansa; q pretražuje sve kolone, na_sef = poslato na SEF."""
    from datetime import date as _date
    from decimal import Decimal

    from fastapi import Depends, HTTPException

    @api.get("/avansni-racuni")
    def list_avansni_racuni(q: str = "", _: dict = Depends(get_current_user)):
        q = q.strip()
        bind = {}
        where = ""
        if q:
            # svaka kolona kao tekst; datumi u DD.MM.YYYY da se pretražuju kao na ekranu
            dela = []
            for k in AVANS_KOLONE:
                if k in ("datumf", "datump"):
                    dela.append(f"COALESCE(TO_CHAR({k}, 'DD.MM.YYYY'), '')")
                else:
                    dela.append(f"COALESCE(CAST(\"{k}\" AS TEXT), '')")
            where = "WHERE (" + " || ' ' || ".join(dela) + ") ILIKE :q"
            bind["q"] = f"%{q}%"
        cols = ", ".join(f'"{k}"' for k in AVANS_KOLONE)
        with engine.connect() as conn:
            rows = conn.execute(text(f"SELECT {cols} FROM avansni_racuni {where} ORDER BY id DESC"), bind).mappings().all()
        out = []
        poslato = 0
        for r in rows:
            d = dict(r)
            for k in ("datumf", "datump"):
                d[k] = d[k].isoformat() if isinstance(d[k], _date) else d[k]
            for k in ("zaduzenje", "saldo", "uplaceno"):
                if isinstance(d[k], Decimal):
                    d[k] = float(d[k])
            d["na_sef"] = str(d["status_efaktura"]).strip() in STATUSI_POSLATO_NA_SEF
            poslato += d["na_sef"]
            out.append(d)
        return {"rows": out, "total": len(out), "poslato_na_sef": poslato}

    @api.get("/avansni-racuni/{avans_id}/pdf")
    def avans_pdf(avans_id: int, _: dict = Depends(get_current_user)):
        """Štampa avansa: PDF koji SEF vraća za InvoiceId reda. Samo za redove poslate na SEF."""
        from fastapi.responses import Response

        from avansni_racuni_api import preuzmi_pdf_sef

        with engine.connect() as conn:
            red = conn.execute(text(
                "SELECT faktura, status_efaktura, \"salesInvoiceId\" FROM avansni_racuni WHERE id = :id"
            ), {"id": avans_id}).mappings().first()
            ag = conn.execute(text("SELECT api_kljuc_efakture FROM agencija ORDER BY id LIMIT 1")).mappings().first()
        if not red:
            raise HTTPException(status_code=404, detail="Avansni račun nije pronađen")
        if str(red["status_efaktura"]).strip() not in STATUSI_POSLATO_NA_SEF or not red["salesInvoiceId"]:
            raise HTTPException(status_code=422, detail="Račun nije poslat na SEF")
        if not ag or not (ag["api_kljuc_efakture"] or "").strip():
            raise HTTPException(status_code=422, detail="API ključ eFakture nije podešen (Osnovni podaci)")
        try:
            pdf = preuzmi_pdf_sef(ag["api_kljuc_efakture"].strip(), str(red["salesInvoiceId"]))
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(status_code=502, detail=f"Štampa nije uspela: {exc}")
        return Response(content=pdf, media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="avans-{red["faktura"].replace("/", "-")}.pdf"'})


def napomena_uplate(uplata_kljuc: int) -> str:
    """Veza avansnog računa sa uplatom (tabela nema posebnu kolonu)."""
    return f"Uplata {uplata_kljuc}"


def zakljucaj_avanse(conn) -> None:
    """Serijalizuje dodelu brojeva avansa i upis reda (važi do kraja transakcije)."""
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('avansni_racuni'))"))


def avans_vec_poslat(conn, uplata_kljuc: int) -> bool:
    return conn.execute(text(
        "SELECT 1 FROM avansni_racuni WHERE napomena = :n AND status_efaktura = :s LIMIT 1"
    ), {"n": napomena_uplate(uplata_kljuc), "s": STATUS_POSLATO}).first() is not None


def nepostlat_avans(conn, uplata_kljuc: int):
    """Red avansa za uplatu koji još nije uspešno poslat (ponovni pokušaj koristi isti broj)."""
    return conn.execute(text(
        "SELECT id, faktura FROM avansni_racuni WHERE napomena = :n AND status_efaktura = :s "
        "ORDER BY id DESC LIMIT 1"
    ), {"n": napomena_uplate(uplata_kljuc), "s": STATUS_NIJE_POSLATO}).first()


def sledeci_broj_avansa(conn, godina: int) -> str:
    """Sledeći broj `n/YY` za godinu. Poziva se unutar transakcije zaključane sa zakljucaj_avanse."""
    yy = f"{godina % 100:02d}"
    max_n = conn.execute(text(
        "SELECT COALESCE(MAX(CAST(split_part(faktura, '/', 1) AS INTEGER)), 0) FROM avansni_racuni "
        "WHERE split_part(faktura, '/', 2) = :yy AND split_part(faktura, '/', 1) ~ '^[0-9]+$'"
    ), {"yy": yy}).scalar_one()
    return f"{max_n + 1}/{yy}"


def upisi_avans(conn, p: dict) -> int:
    """Upisuje pripremljen avans (status 0 = nije poslato) i vraća id reda."""
    return conn.execute(text("""
        INSERT INTO avansni_racuni (
            tipdokumenta, profakt, ugovor, nosilac, destinacija, period, zaduzenje, saldo,
            pib, uplaceno, datumf, datump, faktura, odobrenje, subagent, adresa, mesto,
            status_lokalno, status_efaktura, id_portal, "invoiceId", "purchaseInvoiceId",
            "salesInvoiceId", firma_registracija, saputnik, napomena, jbkjs, racun, crf
        ) VALUES (
            :tipdokumenta, :profakt, :ugovor, :nosilac, :destinacija, :period, :zaduzenje, :saldo,
            :pib, :uplaceno, :datumf, :datump, :faktura, :odobrenje, :subagent, :adresa, :mesto,
            0, :status, 0, 0, 0, 0, :firma_registracija, :saputnik, :napomena, :jbkjs, :racun, 0
        ) RETURNING id
    """), {**p, "tipdokumenta": TIP_AVANS, "status": STATUS_NIJE_POSLATO}).scalar_one()


def build_ubl_avans_xml(*, faktura: str, danas: date, datum: date, ugovor_racun: str,
                        pib: str, poslovno_ime: str, mb: str, adresa: str, mesto: str, email: str,
                        pib_kupca: str, poslovno_ime_kupca: str, mb_kupca: str, adresa_kupca: str,
                        mesto_kupca: str, jbkjs: str, racun: str, iznos: str, artikal: str) -> str:
    """UBL 2.1 XML avansne fakture (isti raspored elemenata kao PHP sendXmlInvoiceAvans)."""
    jbkjs_blok = (
        "<cac:PartyIdentification>"
        f"<cbc:ID>JBKJS:{escape(jbkjs)}</cbc:ID>"
        "</cac:PartyIdentification>"
    ) if jbkjs.strip() else ""
    return (
        '<Invoice xmlns:cec="urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2" '
        'xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2" '
        'xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
        'xmlns:sbt="http://mfin.gov.rs/srbdt/srbdtext" '
        'xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2">'
        "<cbc:CustomizationID>urn:cen.eu:en16931:2017#compliant#urn:mfin.gov.rs:srbdt:2021</cbc:CustomizationID>"
        f"<cbc:ID>{escape(faktura)}</cbc:ID>"
        f"<cbc:IssueDate>{danas.isoformat()}</cbc:IssueDate>"
        f"<cbc:DueDate>{datum.isoformat()}</cbc:DueDate>"
        f"<cbc:InvoiceTypeCode>{TIP_FAKTURE_AVANS}</cbc:InvoiceTypeCode>"
        "<cbc:DocumentCurrencyCode>RSD</cbc:DocumentCurrencyCode>"
        "<cac:InvoicePeriod></cac:InvoicePeriod>"
        "<cac:ContractDocumentReference>"
        f"<cbc:ID>{escape(ugovor_racun)}</cbc:ID>"
        "</cac:ContractDocumentReference>"
        "<cac:AccountingSupplierParty><cac:Party>"
        f'<cbc:EndpointID schemeID="9948">{escape(pib)}</cbc:EndpointID>'
        f"<cac:PartyName><cbc:Name>{escape(poslovno_ime)}</cbc:Name></cac:PartyName>"
        "<cac:PostalAddress>"
        f"<cbc:CityName>{escape(mesto)} {escape(adresa)}</cbc:CityName>"
        "<cac:Country><cbc:IdentificationCode>RS</cbc:IdentificationCode></cac:Country>"
        "</cac:PostalAddress>"
        "<cac:PartyTaxScheme>"
        f"<cbc:CompanyID>RS{escape(pib)}</cbc:CompanyID>"
        "<cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme>"
        "</cac:PartyTaxScheme>"
        "<cac:PartyLegalEntity>"
        f"<cbc:RegistrationName>{escape(poslovno_ime)}</cbc:RegistrationName>"
        f"<cbc:CompanyID>{escape(mb)}</cbc:CompanyID>"
        "</cac:PartyLegalEntity>"
        f"<cac:Contact><cbc:ElectronicMail>{escape(email)}</cbc:ElectronicMail></cac:Contact>"
        "</cac:Party></cac:AccountingSupplierParty>"
        "<cac:AccountingCustomerParty><cac:Party>"
        f'<cbc:EndpointID schemeID="9948">{escape(pib_kupca)}</cbc:EndpointID>'
        f"{jbkjs_blok}"
        f"<cac:PartyName><cbc:Name>{escape(poslovno_ime_kupca)}</cbc:Name></cac:PartyName>"
        "<cac:PostalAddress>"
        f"<cbc:StreetName>{escape(adresa_kupca)}</cbc:StreetName>"
        f"<cbc:CityName>{escape(mesto_kupca)}</cbc:CityName>"
        "<cac:Country><cbc:IdentificationCode>RS</cbc:IdentificationCode></cac:Country>"
        "</cac:PostalAddress>"
        "<cac:PartyTaxScheme>"
        f"<cbc:CompanyID>RS{escape(pib_kupca)}</cbc:CompanyID>"
        "<cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme>"
        "</cac:PartyTaxScheme>"
        "<cac:PartyLegalEntity>"
        f"<cbc:RegistrationName>{escape(poslovno_ime_kupca)}</cbc:RegistrationName>"
        f"<cbc:CompanyID>{escape(mb_kupca)}</cbc:CompanyID>"
        "</cac:PartyLegalEntity>"
        "<cac:Contact><cbc:ElectronicMail></cbc:ElectronicMail></cac:Contact>"
        "</cac:Party></cac:AccountingCustomerParty>"
        "<cac:PaymentMeans><cbc:PaymentMeansCode>30</cbc:PaymentMeansCode>"
        f"<cac:PayeeFinancialAccount><cbc:ID>{escape(racun)}</cbc:ID></cac:PayeeFinancialAccount>"
        "</cac:PaymentMeans>"
        "<cac:TaxTotal>"
        '<cbc:TaxAmount currencyID="RSD">0</cbc:TaxAmount>'
        "<cac:TaxSubtotal>"
        f'<cbc:TaxableAmount currencyID="RSD">{iznos}</cbc:TaxableAmount>'
        '<cbc:TaxAmount currencyID="RSD">0</cbc:TaxAmount>'
        "<cac:TaxCategory>"
        f"<cbc:ID>{TIP_POREZA}</cbc:ID>"
        "<cbc:Percent>0</cbc:Percent>"
        f"<cbc:TaxExemptionReasonCode>{OPIS_TIPA_POREZA}</cbc:TaxExemptionReasonCode>"
        "<cbc:TaxExemptionReason></cbc:TaxExemptionReason>"
        "<cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme>"
        "</cac:TaxCategory>"
        "</cac:TaxSubtotal>"
        "</cac:TaxTotal>"
        "<cac:LegalMonetaryTotal>"
        f'<cbc:LineExtensionAmount currencyID="RSD">{iznos}</cbc:LineExtensionAmount>'
        f'<cbc:TaxExclusiveAmount currencyID="RSD">{iznos}</cbc:TaxExclusiveAmount>'
        f'<cbc:TaxInclusiveAmount currencyID="RSD">{iznos}</cbc:TaxInclusiveAmount>'
        '<cbc:AllowanceTotalAmount currencyID="RSD">0</cbc:AllowanceTotalAmount>'
        '<cbc:PrepaidAmount currencyID="RSD">0</cbc:PrepaidAmount>'
        f'<cbc:PayableAmount currencyID="RSD">{iznos}</cbc:PayableAmount>'
        "</cac:LegalMonetaryTotal>"
        "<cac:InvoiceLine>"
        "<cbc:ID>1</cbc:ID>"
        '<cbc:InvoicedQuantity unitCode="H87">1</cbc:InvoicedQuantity>'
        f'<cbc:LineExtensionAmount currencyID="RSD">{iznos}</cbc:LineExtensionAmount>'
        "<cac:Item>"
        f"<cbc:Name>{escape(artikal)}</cbc:Name>"
        "<cac:SellersItemIdentification><cbc:ID>1</cbc:ID></cac:SellersItemIdentification>"
        "<cac:ClassifiedTaxCategory>"
        f"<cbc:ID>{TIP_POREZA}</cbc:ID>"
        "<cbc:Percent>0</cbc:Percent>"
        "<cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme>"
        "</cac:ClassifiedTaxCategory>"
        "</cac:Item>"
        f'<cac:Price><cbc:PriceAmount currencyID="RSD">{iznos}</cbc:PriceAmount></cac:Price>'
        "</cac:InvoiceLine>"
        "</Invoice>"
    )


def posalji_na_sef(api_kljuc: str, faktura: str, xml: str) -> tuple[int, str]:
    """POST UBL fakture na SEF. Vraća (HTTP status, tekst odgovora)."""
    with httpx.Client(timeout=SEF_TIMEOUT_SEC, follow_redirects=True) as klijent:
        odgovor = klijent.post(
            SEF_URL,
            params={"requestId": faktura, "sendToCir": "No"},
            content=xml.encode("utf-8"),
            headers={
                "Accept": "application/xml",
                "Content-Type": "application/xml",
                "ApiKey": api_kljuc,
                "cache-control": "no-cache",
            },
        )
    return odgovor.status_code, odgovor.text


def parsiraj_odgovor_sef(tekst: str) -> dict:
    """Uspeh: XML sa SalesInvoiceId/PurchaseInvoiceId/InvoiceId. Greška: JSON sa ErrorCode."""
    try:
        j = json.loads(tekst)
        if isinstance(j, dict) and j.get("ErrorCode"):
            return {"greska": str(j["ErrorCode"]), "ids": None}
    except ValueError:
        pass
    try:
        root = ET.fromstring(tekst)
    except ET.ParseError:
        return {"greska": "NeispravanOdgovor", "ids": None}
    ids = {}
    for naziv in ("SalesInvoiceId", "PurchaseInvoiceId", "InvoiceId"):
        # SEF odgovor ima default namespace (SspDTO) — poređenje po lokalnom imenu elementa
        ids[naziv] = next((el.text or "" for el in root.iter() if el.tag.rsplit("}", 1)[-1] == naziv), "").strip()
    if not ids["SalesInvoiceId"]:
        return {"greska": "NeispravanOdgovor", "ids": None}
    return {"greska": None, "ids": ids}


def preuzmi_pdf_sef(api_kljuc: str, invoice_id: str) -> bytes:
    """GET XML fakture sa SEF-a, pa iz DocumentEnvelope/DocumentHeader/DocumentPdf dekodira PDF (base64)."""
    with httpx.Client(timeout=SEF_TIMEOUT_SEC, follow_redirects=True) as klijent:
        odgovor = klijent.get(
            SEF_XML_URL,
            params={"invoiceId": invoice_id},
            headers={"Accept": "application/xml", "ApiKey": api_kljuc, "cache-control": "no-cache"},
        )
    if odgovor.status_code != 200:
        try:
            greska = odgovor.json()
            opis = f"{greska.get('ErrorCode', '')}: {greska.get('Message', '')}".strip(": ")
        except ValueError:
            opis = odgovor.text[:200].strip()
        raise ValueError(f"SEF je vratio HTTP {odgovor.status_code}" + (f" ({opis})" if opis else ""))
    try:
        root = ET.fromstring(odgovor.text)
    except ET.ParseError as exc:
        raise ValueError("SEF je vratio neispravan XML") from exc
    pdf_tekst = next((el.text for el in root.iter() if el.tag.rsplit("}", 1)[-1] == "DocumentPdf"), None)
    if not pdf_tekst:
        raise ValueError("PDF nije pronađen u odgovoru SEF-a")
    return base64.b64decode("".join(pdf_tekst.split()))


def _celobrojno(vrednost: str) -> int:
    return int(vrednost) if (vrednost or "").strip().lstrip("-").isdigit() else 0


def zapisi_uspeh(engine, avans_id: int, ids: dict) -> None:
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE avansni_racuni SET id_portal = :s, \"salesInvoiceId\" = :s, "
            "\"purchaseInvoiceId\" = :p, \"invoiceId\" = :i, status_lokalno = 1, status_efaktura = :st "
            "WHERE id = :id"
        ), {"s": _celobrojno(ids["SalesInvoiceId"]), "p": _celobrojno(ids["PurchaseInvoiceId"]),
            "i": _celobrojno(ids["InvoiceId"]), "st": STATUS_POSLATO, "id": avans_id})


def zapisi_odbijanje(engine, avans_id: int, greska: str) -> None:
    """Red ostaje neposlat (status 0) i zadržava broj; za nepostojeću firmu se beleži firma_registracija = 2."""
    if greska != GRESKA_FIRMA_NIJE_NA_SEF:
        return
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE avansni_racuni SET firma_registracija = :f WHERE id = :id"
        ), {"f": FIRMA_REG_NIJE_NA_SEF, "id": avans_id})
