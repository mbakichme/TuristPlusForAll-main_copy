"""
Generisanje PDF predračuna sa NBS IPS QR kodom.

Raspored prati referentni šablon agencije:
  - header: podaci agencije (iz "Osnovni podaci") + logo (assets/logo.png)
  - dve sive kutije: Naziv kupca (subagent) | Predračun broj + datumi
  - tabela "Opis usluge / Iznos (RSD)" sa tačkastim vodiljama
  - donji blok: PDV napomena, način plaćanja, uputstvo + NBS IPS QR kod + Ovlašćeno lice

QR kod prati specifikaciju Narodne banke Srbije (IPS QR kod):
    K:PR|V:01|C:1|R:<18 cifara>|N:<naziv>|I:RSD<iznos>|SF:<šifra>|S:<svrha>|RO:<poziv>|P:<platilac>
- polja se razdvajaju znakom "|", zapis NE počinje i NE završava se znakom "|"
- R: broj računa primaoca — fiksno 18 cifara, bez crtica
- I: oznaka valute + iznos bez razmaka, decimalni zarez, max 2 decimale
- RO: prve dve cifre model obračuna (00 = nije obračunat po modelu), max 25 karaktera
- opciona polja bez vrednosti se potpuno izostavljaju (nikad "|S:|")
"""
import io
import os
import re
from datetime import datetime

import qrcode
from qrcode.constants import ERROR_CORRECT_M
from reportlab.lib.pagesizes import A4
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas

# ─── Boje (neutralna paleta po referenci) ────────────────────────────────────
INK = HexColor("#111111")        # glavni tekst
GRAY = HexColor("#333333")       # sekundarni tekst
SOFT = HexColor("#555555")       # treci tekst
BOXBG = HexColor("#ECEFF2")      # sive kutije
BOXBAR = HexColor("#64707C")     # tamno-siva gornja ivica kutije
THEAD = HexColor("#E3E7EA")      # header tabele
LINE = HexColor("#B7BEC5")       # linije
DOT = HexColor("#8A9299")        # tačkaste vodilje
WHITE = HexColor("#FFFFFF")

FONT_DIR_CANDIDATES = [
    # fontovi ugradjeni u projekat (rade i u publikovanom kontejneru)
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "fonts"),
    # sistemski fontovi
    "/usr/share/fonts/truetype/liberation",
    "/usr/share/fonts/dejavu",
]

LOGO_CANDIDATES = ["logo.png", "logo.jpg", "logo.jpeg"]

_FONTS_READY = False


def _ensure_fonts():
    """Registruj TTF fontove (Liberation/DejaVu) — podržavaju č ć š ž đ.

    Ako ni jedan TTF nije dostupan, koristi ugrađene Type1 fontove
    (Helvetica) kao alias — dijakritika tada može biti pogrešna, ali
    PDF se generiše bez greške.
    """
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
        # fallback: alias ugrađenih Type1 fontova (TTFont NE prima imena
        # ugrađenih fontova — koristi se pdfmetrics.Font alias)
        from reportlab.pdfbase.pdfmetrics import Font
        pdfmetrics.registerFont(Font("Lib", "Helvetica", "WinAnsiEncoding"))
        pdfmetrics.registerFont(Font("LibB", "Helvetica-Bold", "WinAnsiEncoding"))
        pdfmetrics.registerFont(Font("LibI", "Helvetica-Oblique", "WinAnsiEncoding"))
    _FONTS_READY = True


# ─── NBS IPS QR kod ──────────────────────────────────────────────────────────
def normalize_account(racun: str) -> str | None:
    """Broj računa (npr. 265-3710310000481-09) → 18 cifara bez crtica."""
    if not racun:
        return None
    digits = re.sub(r"\D", "", racun)
    if len(digits) == 18:
        return digits
    parts = [p for p in racun.strip().split("-") if p]
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        return parts[0].zfill(3) + parts[1].zfill(13) + parts[2].zfill(2)
    return digits if len(digits) >= 12 else None


def fmt_amount_rsd(value) -> str | None:
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    s = f"{v:.2f}".rstrip("0").rstrip(",")  # 1-2 decimale
    if s.endswith("."):
        s = s[:-1]
    return s.replace(".", ",")


