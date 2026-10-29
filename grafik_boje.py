from datetime import datetime
from zoneinfo import ZoneInfo


def _lokalno(v: datetime) -> datetime:
    if v.tzinfo is not None:
        return v.astimezone(ZoneInfo("Europe/Belgrade")).replace(tzinfo=None)
    return v


def kategorija_grafika(tip: str | None, subagent: str | None,
                       timelimit: datetime | None, saldo_rsd: float,
                       sada: datetime) -> str:
    """Prioritet kategorija; naive datumi predstavljaju vreme Beograda."""
    tip = (tip or "").strip().casefold()
    if tip == "blok":
        return "blok"
    if tip == "predrezervacija":
        istekao = timelimit is not None and _lokalno(timelimit) <= _lokalno(sada)
        if (subagent or "").strip() and not istekao:
            return "predrezervacija_subagent"
        if timelimit is not None and not istekao:
            return "predrezervacija_aktivna"
        return "predrezervacija_istekla"
    if tip == "last minute" and timelimit is not None and _lokalno(timelimit) <= _lokalno(sada):
        return "predrezervacija_istekla"
    return "isplacen" if round(saldo_rsd, 2) < 400 else "saldo_veci"
