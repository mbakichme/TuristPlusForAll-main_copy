"""Offline A4 ugovor/prijava; accepts raw contract data without persistence access."""
import base64
import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    Flowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from predracun_pdf import _ensure_fonts, _logo_path, build_qr_image, fmt_num

NAVY = colors.HexColor("#172C46")
MUTED = colors.HexColor("#526174")
PALE = colors.HexColor("#EEF2F6")
LEGAL_CLAUSES = (
    "Organizator će jedino za uplaćeni aranžman u celosti izdati svoj vaučer 7 dana pre korišćenja usluge, koji je jedini važeći dokument za korišćenje usluge i koji se mora od strane putnika uručiti ovlašćenom agentu ili predstavniku agencije na destinaciji i pruži usluge isključivo licima navedenim u vaučeru.",
    "Svojim potpisom potvrđujem da su mi neposredno uručeni cenovnik/program putovanja i Opšti uslovi putovanja organizatora i da mi je ponuđeno putno i zdravstveno osiguranje.",
    "Izjavljujem da ću, ukoliko agencija ne bude mogla da realizuje moje čekove i administrativnu zabranu, izvršiti svoju obavezu na drugi način.",
    "Dozvoljeni prtljag je jedan kofer po osobi maksimalne tezine 23kg (dimenzija visina 76cm, sirina 50cm, dubina 30cm). Doplata iznosi 5€/kg ukoliko kofer prelazi dozvoljenu kilazu i dimenzije i to samo ukolko postoji prostor u autobusu. Ukoliko ne postoji prostor u autobusu bez obzira na doplatu isti nece biti primljen. Suncobrani, lezaljke, rucni frizideri, oprema za pecanje, maslinovo ulje, dodatne torbe nisu dozvoljene.",
    "Svojim potpisom potvrdjujem da mi je urucena garancija putovanja.",
)
QR_WARNING = "NBS IPS QR nije dostupan: proverite račun primaoca (18 cifara), naziv agencije i pozitivan iznos u RSD."


def _decimal(value):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _raw(ugovor):
    return ugovor.get("aranzman") or ugovor


def _amounts(ugovor):
    calc = ugovor.get("obracun") or ugovor
    eur = _decimal(ugovor.get("ukupno_eur"))
    if eur is None:
        eur = (_decimal(calc.get("naplata")) or Decimal(0)) + (_decimal(calc.get("provizija")) or Decimal(0))
    kurs = _decimal(ugovor.get("kurs"))
    rsd = _decimal(ugovor.get("ukupno_rsd"))
    if ugovor.get("ukupno_rsd") is None and kurs is not None and kurs > 0:
        rsd = (eur * kurs).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return calc, eur, rsd, kurs


def _qr_text(value, limit):
    return re.sub(r"\s+", " ", str(value or "").replace("|", " ")).strip()[:limit]


def build_ugovor_ips_qr(ugovor: dict, agencija: dict) -> str | None:
    """Return a complete NBS IPS payment payload, never a partial/invalid QR."""
    account = str(agencija.get("racun") or "").strip()
    if re.fullmatch(r"[0-9]{3}-[0-9]{1,13}-[0-9]{2}", account):
        bank, number, control = account.split("-")
        account = bank + number.zfill(13) + control
    if not re.fullmatch(r"[0-9]{18}", account):
        return None
    recipient = _qr_text(agencija.get("naziv") or agencija.get("poslovno_ime"), 70)
    _, _, amount, _ = _amounts(ugovor)
    if not recipient or amount is None or amount <= 0:
        return None
    amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if amount <= 0:
        return None
    raw = _raw(ugovor)
    number = _qr_text(raw.get("kljuc") or ugovor.get("kljuc") or raw.get("broj"), 200)
    reference = re.sub(r"[^0-9-]", "-", number)[:23]
    holder = _qr_text(raw.get("putnik"), 70)
    parts = ["K:PR", "V:01", "C:1", f"R:{account}", f"N:{recipient}",
             f"I:RSD{amount:.2f}".replace(".", ","), "SF:221",
             f"S:{_qr_text('Ugovor br ' + number, 35)}"]
    if reference:
        parts.append(f"RO:00{reference}")
    if holder:
        parts.append(f"P:{holder}")
    return "|".join(parts)


def _text(value):
    if value is None or value == "":
        return "—"
    if isinstance(value, (date, datetime)):
        return value.strftime("%d.%m.%Y")
    value = str(value)
    if re.match(r"^\d{4}-\d{2}-\d{2}(?:$|[ T])", value):
        try:
            return date.fromisoformat(value[:10]).strftime("%d.%m.%Y")
        except ValueError:
            pass
    return value


def _flag(value):
    if value in (None, ""):
        return "—"
    if str(value).lower() in ("0", "false", "ne"):
        return "NE"
    if str(value).lower() in ("1", "true", "da", "-1"):
        return "DA"
    return _text(value)


