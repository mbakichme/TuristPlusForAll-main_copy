"""
Pregled uplata za ugovor — PDF po referentnom šablonu starog sistema.

Raspored (A4 portrait, crno-beli):
  - header: logo (Podešavanja → Dokumenti, tip "logo") gore levo,
    naslov "PREGLED UPLATA" centriran
  - blok PUTNIK: labela "PUTNIK:" (italic), ime (bold italic velika slova),
    adresa (italic), + "Ugovor: <broj>" (sitno)
  - tabela: DATUM | NAČIN PLAĆANJA | DIN | EUR | SUMA/EUR | SVRHA UPLATE | REFERENT | KLJUC
    (EUR = keš evro iz uplate; SUMA/EUR = din / srednji kurs NBS na dan uplate, bold;
     DATUM italic; KLJUC sa tačkom za hiljade)
  - zbirni red "U K U P N O :" — bold zbirovi DIN, EUR, SUMA/EUR
  - deblji spoljni okvir tabele, broj stranice dole desno
"""
import io
import os

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle,
)

BLACK = colors.black
WHITE = colors.white

FONT_DIR_CANDIDATES = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "fonts"),
    "/usr/share/fonts/truetype/liberation",
    "/usr/share/fonts/dejavu",
]

_FONTS_READY = False


def _ensure_fonts():
    """TTF fontovi (Liberation/DejaVu) — podržavaju č ć š ž đ; fallback Helvetica."""
    global _FONTS_READY
    if _FONTS_READY:
        return
    fonts = {
        "Lib": ("LiberationSans-Regular.ttf", "DejaVuSans.ttf"),
        "LibB": ("LiberationSans-Bold.ttf", "DejaVuSans-Bold.ttf"),
        "LibI": ("LiberationSans-Italic.ttf", "DejaVuSans-Oblique.ttf"),
        "LibBI": ("LiberationSans-BoldItalic.ttf", "DejaVuSans-BoldOblique.ttf"),
    }
    registered = set()
    for base in FONT_DIR_CANDIDATES:
        if not os.path.isdir(base):
            continue
        for name, candidates in fonts.items():
            if name in registered:
                continue
            for fname in candidates:
                path = os.path.join(base, fname)
                if os.path.exists(path):
                    pdfmetrics.registerFont(TTFont(name, path))
                    registered.add(name)
                    break
    # Produkcija može imati samo deo TTF porodice. Rezervni font se mora
    # registrovati za SVAKU nedostajuću varijantu, ne samo kada nema regularnog.
    from reportlab.pdfbase.pdfmetrics import Font
    for name, fallback in {
        "Lib": "Helvetica", "LibB": "Helvetica-Bold",
        "LibI": "Helvetica-Oblique", "LibBI": "Helvetica-BoldOblique",
    }.items():
        if name not in registered:
            pdfmetrics.registerFont(Font(name, fallback, "WinAnsiEncoding"))
    pdfmetrics.registerFontFamily("Lib", normal="Lib", bold="LibB", italic="LibI", boldItalic="LibBI")
    _FONTS_READY = True


def _fmt(v, dec=2):
    """sr-RS format broja: 70.000,00 (tačka hiljade, zarez decimale)."""
    if v is None:
        return ""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return str(v)
    s = f"{x:,.{dec}f}"
    return s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _fmt_int(v):
    """Ceo broj sa tačkom za hiljade: 31.060."""
    if v is None:
        return ""
    try:
        return f"{int(v):,}".replace(",", ".")
    except (TypeError, ValueError):
        return str(v)


