"""Offline A4 ugovor/prijava; accepts raw contract data without persistence access.

Izgled: dot-matrix obrazac "PRIJAVA/UGOVOR" (monospace, crno na belom).
Zaglavlje agencije (logo, naziv, banke, licenca) je isto kao i na predračunu.
"""
import base64
import io
import os
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_RIGHT
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
def _mesec_pre(value):
    """Datum mesec dana pre zadatog (ograničen na poslednji dan tog meseca)."""
    d = _to_date(value)
    if not d:
        return None
    year, month = (d.year, d.month - 1) if d.month > 1 else (d.year - 1, 12)
    last = (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(d.day, last))


def _rok_placanja(raw):
    """Rok za 100% uplatu: u celosti → datum kreiranja aranžmana (danas) + 2 dana; delimično / nije izabrano → mesec dana pre datumod."""
    if str(raw.get("nacin_placanja") or "").strip() == "u_celosti":
        kreiran = _to_date(raw.get("danas"))
        return kreiran + timedelta(days=2) if kreiran else None
    return _mesec_pre(raw.get("datumod"))


def legal_clauses(naziv_agencije, placanje_do, lice_reklamacije="", delimicno=False):
    """Izjave i uslovi (Paragraph markup); naziv agencije iz podešavanja, rok plaćanja iz _rok_placanja,
    rečenica za reklamacije iz podešavanja (Osnovni podaci) — prazna = ne ispisuje se.
    delimicno=True → 40% odmah + ostatak do roka; inače 100% do roka (u celosti / nije izabrano)."""
    ag = f'"{escape(naziv_agencije)}"'
    if delimicno:
        placanje = (f"PLAĆANJE 40.00% ODMAH, OSTATAK DO {placanje_do.strftime('%d.%m.%Y.')}" if placanje_do else "PLAĆANJE 40.00% ODMAH")
    else:
        placanje = (f"PLAĆANJE 100.00% DO {placanje_do.strftime('%d.%m.%Y.')}" if placanje_do else "PLAĆANJE 100.00%")
    bold = lambda s: f'<font name="{SANS_B}">{s}</font>'
    return (
        f"Putniku, koji sa agencijom {ag} ugovori aranžman po principu odloženog plaćanja (na rate), garantuje se cena u visini realizovanog dela čekova. U slučaju promena i poremećaja na monetarnom tržištu, ili tržištu roba i usluga, stranka prihvata obavezu da snosi iznos uvećanih cena za nerealizovani deo odloženog plaćanja.",
        "Izjavljujem da ću, ukoliko agencija ne bude mogla da realizuje moje čekove ili administrativnu zabranu izvršiti svoju obavezu prema Organizatoru na drugi način.",
        "Organizator putniku izdaje vaučer 7 dana pred put isključivo za aranžman uplaćen i izmiren u celosti. Vaučer je jedini važeći dokument za korišćenje usluge koji putnik mora uručiti ovlašćenom agentu ili predstavniku agencije na destinaciji, a Organizator se obavezuje da će ugovorene usluge pružiti isključivo licima navedenim na vaučeru.",
        f"{bold('U cenu aranžmana nije uključena obavezna boravišna/ekološka taksa, koja se plaća na samoj destinaciji.')} Putnik je dužan da iznos takse plati na licu mesta predstavniku organizatora putovanja ili lokalnom grčkom partneru (inopartneru), u skladu sa važećim tarifama Republike Grčke za tekuću godinu. Potvrđujem potpisom da su mi uručeni Opšti uslovi i program putovanja agencije {ag} sa kojima sam saglasan-saglasna u svoje ime i ime navedenih putnika, da sam upoznat sa detaljnim dodatnim informacijama o svakoj smeštajnoj jedinici, koje se nalaze na internet stranici Agencije, i da jesam-nisam saglasan-saglasna, da me {ag} poštom, putem sms-a ili email-a, obaveštava o novim ponudama i specijalnim akcijama.",
        "Porez na dodatu vrednost nije obračunat po čl.35 st.7 Zakona o PDV-u. Obavezno prilikom uplate u poziv na broj upisati broj predračuna. Ugovor/Predračun je punovažan bez potpisa i pečata.",
        bold(placanje),
        "Putnik je upoznat sa mogućnošću putnog osiguranja i osiguranja od otkaza. Putniku je uručena garancija putovanja.",
    ) + ((bold(_text_recenice(lice_reklamacije)),) if (lice_reklamacije or "").strip() else ())


