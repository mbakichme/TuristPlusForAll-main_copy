import json
import urllib.request

from routes import create_access_token

tok = create_access_token({"sub": "1"})
hdr = {"Authorization": f"Bearer {tok}"}

req = urllib.request.Request("http://127.0.0.1:3158/api/uplate/55664/priznanica", headers=hdr)
try:
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
        print("status:", r.status, "bytes:", len(data), r.headers.get("Content-Disposition"))
    with open("/tmp/priznanica_test.pdf", "wb") as f:
        f.write(data)
except urllib.error.HTTPError as e:
    print("GRESKA:", e.code, e.read()[:500])