def generate_ugovor_pdf(ugovor: dict, agencija: dict) -> bytes:
    """Render supplied raw data and historical-rate totals, without network calls."""
    _ensure_fonts()
    raw = _raw(ugovor)
    calc, eur, rsd, kurs = _amounts(ugovor)
    width, height = A4
    margin = 40
    body_width = width - 2 * margin
    styles = {
        "body": ParagraphStyle("body", fontName="Lib", fontSize=9, leading=13, textColor=NAVY, spaceAfter=5),
        "small": ParagraphStyle("small", fontName="Lib", fontSize=8, leading=11, textColor=MUTED, spaceAfter=4),
        "section": ParagraphStyle("section", fontName="LibB", fontSize=10, leading=14, textColor=NAVY, spaceBefore=11, spaceAfter=7, keepWithNext=True),
        "title": ParagraphStyle("title", fontName="LibB", fontSize=19, leading=24, textColor=NAVY, spaceAfter=8),
    }

    def p(text, style="body"):
        return Paragraph(escape(str(text)).replace("\n", "<br/>"), styles[style])

    def field(label, value):
        return p(f"{label}: {_text(value)}")

    logo = None
    try:
        data_url = agencija.get("logo_data_url")
        source = io.BytesIO(base64.b64decode(data_url.split(",", 1)[1], validate=True)) if data_url else _logo_path()
        if source:
            logo = ImageReader(source)
            logo.getSize()
    except (ValueError, TypeError, IndexError, OSError):
        logo = None
    name = agencija.get("naziv") or agencija.get("poslovno_ime") or "Agencija"
    address = " ".join(str(agencija.get(k) or "") for k in ("ulica", "broj")).strip()
    place = " ".join(str(agencija.get(k) or "") for k in ("post_broj", "mesto")).strip()
    header_lines = [p(name, "section")]
    for line in (
        ", ".join(x for x in (address, place) if x),
        ", ".join(str(agencija[k]) for k in ("telefon1", "email1") if agencija.get(k)),
        " | ".join(f"{label} {agencija[k]}" for k, label in (("pib", "PIB"), ("mb", "MB")) if agencija.get(k)),
        " ".join(str(agencija.get(k) or "") for k in ("racun", "banka")).strip(),
    ):
        if line:
            header_lines.append(p(line, "small"))
    header_width = body_width - 105 if logo else body_width
    header_height = max(65, sum(line.wrap(header_width, height)[1] + 3 for line in header_lines))

    def page_header(c, doc):
        c.saveState()
        y = height - 30
        for line in header_lines:
            _, h = line.wrap(header_width, height)
            line.drawOn(c, margin, y - h)
            y -= h + 3
        if logo:
            iw, ih = logo.getSize()
            scale = min(95 / iw, 55 / ih)
            c.drawImage(logo, width - margin - iw * scale, height - 35 - ih * scale,
                        iw * scale, ih * scale, mask="auto")
        c.setStrokeColor(colors.HexColor("#CBD4DF"))
        c.line(margin, height - 35 - header_height, width - margin, height - 35 - header_height)
        c.setFont("Lib", 8)
        c.setFillColor(MUTED)
        c.drawString(margin, 24, f"Ugovor/prijava {_text(raw.get('kljuc'))}")
        c.drawRightString(width - margin, 24, f"Strana {doc.page}")
        c.restoreState()

    out = io.BytesIO()
    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=margin, rightMargin=margin,
                            topMargin=header_height + 48, bottomMargin=45,
                            title=f"Ugovor/prijava {_text(raw.get('kljuc'))}", author=str(name))
    story = [p(f"UGOVOR / PRIJAVA BROJ {_text(raw.get('kljuc'))}", "title"),
             field("Datum izdavanja", ugovor.get("datum_izdavanja") or raw.get("danas")),
             field("KEPTP", raw.get("keptp")),
             field("Organizator", raw.get("organizator")), field("Poslovnica", raw.get("poslovnica")),
             p("NOSILAC ARANŽMANA", "section")]
    for label, key in (("Prezime i ime", "putnik"), ("Datum rođenja", "rodjen"),
                       ("Pasoš", "pasos"), ("Uzrast", "uzrast"), ("Adresa", "adresa"),
                       ("Telefon", "telefon"), ("E-mail", "email")):
        story.append(field(label, raw.get(key)))
    story.append(p("SAPUTNICI", "section"))
    story.append(p("Istovremeno prijavljujem za ovo putovanje pod istim uslovima sledeća lica:"))
    companions = ugovor.get("putnici_detalji") or []
    if not companions:
        story.append(p("Nema prijavljenih saputnika."))
    for index, person in enumerate(companions, 1):
        story.append(p(f"{index}. {_text(person.get('saputnik') or person.get('putnik'))}", "section"))
        story.append(p(" | ".join(f"{label}: {_text(person.get(key))}" for label, key in (
            ("Datum rođenja", "rodjen"), ("Pasoš", "pasos"), ("Uzrast", "uzrast")))))
        for label, key in (("Adresa", "adresa"), ("Telefon", "telefon"), ("E-mail", "email")):
            if person.get(key):
                story.append(field(label, person[key]))
        story.append(p(f"Prevoz OW: {_flag(person.get('prevozow'))} | Prevoz RT: {_flag(person.get('prevozrt'))} | Viza: {_flag(person.get('viza'))}"))
        story.append(p(f"Ulazak: {_text(person.get('ulazak'))} | Smer: {_text(person.get('smer'))}"))
    story.append(p("PUTOVANJE I SMEŠTAJ", "section"))
    for label, value in (
        ("Destinacija", raw.get("destinacija")), ("Mesto", raw.get("mesto")),
        ("Naziv objekta", raw.get("naziv")), ("Struktura / tip sobe", raw.get("apartman")),
        ("Opis / struktura", raw.get("opis")), ("Soba", raw.get("soba")),
        ("Usluga", raw.get("obrok") or raw.get("usluga")),
        ("Početak korišćenja usluge", raw.get("datumod")),
        ("Završetak korišćenja usluge", raw.get("datumdo")),
        ("Vrsta prevoza", raw.get("vrsta_prevoza") or ("SOPSTVENI PREVOZ" if not any(_flag(raw.get(k)) == "DA" for k in ("prevozow", "prevozrt")) else "Aranžman sa prevozom")),
        ("Prevoz OW", _flag(raw.get("prevozow"))), ("Prevoz RT", _flag(raw.get("prevozrt"))),
        ("Viza", _flag(raw.get("viza"))), ("Ulazak / mesto polaska", raw.get("ulazak")),
        ("Smer", raw.get("smer")), ("Polazak dana", raw.get("polazak") or raw.get("datumod")),
        ("Usluga osiguranja", raw.get("osiguranje")), ("Napomena", raw.get("napomena")),
    ):
        story.append(field(label, value))
    story.append(p("Molimo Vas da vreme polaska proverite dan pre putovanja.", "small"))
    story.append(p("OBRAČUN ZA NAPLATU", "section"))
    rows = [[p("Opis"), p("EUR"), p("RSD")]]
    for label, value in (("Cena smeštaja ili paketa", calc.get("smestaj")),
                         ("Cena prevoza", calc.get("prevoz")), ("Viza", calc.get("viza")),
                         ("Zdravstveno osiguranje", raw.get("osiguranje1")),
                         ("Dodatne usluge / ostalo", raw.get("cenadod")),
                         ("Popust", calc.get("popust")), ("Naplata", calc.get("naplata")),
                         ("Provizija", calc.get("provizija")), ("UKUPNO", eur)):
        numeric = _decimal(value) or Decimal(0)
        din = rsd if label == "UKUPNO" else (numeric * kurs if kurs and kurs > 0 else None)
        rows.append([p(label), p(fmt_num(numeric)), p(fmt_num(din) if din is not None else "Nije dostupan")])
    table = Table(rows, colWidths=[body_width * .56, body_width * .20, body_width * .24], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PALE), ("BACKGROUND", (0, -1), (-1, -1), PALE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LINEBELOW", (0, 0), (-1, 0), .6, NAVY),
    ]))
    story.extend([table, Spacer(1, 7), field("Srednji kurs NBS (1 EUR / RSD)", kurs),
                  field("Datum kursa", ugovor.get("kurs_datum")),
                  p("Plaćanje u dinarskoj protivvrednosti po srednjem kursu NBS na dan uplate.", "small"),
                  p("DODATNE USLUGE / OSTALO", "section"),
                  p("Informativna specifikacija; stavke se ne dodaju ponovo ukupnoj vrednosti.", "small")])
    extras = ugovor.get("dodatne") or []
    for index, item in enumerate(extras, 1):
        story.append(p(f"{index}. {_text(item.get('usluga'))} — {fmt_num(item.get('eur'))} EUR / {fmt_num(item.get('din'))} RSD"))
    if not extras:
        story.append(p("Nema dodatnih stavki."))
    story.append(p("PLAĆANJE — NBS IPS QR", "section"))
    payload = build_ugovor_ips_qr(ugovor, agencija)
    if payload:
        qr = build_qr_image(payload)
        class QRImage(Flowable):
            width = 116
            height = 116

            def draw(self):
                self.canv.drawImage(qr, 0, 0, self.width, self.height)

        image = QRImage()
        image.hAlign = "LEFT"
        story.append(KeepTogether([image, p("Skenirajte QR kod za plaćanje ugovora.", "small")]))
    else:
        story.append(p(QR_WARNING))
    story.append(p("IZJAVE I USLOVI PUTOVANJA", "section"))
    for clause in LEGAL_CLAUSES:
        story.append(KeepTogether([p(clause)]))
    story.append(KeepTogether([
        Spacer(1, 24), p("____________________________                 ____________________________"),
        p("Potpis putnika                                                     Za Agenciju"),
        Spacer(1, 12), field("Mesto i datum", f"{agencija.get('mesto') or '—'}, {_text(ugovor.get('datum_izdavanja') or raw.get('danas'))}"),
        p("Ugovor je punovažan bez pecata."),
    ]))
    doc.build(story, onFirstPage=page_header, onLaterPages=page_header)
    return out.getvalue()
