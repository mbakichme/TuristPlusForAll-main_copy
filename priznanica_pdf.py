"""
Priznanica o uplati — PDF po referentnom šablonu agencije (stari sistem).

Jedna A4 portrait strana sa DVA identična primerka (agencija + kupac),
razdvojena isprekidanom linijom sa malim makazama na sredini strane.

Raspored primerka (crno-beli tekst):
  - header kao predračun: podaci agencije levo, logo desno
  - "PRIZNANICA  32992/26" bold, poravnato udesno
    (broj = uplate.kljuc bez separatora hiljada + godina uplate "/YY")
  - tri okvira sa labelama UPLATIO | ADRESA | IZNOS (bold, centrirano), vrednosti
    ispod okvira: ime + zaseban bold red "Broj ugovora: X/YY", adresa,
    iznos (krupno bold, desno)
  - levo "Način plaćanja: X", desno blok: Svrha uplate / Mesto / Smeštaj / Termin
  - footer: levo "Datum: DD.MM.YYYY", desno "Referent:" (italic) + poslovnica
"""
import io

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Frame, FrameBreak, Image, PageTemplate, Paragraph, Spacer,
    Table, TableStyle, BaseDocTemplate,
)

BLACK = colors.black
WHITE = colors.white

FONT_DIR_CANDIDATES = [
    __file__.rsplit("/", 1)[0] + "/assets/fonts",
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
    }
    registered = set()
    for base in FONT_DIR_CANDIDATES:
        try:
            import os as _os
            if not _os.path.isdir(base):
                continue
        except Exception:
            continue
        for name, candidates in fonts.items():
            if name in registered:
                continue
            for fname in candidates:
                import os as _os
                path = _os.path.join(base, fname)
                if _os.path.exists(path):
                    pdfmetrics.registerFont(TTFont(name, path))
                    registered.add(name)
                    break
    if "Lib" not in registered:
        from reportlab.pdfbase.pdfmetrics import Font
        pdfmetrics.registerFont(Font("Lib", "Helvetica", "WinAnsiEncoding"))
        pdfmetrics.registerFont(Font("LibB", "Helvetica-Bold", "WinAnsiEncoding"))
        pdfmetrics.registerFont(Font("LibI", "Helvetica-Oblique", "WinAnsiEncoding"))
    _FONTS_READY = True


def _fmt(v, dec=2):
    """sr-RS format broja: 293.274,00 (tačka hiljade, zarez decimale)."""
    if v is None:
        return ""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return str(v)
    s = f"{x:,.{dec}f}"
    return s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _broj_priznanice(kljuc, danas) -> str:
    """Priznanica broj: 32.992/26 (kljuc uplate + godina uplate "/YY")."""
    try:
        broj = str(int(kljuc))
    except (TypeError, ValueError):
        broj = str(kljuc or "")
    godina = f"{danas.year % 100:02d}" if danas else "26"
    return f"{broj}/{godina}"


def _logo_flowable(logo_data_url: str | None, max_w: float, max_h: float):
    """Logo kao Image flowable (čuva proporcije) ili prazan prostor."""
    if logo_data_url and "," in logo_data_url:
        try:
            import base64 as _b64
            raw = _b64.b64decode(logo_data_url.split(",", 1)[1])
            reader = ImageReader(io.BytesIO(raw))
            iw, ih = reader.getSize()
            if iw and ih:
                s = min(max_w / iw, max_h / ih)
                # Image flowable prima str/bytes/file-like — ne i ImageReader objekat
                return Image(io.BytesIO(raw), width=iw * s, height=ih * s, lazy=0)
        except Exception:
            pass
    return Spacer(1, max_h * 0.6)


def _draw_scissors(canv, x, y):
    """Male makaze nacrtane linijama (x, y = središte makaza)."""
    canv.saveState()
    canv.setLineWidth(1.0)
    canv.setStrokeColor(BLACK)
    canv.setFillColor(BLACK)
    s = 5.5
    # prsteni (krugovi) levo
    canv.circle(x - s, y + s * 0.7, s * 0.42, stroke=1, fill=0)
    canv.circle(x - s, y - s * 0.7, s * 0.42, stroke=1, fill=0)
    # sečiva — dve ukrštene linije ka desno
    canv.line(x - s * 0.65, y + s * 0.5, x + s * 1.2, y - s * 0.2)
    canv.line(x - s * 0.65, y - s * 0.5, x + s * 1.2, y + s * 0.2)
    # šaraf (pivot)
    canv.circle(x + s * 0.28, y, 0.7, stroke=0, fill=1)
    canv.restoreState()


