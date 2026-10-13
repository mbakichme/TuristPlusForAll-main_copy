"""Offline test: NBS IPS QR string + PDF generacija."""
import re

from predracun_pdf import (
    build_ips_qr_string, build_qr_image, generate_predracun_pdf, normalize_account,
)

# ── Test normalizacije računa (NBS primeri iz specifikacije) ──
assert normalize_account("840-955845-10") == "840000000095584510", normalize_account("840-955845-10")
assert normalize_account("165-55-74") == "165000000000005574", normalize_account("165-55-74")
assert normalize_account("310-1234567891211-86") == "310123456789121186"
assert normalize_account("265-3710310000481-09") == "265371031000048109"
print("normalize_account OK")

pred = {
    "broj_predracuna": "3668-1/26",
    "datum_fmt": "17.09.2026",
    "nosilac": "RAKIĆ MARINA",
    "saputnik": "MARKO RAKIĆ",
    "destinacija": "Grčka - Halkidiki",
    "period": "01.07.2026 - 11.07.2026",
    "provizija": 2100.0,
    "zaduzenje": 57057.75,
    "subagent": "ODISEJ TRAVEL & SERVICE PLUS*",
    "adresa": "Kneza Miloša 12",
    "mesto": "Čačak",
    "ugovor": "3668/26",
    "organizator": "Oktopod Travel",
    "poslovnica": "Čačak",
    "nacin": "Avans 100%",
    "napomena": "Test napomena sa š č ć ž đ slovima.",
    "racun": "265-3710310000481-09",
}
agencija = {
    "naziv": "Agencija OKTOPOD d.o.o.",
    "poslovno_ime": "",
    "ulica": "Trg oslobođenja",
    "broj": "5",
    "post_broj": "32000",
    "mesto": "Čačak",
    "drzava": "Srbija",
    "pib": "100000000",
    "mb": "20000000",
    "telefon1": "032/000-000",
    "email1": "www@oktopod.rs",
    "racun": "265-3710310000481-09",
    "banka": "Komercijalna banka",
}

qr = build_ips_qr_string(pred, agencija)
print("QR:", qr)

# ── Validacija prema NBS specifikaciji ──
assert not qr.startswith("|") and not qr.endswith("|"), "ne sme početi/završiti pipe"
assert "||" not in qr and " |" not in qr and "| " not in qr, "bez praznih polja"
parts = qr.split("|")
tags = [p.split(":", 1)[0] for p in parts]
assert tags[:5] == ["K", "V", "C", "R", "N"], tags
r = [p for p in parts if p.startswith("R:")][0][2:]
assert len(r) == 18 and r.isdigit(), f"R mora biti 18 cifara: {r}"
i = [p for p in parts if p.startswith("I:")][0][2:]
assert re.match(r"^RSD\d+,\d{1,2}$", i), f"I format: {i}"
sf = [p for p in parts if p.startswith("SF:")][0][3:]
assert len(sf) == 3 and sf.isdigit(), sf
ro = [p for p in parts if p.startswith("RO:")][0][3:]
assert len(ro) <= 25 and ro[:2].isdigit(), ro
s = [p for p in parts if p.startswith("S:")][0][2:]
assert len(s) <= 35, s
print("NBS spec validacija OK")

img = build_qr_image(qr)
print("QR image OK:", img.getSize())

pdf = generate_predracun_pdf(pred, agencija)
with open("/tmp/test_predracun.pdf", "wb") as f:
    f.write(pdf)
print(f"PDF OK: {len(pdf)} bytes -> /tmp/test_predracun.pdf")
