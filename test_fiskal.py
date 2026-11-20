"""Unit test fiskalizacije — bez poziva živog fiskalnog servisa (pravi račune).

Pokretanje: uv run python test_fiskal.py
"""
from urllib.parse import parse_qs, urlsplit

import httpx

import fiskal

FAILS = 0


def check(naziv, uslov):
    global FAILS
    print(("OK   " if uslov else "FAIL ") + naziv)
    if not uslov:
        FAILS += 1


# 1) mapiranje načina plaćanja
check("Gotovina → gotovina", fiskal.tip_placanja_fiskal("Gotovina") == "gotovina")
check("Ček → cek", fiskal.tip_placanja_fiskal("Ček") == "cek")
check("Vaučer → vaucer", fiskal.tip_placanja_fiskal("Vaučer") == "vaucer")
check("IPC → ipc", fiskal.tip_placanja_fiskal("IPC") == "ipc")
try:
    fiskal.tip_placanja_fiskal("Bitcoin")
    check("nepoznat nacin baca ValueError", False)
except ValueError:
    check("nepoznat nacin baca ValueError", True)

# 2) parametri zahteva
p = fiskal.build_fiskal_params(
    uplata_kljuc=12,
    broj_priznanice="12/27",
    aranzman_kljuc="12/27",
    artikal="12/27 / SARTI/12.06.2027",
    nacin="Ček",
    din=53604,
    datum_iso="2027-06-01",
    pib="123456789",
    poslovnica="Novi Sad",
    korisnik="Marko Marković",
    cashier="Marko Marković",
)
check("iznos formatiran 2 decimale", p["iznos"] == "53604.00")
check("broj_priznanice = kljuc uplate", p["broj_priznanice"] == "12")
check("req_id = broj priznanice 12-27", p["req_id"] == "12-27")
check("broj_ugovora = aranzman.kljuc", p["broj_ugovora"] == "12/27")
check("artikli = jedan string", p["artikli"] == "12/27 / SARTI/12.06.2027")
check("opis_racuna i napomena = artikal", p["opis_racuna"] == p["napomena"] == p["artikli"])
check("tip_poreza=12, print=true, stampa=S", (p["tip_poreza"], p["print"], p["stampa"]) == ("12", "true", "S"))
check("tip_racuna=A, pdv/advanceTAX/iznos1/iznos2 = 0", all(p[k] == "0" for k in ("pdv", "advanceTAX", "iznos1", "iznos2")) and p["tip_racuna"] == "A")
check("pib_pravnog_lica i pib_organizatora = PIB agencije", p["pib_pravnog_lica"] == p["pib_organizatora"] == "123456789")
check("cashier = ime i prezime korisnika", p["cashier"] == "Marko Marković")
check("ime_racunara i stampac = ime i prezime", p["ime_racunara"] == p["stampac"] == "Marko Marković")
check("dodatna polja: tip_poreza1/2 prazni, advanceTAX1/2 = 0, artikli1/2 prazni",
      (p["tip_poreza1"], p["tip_poreza2"], p["advanceTAX1"], p["advanceTAX2"], p["artikli1"], p["artikli2"])
      == ("", "", "0", "0", "", ""))
# 5) parsiranje dajInvoice odgovora
inv_json = '{"success": true, "method": "dajInvoice", "invoice": "MSMV7XP7-Dt1Ov2o0-4299", "link_racuna": "https://sandbox.suf.purs.gov.rs/v/?vl=abc"}'
check("parsiraj_invoice: invoice i link", fiskal.parsiraj_invoice(inv_json) == ("MSMV7XP7-Dt1Ov2o0-4299", "https://sandbox.suf.purs.gov.rs/v/?vl=abc"))
check("parsiraj_invoice: nije JSON → (None, None)", fiskal.parsiraj_invoice("<html>") == (None, None))
check("parsiraj_invoice: prazno → (None, None)", fiskal.parsiraj_invoice("") == (None, None))
check("parsiraj_invoice: JSON bez polja → (None, None)", fiskal.parsiraj_invoice('{"success": false}') == (None, None))
check("invoice_odbijen: {success:false} → True", fiskal.invoice_odbijen('{\n    "success": false\n}') is True)
check("invoice_odbijen: success true → False", fiskal.invoice_odbijen(inv_json) is False)
check("invoice_odbijen: prazno/HTML → False", fiskal.invoice_odbijen("") is False and fiskal.invoice_odbijen("<html>") is False)
check("pauza pre dajInvoice = 5 s", fiskal.FISKAL_INVOICE_PAUSA_SEC == 5.0)

# 3) URL enkodiranje (bez slanja)
ZAHTEV = "https://fiskal.example/fiscal/napraviRacun"
req = httpx.Request("GET", ZAHTEV, params=p)
qs = parse_qs(urlsplit(str(req.url)).query, keep_blank_values=True)
check("URL ima isti host/path", str(req.url).startswith(ZAHTEV + "?"))
check("roundtrip: artikli i napomena se vraćaju nepromenjeni", qs["artikli"] == [p["artikli"]] and qs["napomena"] == [p["napomena"]])
check("roundtrip: poslovnica sa razmakom", qs["poslovnica"] == ["Novi Sad"])
check("sva polja prisutna u URL-u", set(qs) == set(p))

# 4) kriterijum uspeha: HTTP 200 (telo se ne proverava)
check("200 → uspeh", fiskal.je_uspeh(200, '{"status":"error"}'))
check("200 prazno telo → uspeh", fiskal.je_uspeh(200, ""))
check("500 → nije uspeh", not fiskal.je_uspeh(500, "success"))
check("0 (mrežna greška) → nije uspeh", not fiskal.je_uspeh(0, ""))

check("timeout fiskalnog poziva = 8 s", fiskal.FISKAL_TIMEOUT_SEC == 8.0)

print(f"\n{'SVE PROLAZI' if FAILS == 0 else f'{FAILS} PADA'}")
raise SystemExit(1 if FAILS else 0)
