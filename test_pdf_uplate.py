import json
import urllib.parse
import urllib.request

from routes import create_access_token

tok = create_access_token({"sub": "1"})
hdr = {"Authorization": f"Bearer {tok}"}

req = urllib.request.Request(
    f"http://127.0.0.1:3158/api/ugovori/{urllib.parse.quote('10120/26', safe='')}/uplate/pdf",
    headers=hdr,
)
with urllib.request.urlopen(req, timeout=120) as r:
    data = r.read()
    print("status:", r.status, "bytes:", len(data), "fname:", r.headers.get("Content-Disposition"))
with open("/tmp/pregled_uplata_test.pdf", "wb") as f:
    f.write(data)
