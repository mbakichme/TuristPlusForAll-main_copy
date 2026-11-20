"""Test PDF-a i detalja administrativne zabrane.

- unit: build_zabrana_pdf sa sintetičkim podacima (8 i 60 rata → više strana)
- API: kreira zabranu, proverava /zabrane/detalj (rate, zbir RSD) i /zabrane/pdf (200, application/pdf),
  404 za nepostojeću zabranu. Briše svoje redove (zabrana + ratazab) direktno iz baze.

Pokretanje: uv run python test_zabrana_pdf.py (dev backend na TEST_API_URL, podrazumevano :3158).
"""

import os
import re
import uuid
from datetime import date

import httpx
from sqlalchemy import text

from routes import create_access_token, get_engine
from zabrana_pdf import build_zabrana_pdf

API = os.environ.get("TEST_API_URL", "http://localhost:3158/api")


def _sintetika(broj_rata: int) -> dict:
    rate = [{"rb": i + 1, "datum": f"{(i % 12) + 1:02d}.2027.", "iznos": 1234.56 + i,
             "rasknjizeno": False} for i in range(broj_rata)]
    return {
        "broj": "141/1", "preduzece": "PREDSKOLSKA USTANOVA RADOSNO DETINJSTVO",
        "mesto_obracuna": "NOVI SAD", "datum": "13.11.2025.", "broj_rata": broj_rata,
        "smestaj": 265178.34, "prevoz": 0, "dod": 0, "ukupno": 265178.34, "valuta": "RSD",
        "kurs": 117.2,
        "nosilac": {"ime": "KOVACEVIC DRAGANA", "rodjen": "27.05.1998.", "adresa": "Novi Sad",
                    "telefon": "0611981321"},
        "putnici": [{"ime": "KOVACEVIC DRAGANA", "rodjen": "27.05.1998."},
                    {"ime": "KOVACEVIC MILOS", "rodjen": "06.10.1993."},
                    {"ime": "KOVACEVIC MILICA", "rodjen": "06.11.2018."}],
        "aranzman": {"mesto": "TUNIS-SOUSSE", "naziv": "Thalassa Sousse and Aqua park 4*",
                     "termin": "07.07.2026. - 21.07.2026.", "apartman": ""},
        "rate": rate,
        "agencija": {"naziv": "OKTOPOD d.o.o.", "mesto": "Beograd", "adresa": "Velimira Bate 7",
                     "telefon": "011/4155555", "email": "finansije@oktopod.rs",
                     "racun": "160-135905-52", "banka": "Banca Intesa"},
    }


def _broj_strana(pdf: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page[^s]", pdf))


def unit() -> int:
    provere = 0
    pdf8 = build_zabrana_pdf(_sintetika(8))
    assert pdf8.startswith(b"%PDF"), "nije PDF"
    assert _broj_strana(pdf8) == 1, f"8 rata = 1 strana (dobijeno {_broj_strana(pdf8)})"
    provere += 2
    pdf60 = build_zabrana_pdf(_sintetika(60))
    assert _broj_strana(pdf60) >= 2, "60 rata mora da prelomi stranu"
    provere += 1
    print("  OK unit: 8 rata = 1 strana, 60 rata =", _broj_strana(pdf60), "strane")
    return provere


def api() -> int:
    engine = get_engine()
    tok = create_access_token({"sub": "1"})
    client = httpx.Client(base_url=API, headers={"Authorization": "Bearer " + tok}, timeout=60)
    provere = 0

    def ok(cond, opis):
        nonlocal provere
        assert cond, opis
        provere += 1
        print("  OK", opis)

    with engine.connect() as conn:
        kljuc = conn.execute(text(
            "SELECT kljuc FROM aranzman WHERE kljuc LIKE '%/26' AND COALESCE(kljuc,'') <> '' "
            "ORDER BY id DESC LIMIT 1"
        )).scalar()
    sub = client.get("/subagenti-izbor", params={"ta": "false"}).json()[0]
    broj = f"TST{uuid.uuid4().hex[:8]}/1"
    try:
        r = client.post("/zabrane", json={
            "kljuc": kljuc, "subagent_id": sub["id"], "mesto_obracuna": "TEST MESTO",
            "datum": date.today().isoformat(), "broj_zabrane": broj,
            "prva_rata": "2027-01-10", "prva_polurata": None,
            "iznos_eur": 1000.0, "broj_rata": 8,
        })
        ok(r.status_code == 201, f"POST zabrane 201 (dobijeno {r.status_code})")
        iznos_rsd = r.json()["iznos_rsd"]

        d = client.get("/zabrane/detalj", params={"broj": broj})
        ok(d.status_code == 200, f"GET detalj 200 (dobijeno {d.status_code})")
        j = d.json()
        ok(j["valuta"] == "RSD", "detalj valuta RSD")
        ok(len(j["rate"]) == 8, "detalj vraća 8 rata")
        ok(abs(sum(x["iznos"] for x in j["rate"]) - iznos_rsd) < 0.005,
           "zbir rata = iznos_rsd")
        ok(j["rate"][0]["datum"] == "10.01.2027.", "prva rata 10.01.2027.")
        ok(len(j["putnici"]) >= 1 and j["putnici"][0]["ime"] != "", "nosilac u listi putnika")
        ok(isinstance(j["agencija"], dict), "agencija blok prisutan")

        p = client.get("/zabrane/pdf", params={"broj": broj})
        ok(p.status_code == 200, f"GET pdf 200 (dobijeno {p.status_code})")
        ok(p.headers.get("content-type", "").startswith("application/pdf"), "content-type pdf")
        ok(p.content.startswith(b"%PDF"), "telo je PDF")
        with open("/tmp/zabrana_test.pdf", "wb") as f:
            f.write(p.content)
        print("  PDF sačuvan: /tmp/zabrana_test.pdf")

        nf = client.get("/zabrane/detalj", params={"broj": "NEPOSTOJI/999"})
        ok(nf.status_code == 404, "nepostojeća zabrana → 404")
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM ratazab WHERE id_zabrane = :b"), {"b": broj})
            conn.execute(text("DELETE FROM zabrana WHERE brojzabrane = :b"), {"b": broj})
    return provere


if __name__ == "__main__":
    print("unit")
    n = unit()
    print("api")
    n += api()
    print(f"SVE OK ({n} provera)")
