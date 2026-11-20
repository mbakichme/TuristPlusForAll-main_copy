"""Test boje-grafik API — GET/PUT roundtrip, validation, auth, cleanup."""
import json
import sys

from fastapi.testclient import TestClient
from routes import create_app, create_access_token

app = create_app(static_dir="/nonexistent")
client = TestClient(app)

# Authenticated headers
tok = create_access_token({"sub": "1"})
auth_hdr = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}

# Default values (all zelena)
DEFAULTS = {
    "isplacen": "zelena",
    "predrezervacija_aktivna": "zelena",
    "predrezervacija_istekla": "zelena",
    "blok": "zelena",
    "saldo_veci": "zelena",
    "predrezervacija_subagent": "zelena",
}

# Snapshot original settings so we can restore them
original = None


def setup_module():
    global original
    r = client.get("/api/boje-grafik", headers=auth_hdr)
    if r.status_code == 200:
        original = r.json()
    else:
        original = DEFAULTS.copy()


def teardown_module():
    if original is not None:
        client.put("/api/boje-grafik", headers=auth_hdr, json=original)


def test_get_unauthenticated():
    r = client.get("/api/boje-grafik")
    assert r.status_code == 401, f"Expected 401, got {r.status_code}"


def test_put_unauthenticated():
    r = client.put("/api/boje-grafik", json=DEFAULTS)
    assert r.status_code == 401, f"Expected 401, got {r.status_code}"


def test_get_defaults():
    r = client.get("/api/boje-grafik", headers=auth_hdr)
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    data = r.json()
    assert set(data) == set(DEFAULTS)
    assert all(v in ("zelena", "plava", "crvena", "zuta", "ljubicasta", "narandzasta", "crna", "roze") for v in data.values())


def test_put_invalid_boja():
    payload = DEFAULTS.copy()
    payload["isplacen"] = "ljubicasta"  # valid
    payload["blok"] = "nepoznata"       # invalid
    r = client.put("/api/boje-grafik", headers=auth_hdr, json=payload)
    assert r.status_code == 422, f"Expected 422, got {r.status_code}"


def test_put_missing_field():
    payload = {k: v for k, v in DEFAULTS.items() if k != "blok"}
    r = client.put("/api/boje-grafik", headers=auth_hdr, json=payload)
    assert r.status_code == 422, f"Expected 422, got {r.status_code}"


def test_put_and_get_roundtrip():
    new_values = {
        "isplacen": "plava",
        "predrezervacija_aktivna": "crvena",
        "predrezervacija_istekla": "zuta",
        "blok": "ljubicasta",
        "saldo_veci": "narandzasta",
        "predrezervacija_subagent": "crna",
    }
    r = client.put("/api/boje-grafik", headers=auth_hdr, json=new_values)
    assert r.status_code == 200, f"PUT failed: {r.status_code} {r.text}"

    r = client.get("/api/boje-grafik", headers=auth_hdr)
    assert r.status_code == 200, f"GET failed: {r.status_code}"
    data = r.json()
    for key, val in new_values.items():
        assert data.get(key) == val, f"Roundtrip mismatch for {key}: expected {val}, got {data.get(key)}"

    # Restore defaults within test so subsequent tests see clean state
    r = client.put("/api/boje-grafik", headers=auth_hdr, json=DEFAULTS)
    assert r.status_code == 200, f"Restore failed: {r.status_code}"


if __name__ == "__main__":
    setup_module()
    try:
        test_get_unauthenticated()
        print("PASS: test_get_unauthenticated")
        test_put_unauthenticated()
        print("PASS: test_put_unauthenticated")
        test_get_defaults()
        print("PASS: test_get_defaults")
        test_put_invalid_boja()
        print("PASS: test_put_invalid_boja")
        test_put_missing_field()
        print("PASS: test_put_missing_field")
        test_put_and_get_roundtrip()
        print("PASS: test_put_and_get_roundtrip")
        print("\nAll tests passed.")
    finally:
        teardown_module()