def fmt_num(value) -> str:
    """Prikaz iznosa: 57.057,75 (sr-RS)."""
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        v = 0.0
    s = f"{v:,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def build_ips_qr_string(pred: dict, agencija: dict) -> str:
    racun18 = normalize_account(agencija.get("racun") or "")
    primalac = (agencija.get("naziv") or agencija.get("poslovno_ime") or "").strip()[:70]
    iznos = fmt_amount_rsd(pred.get("zaduzenje"))

    parts = ["K:PR", "V:01", "C:1"]
    if racun18:
        parts.append(f"R:{racun18}")
    if primalac:
        parts.append(f"N:{primalac}")
    if iznos:
        parts.append(f"I:RSD{iznos}")

    broj = re.sub(r"\s+", "", str(pred.get("broj_predracuna") or ""))
    parts.append("SF:221")  # promet robe i usluga — finalna potrošnja (bezgotovinsko)

    svrha = f"Predračun br. {broj}"[:35]
    if svrha:
        parts.append(f"S:{svrha}")

    # RO: model 00 (nije obračunat po modelu) + broj predracuna; samo cifre i crtice
    if broj:
        poziv = re.sub(r"[^0-9-]", "-", broj)[:23]
        parts.append(f"RO:00{poziv}")

    # platilac = kupac predračuna (subagent), fallback na nosioca
    platilac = (str(pred.get("subagent") or pred.get("nosilac") or "")).strip()[:70]
    if platilac:
        parts.append(f"P:{platilac}")

    return "|".join(parts)


