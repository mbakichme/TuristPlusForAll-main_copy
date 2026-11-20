"""Administrativna zabrana — PDF po šablonu „Prijava aranžmana / administrativna zabrana“.

A4 portrait, crno-belo. Ulazni podaci su rečnik koji vraća `_zabrana_detalj`
(zabrana_api.py). Svi iznosi su u RSD.
"""
import io
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

from uplate_pdf import _ensure_fonts

W, H = A4
M = 40
ROW_H = 15
DNO = 60  # donja granica sadržaja (pre nove strane)
GORE = H - 40


def _iznos(v) -> str:
    """265178.34 → 265.178,34 (srpski format)."""
    s = f"{float(v or 0):,.2f}"
    return s.translate(str.maketrans(",.", ".,"))


def _niz(c, x, y, delovi):
    """Crta delove teksta u nizu: [(tekst, font, veličina), ...]."""
    for txt, font, size in delovi:
        c.setFont(font, size)
        c.drawString(x, y, txt)
        x += pdfmetrics.stringWidth(txt, font, size)
    return x


def _red(c, x, y, widths, red, poravnanje, font, size):
    """Crta jedan red tabele (mreža + tekst). y = gornja ivica. Vraća donju."""
    bottom = y - ROW_H
    cx = x
    for j, w in enumerate(widths):
        c.setLineWidth(0.6)
        c.rect(cx, bottom, w, ROW_H, stroke=1, fill=0)
        txt = str(red[j]) if j < len(red) and red[j] is not None else ""
        c.setFont(font, size)
        ty = bottom + 4.5
        a = poravnanje[j]
        if a == "r":
            c.drawRightString(cx + w - 4, ty, txt)
        elif a == "c":
            c.drawCentredString(cx + w / 2, ty, txt)
        else:
            c.drawString(cx + 4, ty, txt)
        cx += w
    return bottom


def _tabela(c, x, y, widths, redovi, zaglavlje=False, poravnanje=None,
            ukupno=False, size=8.5):
    """Crta tabelu sa mrežom. y = gornja ivica. Prvi red je zaglavlje (bold) ako
    je `zaglavlje`; pri prelomu strane zaglavlje se ponavlja. `ukupno` = poslednji
    red bold. Vraća donju y poziciju."""
    poravnanje = poravnanje or ["l"] * len(widths)
    if not redovi:
        return y
    zag = redovi[0] if zaglavlje else None
    telo = redovi[1:] if zaglavlje else redovi
    if zag is not None:
        y = _red(c, x, y, widths, zag, poravnanje, "LibB", size)
    for i, red in enumerate(telo):
        if y - ROW_H < DNO:
            c.showPage()
            y = GORE
            if zag is not None:
                y = _red(c, x, y, widths, zag, poravnanje, "LibB", size)
        jezadnji = ukupno and i == len(telo) - 1
        y = _red(c, x, y, widths, red, poravnanje, "LibB" if jezadnji else "Lib", size)
    return y


