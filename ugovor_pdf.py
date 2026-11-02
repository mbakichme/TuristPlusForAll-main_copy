"""Offline A4 ugovor/prijava; accepts raw contract data without persistence access.

Izgled: dot-matrix obrazac "PRIJAVA/UGOVOR" (monospace, crno na belom).
Zaglavlje agencije (logo, naziv, banke, licenca) je isto kao i na predračunu.
"""
import base64
import io
import os
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Flowable, Frame, KeepTogether, PageTemplate,
    Paragraph, Spacer, Table, TableStyle,
)
import qrcode

from predracun_pdf import FONT_DIR_CANDIDATES, _ensure_fonts, _logo_path, fmt_num

INK = colors.HexColor("#111111")
MUTED = colors.HexColor("#444444")
RULE = colors.HexColor("#777777")
SANS = "Inter"
SANS_B = "InterBold"
_SANS_READY = False
LEGAL_CLAUSES = (
    "Organizator će jedino za uplaćeni aranžman u celosti izdati svoj vaučer 7 dana pre korišćenja usluge, koji je jedini važeći dokument za korišćenje usluge i koji se mora od strane putnika uručiti ovlašćenom agentu ili predstavniku agencije na destinaciji i pruži usluge isključivo licima navedenim u vaučeru.",
    "Svojim potpisom potvrđujem da su mi neposredno uručeni cenovnik/program putovanja i Opšti uslovi putovanja organizatora i da mi je ponuđeno putno i zdravstveno osiguranje.",
    "Izjavljujem da ću, ukoliko agencija ne bude mogla da realizuje moje čekove i administrativnu zabranu, izvršiti svoju obavezu na drugi način.",
    "Dozvoljeni prtljag je jedan kofer po osobi maksimalne tezine 23kg (dimenzija visina 76cm, sirina 50cm, dubina 30cm). Doplata iznosi 5€/kg ukoliko kofer prelazi dozvoljenu kilazu i dimenzije i to samo ukolko postoji prostor u autobusu. Ukoliko ne postoji prostor u autobusu bez obzira na doplatu isti nece biti primljen. Suncobrani, lezaljke, rucni frizideri, oprema za pecanje, maslinovo ulje, dodatne torbe nisu dozvoljene.",
    "Svojim potpisom potvrdjujem da mi je urucena garancija putovanja.",
)
QR_WARNING = "NBS IPS QR nije dostupan: proverite račun primaoca (18 cifara), naziv agencije i pozitivan iznos u RSD."


def _ensure_sans():
    """Inter (moderan sans-serif, ima č ć š ž đ). Fallback: Helvetica."""
    global _SANS_READY, SANS, SANS_B
    if _SANS_READY:
        return
    for base in FONT_DIR_CANDIDATES:
        reg = os.path.join(base, "Inter-Regular.ttf")
        bold = os.path.join(base, "Inter-Bold.ttf")
        if os.path.exists(reg) and os.path.exists(bold):
            pdfmetrics.registerFont(TTFont(SANS, reg))
            pdfmetrics.registerFont(TTFont(SANS_B, bold))
            break
    else:
        SANS, SANS_B = "Helvetica", "Helvetica-Bold"
    _SANS_READY = True


def _decimal(value):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _num(value):
    d = _decimal(value)
    return d if d is not None else Decimal(0)


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
    account = None
    for key in ("racun", "tekuci_racun1", "tekuci_racun2", "tekuci_racun3", "tekuci_racun4"):
        candidate = str(agencija.get(key) or "").strip()
        if re.fullmatch(r"[0-9]{3}-[0-9]{1,13}-[0-9]{2}", candidate):
            bank, number, control = candidate.split("-")
            candidate = bank + number.zfill(13) + control
        if re.fullmatch(r"[0-9]{18}", candidate):
            account = candidate
            break
    if account is None:
        return None
    # The selected account must be supplied by the agency; never invent one.
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


def _to_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
            try:
                return datetime.strptime(value.strip()[:10], fmt).date()
            except ValueError:
                continue
    return None