def _text_recenice(v) -> str:
    """Rečenica iz podešavanja (Osnovni podaci → Lice za reklamacije), escape za Paragraph."""
    return escape(str(v or "").strip())


LEGAL_CLAUSES = legal_clauses("ASTRA TRAVEL DOO", date(2026, 7, 30))

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


def dodatne_sume(dodatne):
    """Zbir dodatnih usluga (EUR, RSD) iz liste 'dodatne' — ide u ukupnu vrednost ugovora."""
    eur = din = Decimal(0)
    for stavka in dodatne or []:
        eur += _num(stavka.get("eur"))
        din += _num(stavka.get("din"))
    return eur, din


def ukupno_ugovora(raw, calc, dodatne):
    """Cena aranžmana kao u rezervaciji: naplata − cenadod (zamenjen dodatnim uslugama) + dodatne usluge."""
    deur, ddin = dodatne_sume(dodatne)
    return (_num(calc.get("naplata")) - _num(raw.get("cenadod")) + deur), ddin


def _amounts(ugovor):
    calc = ugovor.get("obracun") or ugovor
    raw = _raw(ugovor)
    eur = _decimal(ugovor.get("ukupno_eur"))
    ddin = dodatne_sume(ugovor.get("dodatne"))[1]
    if eur is None:
        eur = ukupno_ugovora(raw, calc, ugovor.get("dodatne"))[0]
    kurs = _decimal(ugovor.get("kurs"))
    rsd = _decimal(ugovor.get("ukupno_rsd"))
    if ugovor.get("ukupno_rsd") is None and kurs is not None and kurs > 0:
        rsd = (eur * kurs).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) + ddin
    return calc, eur, rsd, kurs


def _qr_text(value, limit):
    return re.sub(r"\s+", " ", str(value or "").replace("|", " ")).strip()[:limit]


def _normalizuj_racun(value) -> str | None:
    candidate = str(value or "").strip()
    if re.fullmatch(r"[0-9]{3}-[0-9]{1,13}-[0-9]{2}", candidate):
        bank, number, control = candidate.split("-")
        candidate = bank + number.zfill(13) + control
    return candidate if re.fullmatch(r"[0-9]{18}", candidate) else None


def ips_racuni(agencija: dict) -> list[tuple[str, str]]:
    """Važeći računi agencije kao (račun, naziv banke), bez duplikata, po redosledu podešavanja."""
    rezultat, videni = [], set()
    kandidati = [("racun", agencija.get("banka"))] + [
        (f"tekuci_racun{i}", agencija.get(f"banka{i}")) for i in range(1, 5)
    ]
    for key, banka in kandidati:
        account = _normalizuj_racun(agencija.get(key))
        if account and account not in videni:
            videni.add(account)
            rezultat.append((account, str(banka or "").strip()))
    return rezultat


def build_ugovor_ips_qr(ugovor: dict, agencija: dict, account: str | None = None) -> str | None:
    """Return a complete NBS IPS payment payload, never a partial/invalid QR."""
    if account is None:
        racuni = ips_racuni(agencija)
        account = racuni[0][0] if racuni else None
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


def _subagent_redovi(ugovor, raw):
    """Podaci subagenta (tabela Subagenti) za blok podnosioca; prazna lista ako nema subagenta."""
    sub = ugovor.get("subagent_info") or {}
    naziv = str(sub.get("naziv") or raw.get("subagent") or "").strip()
    if not naziv:
        return []
    adresa = ", ".join(str(x).strip() for x in (sub.get("adresa"), sub.get("mesto")) if str(x or "").strip())
    return _redovi_podnosioca((
        (("Naziv", naziv), ("PIB", sub.get("pib")), ("MB", sub.get("matbroj"))),
        (("Adresa", adresa),),
        (("E-mail", sub.get("email")), ("Telefon", sub.get("tel"))),
    ))


