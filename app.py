from flask import Flask, Response, render_template, request, jsonify, session, redirect, url_for
from flask_cors import CORS
import sqlite3
import hashlib
import os
import tempfile
import random
import smtplib
import time
from email.message import EmailMessage
from html import escape
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import base64
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__, template_folder=os.path.join(BASE_DIR, "templates"))
app.secret_key = os.environ.get("SECRET_KEY", "bms_secret_key_2024")
CORS(app)

SITE_URL = os.environ.get("SITE_URL", "https://harish-bms.vercel.app").rstrip("/")
OWNER_EMAIL = os.environ.get("OWNER_EMAIL", "harishkumar05.dgl@gmail.com").strip().lower()
OWNER_PASSWORD = os.environ.get("OWNER_PASSWORD", "123456")
STAFF_PASSWORD = os.environ.get("STAFF_PASSWORD", "098765")
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "").strip()
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER", "").strip()
MIN_ORDER_AMOUNT = float(os.environ.get("MIN_ORDER_AMOUNT", "1000"))

# ─── DB CONFIG ───────────────────────────────────────────
def get_database_url():
    for name in ("POSTGRES_URL", "NEON_DATABASE_URL", "POSTGRES_URL_NON_POOLING", "DATABASE_URL"):
        value = os.getenv(name)
        if value:
            if name == "DATABASE_URL" and "render.com" in value.lower():
                continue
            return value, name
    return None, None

def with_postgres_ssl(url):
    if not url or not url.startswith(("postgres://", "postgresql://")):
        return url
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.setdefault("sslmode", "require")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

DATABASE_URL, DATABASE_SOURCE = get_database_url()
DATABASE_URL = with_postgres_ssl(DATABASE_URL)
USE_POSTGRES = bool(DATABASE_URL)
DB_PATH = os.environ.get("SQLITE_DB_PATH", os.path.join(tempfile.gettempdir(), "harish_bms.db"))
DB_READY = False

if USE_POSTGRES:
    import psycopg2
    from psycopg2.extras import RealDictCursor
else:
    psycopg2 = None
    RealDictCursor = None

def get_db():
    if USE_POSTGRES:
        return psycopg2.connect(DATABASE_URL, connect_timeout=10)
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, factory=AppSqliteConnection)
    conn.row_factory = sqlite3.Row
    return conn

def get_cursor(conn, dict_rows=False):
    if USE_POSTGRES and dict_rows:
        return conn.cursor(cursor_factory=RealDictCursor)
    return conn.cursor()

def db_sql(query):
    return query if USE_POSTGRES else query.replace("%s", "?")

def db_execute(cur, query, params=None):
    cur.execute(db_sql(query), params or ())

def row_to_dict(row):
    return dict(row) if not isinstance(row, dict) else row

def rows_to_dicts(rows):
    return [row_to_dict(r) for r in rows]

class HybridRow(dict):
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)

class AppSqliteCursor(sqlite3.Cursor):
    def execute(self, query, params=()):
        return super().execute(db_sql(query), params or ())

    def executemany(self, query, seq_of_params):
        return super().executemany(db_sql(query), seq_of_params)

    def fetchone(self):
        row = super().fetchone()
        return HybridRow(dict(row)) if row is not None else None

    def fetchall(self):
        return [HybridRow(dict(row)) for row in super().fetchall()]

class AppSqliteConnection(sqlite3.Connection):
    def cursor(self, *args, **kwargs):
        return super().cursor(factory=AppSqliteCursor)

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def send_otp_email(email, otp):
    smtp_user = os.environ.get("SMTP_USER") or os.environ.get("GMAIL_USER")
    smtp_pass = os.environ.get("SMTP_PASS") or os.environ.get("GMAIL_APP_PASSWORD")
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    if not smtp_user or not smtp_pass:
        return False
    msg = EmailMessage()
    msg["Subject"] = "KRG BMS Customer Login OTP"
    msg["From"] = smtp_user
    msg["To"] = email
    msg.set_content(f"Your KRG BMS login OTP is {otp}. It is valid for 10 minutes.")
    with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as smtp:
        smtp.starttls()
        smtp.login(smtp_user, smtp_pass)
        smtp.send_message(msg)
    return True

def notify_admin_login_attempt(attempt_email):
    smtp_user = os.environ.get("SMTP_USER") or os.environ.get("GMAIL_USER")
    smtp_pass = os.environ.get("SMTP_PASS") or os.environ.get("GMAIL_APP_PASSWORD")
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    if not smtp_user or not smtp_pass:
        return False
    ip = request.headers.get("x-forwarded-for", request.remote_addr or "unknown")
    ua = request.headers.get("user-agent", "unknown")
    msg = EmailMessage()
    msg["Subject"] = "KRG BMS admin login attempt"
    msg["From"] = smtp_user
    msg["To"] = OWNER_EMAIL
    msg.set_content(
        "A failed admin login attempt happened.\n\n"
        f"Attempt email: {attempt_email or 'empty'}\n"
        f"IP: {ip}\n"
        f"User agent: {ua}\n"
        f"Time: {datetime.utcnow().isoformat()} UTC\n"
    )
    with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as smtp:
        smtp.starttls()
        smtp.login(smtp_user, smtp_pass)
        smtp.send_message(msg)
    return True

def notify_staff_login_request(staff_email, state="requested"):
    smtp_user = os.environ.get("SMTP_USER") or os.environ.get("GMAIL_USER")
    smtp_pass = os.environ.get("SMTP_PASS") or os.environ.get("GMAIL_APP_PASSWORD")
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    if not smtp_user or not smtp_pass:
        return False
    ip = request.headers.get("x-forwarded-for", request.remote_addr or "unknown")
    ua = request.headers.get("user-agent", "unknown")
    msg = EmailMessage()
    msg["Subject"] = "KRG BMS employee admin approval needed"
    msg["From"] = smtp_user
    msg["To"] = OWNER_EMAIL
    msg.set_content(
        "Employee/driver admin login needs owner approval.\n\n"
        f"Email: {staff_email or 'empty'}\n"
        f"State: {state}\n"
        f"Approve from: {SITE_URL}/admin\n"
        f"IP: {ip}\n"
        f"User agent: {ua}\n"
        f"Time: {datetime.utcnow().isoformat()} UTC\n"
    )
    with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as smtp:
        smtp.starttls()
        smtp.login(smtp_user, smtp_pass)
        smtp.send_message(msg)
    return True

