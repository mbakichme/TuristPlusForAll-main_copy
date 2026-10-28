"""Unit testovi za raspodelu rata administrativne zabrane (bez baze)."""

from datetime import date

from zabrana_api import BROJ_RATA, _dodaj_mesece, podeli_na_rate


def test_rate_mesecne_od_prve_rate():
    rate = podeli_na_rate(1200.0, date(2027, 1, 1), None)
    assert len(rate) == BROJ_RATA
    assert rate[0] == (date(2027, 1, 1), 100.0)
    assert rate[-1] == (date(2027, 12, 1), 100.0)


def test_polurata_pomera_rate_na_njen_dan():
    rate = podeli_na_rate(1200.0, date(2027, 1, 1), date(2027, 1, 15))
    assert rate[0] == (date(2027, 1, 15), 100.0)
    assert rate[-1] == (date(2027, 12, 15), 100.0)
    assert all(d.day == 15 for d, _ in rate)


def test_ostatak_centi_na_prvim_ratama_zbir_tacan():
    rate = podeli_na_rate(100.0, date(2027, 1, 1), None)
    iznosi = [i for _, i in rate]
    assert round(sum(iznosi), 2) == 100.0
    assert iznosi[:4] == [8.34, 8.34, 8.34, 8.34]
    assert iznosi[4:] == [8.33] * 8


def test_dodaj_mesece_prelazi_godinu():
    assert _dodaj_mesece(date(2026, 11, 1), 3) == date(2027, 2, 1)


def test_dodaj_mesece_clamp_na_kraj_meseca():
    assert _dodaj_mesece(date(2027, 1, 31), 1, 31) == date(2027, 2, 28)


def test_proizvoljan_broj_rata_20():
    rate = podeli_na_rate(1000.0, date(2027, 1, 1), date(2027, 1, 15), 20)
    assert len(rate) == 20
    assert round(sum(i for _, i in rate), 2) == 1000.0
    assert rate[0][0] == date(2027, 1, 15)
    assert rate[-1][0] == date(2028, 8, 15)  # 19 meseci posle prve
    assert all(d.day == 15 for d, _ in rate)


def test_broj_rata_1_jedna_rata_na_prvi_datum():
    rate = podeli_na_rate(500.0, date(2027, 3, 10), None, 1)
    assert rate == [(date(2027, 3, 10), 500.0)]
