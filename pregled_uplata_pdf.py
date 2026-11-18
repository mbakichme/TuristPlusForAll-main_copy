"""
PDF dnevnog pregleda uplata po načinu plaćanja (Gotovina / Ček / Kartica).

Header isti kao na ugovoru i priznanici: podaci agencije levo, logo desno.
Ispod naslova: datum pregleda, način plaćanja, broj uplata i ukupan iznos.
Za Gotovina: jedan red po uplati.
Za Kartica: jedan red po uplati + podaci kartice (tip, broj, potvrda, odobrenje).
Za Ček: jedan red po čeku (uplata, redni broj, datum valute, banka, serijski broj).
"""
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle, BaseDocTemplate, HRFlowable,
)
from xml.sax.saxutils import escape

from priznanica_pdf import _ensure_fonts, _logo_flowable

BLACK = colors.black
WHITE = colors.white

NACIN_NASLOV = {"Gotovina": "GOTOVINA", "Ček": "ČEK", "Kartica": "KARTICA", "Virman": "VIRMAN"}


def _fmt(v, dec=2):
    try:
        s = f"{float(v):,.{dec}f}"
    except (TypeError, ValueError):
        return ""
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _esc(v) -> str:
    return escape(str(v or "").strip())


def build_pregled_uplata_pdf(
    nacin: str,
    datum_display: str,
    uplate: list[dict],
    cekovi: list[dict],
    agencija: dict | None,
    logo_data_url: str | None,
) -> bytes:
    """uplate: redovi uplata sa tim načinom; cekovi: redovi cekova (samo za Ček)."""
    _ensure_fonts()
    page_w, page_h = landscape(A4)
    margin = 28.0
    content_w = page_w - 2 * margin

    ag = agencija or {}
    naziv = ag.get("naziv") or ag.get("poslovno_ime") or "Agencija"
    adresa_ag = " ".join(str(ag.get(k) or "") for k in ("ulica", "broj")).strip()
    mesto_ag = " ".join(str(ag.get(k) or "") for k in ("post_broj", "mesto")).strip()
    naziv_style = ParagraphStyle("ag_naziv", fontName="LibB", fontSize=15, leading=18)
    kontakt_style = ParagraphStyle("ag_kontakt", fontName="Lib", fontSize=9, leading=12)
    title_style = ParagraphStyle("title", fontName="LibB", fontSize=14, leading=17, alignment=1)
    meta_style = ParagraphStyle("meta", fontName="LibB", fontSize=10, leading=13)
    cell_l = ParagraphStyle("cell_l", fontName="Lib", fontSize=7.5, leading=9)
    cell_r = ParagraphStyle("cell_r", fontName="Lib", fontSize=7.5, leading=9, alignment=2)
    cell_c = ParagraphStyle("cell_c", fontName="Lib", fontSize=7.5, leading=9, alignment=1)
    head_l = ParagraphStyle("head_l", fontName="LibB", fontSize=7.5, leading=9)
    head_r = ParagraphStyle("head_r", fontName="LibB", fontSize=7.5, leading=9, alignment=2)

    ag_lines = [
        ", ".join(x for x in (adresa_ag, mesto_ag) if x),
        ", ".join(str(ag.get(k)) for k in ("telefon1", "email1") if ag.get(k)),
        "  |  ".join(x for x in (
            f"PIB {ag['pib']}" if ag.get("pib") else "",
            f"MB {ag['mb']}" if ag.get("mb") else "",
        ) if x),
    ]
    ag_cell = [Paragraph(_esc(naziv), naziv_style)]
    ag_cell.extend(Paragraph(_esc(line), kontakt_style) for line in ag_lines if line)
    logo = _logo_flowable(logo_data_url, 150, 52)
    logo.hAlign = "RIGHT"
    header = Table([[ag_cell, logo]], colWidths=[content_w * 0.7, content_w * 0.3])
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))

    naslov = NACIN_NASLOV.get(nacin, nacin.upper())
    if nacin == "Ček":
        ukupno = sum(float(c.get("iznos") or 0) for c in cekovi)
        broj_stavki = len(cekovi)
        jedinica = "čekova"
    else:
        ukupno = sum(float(u.get("din") or 0) for u in uplate)
        broj_stavki = len(uplate)
        jedinica = "uplata"

    story: list = [
        header,
        Spacer(1, 10),
        HRFlowable(width="100%", thickness=0.8, color=BLACK, spaceAfter=6),
        Paragraph(f"PREGLED UPLATA — {naslov}", title_style),
        Spacer(1, 4),
        Paragraph(
            f"Datum pregleda: {_esc(datum_display)}"
            f"&nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;Broj {jedinica}: {broj_stavki}"
            f"&nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;Ukupno: {_fmt(ukupno)} din",
            meta_style,
        ),
        Spacer(1, 8),
    ]

    if nacin == "Ček":
        head = ["Vreme", "Ugovor", "Uplatilac", "Redni br.", "Datum valute", "Banka čeka",
                "Banka klijenta", "Serijski broj", "Iznos (din)"]
        data = [[Paragraph(h, head_r if h == "Iznos (din)" else head_l) for h in head]]
        for c in cekovi:
            data.append([
                Paragraph(_esc(c.get("vreme")), cell_l),
                Paragraph(_esc(c.get("ugovor")), cell_l),
                Paragraph(_esc(c.get("ime")), cell_l),
                Paragraph(_esc(c.get("redni")), cell_c),
                Paragraph(_esc(c.get("datum")), cell_l),
                Paragraph(_esc(c.get("banka")), cell_l),
                Paragraph(_esc(c.get("banka_klijenta_naziv")), cell_l),
                Paragraph(_esc(c.get("serijski_broj")), cell_l),
                Paragraph(_fmt(c.get("iznos")), cell_r),
            ])
        rel = [48, 62, 170, 50, 70, 120, 130, 110, 80]
    elif nacin == "Kartica":
        head = ["Vreme", "Ugovor", "Uplatilac", "Svrha", "Tip kartice", "Broj kartice",
                "Broj potvrde", "Broj odobrenja", "Iznos (din)"]
        data = [[Paragraph(h, head_r if h == "Iznos (din)" else head_l) for h in head]]
        for u in uplate:
            data.append([
                Paragraph(_esc(u.get("vreme")), cell_l),
                Paragraph(_esc(u.get("ugovor")), cell_l),
                Paragraph(_esc(u.get("ime")), cell_l),
                Paragraph(_esc(u.get("svrha")), cell_l),
                Paragraph(_esc(u.get("tip_kartice")), cell_l),
                Paragraph(_esc(u.get("broj_kartice")), cell_l),
                Paragraph(_esc(u.get("broj_potvrde")), cell_l),
                Paragraph(_esc(u.get("broj_odobrenja")), cell_l),
                Paragraph(_fmt(u.get("din")), cell_r),
            ])
        rel = [44, 62, 150, 120, 90, 120, 100, 100, 80]
    else:
        head = ["Vreme", "Ugovor", "Uplatilac", "Svrha", "Obradio", "Poslovnica", "Iznos (din)"]
        data = [[Paragraph(h, head_r if h == "Iznos (din)" else head_l) for h in head]]
        for u in uplate:
            data.append([
                Paragraph(_esc(u.get("vreme")), cell_l),
                Paragraph(_esc(u.get("ugovor")), cell_l),
                Paragraph(_esc(u.get("ime")), cell_l),
                Paragraph(_esc(u.get("svrha")), cell_l),
                Paragraph(_esc(u.get("obradio")), cell_l),
                Paragraph(_esc(u.get("poslovnica")), cell_l),
                Paragraph(_fmt(u.get("din")), cell_r),
            ])
        rel = [50, 80, 230, 190, 120, 130, 100]

    if len(data) == 1:
        data.append([Paragraph("Nema stavki za izabrani dan.", cell_l)] + [""] * (len(head) - 1))

    scale = content_w / sum(rel)
    table = Table(data, colWidths=[w * scale for w in rel], repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, BLACK),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(table)

    def draw_page(canv, doc):
        canv.setFont("Lib", 8)
        canv.drawRightString(page_w - margin, 16, f"Strana {canv.getPageNumber()}")

    buf = io.BytesIO()
    doc = BaseDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=margin, rightMargin=margin, topMargin=margin, bottomMargin=30,
        title=f"Pregled uplata {naslov.lower()} {datum_display}",
    )
    frame = Frame(margin, 30, content_w, page_h - margin - 30, id="main",
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="all", frames=[frame], onPage=draw_page)])
    doc.build(story)
    buf.seek(0)
    return buf.getvalue()