def _redovi_podnosioca(grupe):
    """Svaka grupa polja ide u jedan red ('Label: vrednost | Label: vrednost'); prazna polja se preskaču."""
    redovi = []
    for grupa in grupe:
        delovi = [str(value).strip() if label is None else f"{label}: {str(value).strip()}"
                  for label, value in grupa if str(value or "").strip()]
        if delovi:
            redovi.append(" | ".join(delovi))
    return redovi


def _polazak_dana(raw):
    """Polazak dana = datumod − 1 dan; '—' ako datum početka nije poznat."""
    od = _to_date(raw.get("datumod"))
    return (od - timedelta(days=1)).strftime("%d.%m.%Y") if od else "—"


def _nacin_placanja(raw):
    """aranzman.nacin_placanja: delimicno | u_celosti → tekst za ugovor; prazno → '—'."""
    return {"delimicno": "delimično", "u_celosti": "u celosti"}.get(str(raw.get("nacin_placanja") or "").strip(), "—")


def _tip_prevoza(raw):
    """Autobuski ako je bar jedan prevoz DA (isto pravilo kao „Vrsta prevoza“), inače Sopstveni."""
    return "Sopstveni" if not any(_flag(raw.get(k)) == "DA" for k in ("prevozow", "prevozrt")) else "Autobuski"


def _vrsta_prevoza(raw):
    """Tekst vrste prevoza (isti izvor kao red „Vrsta prevoza“ u PDF-u)."""
    return raw.get("vrsta_prevoza") or ("SOPSTVENI PREVOZ" if not any(_flag(raw.get(k)) == "DA" for k in ("prevozow", "prevozrt")) else "Aranžman sa prevozom")


def _period_tekst(raw):
    """Period: DD.MM – DD.MM.YYYY; kod aranžmana sa prevozom dodaje se (polazak DD.MM.YYYY) — dan ranije od datumod.
    Sopstveni prevoz: bez dela o polasku."""
    od, do = _to_date(raw.get("datumod")), _to_date(raw.get("datumdo"))
    if not od or not do:
        return f"{_text(raw.get('datumod'))} – {_text(raw.get('datumdo'))}"
    tekst = f"{od.strftime('%d.%m')} – {do.strftime('%d.%m.%Y')}"
    if "sopstven" not in str(_vrsta_prevoza(raw)).lower():
        tekst += f" (polazak {_polazak_dana(raw)})"
    return tekst


def _kategorija_sobe(opis):
    """Kategorija iz opisa sobe — prvi token ako je velikim slovima (STD, APT, APP, DPL, STD+GAL …); inače prazno.
    Brojevni tokeni ('1/2', '3+1') se ne uzimaju."""
    match = re.match(r"\s*([A-ZČĆŠŽĐ][A-ZČĆŠŽĐ+]*)(?=\s|$|,)", str(opis or ""))
    return match.group(1) if match else ""


def _prvi_deo(opis):
    """Prvi deo opisa dodatno do zareza ('1.SP, F+S' → '1.SP')."""
    return str(opis or "").split(",", 1)[0].strip()


