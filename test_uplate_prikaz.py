import json
import urllib.parse
import urllib.request

from routes import create_access_token

tok = create_access_token({"sub": "1"})
hdr = {"Authorization": f"Bearer {tok}"}


def get(url):
    req = urllib.request.Request(url, headers=hdr)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


for ugovor in ("33333/26", "10120/26"):
    d = get(f"http://127.0.0.1:3158/api/ugovori/{urllib.parse.quote(ugovor, safe='')}/uplate")
    print(f"{ugovor}: total={d['total']}")
    suma_din = suma_eur = 0.0
    for row in d["rows"]:
        suma_din += row.get("din") or 0
        suma_eur += row.get("suma_eur") or 0
        print(f"   kljuc={row['kljuc']} danas={row['danas']} nacin={row['nacin']!r} din={row['din']} "
              f"kurs={row['kurs']} kurs_datum={row['kurs_datum']} suma_eur={row['suma_eur']} "
              f"svrha={row['svrha']!r} obradio={row['obradio']!r}")
    print(f"   ZBIR: din={round(suma_din, 2)}  eur={round(suma_eur, 2)}")
