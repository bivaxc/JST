"""Local JST OMC portal demo backend. Run with: python server.py"""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse
from pathlib import Path
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "jst_portal.sqlite3"
ADMIN_FILE = ROOT / "jst_admin_credentials.txt"  # Deny access if an older credentials file exists.
HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", "8000"))
SESSION_SECONDS = 12 * 60 * 60
PBKDF2_ROUNDS = 310_000


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def password_hash(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    value = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
    return salt.hex(), value.hex()


def initialize():
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, company TEXT NOT NULL,
            tin TEXT NOT NULL, registration_no TEXT NOT NULL, contact_name TEXT NOT NULL,
            phone TEXT NOT NULL, password_salt TEXT NOT NULL, password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'omc', status TEXT NOT NULL DEFAULT 'pending',
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            product TEXT NOT NULL, volume_litres INTEGER NOT NULL, collection_date TEXT NOT NULL,
            dispatch TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'submitted',
            created_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS sessions_expiry_idx ON sessions(expires_at);
        CREATE INDEX IF NOT EXISTS orders_user_idx ON orders(user_id, created_at);
        """)
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (int(time.time()),))
        admin = conn.execute("SELECT id FROM users WHERE role='admin' LIMIT 1").fetchone()
        if not admin:
            password = os.environ.get("JST_ADMIN_PASSWORD") or secrets.token_urlsafe(18)
            salt, hashed = password_hash(password)
            conn.execute("""INSERT INTO users(email,company,tin,registration_no,contact_name,phone,
                password_salt,password_hash,role,status,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                ("admin@jst.local", "JST Portal Administration", "", "", "Portal Administrator", "",
                 salt, hashed, "admin", "approved", int(time.time())))
            print("Initial admin account created: admin@jst.local", flush=True)
            print(f"Initial admin password (save this now): {password}", flush=True)


def public_user(row):
    return {"id": row["id"], "email": row["email"], "company": row["company"],
            "role": row["role"], "status": row["status"]}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt, *args):
        # Avoid logging request bodies (which can contain TINs and credentials).
        super().log_message(fmt, *args)

    def translate_path(self, path):
        blocked = super().translate_path(path)
        resolved = Path(blocked).resolve()
        if resolved in (DB_PATH.resolve(), ADMIN_FILE.resolve()) or resolved.name.startswith("."):
            return str(ROOT / "__not_public__")
        return str(resolved)

    def send_json(self, code, value, headers=None):
        raw = json.dumps(value).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        if headers:
            for key, val in headers.items():
                self.send_header(key, val)
        self.end_headers()
        self.wfile.write(raw)

    def body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > 32_000:
            raise ValueError("Request too large")
        value = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(value, dict):
            raise ValueError("Expected an object")
        return value

    def current_user(self):
        cookie = self.headers.get("Cookie", "")
        token = next((item[len("jst_session="):] for item in cookie.split("; ") if item.startswith("jst_session=")), "")
        if not token:
            return None
        digest = hashlib.sha256(token.encode()).hexdigest()
        with db() as conn:
            return conn.execute("""SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id
                WHERE s.token_hash=? AND s.expires_at>?""", (digest, int(time.time()))).fetchone()

    def require_user(self, roles=None):
        user = self.current_user()
        if not user:
            self.send_json(401, {"error": "Sign in to continue."})
            return None
        if roles and user["role"] not in roles:
            self.send_json(403, {"error": "You do not have access to this area."})
            return None
        return user

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/healthz":
            return self.send_json(200, {"status": "ok"})
        if path.startswith("/api/"):
            if path == "/api/me":
                user = self.current_user()
                return self.send_json(200, {"user": public_user(user) if user else None})
            if path == "/api/admin/accounts":
                user = self.require_user(["admin"])
                if user:
                    with db() as conn:
                        rows = conn.execute("""SELECT id,email,company,tin,registration_no,contact_name,phone,status,created_at
                            FROM users WHERE role='omc' ORDER BY created_at DESC""").fetchall()
                    self.send_json(200, {"accounts": [dict(row) for row in rows]})
                return
            if path == "/api/admin/orders":
                user = self.require_user(["admin"])
                if user:
                    with db() as conn:
                        rows = conn.execute("""SELECT o.*,u.company,u.email FROM orders o JOIN users u ON u.id=o.user_id
                            ORDER BY o.created_at DESC""").fetchall()
                    self.send_json(200, {"orders": [dict(row) for row in rows]})
                return
            return self.send_json(404, {"error": "Not found."})
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            data = self.body()
        except (ValueError, json.JSONDecodeError):
            return self.send_json(400, {"error": "Invalid request."})
        if path == "/api/register":
            required = ["company", "tin", "registrationNo", "contactName", "email", "phone", "password"]
            if any(not str(data.get(key, "")).strip() for key in required):
                return self.send_json(400, {"error": "Complete all required business and account fields."})
            email = str(data["email"]).strip().lower()
            tin = re.sub(r"\s", "", str(data["tin"]))
            password = str(data["password"])
            if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
                return self.send_json(400, {"error": "Enter a valid business email."})
            if not re.fullmatch(r"\d{10}", tin):
                return self.send_json(400, {"error": "Enter a 10-digit TIN."})
            if len(password) < 12:
                return self.send_json(400, {"error": "Password must be at least 12 characters."})
            salt, hashed = password_hash(password)
            try:
                with db() as conn:
                    conn.execute("""INSERT INTO users(email,company,tin,registration_no,contact_name,phone,
                        password_salt,password_hash,role,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                        (email, str(data["company"]).strip(), tin, str(data["registrationNo"]).strip(),
                         str(data["contactName"]).strip(), str(data["phone"]).strip(), salt, hashed,
                         "omc", "pending", int(time.time())))
                return self.send_json(201, {"message": "Application submitted for administrator review. You can sign in after approval."})
            except sqlite3.IntegrityError:
                return self.send_json(409, {"error": "An account already exists for this business email."})
        if path == "/api/login":
            email = str(data.get("email", "")).strip().lower()
            password = str(data.get("password", ""))
            with db() as conn:
                row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
                valid = False
                if row:
                    salt = bytes.fromhex(row["password_salt"])
                    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS).hex()
                    valid = hmac.compare_digest(candidate, row["password_hash"])
                if not valid:
                    return self.send_json(401, {"error": "Email or password is incorrect."})
                if row["role"] == "omc" and row["status"] != "approved":
                    return self.send_json(403, {"error": "Your company account is awaiting administrator approval."})
                token = secrets.token_urlsafe(32)
                conn.execute("INSERT INTO sessions(token_hash,user_id,expires_at) VALUES(?,?,?)",
                             (hashlib.sha256(token.encode()).hexdigest(), row["id"], int(time.time()) + SESSION_SECONDS))
            return self.send_json(200, {"user": public_user(row)}, {
                "Set-Cookie": f"jst_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_SECONDS}" + ("; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else "")
            })
        if path == "/api/logout":
            cookie = self.headers.get("Cookie", "")
            token = next((item[len("jst_session="):] for item in cookie.split("; ") if item.startswith("jst_session=")), "")
            if token:
                with db() as conn:
                    conn.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))
            return self.send_json(200, {"ok": True}, {"Set-Cookie": "jst_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0" + ("; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else "")})
        if path.startswith("/api/admin/accounts/") and path.endswith("/decision"):
            admin = self.require_user(["admin"])
            if not admin:
                return
            bits = path.strip("/").split("/")
            try:
                account_id = int(bits[3])
            except (IndexError, ValueError):
                return self.send_json(404, {"error": "Not found."})
            decision = data.get("status")
            if decision not in ("approved", "rejected"):
                return self.send_json(400, {"error": "Choose approve or reject."})
            with db() as conn:
                cur = conn.execute("UPDATE users SET status=? WHERE id=? AND role='omc'", (decision, account_id))
                if cur.rowcount == 0:
                    return self.send_json(404, {"error": "OMC account not found."})
            return self.send_json(200, {"message": f"OMC account {decision}."})
        if path == "/api/orders":
            user = self.require_user(["omc"])
            if not user:
                return
            if user["status"] != "approved":
                return self.send_json(403, {"error": "Your company account is not approved."})
            product = str(data.get("product", ""))
            try:
                volume = int(data.get("volume", 0))
            except (ValueError, TypeError):
                volume = 0
            date = str(data.get("collectionDate", ""))
            dispatch = str(data.get("dispatch", ""))
            if product not in ("PMS", "AGO") or volume < 1000 or volume > 20_000_000 or volume % 1000:
                return self.send_json(400, {"error": "Select PMS or AGO and enter a volume from 1,000 to 20,000,000 litres in 1,000-litre increments."})
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) or dispatch not in ("road", "rail"):
                return self.send_json(400, {"error": "Enter a requested collection date and dispatch mode."})
            with db() as conn:
                cur = conn.execute("""INSERT INTO orders(user_id,product,volume_litres,collection_date,dispatch,notes,created_at)
                    VALUES(?,?,?,?,?,?,?)""", (user["id"], product, volume, date, dispatch,
                    str(data.get("notes", ""))[:2000], int(time.time())))
                order_id = cur.lastrowid
            return self.send_json(201, {"message": "Order request submitted for UNOC review.", "orderId": order_id})
        if path == "/api/admin/orders/decision":
            admin = self.require_user(["admin"])
            if not admin:
                return
            try:
                order_id = int(data.get("orderId"))
            except (ValueError, TypeError):
                return self.send_json(400, {"error": "Invalid order."})
            status = data.get("status")
            if status not in ("accepted", "declined"):
                return self.send_json(400, {"error": "Choose accept or decline."})
            with db() as conn:
                cur = conn.execute("UPDATE orders SET status=? WHERE id=?", (status, order_id))
                if cur.rowcount == 0:
                    return self.send_json(404, {"error": "Order not found."})
            return self.send_json(200, {"message": f"Order {status}."})
        return self.send_json(404, {"error": "Not found."})


if __name__ == "__main__":
    initialize()
    print(f"JST portal listening on {HOST}:{PORT}", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
