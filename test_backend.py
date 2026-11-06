"""Local end-to-end smoke test: python test_backend.py (server must be running)."""
import http.cookiejar
import json
import os
import sqlite3
import threading
import urllib.error
import urllib.request
import uuid
from http.server import ThreadingHTTPServer
import server as backend

BASE = ""


def call(client, path, payload=None):
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"} if payload is not None else {},
    )
    try:
        with client.open(request) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def main():
    global BASE
    backend.initialize()
    app = ThreadingHTTPServer(("127.0.0.1", 0), backend.Handler)
    BASE = f"http://127.0.0.1:{app.server_port}"
    threading.Thread(target=app.serve_forever, daemon=True).start()
    assert urllib.request.urlopen(BASE + "/index.html").status == 200
    assert urllib.request.urlopen(BASE + "/unoc-logo.png").status == 200
    for private_path in ("/jst_portal.sqlite3", "/jst_admin_credentials.txt"):
        try:
            urllib.request.urlopen(BASE + private_path)
            raise AssertionError(f"Private file served: {private_path}")
        except urllib.error.HTTPError as error:
            assert error.code == 404

    password = os.environ["JST_ADMIN_PASSWORD"]
    admin = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    assert call(admin, "/api/login", {"email": "admin@jst.local", "password": password})[0] == 200

    email = "smoke-" + uuid.uuid4().hex[:10] + "@example.test"
    omc_data = {
        "company": "JST Backend Smoke Test Ltd", "tin": "1234567890",
        "registrationNo": "TEST-REG-001", "contactName": "Demo Tester",
        "email": email, "phone": "0700000000", "password": "SmokeTestPass!2026",
    }
    try:
        assert call(admin, "/api/register", omc_data)[0] == 201
        omc = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        assert call(omc, "/api/login", {"email": email, "password": omc_data["password"]})[0] == 403
        _, accounts = call(admin, "/api/admin/accounts")
        account = next(row for row in accounts["accounts"] if row["email"] == email)
        assert account["status"] == "pending" and account["tin"] == "1234567890"
        assert call(admin, f"/api/admin/accounts/{account['id']}/decision", {"status": "approved"})[0] == 200
        assert call(omc, "/api/login", {"email": email, "password": omc_data["password"]})[0] == 200
        assert call(omc, "/api/orders", {
            "product": "PMS", "volume": 25000, "collectionDate": "2026-11-30",
            "dispatch": "road", "notes": "smoke test",
        })[0] == 201
        _, orders = call(admin, "/api/admin/orders")
        assert any(row["email"] == email for row in orders["orders"])
    finally:
        with sqlite3.connect("jst_portal.sqlite3") as conn:
            conn.execute("DELETE FROM orders WHERE user_id=(SELECT id FROM users WHERE email=?)", (email,))
            conn.execute("DELETE FROM users WHERE email=?", (email,))
    app.shutdown()
    app.server_close()
    print("PASS: static site and logo; private files blocked; admin login; OMC application pending until approval; approved OMC login and order; admin order visibility; test data removed.")


if __name__ == "__main__":
    main()