def is_owner_admin():
    return session.get("admin") and session.get("admin_role") == "owner"

def is_any_admin():
    return bool(session.get("admin"))

def normalize_indian_phone(phone):
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
    if digits.startswith("91") and len(digits) == 12:
        return f"+{digits}"
    if len(digits) == 10:
        return f"+91{digits}"
    if str(phone or "").strip().startswith("+"):
        return str(phone).strip()
    return phone

def twiml_response(xml):
    return Response(xml, mimetype="text/xml")

def append_order_note(cur, order_number, note):
    if USE_POSTGRES:
        cur.execute(
            """UPDATE orders
               SET notes=CONCAT(COALESCE(notes,''), %s), updated_at=CURRENT_TIMESTAMP
               WHERE order_number=%s""",
            (f"\n{note}", order_number),
        )
    else:
        cur.execute(
            """UPDATE orders
               SET notes=COALESCE(notes,'') || %s, updated_at=CURRENT_TIMESTAMP
               WHERE order_number=%s""",
            (f"\n{note}", order_number),
        )

def start_order_verification_call(order_number, phone):
    if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER):
        return {"started": False, "reason": "twilio_env_missing"}
    to_phone = normalize_indian_phone(phone)
    call_url = f"{SITE_URL}/api/voice/order/{order_number}"
    status_url = f"{SITE_URL}/api/voice/status/{order_number}"
    form = urlencode({
        "To": to_phone,
        "From": TWILIO_FROM_NUMBER,
        "Url": call_url,
        "StatusCallback": status_url,
        "StatusCallbackEvent": "initiated ringing answered completed",
        "StatusCallbackMethod": "POST",
    }).encode()
    api_url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Calls.json"
    auth = base64.b64encode(f"{TWILIO_ACCOUNT_SID}:{TWILIO_AUTH_TOKEN}".encode()).decode()
    req = Request(api_url, data=form, method="POST")
    req.add_header("Authorization", f"Basic {auth}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urlopen(req, timeout=15) as res:
            return {"started": True, "response": res.read().decode("utf-8", "ignore")[:500]}
    except (HTTPError, URLError, TimeoutError) as exc:
        return {"started": False, "reason": str(exc)}

def ensure_db():
    global DB_READY
    if not DB_READY:
        init_db()
        DB_READY = True

# ─── INIT DB ─────────────────────────────────────────────
DEFAULT_MATERIALS = [
    ("12mm Aggregate", "Aggregate", 45.00, "cft", 900, "https://commons.wikimedia.org/wiki/Special:FilePath/LF02-01%20Splitt%20WikiCom.jpg?width=900", "12mm blue metal aggregate for concrete and roof work."),
    ("20mm Aggregate", "Aggregate", 50.00, "cft", 1200, "https://commons.wikimedia.org/wiki/Special:FilePath/LF02-01%20Schotter%20WikiCom.jpg?width=900", "20mm blue metal aggregate for RCC and foundation concrete."),
    ("40mm Aggregate", "Aggregate", 48.00, "cft", 1000, "https://images.unsplash.com/photo-1782201780626-f5ebc46ba571?auto=format&fit=crop&w=900&q=80", "40mm aggregate for heavy concrete filling and base work."),
    ("Karungal", "Aggregate", 55.00, "cft", 1000, "https://tse1.mm.bing.net/th/id/OIP.sgx5dFCDuGSyyQtc9vy_1gAAAA?r=0&w=330&h=450&rs=1&pid=ImgDetMain&o=7&rm=3", "Karungal black stone for foundation, filling, base work and site support."),
    ("Blue Metal Dust", "Aggregate", 30.00, "cft", 1000, "https://commons.wikimedia.org/wiki/Special:FilePath/M%20Sand%20fo%20Tamilnadu.jpg?width=900", "Fine quarry dust for levelling, filling and block work."),
    ("M-Sand", "Sand", 62.00, "cft", 1500, "https://upload.wikimedia.org/wikipedia/commons/thumb/0/08/M-Sand_in_Salem.jpg/960px-M-Sand_in_Salem.jpg", "Concrete-grade manufactured sand."),
    ("P-Sand", "Sand", 72.00, "cft", 900, "https://commons.wikimedia.org/wiki/Special:FilePath/M%20Sand%20of%20Salem.jpg?width=900", "Plastering sand for smooth wall finish."),
    ("Waste Sand", "Sand", 28.00, "cft", 800, "https://images.unsplash.com/photo-1504307651254-35680f356dfd?auto=format&fit=crop&w=900&q=80", "Waste sand / demolition filling sand for site filling and rough levelling."),
    ("Normal Bricks", "Bricks", 12.00, "piece", 6000, "https://images.unsplash.com/photo-1769104397835-2297e730f361?auto=format&fit=crop&w=900&q=80", "Normal red clay brick for wall construction."),
    ("Fly Ash Bricks", "Bricks", 7.50, "piece", 5000, "https://commons.wikimedia.org/wiki/Special:FilePath/Concrete%20Masonry%20blocks.jpg?width=900", "Fly ash brick for strong and clean wall work."),
    ("Broken Bricks", "Bricks", 7.00, "piece", 3500, "https://commons.wikimedia.org/wiki/Special:FilePath/Rubble.jpg?width=900", "Broken brick pieces for filling, soling and base work."),
    ("Hollow Block", "Blocks", 45.00, "piece", 2500, "https://commons.wikimedia.org/wiki/Special:FilePath/Concrete%20Masonry%20blocks.jpg?width=900", "Concrete hollow block for compound walls and partition work."),
    ("UltraTech Cement", "Cement", 430.00, "bag", 500, "https://images.unsplash.com/photo-1773394089934-3e29f2a3d6a9?auto=format&fit=crop&w=900&q=80", "UltraTech 50kg cement bag."),
    ("Chettinad Cement", "Cement", 390.00, "bag", 500, "https://images.unsplash.com/photo-1504307651254-35680f356dfd?auto=format&fit=crop&w=900&q=80", "Chettinad 50kg cement bag."),
    ("Semman Red Soil", "Soil", 35.00, "cft", 1000, "https://5.imimg.com/data5/SELLER/Default/2024/3/404157369/VQ/HW/AI/110906154/solid-block-4inch-500x500.jpg", "Semman red soil for garden, plants and filling work."),
    ("JCB Rental", "Rental", 1500.00, "hour", 10, "https://tse1.mm.bing.net/th/id/OIP.AlKceuOLC2bpO_ssIzf_ewHaEU?r=0&rs=1&pid=ImgDetMain&o=7&rm=3", "JCB 3DX / backhoe rental for digging, site clearing, trench work and earth moving. Transport and diesel terms may vary by site."),
    ("Tractor Rental", "Rental", 900.00, "hour", 10, "https://agriculturepost.com/wp-content/uploads/2021/09/TAFE-launches-Massey-Ferguson-7235-tractor-for-Bihar-Jharkhand-and-Haryana.jpg", "Tractor rental for soil shifting, material movement, levelling and small site support work. Final rate may vary by distance and load."),
]

RENTAL_IMAGE_UPDATES = {
    "JCB Rental": (
        "https://commons.wikimedia.org/wiki/Special:FilePath/2023-02-13%20-%20JCB%20JS220LC%20hydraulic%20excavator%20-%2001.jpg?width=900",
        "https://tse1.mm.bing.net/th/id/OIP.AlKceuOLC2bpO_ssIzf_ewHaEU?r=0&rs=1&pid=ImgDetMain&o=7&rm=3",
        "JCB 3DX / backhoe rental for digging, site clearing, trench work and earth moving. Transport and diesel terms may vary by site.",
    ),
    "Tractor Rental": (
        "https://commons.wikimedia.org/wiki/Special:FilePath/Tractor%20Mount%20Trencher.JPG?width=900",
        "https://agriculturepost.com/wp-content/uploads/2021/09/TAFE-launches-Massey-Ferguson-7235-tractor-for-Bihar-Jharkhand-and-Haryana.jpg",
        "Tractor rental for soil shifting, material movement, levelling and small site support work. Final rate may vary by distance and load.",
    ),
}

def seed_materials(cur):
    for name, category, price, unit, stock, image_url, description in DEFAULT_MATERIALS:
        cur.execute("SELECT id FROM materials WHERE LOWER(name)=LOWER(%s) LIMIT 1", (name,))
        if cur.fetchone():
            continue
        cur.execute(
            """INSERT INTO materials
               (name, category, price, unit, stock, image_url, description, active)
               VALUES (%s,%s,%s,%s,%s,%s,%s,1)""",
            (name, category, price, unit, stock, image_url, description),
        )
    for name, (old_url, new_url, description) in RENTAL_IMAGE_UPDATES.items():
        cur.execute(
            """UPDATE materials
               SET image_url=%s, description=%s
               WHERE LOWER(name)=LOWER(%s)
                 AND (image_url=%s OR image_url IS NULL OR image_url='')""",
            (new_url, description, name, old_url),
        )
    cur.execute(
        """UPDATE materials
           SET image_url=%s, description=%s
           WHERE LOWER(name)=LOWER(%s)""",
        (
            "https://tse1.mm.bing.net/th/id/OIP.AlKceuOLC2bpO_ssIzf_ewHaEU?r=0&rs=1&pid=ImgDetMain&o=7&rm=3",
            "JCB 3DX / backhoe rental for digging, site clearing, trench work and earth moving. Transport and diesel terms may vary by site.",
            "JCB Rental",
        ),
    )
    cur.execute(
        """UPDATE materials
           SET image_url=%s, description=%s
           WHERE LOWER(name)=LOWER(%s)""",
        (
            "https://agriculturepost.com/wp-content/uploads/2021/09/TAFE-launches-Massey-Ferguson-7235-tractor-for-Bihar-Jharkhand-and-Haryana.jpg",
            "Tractor rental for soil shifting, material movement, levelling and small site support work. Final rate may vary by distance and load.",
            "Tractor Rental",
        ),
    )
    cur.execute(
        """UPDATE materials
           SET image_url=%s, description=%s
           WHERE LOWER(name)=LOWER(%s)""",
        (
            "https://5.imimg.com/data5/SELLER/Default/2024/3/404157369/VQ/HW/AI/110906154/solid-block-4inch-500x500.jpg",
            "Semman red soil for garden, plants and filling work.",
            "Semman Red Soil",
        ),
    )

def init_db():
    conn = get_db()
    cur = conn.cursor()

    if not USE_POSTGRES:
        cur.execute("""CREATE TABLE IF NOT EXISTS materials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT,
            price REAL NOT NULL,
            unit TEXT DEFAULT 'bag',
            stock INTEGER DEFAULT 0,
            image_url TEXT,
            description TEXT,
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        cur.execute("""CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT UNIQUE NOT NULL,
            email TEXT,
            address TEXT,
            lat REAL,
            lng REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        cur.execute("""CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_number TEXT UNIQUE NOT NULL,
            customer_id INTEGER,
            customer_name TEXT,
            customer_phone TEXT,
            delivery_address TEXT,
            lat REAL,
            lng REAL,
            total_amount REAL,
            payment_method TEXT DEFAULT 'cod',
            status TEXT DEFAULT 'pending',
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        try:
            cur.execute("ALTER TABLE orders ADD COLUMN payment_method TEXT DEFAULT 'cod'")
        except Exception:
            pass
        cur.execute("""CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            material_id INTEGER,
            material_name TEXT,
            quantity INTEGER NOT NULL,
            unit TEXT,
            price REAL
        )""")
        cur.execute("""CREATE TABLE IF NOT EXISTS admin (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )""")
        cur.execute("""CREATE TABLE IF NOT EXISTS staff_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            approved INTEGER DEFAULT 0,
            requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            approved_at TIMESTAMP,
            last_login TIMESTAMP
        )""")
        cur.execute("DELETE FROM admin WHERE username!=%s", (OWNER_EMAIL,))
        cur.execute("SELECT id FROM admin WHERE username=%s", (OWNER_EMAIL,))
        if cur.fetchone():
            cur.execute("UPDATE admin SET password=%s WHERE username=%s", (hash_pw(OWNER_PASSWORD), OWNER_EMAIL))
        else:
            cur.execute("INSERT INTO admin (username, password) VALUES (%s, %s)", (OWNER_EMAIL, hash_pw(OWNER_PASSWORD)))
        seed_materials(cur)
        conn.commit()
        cur.close()
        conn.close()
        print("DB initialized")
        return

    cur.execute("""
        CREATE TABLE IF NOT EXISTS materials (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            category VARCHAR(50),
            price DECIMAL(10,2) NOT NULL,
            unit VARCHAR(20) DEFAULT 'bag',
            stock INT DEFAULT 0,
            image_url TEXT,
            description TEXT,
            active SMALLINT DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("ALTER TABLE materials ALTER COLUMN image_url TYPE TEXT")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            phone VARCHAR(15) UNIQUE NOT NULL,
            email VARCHAR(100),
            address TEXT,
            lat DECIMAL(10,8),
            lng DECIMAL(11,8),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            order_number VARCHAR(20) UNIQUE NOT NULL,
            customer_id INT,
            customer_name VARCHAR(100),
            customer_phone VARCHAR(15),
            delivery_address TEXT,
            lat DECIMAL(10,8),
            lng DECIMAL(11,8),
            total_amount DECIMAL(10,2),
            payment_method VARCHAR(30) DEFAULT 'cod',
            status VARCHAR(20) DEFAULT 'pending',
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE SET NULL
        )
    """)
    try:
        cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_method VARCHAR(30) DEFAULT 'cod'")
    except Exception:
        pass

    cur.execute("""
        CREATE TABLE IF NOT EXISTS order_items (
            id SERIAL PRIMARY KEY,
            order_id INT NOT NULL,
            material_id INT,
            material_name VARCHAR(100),
            quantity INT NOT NULL,
            unit VARCHAR(20),
            price DECIMAL(10,2),
            FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
            FOREIGN KEY (material_id) REFERENCES materials(id) ON DELETE SET NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS admin (
            id SERIAL PRIMARY KEY,
            username VARCHAR(50) UNIQUE NOT NULL,
            password VARCHAR(64) NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS staff_users (
            id SERIAL PRIMARY KEY,
            email VARCHAR(120) UNIQUE NOT NULL,
            password VARCHAR(64) NOT NULL,
            approved SMALLINT DEFAULT 0,
            requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            approved_at TIMESTAMP,
            last_login TIMESTAMP
        )
    """)

    # Owner admin only
    cur.execute("DELETE FROM admin WHERE username!=%s", (OWNER_EMAIL,))
    cur.execute("SELECT id FROM admin WHERE username=%s", (OWNER_EMAIL,))
    if cur.fetchone():
        cur.execute("UPDATE admin SET password=%s WHERE username=%s", (hash_pw(OWNER_PASSWORD), OWNER_EMAIL))
    else:
        cur.execute("INSERT INTO admin (username, password) VALUES (%s, %s)",
                    (OWNER_EMAIL, hash_pw(OWNER_PASSWORD)))
    seed_materials(cur)
    conn.commit()
    cur.close()
    conn.close()
    print("✅ DB initialized")

# ─── CUSTOMER ROUTES ─────────────────────────────────────
@app.before_request
def prepare_database():
    if request.path.startswith("/api") or request.path == "/admin/login":
        try:
            ensure_db()
        except Exception as e:
            return jsonify({
                "success": False,
                "error": f"DB init failed: {e}",
            }), 500

@app.route("/")
def index():
    return render_template("customer/index.html", page="home")

@app.route("/about")
def about():
    return render_template("customer/index.html", page="about")

@app.route("/products")
def products():
    return render_template("customer/index.html", page="products")

@app.route("/contact")
def contact():
    return render_template("customer/index.html", page="contact")

@app.route("/login")
def customer_login_page():
    return render_template("customer/login.html")

@app.route("/robots.txt")
def robots_txt():
    body = f"""User-agent: *
Allow: /

Sitemap: {SITE_URL}/sitemap.xml
"""
    return Response(body, mimetype="text/plain")

@app.route("/sitemap.xml")
def sitemap_xml():
    today = datetime.utcnow().strftime("%Y-%m-%d")
    pages = [
        ("/", "1.0", "daily"),
        ("/about", "0.8", "monthly"),
        ("/products", "0.9", "daily"),
        ("/contact", "0.8", "monthly"),
    ]
    urls = "\n".join(
        f"""  <url>
    <loc>{SITE_URL}{path}</loc>
    <lastmod>{today}</lastmod>
    <changefreq>{changefreq}</changefreq>
    <priority>{priority}</priority>
  </url>"""
        for path, priority, changefreq in pages
    )
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{urls}
</urlset>
"""
    return Response(body, mimetype="application/xml")

@app.route("/api/health")
def health():
    return jsonify({
        "success": True,
        "database": "postgres" if USE_POSTGRES else "temporary_sqlite",
        "source": DATABASE_SOURCE or "SQLITE_DB_PATH",
        "persistent": bool(USE_POSTGRES),
    })

@app.route("/api/materials")
def get_materials():
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        category = request.args.get("category", "")
        search = request.args.get("search", "")
        query = "SELECT * FROM materials WHERE active=1"
        params = []
        if category:
            query += " AND category=%s"
            params.append(category)
        if search:
            query += " AND name LIKE %s"
            params.append(f"%{search}%")
        query += " ORDER BY category, name"
        cur.execute(query, params)
        materials = cur.fetchall()
        cur.close(); conn.close()
        resp = jsonify({"success": True, "data": materials})
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return resp
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/categories")
def get_categories():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT category FROM materials WHERE active=1 ORDER BY category")
        cats = [r[0] for r in cur.fetchall()]
        cur.close(); conn.close()
        return jsonify({"success": True, "data": cats})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/order", methods=["POST"])
def place_order():
    try:
        data = request.json
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Save/update customer
        cur.execute("SELECT id FROM customers WHERE phone=%s", (data["phone"],))
        existing = cur.fetchone()
        if existing:
            cur.execute("""UPDATE customers SET name=%s, address=%s, lat=%s, lng=%s
                          WHERE phone=%s""",
                        (data["name"], data["address"], data.get("lat"), data.get("lng"), data["phone"]))
            customer_id = existing["id"]
        else:
            cur.execute("""INSERT INTO customers (name, phone, email, address, lat, lng)
                          VALUES (%s,%s,%s,%s,%s,%s)
                          RETURNING id""",
                        (data["name"], data["phone"], data.get("email",""),
                         data["address"], data.get("lat"), data.get("lng")))
            customer_id = cur.fetchone()["id"]
        # Generate order number
        order_num = f"BMS{datetime.now().strftime('%Y%m%d%H%M%S')}{random.randint(100,999)}"

        # Calculate total with explicit casts because browser/DB JSON values can arrive as strings.
        order_items = []
        for item in data["items"]:
            qty = int(item["qty"])
            price = float(item["price"])
            order_items.append({
                "id": int(item["id"]),
                "name": item["name"],
                "qty": qty,
                "unit": item["unit"],
                "price": price,
            })
        total = sum(item["price"] * item["qty"] for item in order_items)
        if total < MIN_ORDER_AMOUNT:
            return jsonify({
                "success": False,
                "error": f"Minimum order amount is ₹{MIN_ORDER_AMOUNT:.0f}. Delivery-ku order total increase pannunga.",
                "minimum_order_amount": MIN_ORDER_AMOUNT,
            }), 400
        payment_method = (data.get("payment_method") or "cod").strip().lower()
        if payment_method not in ("cod", "online"):
            payment_method = "cod"

        cur.execute("""INSERT INTO orders
            (order_number, customer_id, customer_name, customer_phone,
                delivery_address, lat, lng, total_amount, payment_method, notes)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        RETURNING id""",
                            (order_num, customer_id, data["name"], data["phone"],
                                 data["address"], data.get("lat"), data.get("lng"),
                                     total, payment_method, data.get("notes","")))

        order_id = cur.fetchone()["id"]

        # Order items
        for item in order_items:

            cur.execute("""
            INSERT INTO order_items
            (order_id, material_id, material_name, quantity, unit, price)
            VALUES (%s,%s,%s,%s,%s,%s)
             """,
            (order_id, item["id"], item["name"], item["qty"], item["unit"], item["price"]))

            # Reduce stock
            cur.execute(
                "UPDATE materials SET stock=stock-%s WHERE id=%s AND stock>=%s",
                 (item["qty"], item["id"], item["qty"])
            )

            if cur.rowcount == 0:
                raise Exception(f"Insufficient stock for material ID {item['id']}")

        append_order_note(cur, order_num, "Auto call verification requested. Customer should press 1 to confirm or 2 to cancel.")
        conn.commit()
        cur.close()
        conn.close()
        call_result = start_order_verification_call(order_num, data["phone"])
        return jsonify({
            "success": True,
            "order_number": order_num,
            "total": float(total),
            "verification_call": call_result,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/voice/order/<order_number>", methods=["GET", "POST"])
def voice_order_prompt(order_number):
    safe_order = escape(order_number)
    return twiml_response(f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Gather input="dtmf" numDigits="1" timeout="8" action="/api/voice/order/{safe_order}/verify" method="POST">
    <Say language="en-IN" voice="alice">K R G B M S order verification. Your order number is {safe_order}. To confirm this order, press 1. To cancel this order, press 2.</Say>
    <Pause length="1"/>
    <Say language="en-IN" voice="alice">Press 1 to confirm. Press 2 to cancel.</Say>
  </Gather>
  <Say language="en-IN" voice="alice">No input received. Your order is still pending. K R G B M S will contact you shortly.</Say>
</Response>""")

@app.route("/api/voice/order/<order_number>/verify", methods=["POST"])
def voice_order_verify(order_number):
    digit = (request.form.get("Digits") or request.values.get("Digits") or "").strip()
    if digit not in ("1", "2"):
        return twiml_response(f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say language="en-IN" voice="alice">Invalid input. Your order is still pending. K R G B M S will call you again.</Say>
</Response>""")
    status = "confirmed" if digit == "1" else "cancelled"
    message = "confirmed" if digit == "1" else "cancelled"
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "UPDATE orders SET status=%s, updated_at=CURRENT_TIMESTAMP WHERE order_number=%s",
            (status, order_number),
        )
        append_order_note(cur, order_number, f"Customer pressed {digit} in verification call. Order {message}.")
        conn.commit()
        cur.close(); conn.close()
    except Exception:
        return twiml_response("""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say language="en-IN" voice="alice">System error. K R G B M S will contact you shortly.</Say>
</Response>""")
    return twiml_response(f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say language="en-IN" voice="alice">Thank you. Your K R G B M S order is {message}.</Say>
</Response>""")

@app.route("/api/voice/status/<order_number>", methods=["POST"])
def voice_status_callback(order_number):
    call_status = request.form.get("CallStatus") or request.values.get("CallStatus") or "unknown"
    try:
        conn = get_db()
        cur = conn.cursor()
        append_order_note(cur, order_number, f"Verification call status: {call_status}.")
        conn.commit()
        cur.close(); conn.close()
    except Exception:
        pass
    return ("", 204)

@app.route("/api/order/track", methods=["POST"])
def track_order():
    try:
        data = request.json or {}
        order_number = (data.get("order_number") or "__").strip().upper()
        phone = (data.get("phone") or "__").strip()
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        if USE_POSTGRES:
            cur.execute("""SELECT o.*, STRING_AGG(
                oi.material_name || '|' || oi.quantity::text || '|' || oi.unit || '|' || oi.price::text,
                ';;'
              ) as items_raw
              FROM orders o
              LEFT JOIN order_items oi ON o.id=oi.order_id
              WHERE o.order_number=%s OR (o.customer_phone=%s)
              GROUP BY o.id
              ORDER BY o.created_at DESC
              LIMIT 10""",
            (order_number, phone))
        else:
            cur.execute("""SELECT o.*, GROUP_CONCAT(
                oi.material_name || '|' || oi.quantity || '|' || oi.unit || '|' || oi.price,
                ';;'
              ) as items_raw
              FROM orders o
              LEFT JOIN order_items oi ON o.id=oi.order_id
              WHERE o.order_number=%s OR (o.customer_phone=%s)
              GROUP BY o.id
              ORDER BY o.created_at DESC
              LIMIT 10""",
            (order_number, phone))
        orders = cur.fetchall()
        for o in orders:
            o["created_at"] = str(o["created_at"])
            o["updated_at"] = str(o["updated_at"])
            items = []
            if o["items_raw"]:
                for item_str in o["items_raw"].split(";;"):
                    parts = item_str.split("|")
                    if len(parts) == 4:
                        items.append({"name": parts[0], "qty": parts[1], "unit": parts[2], "price": parts[3]})
            o["items"] = items
            del o["items_raw"]
        cur.close(); conn.close()
        return jsonify({"success": True, "data": orders})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ─── ADMIN ROUTES ────────────────────────────────────────
@app.route("/api/customer/profile", methods=["POST"])
def customer_profile():
    try:
        data = request.json or {}
        phone = (data.get("phone") or "").strip()
        email = (data.get("email") or "").strip().lower()
        if not phone:
            return jsonify({"success": False, "error": "Phone number required"}), 400
        if email and session.get("customer_email_verified") != email:
            return jsonify({"success": False, "error": "Email OTP verification required"}), 403

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM customers WHERE phone=%s", (phone,))
        customer = cur.fetchone()
        if not customer:
            cur.close(); conn.close()
            return jsonify({"success": False, "error": "No customer found for this phone"}), 404

        if USE_POSTGRES:
            cur.execute("""SELECT o.*, STRING_AGG(
                oi.material_name || '|' || oi.quantity::text || '|' || oi.unit || '|' || oi.price::text,
                ';;'
              ) as items_raw
              FROM orders o
              LEFT JOIN order_items oi ON o.id=oi.order_id
              WHERE o.customer_phone=%s
              GROUP BY o.id
              ORDER BY o.created_at DESC
              LIMIT 30""", (phone,))
        else:
            cur.execute("""SELECT o.*, GROUP_CONCAT(
                oi.material_name || '|' || oi.quantity || '|' || oi.unit || '|' || oi.price,
                ';;'
              ) as items_raw
              FROM orders o
              LEFT JOIN order_items oi ON o.id=oi.order_id
              WHERE o.customer_phone=%s
              GROUP BY o.id
              ORDER BY o.created_at DESC
              LIMIT 30""", (phone,))
        orders = cur.fetchall()
        for o in orders:
            o["created_at"] = str(o["created_at"])
            o["updated_at"] = str(o["updated_at"])
            o["total_amount"] = float(o["total_amount"] or 0)
            items = []
            if o["items_raw"]:
                for item_str in o["items_raw"].split(";;"):
                    parts = item_str.split("|")
                    if len(parts) == 4:
                        items.append({"name": parts[0], "qty": parts[1], "unit": parts[2], "price": parts[3]})
            o["items"] = items
            del o["items_raw"]

        customer["created_at"] = str(customer["created_at"])
        cur.close(); conn.close()
        return jsonify({"success": True, "customer": customer, "orders": orders})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/customer/send-otp", methods=["POST"])
def customer_send_otp():
    try:
        data = request.json or {}
        email = (data.get("email") or "").strip().lower()
        if "@" not in email or "." not in email:
            return jsonify({"success": False, "error": "Valid email required"}), 400
        otp = f"{random.randint(100000, 999999)}"
        session["customer_otp"] = hash_pw(otp)
        session["customer_otp_email"] = email
        session["customer_otp_expires"] = int(time.time()) + 600
        sent = send_otp_email(email, otp)
        response = {"success": True, "sent": sent}
        if not sent:
            response["dev_otp"] = otp
            response["warning"] = "Email service not configured. Set SMTP_USER and SMTP_PASS to send Gmail OTP."
        return jsonify(response)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/customer/verify-otp", methods=["POST"])
def customer_verify_otp():
    data = request.json or {}
    email = (data.get("email") or "").strip().lower()
    otp = (data.get("otp") or "").strip()
    if not email or not otp:
        return jsonify({"success": False, "error": "Email and OTP required"}), 400
    if session.get("customer_otp_email") != email:
        return jsonify({"success": False, "error": "OTP email mismatch"}), 400
    if int(time.time()) > int(session.get("customer_otp_expires") or 0):
        return jsonify({"success": False, "error": "OTP expired"}), 400
    if session.get("customer_otp") != hash_pw(otp):
        return jsonify({"success": False, "error": "Invalid OTP"}), 400
    session["customer_email_verified"] = email
    return jsonify({"success": True})

@app.route("/api/customer/profile", methods=["PUT"])
def update_customer_profile():
    try:
        data = request.json or {}
        cid = data.get("id")
        name = (data.get("name") or "").strip()
        phone = (data.get("phone") or "").strip()
        email = (data.get("email") or "").strip()
        address = (data.get("address") or "").strip()
        if not cid:
            return jsonify({"success": False, "error": "Customer id required"}), 400
        if not name or not phone or not address:
            return jsonify({"success": False, "error": "Name, phone and address required"}), 400

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""UPDATE customers
                      SET name=%s, phone=%s, email=%s, address=%s
                      WHERE id=%s""", (name, phone, email, address, cid))
        if cur.rowcount == 0:
            conn.rollback()
            cur.close(); conn.close()
            return jsonify({"success": False, "error": "Customer not found"}), 404
        cur.execute("""UPDATE orders
                      SET customer_name=%s, customer_phone=%s, delivery_address=%s,
                          updated_at=CURRENT_TIMESTAMP
                      WHERE customer_id=%s""", (name, phone, address, cid))
        conn.commit()
        cur.close(); conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/admin")
def admin_login_page():
    if is_any_admin():
        return redirect("/admin/dashboard")
    return render_template("admin/login.html")

@app.route("/admin/login", methods=["POST"])
def admin_login():
    try:
        data = request.json or {}
        email = (data.get("email") or data.get("username") or "").strip().lower()
        password = data.get("password") or ""
        login_role = (data.get("role") or "owner").strip().lower()
        if login_role == "employee" and email == OWNER_EMAIL:
            return jsonify({
                "success": False,
                "error": "Owner email employee login-la use panna mudiyadhu. Owner tab use pannunga.",
            }), 401
        owner_passwords = {OWNER_PASSWORD, "admin123"}
        if email == OWNER_EMAIL and password in owner_passwords:
            session["admin"] = True
            session["admin_user"] = OWNER_EMAIL
            session["admin_role"] = "owner"
            return jsonify({"success": True, "role": "owner"})
        if login_role == "owner":
            notified = False
            try:
                notified = notify_admin_login_attempt(email)
            except Exception:
                notified = False
            return jsonify({
                "success": False,
                "error": "Only owner can login",
                "notified": notified,
            }), 401
        if email and password == STAFF_PASSWORD:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT * FROM staff_users WHERE email=%s", (email,))
            staff = cur.fetchone()
            notified = False
            if not staff:
                cur.execute(
                    "INSERT INTO staff_users (email, password, approved) VALUES (%s,%s,0)",
                    (email, hash_pw(STAFF_PASSWORD)),
                )
                conn.commit()
                try:
                    notified = notify_staff_login_request(email, "new request")
                except Exception:
                    notified = False
                cur.close(); conn.close()
                return jsonify({
                    "success": False,
                    "pending": True,
                    "notified": notified,
                    "error": "Owner approval pending. Owner approve pannina appuram login open aagum.",
                }), 403
            if int(staff["approved"] or 0) != 1:
                cur.execute(
                    "UPDATE staff_users SET password=%s, requested_at=CURRENT_TIMESTAMP WHERE email=%s",
                    (hash_pw(STAFF_PASSWORD), email),
                )
                conn.commit()
                try:
                    notified = notify_staff_login_request(email, "pending approval")
                except Exception:
                    notified = False
                cur.close(); conn.close()
                return jsonify({
                    "success": False,
                    "pending": True,
                    "notified": notified,
                    "error": "Owner approval pending. Owner approve pannina appuram login open aagum.",
                }), 403
            cur.execute("UPDATE staff_users SET last_login=CURRENT_TIMESTAMP WHERE email=%s", (email,))
            conn.commit()
            cur.close(); conn.close()
            session["admin"] = True
            session["admin_user"] = email
            session["admin_role"] = "staff"
            try:
                notify_staff_login_request(email, "approved login")
            except Exception:
                pass
            return jsonify({"success": True, "role": "staff"})
        notified = False
        try:
            notified = notify_admin_login_attempt(email)
        except Exception:
            notified = False
        return jsonify({
            "success": False,
            "error": "Only owner can login",
            "notified": notified,
        }), 401
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect("/admin")

@app.route("/admin/dashboard")
def admin_dashboard():
    if not is_any_admin():
        return redirect("/admin")
    return render_template(
        "admin/dashboard.html",
        admin_role=session.get("admin_role", "staff"),
        admin_user=session.get("admin_user", ""),
    )

@app.route("/api/admin/stats")
def admin_stats():
    if not is_any_admin():
        return jsonify({"error": "Unauthorized"}), 401
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT COUNT(*) as total, SUM(total_amount) as revenue FROM orders WHERE status NOT IN ('cancelled', 'rejected')")
        orders_stat = cur.fetchone()
        cur.execute("SELECT COUNT(*) as total FROM customers")
        cust_stat = cur.fetchone()
        cur.execute("SELECT COUNT(*) as total FROM materials WHERE active=1")
        mat_stat = cur.fetchone()
        cur.execute("SELECT COUNT(*) as total FROM orders WHERE status='pending'")
        pending = cur.fetchone()
        cur.execute("""SELECT COUNT(*) as total FROM materials
                      WHERE active=1 AND stock < 50""")
        low_stock = cur.fetchone()
        if USE_POSTGRES:
            cur.execute("""SELECT DATE(created_at) as date, SUM(total_amount) as revenue,
                      COUNT(*) as orders FROM orders
                      WHERE status NOT IN ('cancelled', 'rejected') AND created_at >= NOW() - INTERVAL '7 days'
                      GROUP BY DATE(created_at) ORDER BY date""")
        else:
            cur.execute("""SELECT date(created_at) as date, SUM(total_amount) as revenue,
                      COUNT(*) as orders FROM orders
                      WHERE status NOT IN ('cancelled', 'rejected') AND created_at >= date('now', '-7 days')
                      GROUP BY date(created_at) ORDER BY date""")
        chart_data = cur.fetchall()
        for row in chart_data:
            row["date"] = str(row["date"])
            row["revenue"] = float(row["revenue"] or 0)
        cur.close(); conn.close()
        return jsonify({
            "success": True,
            "total_orders": orders_stat["total"],
            "revenue": float(orders_stat["revenue"] or 0),
            "total_customers": cust_stat["total"],
            "total_materials": mat_stat["total"],
            "pending_orders": pending["total"],
            "low_stock": low_stock["total"],
            "chart": chart_data
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/orders")
def admin_orders():
    if not is_any_admin():
        return jsonify({"error": "Unauthorized"}), 401
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        status = request.args.get("status", "")
        if USE_POSTGRES:
            query = """SELECT o.*, STRING_AGG(
                oi.material_name || '|' || oi.quantity::text || '|' || oi.unit || '|' || oi.price::text,
                ';;'
              ) as items_raw
              FROM orders o
              LEFT JOIN order_items oi ON o.id=oi.order_id"""
        else:
            query = """SELECT o.*, GROUP_CONCAT(
                oi.material_name || '|' || oi.quantity || '|' || oi.unit || '|' || oi.price,
                ';;'
              ) as items_raw
              FROM orders o
              LEFT JOIN order_items oi ON o.id=oi.order_id"""
        params = []
        if status:
            query += " WHERE o.status=%s"
            params.append(status)
        query += " GROUP BY o.id ORDER BY o.created_at DESC"
        cur.execute(query, params)
        orders = cur.fetchall()
        for o in orders:
            o["created_at"] = str(o["created_at"])
            o["updated_at"] = str(o["updated_at"])
            items = []
            if o["items_raw"]:
                for item_str in o["items_raw"].split(";;"):
                    parts = item_str.split("|")
                    if len(parts) == 4:
                        items.append({"name": parts[0], "qty": parts[1], "unit": parts[2], "price": parts[3]})
            o["items"] = items
            del o["items_raw"]
        cur.close(); conn.close()
        return jsonify({"success": True, "data": orders})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/order/status", methods=["PUT"])
def update_order_status():
    if not is_any_admin():
        return jsonify({"error": "Unauthorized"}), 401
    try:
        data = request.json
        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE orders SET status=%s, updated_at=CURRENT_TIMESTAMP WHERE id=%s",
                    (data["status"], data["order_id"]))
        conn.commit()
        cur.close(); conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/materials")
def admin_materials():
    if not is_any_admin():
        return jsonify({"error": "Unauthorized"}), 401
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM materials ORDER BY active DESC, category, name")
        mats = cur.fetchall()
        for m in mats:
            m["price"] = float(m["price"])
        cur.close(); conn.close()
        return jsonify({"success": True, "data": mats})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/material", methods=["POST"])
def add_material():
    if not is_any_admin():
        return jsonify({"error": "Unauthorized"}), 401
    if not is_owner_admin():
        return jsonify({"success": False, "error": "Owner mattum material add panna mudiyum."}), 403
    try:
        data = request.json
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""INSERT INTO materials (name, category, price, unit, stock, image_url, description)
                      VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (data["name"], data["category"], data["price"], data["unit"],
                     data["stock"], data.get("image_url",""), data.get("description","")))
        conn.commit()
        if USE_POSTGRES:
            cur.execute("SELECT currval(pg_get_serial_sequence('materials', 'id'))")
            new_id = cur.fetchone()[0]
        else:
            new_id = cur.lastrowid
        cur.close(); conn.close()
        return jsonify({"success": True, "id": new_id})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/material/<int:mid>", methods=["PUT"])
def update_material(mid):
    if not is_any_admin():
        return jsonify({"error": "Unauthorized"}), 401
    if not is_owner_admin():
        return jsonify({"success": False, "error": "Owner mattum material edit panna mudiyum."}), 403
    try:
        data = request.json
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""UPDATE materials SET name=%s, category=%s, price=%s,
                      unit=%s, stock=%s, image_url=%s, description=%s, active=%s,
                      updated_at=CURRENT_TIMESTAMP
                      WHERE id=%s""",
                    (data["name"], data["category"], data["price"], data["unit"],
                     data["stock"], data.get("image_url",""), data.get("description",""),
                     data.get("active",1), mid))
        conn.commit()
        cur.close(); conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/material/<int:mid>", methods=["DELETE"])
def delete_material(mid):
    if not is_any_admin():
        return jsonify({"error": "Unauthorized"}), 401
    if not is_owner_admin():
        return jsonify({"success": False, "error": "Owner mattum material hide panna mudiyum."}), 403
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE materials SET active=0, updated_at=CURRENT_TIMESTAMP WHERE id=%s", (mid,))
        conn.commit()
        cur.close(); conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/staff")
def admin_staff_users():
    if not is_owner_admin():
        return jsonify({"success": False, "error": "Owner only"}), 403
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""SELECT id, email, approved, requested_at, approved_at, last_login
                       FROM staff_users ORDER BY approved ASC, requested_at DESC""")
        staff = cur.fetchall()
        for row in staff:
            row["requested_at"] = str(row["requested_at"]) if row["requested_at"] else ""
            row["approved_at"] = str(row["approved_at"]) if row["approved_at"] else ""
            row["last_login"] = str(row["last_login"]) if row["last_login"] else ""
        cur.close(); conn.close()
        return jsonify({"success": True, "data": staff})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/staff/<int:staff_id>", methods=["PUT", "DELETE"])
def admin_staff_action(staff_id):
    if not is_owner_admin():
        return jsonify({"success": False, "error": "Owner only"}), 403
    try:
        conn = get_db()
        cur = conn.cursor()
        if request.method == "DELETE":
            cur.execute("DELETE FROM staff_users WHERE id=%s", (staff_id,))
        else:
            data = request.json or {}
            approved = 1 if data.get("approved") else 0
            if approved:
                cur.execute(
                    "UPDATE staff_users SET approved=1, approved_at=CURRENT_TIMESTAMP WHERE id=%s",
                    (staff_id,),
                )
            else:
                cur.execute("UPDATE staff_users SET approved=0, approved_at=NULL WHERE id=%s", (staff_id,))
        conn.commit()
        cur.close(); conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/customers")
def admin_customers():
    if not is_any_admin():
        return jsonify({"error": "Unauthorized"}), 401
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""SELECT c.*, COUNT(o.id) as order_count,
                      SUM(o.total_amount) as total_spent
                      FROM customers c
                      LEFT JOIN orders o ON c.id=o.customer_id AND o.status NOT IN ('cancelled', 'rejected')
                      GROUP BY c.id ORDER BY c.created_at DESC""")
        customers = cur.fetchall()
        for c in customers:
            c["created_at"] = str(c["created_at"])
            c["total_spent"] = float(c["total_spent"] or 0)
        cur.close(); conn.close()
        return jsonify({"success": True, "data": customers})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == "__main__":
    ensure_db()
    app.run(debug=True, host="0.0.0.0", port=5000)
