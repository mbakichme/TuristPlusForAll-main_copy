"""
Dnevni izveštaj prodaje aranžmana — PDF po referentnom šablonu agencije.

Raspored (A4 landscape, crno-beli):
  - header: logo (iz Podešavanja → Dokumenti, tip "logo") gore levo,
    naslov "DNEVNA PRODAJA APARTMANA" centriran, ispod "Datum <datum>" centriran
  - sekcije po poslovnici: naziv poslovnice (bold) + debela crna linija,
    ispod tabela sa tankim crnim mrežastim okvirima
  - kolone: R.br | Ime i prezime (+br. osoba) | Subagent | Mesto | Destinacija |
    Objekat (+soba) | Tip | Datum smene | od/do | Operater | (datum) | Ugovor broj
  - numeracija redova je kontinuirana kroz ceo dokument
  - footer: broj stranice dole desno
"""
import io
import os

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
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
    if "Lib" not in registered:
        from reportlab.pdfbase.pdfmetrics import Font
        pdfmetrics.registerFont(Font("Lib", "Helvetica", "WinAnsiEncoding"))
        pdfmetrics.registerFont(Font("LibB", "Helvetica-Bold", "WinAnsiEncoding"))
    _FONTS_READY = True


def build_dnevni_izvestaj_pdf(datum_display: str, rows: list[dict], logo_data_url: str | None) -> bytes:
    """rows: redovi jednog dana (sve poslovnice); grupisanje po poslovnica ovde."""
    _ensure_fonts()

    page_w, page_h = landscape(A4)
    margin = 26.0
    content_w = page_w - 2 * margin

    # ─── Header: logo levo (apsolutno), naslov + datum centrirano ───────────
    title_style = ParagraphStyle(
        "title", fontName="LibB", fontSize=16, leading=19, alignment=1, textColor=BLACK,
    )
    datum_style = ParagraphStyle(
        "datum", fontName="LibB", fontSize=12, leading=15, alignment=1, textColor=BLACK,
    )
    head = [
        Paragraph("DNEVNA PRODAJA APARTMANA", title_style),
        Spacer(1, 3),
        Paragraph(f"Datum&nbsp;&nbsp;&nbsp;{datum_display}", datum_style),
        Spacer(1, 8),
    ]

    group_style = ParagraphStyle(
        "group", fontName="LibB", fontSize=11, leading=14, alignment=0, textColor=BLACK,
    )
    group_style.keepWithNext = 1
    cell_l = ParagraphStyle("cell_l", fontName="Lib", fontSize=6.5, leading=8, alignment=0)
    cell_c = ParagraphStyle("cell_c", fontName="Lib", fontSize=6.5, leading=8, alignment=1)
    cell_r = ParagraphStyle("cell_r", fontName="Lib", fontSize=6.5, leading=8, alignment=2)

    header_cells = [
        "", "Ime i prezime", "", "Subagent", "Mesto", "Destinacija",
        "Objekat", "", "Tip", "Datum smene", "", "Operater", "Ugovor broj",
    ]

    # ─── Footer: broj stranice dole desno + logo gore levo ──────────────────
    story: list = list(head)

    # grupisanje po poslovnici (prazno → OSTALE), sortirano abecedno
    groups: dict[str, list[dict]] = {}
    for r in rows:
        g = (r.get("poslovnica") or "").strip() or "OSTALE"
        groups.setdefault(g, []).append(r)

    rbr = 0
    for gname in sorted(groups):
        # naslov poslovnice VAN tabele — ne ponavlja se na nastavku strane;
        # keepWithNext drži naslov + liniju zajedno sa početkom tabele
        title = Paragraph(gname.upper(), group_style)
        title.keepWithNext = 1
        hr = HRFlowable(width="100%", thickness=2.2, color=BLACK, spaceBefore=1, spaceAfter=3)
        hr.keepWithNext = 1
        story.append(title)
        story.append(hr)

        data = [header_cells]
        for r in sorted(groups[gname], key=lambda x: str(x.get("kljuc") or "")):
            rbr += 1
            br_osoba = str(r.get("broj_putnika") or 1)
            soba = (r.get("soba") or "").strip()
            od = r.get("datum_od") or ""
            do = r.get("datum_do") or ""
            broj = r.get("broj_fmt") or ""
            data.append([
                Paragraph(str(rbr), cell_c),
                Paragraph(str(r.get("putnik") or ""), cell_l),
                Paragraph(br_osoba, cell_r),
                Paragraph(str(r.get("subagent") or ""), cell_l),
                Paragraph(str(r.get("mesto") or ""), cell_l),
                Paragraph(str(r.get("destinacija") or ""), cell_l),
                Paragraph(str(r.get("smestaj") or ""), cell_l),
                Paragraph(soba, cell_r),
                Paragraph(str(r.get("tip") or ""), cell_c),
                Paragraph(str(r.get("datum_smene") or ""), cell_l),
                Paragraph(f"{od}&nbsp;&nbsp;{do}".strip(), cell_l),
                Paragraph(str(r.get("operater") or ""), cell_l),
                Paragraph(broj, cell_r),
            ])

        rel_widths = [18, 112, 16, 58, 64, 78, 92, 26, 30, 84, 94, 54, 52]
        scale = content_w / sum(rel_widths)
        widths = [w * scale for w in rel_widths]

        table = Table(data, colWidths=widths, repeatCols=1, repeatRows=1, hAlign="LEFT")
        table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), "Lib"),
            ("FONTNAME", (0, 0), (-1, 0), "LibB"),
            ("FONTSIZE", (0, 0), (-1, -1), 6.5),
            ("TEXTCOLOR", (0, 0), (-1, -1), BLACK),
            ("GRID", (0, 0), (-1, -1), 0.6, BLACK),
            ("BACKGROUND", (0, 0), (-1, 0), WHITE),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 1.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
            # header spans: Ime i prezime (kol 1-2), Objekat (kol 6-7),
            # Datum smene (kol 9-10 — raspon + od/do)
            ("SPAN", (1, 0), (2, 0)),
            ("SPAN", (6, 0), (7, 0)),
            ("SPAN", (9, 0), (10, 0)),
        ]))
        story.append(table)
        story.append(Spacer(1, 10))

    def draw_page(canv, doc):
        # logo gore levo — samo na prvoj strani
        if canv.getPageNumber() == 1 and logo_data_url and "," in logo_data_url:
            try:
                import base64 as _b64
                raw = _b64.b64decode(logo_data_url.split(",", 1)[1])
                reader = ImageReader(io.BytesIO(raw))
                iw, ih = reader.getSize()
                if iw and ih:
                    scale = min(150.0 / iw, 46.0 / ih)
                    canv.drawImage(reader, margin, page_h - margin - ih * scale,
                                   width=iw * scale, height=ih * scale, mask="auto")
            except Exception:
                pass
        canv.setFont("Lib", 8)
        canv.drawRightString(page_w - margin, 16, str(canv.getPageNumber()))

    buf = io.BytesIO()
    doc = BaseDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=margin, rightMargin=margin, topMargin=margin, bottomMargin=30,
        title="Dnevna prodaja apartmana",
    )
    frame = Frame(margin, 30, content_w, page_h - margin - 30, id="main")
    doc.addPageTemplates([PageTemplate(id="all", frames=[frame], onPage=draw_page)])
    doc.build(story)

    buf.seek(0)
    return buf.getvalue()