def build_zabrana_pdf(d: dict) -> bytes:
    """d: detalj zabrane (vidi `_zabrana_detalj`)."""
    _ensure_fonts()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"Administrativna zabrana {d['broj']}")
    ag = d.get("agencija") or {}
    x0 = M
    y = GORE

    # --- zaglavlje ---------------------------------------------------------
    _niz(c, x0, y, [("NAZIV PREDUZEĆA: ", "Lib", 9.5), (d["preduzece"], "LibB", 9.5)])
    y -= 13
    _niz(c, x0, y, [("MESTO OBRAČUNA: ", "Lib", 9.5), (d["mesto_obracuna"], "Lib", 9.5)])
    y -= 28
    c.setFont("LibB", 13)
    c.drawCentredString(W / 2, y, "PRIJAVA ARANŽMANA /")
    y -= 17
    c.drawCentredString(W / 2, y, f"ADMINISTRATIVNA ZABRANA BROJ: {d['broj']}")
    y -= 22

    # --- strane ugovora ----------------------------------------------------
    _niz(c, x0, y, [("Sačinjen dana ", "Lib", 10), (d["datum"], "LibB", 10),
                    ("   izmedju:", "Lib", 10)])
    y -= 16
    _niz(c, x0, y, [("1. ", "LibB", 10), (ag.get("naziv") or "", "LibB", 10)])
    y -= 12
    adr_ag = ", ".join(x for x in [ag.get("adresa"), ag.get("mesto")] if x)
    kontakt_ag = " ".join(x for x in [
        f"kontakt telefon {ag['telefon']}" if ag.get("telefon") else "",
        f"kontakt mail: {ag['email']}" if ag.get("email") else "",
    ] if x)
    c.setFont("Lib", 9)
    c.drawString(x0 + 12, y, f"iz {adr_ag}, {kontakt_ag}".strip().rstrip(","))
    y -= 14
    n = d["nosilac"]
    _niz(c, x0, y, [("2. Korisnik usluge: ", "Lib", 10), (n["ime"], "LibB", 10)])
    y -= 12
    _niz(c, x0 + 12, y, [("adresa: ", "Lib", 9.5), (n.get("adresa") or "", "LibB", 9.5),
                         ("   kontakt telefon: ", "Lib", 9.5),
                         (n.get("telefon") or "", "LibB", 9.5)])
    y -= 18

    _niz(c, x0, y, [("NAČIN PLAĆANJA: ADMINISTRATIVNA ZABRANA U ", "Lib", 10),
                    (str(d["broj_rata"]), "LibB", 10), (" RATA/e", "Lib", 10)])
    y -= 16

    # --- aranžman ----------------------------------------------------------
    c.setFont("LibB", 10)
    c.drawString(x0, y, "ARANŽMAN:")
    y -= 4
    ar = d["aranzman"]
    arw = [140, 160, 105, W - 2 * M - 405]
    y = _tabela(c, x0, y, arw,
                [["MESTO", "VILA/HOTEL", "TERMIN", "TIP STUDIA/APT/SOB"],
                 [ar.get("mesto", ""), ar.get("naziv", ""), ar.get("termin", ""),
                  ar.get("apartman", "")]],
                zaglavlje=True, poravnanje=["c", "c", "c", "c"], size=8)
    y -= 12

    # --- putnici + obračun usluge (dve tabele) -----------------------------
    putnici = d["putnici"][:5]
    putnici += [{"ime": "", "rodjen": ""}] * (5 - len(putnici))
    yl = y - 13
    c.setFont("LibB", 9.5)
    c.drawString(x0, y, "PREZIMEI IME, DATUM RODJENJA PUTNIKA")
    xr = W - M - 185
    c.drawString(xr + 40, y, "OBRAČUN USLUGE")
    lw = [22, 205, 85]
    levo_redovi = [[str(i + 1) + ".", p["ime"], p["rodjen"]] for i, p in enumerate(putnici)]
    y_levo = _tabela(c, x0, yl, lw, levo_redovi, poravnanje=["c", "l", "c"], size=8.5)
    desno = [
        ["USLUGA", "IZNOS (DIN.)"],
        ["SMEŠTAJ", _iznos(d["smestaj"])],
        ["PREVOZ", _iznos(d["prevoz"])],
        ["USLUGA +", _iznos(d["dod"])],
        ["UKUPNO", _iznos(d["ukupno"])],
    ]
    y_desno = _tabela(c, xr, yl, [110, 75], desno, zaglavlje=True,
                      poravnanje=["l", "r"], ukupno=True, size=8.5)
    y = min(y_levo, y_desno) - 16

    # --- obračun rata ------------------------------------------------------
    c.setFont("LibB", 10)
    c.drawString(x0, y, "OBRAČUN RATA:")
    y -= 4
    rate = d["rate"]
    rate_redovi = [["r.b.", "Datum rate", "Iznos rate (din.)"]]
    rate_redovi += [[str(r["rb"]), r["datum"], _iznos(r["iznos"])] for r in rate]
    rate_redovi += [["UKUPNO", "", _iznos(sum(r["iznos"] for r in rate))]]
    y = _tabela(c, x0, y, [60, 110, 120], rate_redovi, zaglavlje=True,
                poravnanje=["c", "c", "r"], ukupno=True, size=8.5)
    y -= 18

    # --- pravni tekst -------------------------------------------------------
    stil = ParagraphStyle("zab", fontName="Lib", fontSize=9, leading=11.5)
    racun = ag.get("racun") or ""
    banka = ag.get("banka") or ""
    tekst = (
        f"Služba za obračun zarada Preduzeća <b>{escape(d['preduzece'])}</b> obavezuje se da "
        f"iznos prispele rate za naplatu obustavi korisniku usluga od zarade i uplati na tekući "
        f"račun br. {escape(racun)} kod {escape(banka)} davaocu usluga "
        f"<b>\"{escape(ag.get('naziv') or '')}\"</b> iz {escape(ag.get('mesto') or '')}, "
        f"sa pozivom na broj: <b>{escape(d['broj'])}</b>.<br/>"
        f"U slučaju da kod odloženog plaćanja na rate putem administrativne zabrane na lična "
        f"primanja Služba za obračun zarada Preduzeća {escape(d['preduzece'])} nije u mogućnosti "
        f"da iznos dospele rate naplati od moje zarade u tom mesecu, obavezujem se da iznos "
        f"dospele rate sam uplatim u agenciji ili na tekući račun {escape(racun)} kod "
        f"{escape(banka)}, sa pozivom na broj: <b>{escape(d['broj'])}</b>.<br/><br/>"
        f"Izjavljujem da sam upoznat sa uslovima putovanja turističke agencije "
        f"\"{escape(ag.get('naziv') or '')}\" iz {escape(ag.get('mesto') or '')} sa kojima sam "
        f"saglasan u svoje ime i u ime navedenih putnika."
    )
    p = Paragraph(tekst, stil)
    _, visina = p.wrap(W - 2 * M, 1000)
    potpisi_h = 28 + 4 * 16 + 10
    if y - (visina + 14 + potpisi_h) < DNO:
        c.showPage()
        y = GORE
    p.drawOn(c, x0, y - visina)
    y -= visina + 14

    # --- potpisi -----------------------------------------------------------
    c.setFont("Lib", 10)
    c.drawRightString(W - M, y, "SLUŽBA OBRAČUNA ZARADA")
    y -= 24
    levo = ["KORISNIK USLUGE:", "PREDUZEĆE:", "JMBG:", "BR. L.K.", "IDENT BROJ:"]
    desno_pot = ["ODGOVORNO LICE", "BROJ TELEFONA", "M.P."]
    for i, lab in enumerate(levo):
        yy = y - i * 16
        c.setFont("LibB", 10)
        c.drawString(x0, yy, lab)
        c.setLineWidth(0.5)
        c.line(x0 + 120, yy - 2, x0 + 310, yy - 2)
    for i, lab in enumerate(desno_pot):
        yy = y - i * 16
        c.setFont("Lib", 8)
        c.drawString(W - M - 230, yy - 10, lab)
        c.line(W - M - 230, yy - 2, W - M, yy - 2)
    c.save()
    return buf.getvalue()
