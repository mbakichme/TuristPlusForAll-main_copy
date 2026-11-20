import json
import urllib.request

from routes import create_access_token

tok = create_access_token({"sub": "1"})
hdr = {"Authorization": f"Bearer {tok}"}


def get(url):
    req = urllib.request.Request(url, headers=hdr)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


for ugovor in ("33333/26", "10120/26", "31944/26"):
    d = get(f"http://127.0.0.1:3158/api/ugovori/{urllib.parse.quote(ugovor, safe='')}/uplate")
    print(f"{ugovor}: total={d['total']}")
    for row in d["rows"][:2]:
        print("   ", {k: row[k] for k in ("kljuc", "danas", "ime", "nacin", "din", "uevro", "broj", "faktura", "id")})