def _nights(od, do):
    a, b = _to_date(od), _to_date(do)
    return (b - a).days if a and b else None


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
    _ensure_sans()
    raw = _raw(ugovor)
    calc, eur, rsd, kurs = _amounts(ugovor)
    width, height = A4
    margin = 30
    body_width = width - 2 * margin
    styles = {
        "mono": ParagraphStyle("mono", fontName=SANS, fontSize=8.5, leading=11, textColor=INK),
        "monoB": ParagraphStyle("monoB", fontName=SANS_B, fontSize=8.5, leading=11, textColor=INK),
        "right": ParagraphStyle("right", fontName=SANS, fontSize=8.5, leading=11, textColor=INK, alignment=TA_RIGHT),
        "rightB": ParagraphStyle("rightB", fontName=SANS_B, fontSize=9, leading=11, textColor=INK, alignment=TA_RIGHT),
        "small": ParagraphStyle("small", fontName=SANS, fontSize=7.5, leading=9.5, textColor=MUTED),
        "legal": ParagraphStyle("legal", fontName=SANS, fontSize=6.8, leading=8.4, textColor=INK, spaceAfter=1.5),
        "section": ParagraphStyle("section", fontName=SANS_B, fontSize=9, leading=11, textColor=INK, spaceBefore=6, spaceAfter=2, keepWithNext=True),
        "title": ParagraphStyle("title", fontName=SANS_B, fontSize=13, leading=16, textColor=INK, spaceBefore=4, spaceAfter=6),
    }

    def p(text, style="mono"):
        return Paragraph(escape(str(text)).replace("\n", "<br/>"), styles[style])

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
    banke = agencija.get("banke") or [
        " ".join(filter(None, (str(agencija[f"tekuci_racun{i}"]), f"({agencija[f'banka{i}']})" if agencija.get(f"banka{i}") else "")))
        for i in range(1, 5) if agencija.get(f"tekuci_racun{i}")
    ] or [" ".join(filter(None, (str(agencija.get("racun") or ""), str(agencija.get("banka") or ""))))]
    for line in (
        ", ".join(x for x in (address, place) if x),
        ", ".join(str(agencija[k]) for k in ("telefon1", "email1") if agencija.get(k)),
        " | ".join(f"{label} {agencija[k]}" for k, label in (("pib", "PIB"), ("mb", "MB")) if agencija.get(k)),
        *banke,
        f"Licenca: {agencija['licenca']}" if agencija.get("licenca") else "",
    ):
        if line:
            header_lines.append(p(line, "small"))
    header_width = body_width - 105 if logo else body_width
    header_height = max(65, sum(line.wrap(header_width, height)[1] + 3 for line in header_lines))

    def page_header(c, doc):
        c.saveState()
        if doc.page > 1:
            page_footer(c, doc)
            c.restoreState()
            return
        y = height - 25
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
        page_footer(c, doc)
        c.restoreState()

    def page_footer(c, doc):
        c.setFont(SANS, 7.5)
        c.setFillColor(MUTED)
        c.drawString(margin, 20, f"Ugovor/prijava {_text(raw.get('kljuc'))}")
        c.drawRightString(width - margin, 20, f"Strana {doc.page}")

    def frames(top):
        return [Frame(margin, 38, body_width, top - 38, id="body",
                      leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)]

    def grid(rows, widths, header=False, last_line=False):
        """Tabela bez okvira u stilu obrasca; opciono podvučen red zaglavlja."""
        table = Table(rows, colWidths=[body_width * w for w in widths], repeatRows=1 if header else 0)
        style = [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
            ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]
        if header:
            style.append(("LINEBELOW", (0, 0), (-1, 0), .6, INK))
        if last_line:
            style.append(("LINEABOVE", (0, -1), (-1, -1), .6, INK))
        table.setStyle(TableStyle(style))
        return table

    doc_out = io.BytesIO()
    doc = BaseDocTemplate(doc_out, pagesize=A4, leftMargin=margin, rightMargin=margin,
                          bottomMargin=38,
                          title=f"Ugovor/prijava {_text(raw.get('kljuc'))}", author=str(name))
    doc.addPageTemplates([
        PageTemplate(id="first", frames=frames(height - header_height - 43),
                     onPage=page_header, autoNextPageTemplate="later"),
        PageTemplate(id="later", frames=frames(height - margin), onPage=page_header),
    ])

    story = [grid([[p(f"Datum izdavanja: {_text(ugovor.get('datum_izdavanja') or raw.get('danas'))}", "small"),
                    p(f"KEPTP: {_text(raw.get('keptp'))}", "right")]], [0.7, 0.3]),
             p(f"PRIJAVA/UGOVOR Br.: {_text(raw.get('kljuc'))}", "title")]

    # --- putovanje -------------------------------------------------------------
    nights = _nights(raw.get("datumod"), raw.get("datumdo"))
    story.append(grid([
        [p("Datum:"), p(f"{_text(raw.get('datumod'))} – {_text(raw.get('datumdo'))}"), p("Trajanje:"), p(f"{nights} noćenja" if nights is not None else "—", "monoB")],
        [p("Destinacija:"), p(_text(raw.get("destinacija"))), p("Mesto:"), p(_text(raw.get("mesto")))],
        [p("Hotel:"), p(_text(raw.get("naziv")), "monoB"), p("Soba:"), p(f"#{_text(raw.get('soba'))}  {_text(raw.get('apartman'))}  {_text(raw.get('opis'))}")],
    ], [0.13, 0.37, 0.12, 0.38]))

    # --- putnici (nosilac + saputnici) -------------------------------------------
    story.append(p("PUTNICI", "section"))
    rows = [[p("Prezime i ime", "monoB"), p("Rođen", "monoB"), p("Uzrast", "monoB"),
             p("Pasoš", "monoB"), p("Prevoz OW", "monoB"), p("Prevoz RT", "monoB"), p("Viza", "monoB")],
            [p(_text(raw.get("putnik")), "monoB"), p(_text(raw.get("rodjen"))), p(_text(raw.get("uzrast"))),
             p(_text(raw.get("pasos"))), p(_flag(raw.get("prevozow"))), p(_flag(raw.get("prevozrt"))),
             p(_flag(raw.get("viza")))]]
    companions = ugovor.get("putnici_detalji") or []
    for person in companions:
        rows.append([p(_text(person.get("saputnik") or person.get("putnik")), "monoB"), p(_text(person.get("rodjen"))),
                     p(_text(person.get("uzrast"))), p(_text(person.get("pasos"))),
                     p(_flag(person.get("prevozow"))), p(_flag(person.get("prevozrt"))), p(_flag(person.get("viza")))])
    story.append(grid(rows, [0.30, 0.13, 0.10, 0.18, 0.10, 0.10, 0.09], header=True))
    if not companions:
        story.append(p("Nema prijavljenih saputnika.", "small"))
    for person in companions:
        extra = " | ".join(f"{label}: {_text(person.get(key))}" for label, key in (
            ("Adresa", "adresa"), ("Telefon", "telefon"), ("E-mail", "email")) if person.get(key))
        if extra:
            story.append(p(f"{_text(person.get('saputnik') or person.get('putnik'))} — {extra}", "small"))
        if person.get("ulazak") or person.get("smer"):
            story.append(p(f"Ulazak: {_text(person.get('ulazak'))} | Smer: {_text(person.get('smer'))}", "small"))

    # --- stavke obračuna (Htl/Prv | Opis | Kol | Cena/EUR | Iznos/EUR) -----------
    story.append(p("OBRAČUN", "section"))
    kol_a, cen_a = _num(raw.get("kolaranz")), _num(raw.get("cenaaranz"))
    kol_c, cen_c = _num(raw.get("kolchd")), _num(raw.get("cenachd"))
    kol_ow, cen_ow = _num(raw.get("kolow")), _num(raw.get("cenaow"))
    kol_rt, cen_rt = _num(raw.get("kolrt")), _num(raw.get("cenart"))
    kol_vi, cen_vi = _num(raw.get("kolviza")), _num(raw.get("cenaviza"))
    popust = _num(calc.get("popust"))
    dodatno = _num(raw.get("cenadod"))
    osiguranje = _num(raw.get("osiguranje1"))
    stavke = [[p("Htl/Prv", "monoB"), p("Opis", "monoB"), p("Kol", "rightB"),
               p("Cena/EUR", "rightB"), p("Iznos/EUR", "rightB")]]

    def stavka(htl, opis, kol, cena, iznos):
        stavke.append([p(htl), p(opis), p(f"{kol:g}" if kol else ""), p(fmt_num(cena) if cena else "", "right"),
                       p(fmt_num(iznos), "right")])

    smestaj, prevoz, viza = _num(calc.get("smestaj")), _num(calc.get("prevoz")), _num(calc.get("viza"))
    if smestaj or kol_a:
        if kol_c or cen_c:
            stavka("HOTEL", "Smeštaj (odrasli i deca)", None, None, smestaj)
        else:
            stavka("HOTEL", "Smeštaj", kol_a or None, cen_a or None, smestaj)
    if prevoz:
        ow, rt = bool(kol_ow or cen_ow), bool(kol_rt or cen_rt)
        if ow and not rt:
            stavka("PREVOZ", "Prevoz — polazak", kol_ow or None, cen_ow or None, prevoz)
        elif rt and not ow:
            stavka("PREVOZ", "Prevoz — povratak", kol_rt or None, cen_rt or None, prevoz)
        else:
            stavka("PREVOZ", "Prevoz", None, None, prevoz)
    if viza:
        stavka("VIZA", "Viza", kol_vi or None, cen_vi or None, viza)
    if popust:
        stavka("POPUST", "Umanjenje", None, None, -popust)
    if dodatno:
        stavka("DODATNO", "Dodatne usluge / ostalo", None, None, dodatno)
    if osiguranje:
        stavka("OSIG.", "Zdravstveno osiguranje", None, None, osiguranje)
    story.append(grid(stavke, [0.13, 0.41, 0.09, 0.16, 0.21], header=True))

    # --- rekapitulacija ----------------------------------------------------------
    story.append(Spacer(1, 8))
    story.append(grid([
        [p("REKAPITULACIJA OBRAČUNA:", "monoB"), p("CENA ARANŽMANA", "monoB"),
         p(f"{fmt_num(eur)} EUR", "rightB")],
        ["", p("ZA UPLATU", "monoB"),
         p(f"{fmt_num(rsd)} RSD" if rsd is not None else "Nije dostupan", "rightB")],
    ], [0.42, 0.30, 0.28]))
    story.append(p(f"U tome: naplata organizatoru {fmt_num(_num(calc.get('naplata')))} EUR | "
                   f"provizija agencije {fmt_num(_num(calc.get('provizija')))} EUR", "small"))
    story.append(p(f"Srednji kurs NBS (1 EUR / RSD): {f'{kurs:.2f}' if kurs else 'Nije dostupan'} | "
                   f"Datum kursa: {_text(ugovor.get('kurs_datum'))}. "
                   "Plaćanje u dinarskoj protivvrednosti po srednjem kursu NBS na dan uplate.", "small"))

    extras = ugovor.get("dodatne") or []
    if extras:
        story.append(p("DODATNE USLUGE / OSTALO (informativno, ne dodaje se ponovo ukupnoj vrednosti)", "section"))
        for index, item in enumerate(extras, 1):
            story.append(p(f"{index}. {_text(item.get('usluga'))} — {fmt_num(item.get('eur'))} EUR / {fmt_num(item.get('din'))} RSD"))

    # --- prevoz i polazak ----------------------------------------------------------
    story.append(p("PREVOZ I POLAZAK", "section"))
    story.append(grid([
        [p("Vrsta prevoza:"), p(raw.get("vrsta_prevoza") or ("SOPSTVENI PREVOZ" if not any(_flag(raw.get(k)) == "DA" for k in ("prevozow", "prevozrt")) else "Aranžman sa prevozom")),
         p("Ulazak / mesto polaska:"), p(_text(raw.get("ulazak")))],
        [p("Smer:"), p(_text(raw.get("smer"))), p("Polazak dana:"), p(_text(raw.get("polazak") or raw.get("datumod")))],
        [p("Usluga osiguranja:"), p(_text(raw.get("osiguranje"))), p("Usluga / obrok:"), p(_text(raw.get("obrok") or raw.get("usluga")))],
        [p("Početak usluge:"), p(_text(raw.get("datumod"))), p("Završetak usluge:"), p(_text(raw.get("datumdo")))],
    ], [0.22, 0.28, 0.26, 0.24]))
    story.append(p(f"Napomena: {_text(raw.get('napomena'))}"))
    story.append(p("Molimo Vas da vreme polaska proverite dan pre putovanja.", "small"))

    # --- podnosilac ------------------------------------------------------------------
    # --- QR za plaćanje (u istom redu sa podnosiocem) -----------------------------------
    payload = build_ugovor_ips_qr(ugovor, agencija)
    qr_cell = [p(QR_WARNING, "small")]
    if payload:
        code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,
                             box_size=10, border=4)
        code.add_data(payload.encode("utf-8"))
        code.make(fit=True)
        buffer = io.BytesIO()
        code.make_image(fill_color="black", back_color="white").save(buffer, format="PNG")
        buffer.seek(0)
        qr = ImageReader(buffer)

        class QRImage(Flowable):
            def __init__(self):
                super().__init__()
                self.width = self.height = 104

            def draw(self):
                self.canv.drawImage(qr, 0, 0, self.width, self.height)

        image = QRImage()
        image.hAlign = "LEFT"
        qr_cell = [image, p("Skenirajte QR kod za plaćanje ugovora.", "small")]

    story.append(Spacer(1, 6))
    story.append(KeepTogether([grid([[
        [p("Podnosilac prijave:", "monoB"),
         p("\n".join(x for x in (
             _text(raw.get("putnik")),
             _text(raw.get("adresa")) if raw.get("adresa") else "",
             f"Tel.: {_text(raw.get('telefon'))}" if raw.get("telefon") else "",
             f"E-mail: {_text(raw.get('email'))}" if raw.get("email") else "",
         ) if x), "monoB"),
         Spacer(1, 8),
         p("Potpis stranke: ________________________"),
         Spacer(1, 6),
         p("M. P.          Potpis službenika: ______________"),
        ],
        qr_cell,
    ]], [0.60, 0.40])]))

    # --- izjave ----------------------------------------------------------------------
    story.append(Spacer(1, 6))
    story.append(p("IZJAVE I USLOVI PUTOVANJA", "section"))
    for clause in LEGAL_CLAUSES:
        story.append(p(clause, "legal"))
    story.append(p(f"Mesto i datum: {agencija.get('mesto') or '—'}, {_text(ugovor.get('datum_izdavanja') or raw.get('danas'))}      Ugovor je punovažan bez pecata.", "small"))
    doc.build(story)
    return doc_out.getvalue()
