"""Saglasnost za obradu podataka o ličnosti — PDF po šablonu agencije.

A4 portrait, crno-belo. Zaglavlje, naziv i licenca dolaze iz tabele `agencija`
(Osnovni podaci); broj saglasnosti = broj ugovora; davalac = nosilac aranžmana.
"""
import io
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph
from sqlalchemy import text

from uplate_pdf import _ensure_fonts

W, H = A4
M = 60


def init_saglasnost(engine) -> None:
    """Licenca agencije (kolona za zaglavlje saglasnosti)."""
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE agencija ADD COLUMN IF NOT EXISTS licenca TEXT"))


def build_saglasnost_pdf(ag: dict, broj: str, datum: str, ime: str) -> bytes:
    _ensure_fonts()
    naziv = (ag.get("naziv") or "").strip()
    mesto = (ag.get("mesto") or "").strip()
    adresa = " ".join(x for x in [ag.get("ulica"), ag.get("broj")] if (x or "").strip())
    grad = " ".join(x for x in [ag.get("post_broj"), mesto] if (x or "").strip())
    telefoni = " / ".join(x.strip() for x in [ag.get("telefon1"), ag.get("telefon2")] if (x or "").strip())

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"Saglasnost {broj}")

    # --- zaglavlje: agencija levo, licenca i mesto/datum desno -------------
    y = H - 50
    c.setFont("LibB", 10)
    c.drawString(M, y, naziv)
    c.setFont("Lib", 9)
    if adresa or grad:
        c.drawString(M, y - 14, f"Adresa: {adresa}, {grad}".replace(" ,", ","))
    if telefoni:
        c.drawString(M, y - 28, f"Telefon: {telefoni}")
    c.setFont("Lib", 9)
    c.drawRightString(W - M, y, f"Licenca: {ag.get('licenca') or '—'}")
    c.drawRightString(W - M, y - 14, f"{mesto.upper()}, {datum}")

    # --- naslov --------------------------------------------------------------
    y -= 90
    c.setFont("LibB", 11)
    c.drawString(M, y, f"Saglasnost za obradu podataka o ličnosti Br.: {broj}")

    # --- oslovljavanje + tekst ---------------------------------------------
    y -= 34
    c.setFont("Lib", 10)
    c.drawString(M, y, f"Poštovana/Poštovani {ime}")

    stil = ParagraphStyle("sag", fontName="Lib", fontSize=10, leading=14)
    stil_mali = ParagraphStyle("sagm", fontName="Lib", fontSize=10, leading=14)
    naz = escape(naziv)
    tekst1 = (
        "Da li ste saglasni da, u skladu sa članom 15, Zakona o zaštiti podataka o ličnosti "
        "(\"Službeni glasnik RS\", br. 87 od 13. novembra 2018.) (u daljem tekstu: Zakon) koji "
        "predviđa pristanak na obradu podataka o ličnosti kao jedan od pravnih osnova obrade iz "
        "člana 12. Zakona, date svoj pristanak za obradu podataka o ličnosti, kako bismo mogli "
        "blagovremeno da Vas kontaktiramo, pre svega u svrhu ostvarivanja potencijalne poslovne "
        f"saradnje sa <b>{naz}</b>."
    )
    tekst2 = (
        "Moji podaci o ličnosti obrađivaće se i koristiti u svrhe koje su predviđene Zakonom, kao i "
        "Pravilnikom o zaštiti podataka o ličnosti."
    )
    tekst3 = (
        "Pozivamo Vas da se upoznate sa našim Aktom o bezbednosti i privatnosti podataka o ličnosti "
        "koji možete naći na našem sajtu, kako biste saznali sve o svrhama obrade, o vrsti podataka "
        "o ličnosti koje obrađujemo i kako biste bili u mogućnosti da u punom obimu koristite svoja "
        "prava predviđena Zakonom."
    )
    y -= 26
    for t in (tekst1, tekst2):
        p = Paragraph(t, stil)
        _, h = p.wrap(W - 2 * M, 400)
        p.drawOn(c, M, y - h)
        y -= h + 10

    # --- opcije saglasnosti ----------------------------------------------------
    y -= 6
    c.setFont("Lib", 10)
    c.drawString(M, y, "(   )  Saglasan sam")
    y -= 16
    c.drawString(M, y, "(   )  Nisam saglasan")
    y -= 24
    c.setFont("LibI", 9)
    c.drawString(M, y, "Napomena: Davalac podataka treba da štiklira ili zaokruži željeni odgovor.")

    # --- zatvaranje --------------------------------------------------------------
    y -= 26
    p = Paragraph(tekst3, stil_mali)
    _, h = p.wrap(W - 2 * M, 400)
    p.drawOn(c, M, y - h)
    y -= h + 16

    c.setFont("Lib", 10)
    c.drawString(M, y, f"{naziv} brine o Vašoj privatnosti. Hvala na poverenju!")

    # --- potpis davaoca --------------------------------------------------------
    y -= 70
    c.setFont("Lib", 10)
    c.drawCentredString(W - M - 110, y, "Davalac saglasnosti:")
    y -= 34
    c.setLineWidth(0.6)
    c.line(W - M - 220, y, W - M, y)
    c.setFont("Lib", 10)
    c.drawCentredString(W - M - 110, y - 14, ime)

    c.showPage()
    c.save()
    return buf.getvalue()