def build_qr_image(qr_string: str) -> ImageReader:
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, box_size=10, border=1)
    qr.add_data(qr_string.encode("utf-8"))
    qr.make(fit=True)
    img = qr.make_image(fill_color="#111111", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return ImageReader(buf)


# ─── Crtanje pomoćne funkcije ────────────────────────────────────────────────
def _c(c: rl_canvas.Canvas, x: float, y: float, text: str, font: str, size: float, color, align: str = "l") -> float:
    """Crtaj tekst; vraća istu y koordinatu."""
    c.setFont(font, size)
    c.setFillColor(color)
    if align == "c":
        c.drawCentredString(x, y, text)
        return y
    if align == "r":
        c.drawRightString(x, y, text)
        return y
    c.drawString(x, y, text)
    return y


def _wrapped(c, x, y, text, font, size, color, max_w):
    """Prost tekst u više linija; vraća novu y."""
    if not text:
        return y
    words = text.split()
    line = ""
    for w in words:
        trial = (line + " " + w).strip()
        if c.stringWidth(trial, font, size) > max_w and line:
            y = _c(c, x, y, line, font, size, color)
            y -= size + 2.5
            line = w
        else:
            line = trial
    if line:
        y = _c(c, x, y, line, font, size, color)
        y -= size + 2.5
    return y


def _dots(c, x_from, x_to, y):
    """Tačkasta vodilja između teksta i iznosa."""
    if x_to - x_from < 8:
        return
    c.setStrokeColor(DOT)
    c.setLineWidth(0.9)
    c.setDash(1, 3)
    c.line(x_from, y + 1.5, x_to, y + 1.5)
    c.setDash()


def _logo_source(data_url: str | None):
    """Logo iz baze (data URL, tip 'logo' u dokumenti); bez njega statički fallback."""
    if data_url and "," in data_url:
        import base64 as _b64
        try:
            return io.BytesIO(_b64.b64decode(data_url.split(",", 1)[1], validate=True))
        except (ValueError, TypeError):
            return None
    return _logo_path()


def _logo_path() -> str | None:
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
    for fname in LOGO_CANDIDATES:
        path = os.path.join(base, fname)
        if os.path.exists(path):
            return path
    return None


# ─── Glavni generator ────────────────────────────────────────────────────────
def generate_predracun_pdf(pred: dict, agencija: dict) -> bytes:
    _ensure_fonts()
    W, H = A4  # 595 x 842
    M = 40
    CW = W - 2 * M
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"Predračun {pred.get('broj_predracuna', '')}")
    c.setAuthor((agencija.get("naziv") or "Agencija")[:120])

    broj = str(pred.get("broj_predracuna") or "")
    datum = pred.get("datum_fmt") or (str(pred.get("datum") or "")[:10])
    datumod = pred.get("a_datumod") or ""
    datumdo = pred.get("a_datumdo") or ""

    zaduzenje = float(pred.get("zaduzenje") or 0)
    provizija = float(pred.get("provizija") or 0)
    ukupno_naplata = zaduzenje - provizija

    # ── Header: podaci agencije + logo ──
    y = H - 52
    naziv = agencija.get("naziv") or agencija.get("poslovno_ime") or "Agencija"
    _c(c, M, y, naziv, "LibB", 16, INK)
    logo = _logo_source(agencija.get("logo_data_url"))
    if logo:
        try:
            img = ImageReader(logo)
            iw, ih = img.getSize()
            lh = 58
            lw = min(150, lh * iw / ih)
            c.drawImage(img, W - M - lw, y - lh + 12, lw, lh, mask="auto")
        except Exception:
            pass
    y -= 15
    adresa = " ".join(x for x in [(agencija.get("ulica") or ""), (agencija.get("broj") or "")] if x)
    mesto = " ".join(x for x in [(agencija.get("post_broj") or ""), (agencija.get("mesto") or "")] if x)
    y = _c(c, M, y, ", ".join(x for x in [adresa, mesto] if x), "Lib", 9.5, INK) - 13
    kontakt = ", ".join(x for x in [agencija.get("telefon1"), agencija.get("email1")] if x)
    y = _c(c, M, y, kontakt, "Lib", 9.5, INK) - 13
    pib_mb = "  |  ".join(x for x in [
        f"PIB {agencija['pib']}" if agencija.get("pib") else "",
        f"MB {agencija['mb']}" if agencija.get("mb") else "",
    ] if x)
    if pib_mb:
        y = _c(c, M, y, pib_mb, "Lib", 9.5, INK) - 13
    banke = agencija.get("banke") or []
    if not banke:
        racun = agencija.get("racun") or pred.get("racun") or ""
        banka = agencija.get("banka") or ""
        banke = [f"{racun}" + (f" ({banka})" if banka else "")] if racun else []
    for red in banke:
        y = _c(c, M, y, red, "LibB", 10, INK) - 13
    if agencija.get("licenca"):
        y = _c(c, M, y, f"Licenca: {agencija['licenca']}", "Lib", 9.5, INK) - 13

    y -= 14
    c.setStrokeColor(LINE); c.setLineWidth(1)
    c.line(M, y, W - M, y)

    # ── Kutije: Kupac | Predračun ──
    y -= 16
    box_h = 118
    box_w = (CW - 14) / 2
    by = y - box_h

    # — leva kutija: Naziv kupca —
    c.setFillColor(BOXBG); c.setStrokeColor(LINE); c.setLineWidth(0.7)
    c.rect(M, by, box_w, box_h, fill=1, stroke=1)
    c.setFillColor(BOXBAR)
    c.rect(M, by + box_h - 3.5, box_w, 3.5, fill=1, stroke=0)
    bx = M + 10
    ty = y - 20
    ty = _c(c, bx, ty, "Naziv kupca:", "Lib", 9.5, GRAY) - 16
    kupac = (pred.get("subagent") or pred.get("nosilac") or "—").strip()
    ty = _c(c, bx, ty, kupac[:36], "LibB", 12.5, INK) - 14
    if (pred.get("adresa") or "").strip():
        ty = _c(c, bx, ty, f"Adresa: {pred['adresa']}"[:60], "Lib", 9, GRAY) - 12.5
    if (pred.get("mesto") or "").strip():
        _c(c, bx, ty, f"Mesto: {pred['mesto']}"[:60], "Lib", 9, GRAY)

    # — desna kutija: Predračun broj + datumi —
    rx = M + box_w + 14
    c.setFillColor(BOXBG); c.setStrokeColor(LINE); c.setLineWidth(0.7)
    c.rect(rx, by, box_w, box_h, fill=1, stroke=1)
    c.setFillColor(BOXBAR)
    c.rect(rx, by + box_h - 3.5, box_w, 3.5, fill=1, stroke=0)
    bx = rx + 10
    ty = y - 20
    ty = _c(c, bx, ty, f"Predračun broj: {broj}", "LibB", 12.5, INK) - 14
    for line_txt in [
        f"Datum izdavanja: {datum}",
        f"Datum prometa: {datumdo or datum}",
        f"Datum dospeća: {datumdo or datum}",
        "Valuta: RSD",
        f"Iznos za plaćanje: {fmt_num(zaduzenje)} RSD",
        f"Poziv na broj: {broj}",
    ]:
        ty = _c(c, bx, ty, line_txt[:62], "Lib", 9, INK) - 12

    # ── Tabela: Opis usluge | Iznos (RSD) ──
    y = by - 22
    col_r = W - M - 150          # leva ivica kolone sa iznosima
    head_h = 20
    c.setFillColor(THEAD)
    c.rect(M, y - head_h, CW, head_h, fill=1, stroke=0)
    _c(c, M + 8, y - head_h + 6, "Opis usluge", "Lib", 9.5, INK)
    _c(c, W - M - 8, y - head_h + 6, "Iznos (RSD)", "Lib", 9.5, INK, align="r")
    y -= head_h + 18

    # — opis usluge —
    y = _c(c, M + 10, y, "Zadužujemo Vas na ime troškova aranžmana u periodu:", "Lib", 9.5, INK) - 13
    y = _c(c, M + 10, y, f"{datumod or '—'} - {datumdo or '—'}", "Lib", 9.5, INK) - 20
    aranzman_txt = " / ".join(x for x in [pred.get("a_mesto") or "", pred.get("destinacija") or ""] if x)
    y = _c(c, M + 10, y, f"Aranžman: {aranzman_txt}"[:90], "Lib", 9.5, INK) - 20
    y = _c(c, M + 10, y, f"Na ime: {pred.get('nosilac') or '—'}", "Lib", 9.5, INK) - 13
    saputnici = [s.strip() for s in (pred.get("saputnik") or "").split(",") if s.strip()]
    for s in saputnici[:4]:
        y = _c(c, M + 10, y, s[:60], "Lib", 9.5, INK) - 13
    y -= 7
    y = _c(c, M + 10, y, f"Po ugovoru broj: {pred.get('ugovor') or '—'}", "Lib", 9.5, INK) - 20

    # — stavke sa tačkastim vodiljama —
    def stavka(label, value, bold=True, size=10):
        nonlocal y
        f = "LibB" if bold else "Lib"
        y = _c(c, M + 10, y, label, "Lib", 9.5, INK)
        lw = c.stringWidth(label, "Lib", 9.5)
        _dots(c, M + 10 + lw + 6, col_r - 10, y)
        _c(c, W - M - 8, y, fmt_num(value), f, size, INK, align="r")
        y -= 17

    stavka("Iznos", zaduzenje)
    stavka("Provizija", provizija)
    y -= 8
    c.setStrokeColor(LINE); c.setLineWidth(0.8)
    c.line(M, y + 5, W - M, y + 5)
    y -= 6
    stavka("Ukupno za naplatu", ukupno_naplata, size=10.5)
    y -= 12

    # ── Donji blok: napomene, QR ispod teksta, potpis donji desni ──
    qr_side = 96

    ty = y - 4
    ty = _c(c, M, ty, "PDV uključen u cenu po članu 35, Zakona o PDV-u.", "Lib", 9.5, INK) - 14
    if (pred.get("nacin") or "").strip():
        ty = _c(c, M, ty, f"Način plaćanja: {pred['nacin']}", "Lib", 9.5, INK) - 14
    if (pred.get("napomena") or "").strip():
        ty = _wrapped(c, M, ty, f"Napomena: {pred['napomena']}".strip(), "Lib", 9.5, INK, CW) - 1
    racun = agencija.get("racun") or pred.get("racun") or ""
    ty = _c(c, M, ty, f"Uplatu izvršiti na račun broj {racun}, sa pozivom na broj {broj}"[:95], "Lib", 9.5, INK) - 14
    ty = _c(c, M, ty, "Dokument dostavljen e-mailom je validan bez potpisa i pečata", "Lib", 9.5, INK)

    # — QR kod ispod teksta —
    qr_y = ty - 14 - qr_side
    if qr_y > 30:
        qr_string = build_ips_qr_string(pred, agencija)
        c.setFillColor(WHITE); c.setStrokeColor(LINE); c.setLineWidth(0.7)
        c.rect(M - 7, qr_y - 7, qr_side + 14, qr_side + 14, fill=1, stroke=1)
        c.drawImage(build_qr_image(qr_string), M, qr_y, qr_side, qr_side)
        _c(c, M + qr_side / 2, qr_y - 15, "NBS IPS QR KOD", "LibB", 6.5, INK, align="c")

    # — Ovlašćeno lice: fiksno donji desni ugao —
    _c(c, W - M - 105, 92, "Ovlašćeno lice:", "Lib", 9.5, INK, align="c")
    c.setStrokeColor(INK); c.setLineWidth(0.8)
    c.line(W - M - 190, 40, W - M, 40)

    c.showPage()
    c.save()
    return buf.getvalue()