def build_uplate_pdf(putnik: str | None, adresa: str | None, ugovor: str,
                     rows: list[dict], logo_data_url: str | None) -> bytes:
    _ensure_fonts()

    page_w, page_h = A4
    margin = 30.0
    content_w = page_w - 2 * margin

    title_style = ParagraphStyle(
        "title", fontName="LibB", fontSize=15, leading=19, alignment=1, textColor=BLACK,
    )
    label_style = ParagraphStyle(
        "label", fontName="LibI", fontSize=9, leading=11, alignment=0, textColor=BLACK,
    )
    putnik_style = ParagraphStyle(
        "putnik", fontName="LibBI", fontSize=12, leading=15, alignment=0, textColor=BLACK,
    )
    adresa_style = ParagraphStyle(
        "adresa", fontName="LibI", fontSize=9, leading=11, alignment=0, textColor=BLACK,
    )
    ugovor_style = ParagraphStyle(
        "ugovor", fontName="Lib", fontSize=8.5, leading=11, alignment=0, textColor=BLACK,
    )
    # kolone sa slobodnim tekstom — Paragraph da se dugačke vrednosti prelome
    cell_l = ParagraphStyle("cell_l", fontName="Lib", fontSize=8.5, leading=10.5, alignment=0, textColor=BLACK)

    header_cells = [
        "DATUM", "NAČIN PLAĆANJA", "DIN", "EUR", "SUMA/EUR",
        "SVRHA UPLATE", "REFERENT", "KLJUC",
    ]

    data = [header_cells]
    sum_din = sum_evro = sum_eur = 0.0
    for r in rows:
        din = r.get("din")
        evro = r.get("evro")
        suma = r.get("suma_eur")
        sum_din += din or 0
        sum_evro += evro or 0
        sum_eur += suma or 0
        data.append([
            str(r.get("danas") or ""),
            Paragraph(str(r.get("nacin") or "").strip(), cell_l),
            _fmt(din),
            _fmt(evro),
            _fmt(suma),
            Paragraph(str(r.get("svrha") or "").strip(), cell_l),
            Paragraph(str(r.get("obradio") or "").strip(), cell_l),
            _fmt_int(r.get("kljuc")),
        ])

    data.append([
        "U K U P N O :", "",
        _fmt(sum_din), _fmt(sum_evro), _fmt(sum_eur),
        "", "", "",
    ])

    rel_widths = [58, 84, 68, 50, 62, 72, 84, 56]
    scale = content_w / sum(rel_widths)
    widths = [w * scale for w in rel_widths]

    table = Table(data, colWidths=widths, repeatRows=1, hAlign="CENTER")
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Lib"),
        ("FONTNAME", (0, 0), (-1, 0), "LibB"),          # zaglavlja bold
        ("FONTNAME", (0, 1), (0, -1), "LibI"),          # datum italic
        ("FONTNAME", (4, 1), (4, -1), "LibB"),          # SUMA/EUR bold
        ("FONTNAME", (0, -1), (-1, -1), "LibB"),        # zbirni red bold
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("FONTSIZE", (0, -1), (0, -1), 9.5),            # U K U P N O krupnije
        ("FONTSIZE", (4, -1), (4, -1), 9),
        ("TEXTCOLOR", (0, 0), (-1, -1), BLACK),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        # poravnanja po kolonama
        ("ALIGN", (0, 0), (0, -1), "CENTER"),           # DATUM
        ("ALIGN", (2, 1), (4, -1), "RIGHT"),            # DIN / EUR / SUMA-EUR
        ("ALIGN", (7, 1), (7, -1), "RIGHT"),            # KLJUC
        ("ALIGN", (0, -1), (0, -1), "LEFT"),            # U K U P N O labela
        # linije: tanke unutrašnje, deblji spoljni okvir i istaci redova
        ("GRID", (0, 0), (-1, -1), 0.5, BLACK),
        ("BOX", (0, 0), (-1, -1), 1.4, BLACK),
        ("LINEBELOW", (0, 0), (-1, 0), 1.0, BLACK),
        ("LINEABOVE", (0, -1), (-1, -1), 1.0, BLACK),
        ("SPAN", (0, -1), (1, -1)),                     # U K U P N O preko 2 kolone
        ("BACKGROUND", (0, 0), (-1, 0), WHITE),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]))

    story: list = [
        Paragraph("PREGLED UPLATA", title_style),
        Spacer(1, 34),  # prostor za logo gore levo (crtan preko canvas-a na strani 1)
        Paragraph("PUTNIK:", label_style),
        Paragraph((putnik or "").strip().upper(), putnik_style),
        Paragraph((adresa or "").strip(), adresa_style),
        Paragraph(f"Ugovor: {ugovor}", ugovor_style),
        Spacer(1, 14),
        table,
    ]

    def draw_page(canv, doc):
        # logo gore levo — samo na prvoj strani
        if canv.getPageNumber() == 1 and logo_data_url and "," in logo_data_url:
            try:
                import base64 as _b64
                raw = _b64.b64decode(logo_data_url.split(",", 1)[1])
                reader = ImageReader(io.BytesIO(raw))
                iw, ih = reader.getSize()
                if iw and ih:
                    s = min(150.0 / iw, 46.0 / ih)
                    canv.drawImage(reader, margin, page_h - margin - ih * s,
                                   width=iw * s, height=ih * s, mask="auto")
            except Exception:
                pass
        canv.setFont("Lib", 8)
        canv.drawRightString(page_w - margin, 16, str(canv.getPageNumber()))

    buf = io.BytesIO()
    doc = BaseDocTemplate(
        buf, pagesize=A4,
        leftMargin=margin, rightMargin=margin, topMargin=margin, bottomMargin=30,
        title=f"Pregled uplata {ugovor}",
    )
    frame = Frame(margin, 30, content_w, page_h - margin - 30, id="main")
    doc.addPageTemplates([PageTemplate(id="all", frames=[frame], onPage=draw_page)])
    doc.build(story)

    buf.seek(0)
    return buf.getvalue()
