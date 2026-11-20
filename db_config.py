"""Jedinstveno mesto za konekciju na bazu.

Sve (app, import/seed/migrate skripte, testovi) uzimaju URL odavde.
Da bi se aplikacija postavila na drugu bazu, menja se SAMO promenljiva
okruženja DB_URL_ENV (ili vrednost ovde ako je potrebno).
"""
import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

DB_URL_ENV = "EXTERNAL_NEON_DATABASE_URL"


def _ucitaj_dotenv(putanja: Path) -> None:
    """Učitava KEY=VALUE parove iz .env bez prepisivanja postojećih promenljivih.

    Parser je namerno jednostavan (bez shell interpretacije), jer URL-ovi
    sadrže znakove kao što su & i ?.
    """
    if not putanja.is_file():
        return
    for linija in putanja.read_text(encoding="utf-8").splitlines():
        linija = linija.strip()
        if not linija or linija.startswith("#") or "=" not in linija:
            continue
        kljuc, vrednost = linija.split("=", 1)
        kljuc = kljuc.strip()
        vrednost = vrednost.strip()
        if len(vrednost) >= 2 and vrednost[0] == vrednost[-1] and vrednost[0] in "\"'":
            vrednost = vrednost[1:-1]
        if kljuc and kljuc not in os.environ:
            os.environ[kljuc] = vrednost


# Env fajl instance (organizatora): INSTANCE_ENV_FILE=instances/helena.env, inače .env
_ucitaj_dotenv(
    Path(os.environ.get("INSTANCE_ENV_FILE") or Path(__file__).resolve().parent / ".env")
)


def get_database_url() -> str:
    url = (os.environ.get(DB_URL_ENV) or "").strip()
    if not url:
        raise RuntimeError(f"{DB_URL_ENV} nije podešen")
    return url


def get_engine(**kwargs) -> Engine:
    opcije = {"pool_pre_ping": True}
    opcije.update(kwargs)
    return create_engine(get_database_url(), **opcije)


SEARCH_DB_URL_ENV = "SEARCH_DATABASE_URL"


def get_search_engine(fallback: Engine) -> Engine:
    """Read-only engine za rute pretrage (mesto, period-grupa, slobodne-sobe).

    Ako SEARCH_DATABASE_URL nije podešen, vraća fallback (lokalni engine).
    Sesija je read-only na nivou servera: svaki upis iz ovih ruta puca.
    """
    url = (os.environ.get(SEARCH_DB_URL_ENV) or "").strip()
    if not url:
        return fallback
    # SEARCH_READ_ONLY=0 samo za test baze (upis testiranje); podrazumevano read-only.
    read_only = (os.environ.get("SEARCH_READ_ONLY", "1").strip() != "0")
    opcije = {"pool_pre_ping": True}
    if read_only:
        opcije["connect_args"] = {"options": "-c default_transaction_read_only=on"}
    return create_engine(url, **opcije)