def build_priznanica_pdf(uplata: dict, aranzman: dict | None,
                         agencija: dict | None, logo_data_url: str | None,
                         preostalo_eur: float | None = None) -> bytes:
    _ensure_fonts()

    page_w, page_h = A4
    margin = 30.0
    top = 14.0
    bottom = 26.0
    content_w = page_w - 2 * margin

    # Svedena crno-bela hijerarhija, pogodna i za štampu.
    muted = colors.HexColor("#60666C")
    rule = colors.HexColor("#D8DDE1")
    soft = colors.HexColor("#F2F4F5")
    title_style = ParagraphStyle("title", fontName="LibB", fontSize=18, leading=22)
    number_style = ParagraphStyle("number", fontName="LibB", fontSize=12, leading=16, alignment=2)
    label_style = ParagraphStyle("label", fontName="Lib", fontSize=7.5, leading=11, textColor=muted)
    value_style = ParagraphStyle("value", fontName="Lib", fontSize=9.5, leading=13)
    name_style = ParagraphStyle("name", fontName="LibB", fontSize=12, leading=16)
    amount_style = ParagraphStyle("amount", fontName="LibB", fontSize=21, leading=25, alignment=2)
    right_label = ParagraphStyle("right_label", parent=label_style, alignment=2)
    right_value = ParagraphStyle("right_value", parent=value_style, alignment=2)
    contract_style = ParagraphStyle("contract", fontName="LibB", fontSize=10.5, leading=14)

    def esc(v) -> str:
        return str(v or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # ─── jedan primerak priznanice ────────────────────────────────────────────
    def copy_flowables() -> list:
        # Raspored i podaci kao u predračunu: agencija levo, logo desno.
        ag = agencija or {}
        adresa_ag = " ".join(str(ag.get(k) or "") for k in ("ulica", "broj")).strip()
        mesto_ag = " ".join(str(ag.get(k) or "") for k in ("post_broj", "mesto")).strip()
        naziv = ag.get("naziv") or ag.get("poslovno_ime") or "Agencija"
        naziv_style = ParagraphStyle("ag_naziv", fontName="LibB", fontSize=16, leading=19)
        kontakt_style = ParagraphStyle("ag_kontakt", fontName="Lib", fontSize=9.5, leading=13)
        racun_style = ParagraphStyle("ag_racun", fontName="LibB", fontSize=10, leading=13)
        ag_cell = [Paragraph(esc(naziv), naziv_style)]
        ag_lines = [
            ", ".join(x for x in (adresa_ag, mesto_ag) if x),
            ", ".join(str(ag.get(k)) for k in ("telefon1", "email1") if ag.get(k)),
            "  |  ".join(x for x in (
                f"PIB {ag['pib']}" if ag.get("pib") else "",
                f"MB {ag['mb']}" if ag.get("mb") else "",
            ) if x),
        ]
        ag_cell.extend(Paragraph(esc(line), kontakt_style) for line in ag_lines if line)
        racun = str(ag.get("racun") or "")
        if ag.get("banka"):
            racun += f" ({ag['banka']})"
        if racun:
            ag_cell.append(Paragraph(esc(racun), racun_style))
        logo = _logo_flowable(logo_data_url, 150, 58)
        logo.hAlign = "RIGHT"
        header = Table(
            [[ag_cell, logo]],
            colWidths=[content_w - 158, 158],
        )
        header.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (0, 0), (0, 0), "LEFT"),
            ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ("LINEBELOW", (0, 0), (-1, -1), 1, colors.HexColor("#CBD2D8")),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))

        def clean_table(rows, widths):
            table = Table(rows, colWidths=widths)
            table.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]))
            return table

        danas = uplata.get("danas")
        datum_fmt = danas.strftime("%d.%m.%Y") if danas else ""
        title = clean_table([[
            Paragraph("PRIZNANICA", title_style),
            [Paragraph(esc(_broj_priznanice(uplata.get("kljuc"), danas)), number_style),
             Paragraph(f"Datum: {esc(datum_fmt)}", right_label)],
        ]], [content_w * 0.6, content_w * 0.4])

        payer = [
            Paragraph("UPLATILAC", label_style),
            Paragraph(esc(str(uplata.get("ime") or "").strip().upper()), name_style),
            Paragraph(esc(uplata.get("adresa")) or "—", value_style),
        ]
        amount = [
            Paragraph("IZNOS UPLATE", right_label),
            Paragraph(f"{_fmt(uplata.get('din'))} din", amount_style),
        ]
        summary = clean_table([[payer, amount]], [content_w * 0.60, content_w * 0.40])

        ar = aranzman or {}
        broj_ugovora = str(ar.get("kljuc") or "").strip()
        if not broj_ugovora and uplata.get("id") is not None:
            godina = f"{danas.year % 100:02d}" if danas else "26"
            broj_ugovora = f"{uplata['id']}/{godina}"
        contract = clean_table([[
            Paragraph(f"Broj ugovora: {esc(broj_ugovora) or '—'}", contract_style),
        ]], [content_w])
        contract.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), soft),
            ("LINEBEFORE", (0, 0), (0, 0), 2, BLACK),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))

        def field(label, value):
            return [Paragraph(esc(label), label_style),
                    Paragraph(esc(value) or "—", value_style)]

        od, do = ar.get("od") or "", ar.get("do") or ""
        termin = " – ".join(x for x in (od, do) if x)
        detail_rows = [[
            field("NAČIN PLAĆANJA", uplata.get("nacin")),
            field("SVRHA UPLATE", uplata.get("svrha")),
        ]]
        if uplata.get("mesto") or ar.get("naziv"):
            detail_rows.append([
                field("MESTO", uplata.get("mesto")),
                field("SMEŠTAJ", ar.get("naziv")),
            ])
        if termin:
            detail_rows.append([field("TERMIN BORAVKA", termin), ""])
        if preostalo_eur is not None:
            preostalo_style = ParagraphStyle("preostalo", fontName="LibB", fontSize=10,
                                             leading=13, alignment=2)
            detail_rows.append(["", Paragraph(
                f"Preostalo za uplatu: {esc(_fmt(preostalo_eur))} EUR", preostalo_style)])
        details = clean_table(detail_rows, [content_w * 0.5, content_w * 0.5])
        details.setStyle(TableStyle([
            ("RIGHTPADDING", (0, 0), (0, -1), 18),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))

        referent = str(uplata.get("obradio") or "").strip()
        footer = clean_table([[
            Paragraph("POTVRDA O EVIDENTIRANOJ UPLATI", label_style),
            [Paragraph("REFERENT", right_label),
             Paragraph(esc(referent) or "—", right_value)],
        ]], [content_w * 0.55, content_w * 0.45])
        footer.setStyle(TableStyle([
            ("LINEABOVE", (0, 0), (-1, -1), 0.6, rule),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
        ]))

        return [header, Spacer(1, 12), title, Spacer(1, 12), summary,
                Spacer(1, 10), contract, Spacer(1, 5), details,
                Spacer(1, 6), footer]

    # ─── strana: dva frejma (gornji i donji primerak) ─────────────────────────
    first_copy = copy_flowables()
    copy_height = sum(flow.wrap(content_w, page_h)[1] for flow in first_copy)
    # Razmak prati stvarnu visinu primerka, umesto fiksne polovine A4.
    frame_height = copy_height + 2
    separator_y = page_h - top - frame_height - 12
    lower_top = separator_y - 12
    if lower_top - bottom < frame_height:
        raise ValueError("Sadržaj dve priznanice ne staje na jednu A4 stranu")
    story: list = [*first_copy, FrameBreak(), *copy_flowables()]

    def draw_page(canv, doc):
        # isprekidana razdelna linija + makaze između primeraka
        y = separator_y
        canv.saveState()
        canv.setLineWidth(0.8)
        canv.setStrokeColor(BLACK)
        canv.setDash(4, 3)
        canv.line(margin, y, page_w - margin, y)
        canv.restoreState()
        cx = page_w / 2.0
        # bela podloga da se isprekidana linija prekine ispod makaza
        canv.saveState()
        canv.setFillColor(WHITE)
        canv.rect(cx - 11, y - 7, 28, 14, stroke=0, fill=1)
        canv.restoreState()
        _draw_scissors(canv, cx + 2, y)

    buf = io.BytesIO()
    doc = BaseDocTemplate(
        buf, pagesize=A4,
        leftMargin=margin, rightMargin=margin, topMargin=top, bottomMargin=bottom,
        title=f"Priznanica {_broj_priznanice(uplata.get('kljuc'), uplata.get('danas'))}",
    )
    frame_top = Frame(margin, page_h - top - frame_height, content_w, frame_height, id="top",
                      leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    frame_bot = Frame(margin, lower_top - frame_height, content_w, frame_height, id="bot",
                      leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="all", frames=[frame_top, frame_bot], onPage=draw_page)])
    doc.build(story)

    buf.seek(0)
    return buf.getvalue()
