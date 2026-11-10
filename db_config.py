"""Jedinstveno mesto za konekciju na bazu.

Sve (app, import/seed/migrate skripte, testovi) uzimaju URL odavde.
Da bi se aplikacija postavila na drugu bazu, menja se SAMO promenljiva
okruženja DB_URL_ENV (ili vrednost ovde ako je potrebno).
"""
import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

DB_URL_ENV = "EXTERNAL_NEON_DATABASE_URL"


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
