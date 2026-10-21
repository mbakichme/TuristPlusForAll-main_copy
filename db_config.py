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
