"""Fiskalizacija uplate — poziv fiskalnog servisa (napraviRacun).

Servis prima sve parametre kao query string (GET). Odgovor je tekst (JSON);
uspeh = HTTP 200 (telo odgovora se ne proverava).
"""
from __future__ import annotations

import httpx

FISKAL_TIMEOUT_SEC = 8.0
FISKAL_INVOICE_PAUSA_SEC = 5.0

# Način plaćanja iz aplikacije → vrednost koju prima fiskalni servis
TIP_PLACANJA_FISKAL = {
    "Gotovina": "gotovina",
    "Kartica": "kartica",
    "Ček": "cek",
    "Virman": "virman",
    "IPC": "ipc",
    "Vaučer": "vaucer",
    "Ostalo": "ostalo",
}


def tip_placanja_fiskal(nacin: str) -> str:
    try:
        return TIP_PLACANJA_FISKAL[nacin]
    except KeyError as exc:
        raise ValueError(f"Nepoznat način plaćanja za fiskal: {nacin!r}") from exc


def build_fiskal_params(
    *,
    uplata_kljuc: int,
    broj_priznanice: str,
    aranzman_kljuc: str,
    artikal: str,
    nacin: str,
    din: float,
    datum_iso: str,
    pib: str,
    poslovnica: str,
    korisnik: str,
    cashier: str,
) -> dict[str, str]:
    """Parametri zahteva. `artikal` = "kljuc / mesto / datumod" (jedna stavka)."""
    return {
        "iznos": f"{float(din):.2f}",
        "tip_placanja": tip_placanja_fiskal(nacin),
        "broj_priznanice": str(uplata_kljuc),
        "broj_ugovora": aranzman_kljuc,
        "opis_racuna": artikal,
        "stampac": korisnik,
        "tip_racuna": "A",
        "pib_pravnog_lica": pib,
        "pib_organizatora": pib,
        "datum": datum_iso,
        "poslovnica": poslovnica,
        "tip_poreza": "12",
        "print": "true",
        "stampa": "S",
        "req_id": broj_priznanice.replace("/", "-"),
        "pdv": "0",
        "advanceTAX": "0",
        "iznos1": "0",
        "iznos2": "0",
        "artikli": artikal,
        "cashier": cashier,
        "ime_racunara": korisnik,
        "napomena": artikal,
        "tip_poreza1": "",
        "advanceTAX1": "0",
        "artikli1": "",
        "artikli2": "",
        "advanceTAX2": "0",
        "tip_poreza2": "",
    }


def je_uspeh(http_status: int, tekst: str) -> bool:
    return http_status == 200


def posalji_fiskal(zahtev_url: str, params: dict[str, str]) -> tuple[int, str]:
    """GET na fiskalni servis (zahtev_url iz Osnovnih podataka). Vraća (http_status, sirovi tekst odgovora).
    Mrežne greške se propagiraju kao httpx.HTTPError."""
    resp = httpx.get(zahtev_url, params=params, timeout=FISKAL_TIMEOUT_SEC)
    return resp.status_code, resp.text


def dohvati_invoice(odgovor_url: str, req_id: str) -> tuple[int, str]:
    """GET dajInvoice?req_id=... (odgovor_url iz Osnovnih podataka). Vraća (http_status, sirovi tekst)."""
    resp = httpx.get(odgovor_url, params={"req_id": req_id}, timeout=FISKAL_TIMEOUT_SEC)
    return resp.status_code, resp.text


def invoice_odbijen(tekst: str | None) -> bool:
    """True ako dajInvoice vrati JSON sa "success": false."""
    import json

    try:
        data = json.loads(tekst or "")
    except ValueError:
        return False
    return isinstance(data, dict) and data.get("success") is False


def parsiraj_invoice(tekst: str) -> tuple[str | None, str | None]:
    """Iz JSON odgovora dajInvoice vraća (invoice, link_racuna); None ako nedostaje ili nije JSON."""
    import json

    try:
        data = json.loads(tekst or "")
    except ValueError:
        return None, None
    if not isinstance(data, dict):
        return None, None
    invoice = (data.get("invoice") or None)
    link = (data.get("link_racuna") or None)
    return (str(invoice) if invoice else None), (str(link) if link else None)