def generate_ugovor_pdf(ugovor: dict, agencija: dict) -> bytes:
    """Render supplied raw data and historical-rate totals, without network calls."""
    _ensure_fonts()
    _ensure_sans()
    raw = _raw(ugovor)
    calc, eur, rsd, kurs = _amounts(ugovor)
    uplaceno = _num(ugovor.get("uplaceno_eur"))
    width, height = A4
    margin = 30
    body_width = width - 2 * margin
    styles = {
        "mono": ParagraphStyle("mono", fontName=SANS, fontSize=8.5, leading=11, textColor=INK),
        "monoB": ParagraphStyle("monoB", fontName=SANS_B, fontSize=8.5, leading=11, textColor=INK),
        "right": ParagraphStyle("right", fontName=SANS, fontSize=8.5, leading=11, textColor=INK, alignment=TA_RIGHT),
        "rightB": ParagraphStyle("rightB", fontName=SANS_B, fontSize=9, leading=11, textColor=INK, alignment=TA_RIGHT),
        "small": ParagraphStyle("small", fontName=SANS, fontSize=7.5, leading=9.5, textColor=MUTED),
        "small_right": ParagraphStyle("small_right", fontName=SANS, fontSize=7.5, leading=9.5, textColor=MUTED, alignment=TA_RIGHT),
        "small_center": ParagraphStyle("small_center", fontName=SANS_B, fontSize=7.5, leading=9.5, textColor=INK, alignment=TA_CENTER),
        "legal": ParagraphStyle("legal", fontName=SANS, fontSize=6.2, leading=7.5, textColor=INK, spaceAfter=0.8, alignment=TA_JUSTIFY),
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
    header_height = max(65, sum(line.wrap(header_width, height)[1] for line in header_lines))

    def page_header(c, doc):
        c.saveState()
        if doc.page > 1:
            c.restoreState()
            return
        y = height - 25
        for line in header_lines:
            _, h = line.wrap(header_width, height)
            line.drawOn(c, margin, y - h)
            y -= h
        if logo:
            iw, ih = logo.getSize()
            scale = min(95 / iw, 55 / ih)
            c.drawImage(logo, width - margin - iw * scale, height - 35 - ih * scale,
                        iw * scale, ih * scale, mask="auto")
        c.setStrokeColor(colors.HexColor("#CBD4DF"))
        c.line(margin, height - 35 - header_height, width - margin, height - 35 - header_height)
        c.restoreState()

    def frames(top):
        return [Frame(margin, 38, body_width, top - 38, id="body",
                      leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)]

    def grid(rows, widths, header=False, last_line=False, box=False):
        """Tabela bez okvira u stilu obrasca; opciono podvučen red zaglavlja ili svetlo sivi okvir."""
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
        if box:
            style += [("BOX", (0, 0), (-1, -1), .6, colors.HexColor("#C8C8C8")),
                      ("TOPPADDING", (0, 0), (-1, 0), 3), ("BOTTOMPADDING", (0, -1), (-1, -1), 3),
                      ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5)]
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
                    [p(f"KEPTP: {_text(raw.get('keptp'))}", "right")] + (
                        [p(f"JID: {str(raw.get('mesto_cis')).strip()}", "right")] if str(raw.get("mesto_cis") or "").strip() else [])]], [0.7, 0.3]),
             p(f"UGOVOR/PREDRACUN Br.: {_text(raw.get('kljuc'))}", "title")]

    # --- putovanje -------------------------------------------------------------
    nights = _nights(raw.get("datumod"), raw.get("datumdo"))
    # opis smeštaja za ugovor (Osnovni podaci): 'dugacak' (podrazumevano) ili 'kratak' (samo struktura)
    dugacak_opis = str(agencija.get("opis_smestaja_ugovor") or "dugacak").strip() != "kratak"
    story.append(grid([
        [p("Period:"), p(_period_tekst(raw)), p("Trajanje:"), p(f"{nights} noćenja" if nights is not None else "—", "monoB")],
        [p("Destinacija:"), p(_text(raw.get("destinacija"))), p("Mesto:"), p(_text(raw.get("mesto")))],
        [p("Smeštaj:"), [p(_text(raw.get("naziv")), "monoB")] + (
            [p(f"Napomena: {str(raw.get('smestaj_napomena')).strip()}", "small")] if str(raw.get("smestaj_napomena") or "").strip() else []),
         p("Soba:"), p(" | ".join(x for x in (
             # kratak opis: samo struktura, bez broja/spratnosti/dodatnog teksta
             f"broj {_text(raw.get('soba'))}" if dugacak_opis else "",
             f"struktura {' '.join(x for x in (str(raw.get('soba_tip') or '').strip(), _kategorija_sobe(raw.get('soba_opis'))) if x)}".rstrip(),
             f"spratnost: {_prvi_deo(raw.get('soba_opis_dodatno'))}" if (dugacak_opis and _prvi_deo(raw.get("soba_opis_dodatno"))) else "",
             str(raw.get("soba_opis_ugovor") or "").strip() if dugacak_opis else "") if x))],
        [p("Tip prevoza:"), p(_tip_prevoza(raw)), p("Tip plaćanja:"), p(_nacin_placanja(raw))],
    ], [0.13, 0.37, 0.12, 0.38], box=True))

    # --- putnici (nosilac + saputnici) -------------------------------------------
    story.append(Spacer(1, 8))
    story.append(p("PUTNICI", "section"))
    rows = [[p("Prezime i ime", "monoB"), p("Uzrast", "monoB"),
             p("Prevoz RT", "monoB"), p("Ulazak", "monoB"), p("Dolazak", "monoB"), p("Izlazak", "monoB")],
            [p(_text(raw.get("putnik")), "monoB"), p(_text(raw.get("uzrast"))),
             p(_flag(raw.get("prevozrt"))),
             p(_text(raw.get("ulazak"))), p(_text(raw.get("mesto"))), p(_text(raw.get("mesto_izlaska")))]]
    companions = ugovor.get("putnici_detalji") or []
    for person in companions:
        rows.append([p(_text(person.get("saputnik") or person.get("putnik")), "monoB"), p(_text(person.get("uzrast"))),
                     p(_flag(person.get("prevozrt"))),
                     p(_text(person.get("ulazak"))), p(_text(raw.get("mesto"))), p(_text(person.get("mesto_izlaska")))])
    story.append(grid(rows, [0.28, 0.09, 0.11, 0.16, 0.18, 0.18], header=True, box=True))
    if not companions:
        story.append(p("Nema prijavljenih saputnika.", "small"))

    # --- stavke obračuna (Htl/Prv | Opis | Kol | Cena/EUR | Iznos/EUR) -----------
    story.append(Spacer(1, 8))
    story.append(p("OBRAČUN", "section"))
    kol_a, cen_a = _num(raw.get("kolaranz")), _num(raw.get("cenaaranz"))
    kol_c, cen_c = _num(raw.get("kolchd")), _num(raw.get("cenachd"))
    kol_ow, cen_ow = _num(raw.get("kolow")), _num(raw.get("cenaow"))
    kol_rt, cen_rt = _num(raw.get("kolrt")), _num(raw.get("cenart"))
    kol_vi, cen_vi = _num(raw.get("kolviza")), _num(raw.get("cenaviza"))
    popust = _num(calc.get("popust"))
    provizija = _num(calc.get("provizija"))
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
            stavka("SMEŠTAJ", "Smeštaj (odrasli i deca)", None, None, smestaj)
        else:
            stavka("SMEŠTAJ", "Smeštaj", kol_a or None, cen_a or None, smestaj)
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
    if provizija:
        stavka("PROVIZIJA", "Provizija agencije", None, None, -provizija)
    doplate_eur, _ = dodatne_sume(ugovor.get("dodatne"))
    if doplate_eur:
        stavke.append([p("DOPLATE"), p(""), p(""), p(""), p(f"+{fmt_num(doplate_eur)}", "right")])
    if dodatno:
        stavka("DODATNO", "Dodatne usluge / ostalo", None, None, dodatno)
    if osiguranje:
        stavka("OSIG.", "Zdravstveno osiguranje", None, None, osiguranje)
    story.append(grid(stavke, [0.13, 0.41, 0.09, 0.16, 0.21], header=True, box=True))

    # --- rekapitulacija ----------------------------------------------------------
    story.append(Spacer(1, 8))
    story.append(grid([
        [p("REKAPITULACIJA OBRAČUNA:", "monoB"), p("CENA ARANŽMANA", "monoB"),
         p(f"{fmt_num(eur)} EUR", "rightB")],
        ["", p(f"UPLAĆENO {fmt_num(uplaceno)} EUR", "monoB"),
         p(f"ZA UPLATU {fmt_num(eur - uplaceno)} EUR", "rightB")],
    ], [0.42, 0.30, 0.28]))
    story.append(p(f"Srednji kurs NBS (1 EUR / RSD): {f'{kurs:.2f}' if kurs else 'Nije dostupan'} | "
                   f"Datum kursa: {_text(ugovor.get('kurs_datum'))}. "
                   "Plaćanje u dinarskoj protivvrednosti po srednjem kursu NBS na dan uplate.", "small"))

    extras = ugovor.get("dodatne") or []
    if extras:
        story.append(p("DODATNE USLUGE / OSTALO (uračunato u ukupnu vrednost)", "section"))
        for index, item in enumerate(extras, 1):
            naziv = _text(item.get("usluga")).replace("PLAĆENO MESTO - ", "PLAĆENO MESTO U AUTOBUSU - ", 1)
            story.append(p(f"{index}. {naziv} — {fmt_num(item.get('eur'))} EUR / {fmt_num(item.get('din'))} RSD"))

    # --- napomena ----------------------------------------------------------------
    story.append(Spacer(1, 8))
    story.append(p(f"Napomena: {_text(raw.get('napomena1'))}"))
    story.append(p("Molimo Vas da vreme polaska proverite dan pre putovanja.", "small"))

    # --- podnosilac ------------------------------------------------------------------
    # --- QR za plaćanje (u istom redu sa podnosiocem) -----------------------------------
    payloads = [(build_ugovor_ips_qr(ugovor, agencija, racun), banka)
                for racun, banka in ips_racuni(agencija)[:2]]
    payloads = [(payload, banka) for payload, banka in payloads if payload]
    qr_cell = [p(QR_WARNING, "small")]
    if payloads:
        class QRImage(Flowable):
            """QR centriran u svojoj koloni (širina iz wrap-a)."""
            def __init__(self, image, size=90):
                super().__init__()
                self.image = image
                self.size = size
                self.avail = 0

            def wrap(self, avail_w, avail_h):
                self.avail = avail_w
                return avail_w, self.size

            def draw(self):
                self.canv.drawImage(self.image, (self.avail - self.size) / 2, 0, self.size, self.size)

        kolone, caption = [], []
        for payload, banka in payloads:
            code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,
                                 box_size=10, border=4)
            code.add_data(payload.encode("utf-8"))
            code.make(fit=True)
            buffer = io.BytesIO()
            code.make_image(fill_color="black", back_color="white").save(buffer, format="PNG")
            buffer.seek(0)
            kolone.append(QRImage(ImageReader(buffer)))
            caption.append(p(banka or "Banka nije navedena", "small_center"))
        qr_block = Table([kolone, caption],
                         colWidths=[100 if len(kolone) == 2 else 200] * len(kolone),
                         style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                           ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                           ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
        qr_cell = [qr_block]

    ulogovan = _text(ugovor.get("ulogovan")).strip() if ugovor.get("ulogovan") else ""
    sluzbenik = f" ({ulogovan})" if ulogovan else ""
    story.append(Spacer(1, 8))
    story.append(KeepTogether([grid([[
        [p("Podnosilac prijave:", "monoB"),
         p("\n".join(x for x in (_subagent_redovi(ugovor, raw) or _redovi_podnosioca((
             ((None, _text(raw.get("putnik"))),),
             (("Adresa", ", ".join(_text(raw.get(k)).strip() for k in ("adresa", "grad") if _text(raw.get(k)).strip())),),
             (("Tel.", _text(raw.get("telefon")) if raw.get("telefon") else ""),
              ("E-mail", _text(raw.get("email")) if raw.get("email") else "")),
         )))
         if x), "monoB"),
         Spacer(1, 24),
         p("Potpis stranke: ________________________"),
         Spacer(1, 14),
         p(f"Potpis službenika{sluzbenik}: ______________________"),
         p("M. P.", "right"),
        ],
        qr_cell,
    ]], [0.60, 0.40])]))

    # --- izjave ----------------------------------------------------------------------
    story.append(Spacer(1, 3))
    story.append(p("IZJAVE I USLOVI PUTOVANJA", "section"))
    for clause in legal_clauses(agencija.get("naziv") or agencija.get("poslovno_ime") or "",
                                _rok_placanja(raw),
                                agencija.get("lice_reklamacije") or "",
                                delimicno=str(raw.get("nacin_placanja") or "").strip() == "delimicno"):
        story.append(Paragraph(clause, styles["legal"]))
    doc.build(story)
    return doc_out.getvalue()
