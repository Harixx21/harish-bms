from flask import Flask, render_template, request, jsonify, session, redirect
import hashlib
import os
from datetime import datetime

app = Flask(__name__)
app.secret_key = "bms_secret_key_2024"

# ── DB SETUP ─────────────────────────────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL", "")

def get_db():
    if DATABASE_URL:
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        return conn, True  # True = postgres
    else:
        import sqlite3
        conn = sqlite3.connect("harish_bms.db")
        conn.row_factory = sqlite3.Row
        return conn, False  # False = sqlite

def fetchall(cur, pg):
    rows = cur.fetchall()
    if pg:
        return [dict(r) for r in rows]
    return [dict(r) for r in rows]

def fetchone(cur, pg):
    row = cur.fetchone()
    if row is None:
        return None
    return dict(row)

def ph(pg):
    """Placeholder — %s for postgres, ? for sqlite"""
    return "%s" if pg else "?"

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

# ── INIT DB ──────────────────────────────────────────────
def init_db():
    conn, pg = get_db()
    cur = conn.cursor()
    p = ph(pg)

    cur.execute(f"""CREATE TABLE IF NOT EXISTS materials (
        id {'SERIAL' if pg else 'INTEGER'} PRIMARY KEY {'AUTOINCREMENT' if not pg else ''},
        name TEXT NOT NULL,
        category TEXT,
        price REAL NOT NULL,
        unit TEXT DEFAULT 'bag',
        stock INTEGER DEFAULT 0,
        image_url TEXT,
        description TEXT,
        active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""".replace('INTEGER PRIMARY KEY AUTOINCREMENT', 'INTEGER PRIMARY KEY AUTOINCREMENT') if not pg else f"""CREATE TABLE IF NOT EXISTS materials (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        category TEXT,
        price REAL NOT NULL,
        unit TEXT DEFAULT 'bag',
        stock INTEGER DEFAULT 0,
        image_url TEXT,
        description TEXT,
        active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS customers (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        phone TEXT UNIQUE NOT NULL,
        email TEXT,
        address TEXT,
        lat REAL,
        lng REAL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""" if pg else """CREATE TABLE IF NOT EXISTS customers (
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
        id SERIAL PRIMARY KEY,
        order_number TEXT UNIQUE NOT NULL,
        customer_id INTEGER,
        customer_name TEXT,
        customer_phone TEXT,
        delivery_address TEXT,
        lat REAL,
        lng REAL,
        total_amount REAL,
        status TEXT DEFAULT 'pending',
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""" if pg else """CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_number TEXT UNIQUE NOT NULL,
        customer_id INTEGER,
        customer_name TEXT,
        customer_phone TEXT,
        delivery_address TEXT,
        lat REAL,
        lng REAL,
        total_amount REAL,
        status TEXT DEFAULT 'pending',
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS order_items (
        id SERIAL PRIMARY KEY,
        order_id INTEGER NOT NULL,
        material_id INTEGER,
        material_name TEXT,
        quantity INTEGER NOT NULL,
        unit TEXT,
        price REAL
    )""" if pg else """CREATE TABLE IF NOT EXISTS order_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL,
        material_id INTEGER,
        material_name TEXT,
        quantity INTEGER NOT NULL,
        unit TEXT,
        price REAL
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS admin (
        id SERIAL PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL
    )""" if pg else """CREATE TABLE IF NOT EXISTS admin (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL
    )""")

    # Admin default — only if not exists
    cur.execute(f"SELECT id FROM admin WHERE username={p}", ("admin",))
    if not fetchone(cur, pg):
        cur.execute(f"INSERT INTO admin (username, password) VALUES ({p},{p})",
                    ("admin", hash_pw("admin123")))

    # ── FIX: Sample materials ONLY if table is completely empty ──
    cur.execute("SELECT COUNT(*) as cnt FROM materials")
    row = fetchone(cur, pg)
    count = row["cnt"] if row else 0

    if count == 0:
        # First time only — insert sample data
        materials = [
            ("Cement (OPC 53 Grade)", "Cement", 380.00, "bag", 500,
             "https://images.unsplash.com/photo-1504307651254-35680f356dfd?w=400",
             "Premium quality OPC 53 Grade cement"),
            ("River Sand", "Sand", 55.00, "cft", 1000,
             "https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=400",
             "Clean river sand for construction"),
            ("M-Sand (Manufactured)", "Sand", 42.00, "cft", 800,
             "https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=400",
             "Eco-friendly manufactured sand"),
            ("Red Bricks", "Bricks", 8.50, "piece", 5000,
             "https://images.unsplash.com/photo-1587582423116-ec07293f0395?w=400",
             "Standard red clay bricks"),
            ("Fly Ash Bricks", "Bricks", 7.00, "piece", 3000,
             "https://images.unsplash.com/photo-1587582423116-ec07293f0395?w=400",
             "Lightweight fly ash bricks"),
            ("TMT Steel Bar (8mm)", "Steel", 68.00, "kg", 2000,
             "https://images.unsplash.com/photo-1504307651254-35680f356dfd?w=400",
             "Fe500D grade TMT bars"),
            ("TMT Steel Bar (12mm)", "Steel", 72.00, "kg", 1500,
             "https://images.unsplash.com/photo-1504307651254-35680f356dfd?w=400",
             "Fe500D grade TMT bars"),
            ("20mm Blue Metal", "Aggregate", 48.00, "cft", 600,
             "https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=400",
             "Crushed granite aggregate"),
            ("40mm Blue Metal", "Aggregate", 44.00, "cft", 600,
             "https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=400",
             "Crushed granite aggregate"),
            ("Wall Putty", "Finishing", 320.00, "bag", 200,
             "https://images.unsplash.com/photo-1562259929-b4e1fd3aef09?w=400",
             "Smooth finish wall putty"),
        ]
        for m in materials:
            cur.execute(
                f"INSERT INTO materials (name,category,price,unit,stock,image_url,description) VALUES ({p},{p},{p},{p},{p},{p},{p})",
                m
            )
        print("✅ Sample materials inserted (first time only)")
    else:
        # ── KEY FIX: Do NOT touch materials if they already exist ──
        print(f"✅ DB ready — {count} materials found, skipping sample insert")

    conn.commit()
    cur.close()
    conn.close()
    print("✅ DB initialized")

# ── CUSTOMER ROUTES ──────────────────────────────────────
@app.route("/")
def index():
    return render_template("customer/index.html")

@app.route("/api/materials")
def get_materials():
    try:
        conn, pg = get_db()
        cur = conn.cursor()
        p = ph(pg)
        category = request.args.get("category", "")
        search = request.args.get("search", "")
        query = "SELECT * FROM materials WHERE active=1"
        params = []
        if category:
            query += f" AND category={p}"
            params.append(category)
        if search:
            query += f" AND name LIKE {p}"
            params.append(f"%{search}%")
        query += " ORDER BY category, name"
        cur.execute(query, params)
        rows = fetchall(cur, pg)
        cur.close(); conn.close()
        return jsonify({"success": True, "data": rows})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/categories")
def get_categories():
    try:
        conn, pg = get_db()
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
        conn, pg = get_db()
        cur = conn.cursor()
        p = ph(pg)

        cur.execute(f"SELECT id FROM customers WHERE phone={p}", (data["phone"],))
        existing = fetchone(cur, pg)
        if existing:
            cur.execute(f"UPDATE customers SET name={p},address={p},lat={p},lng={p} WHERE phone={p}",
                        (data["name"], data["address"], data.get("lat"), data.get("lng"), data["phone"]))
            customer_id = existing["id"]
        else:
            if pg:
                cur.execute(f"INSERT INTO customers (name,phone,email,address,lat,lng) VALUES ({p},{p},{p},{p},{p},{p}) RETURNING id",
                            (data["name"], data["phone"], data.get("email",""), data["address"], data.get("lat"), data.get("lng")))
                customer_id = cur.fetchone()[0]
            else:
                cur.execute(f"INSERT INTO customers (name,phone,email,address,lat,lng) VALUES ({p},{p},{p},{p},{p},{p})",
                            (data["name"], data["phone"], data.get("email",""), data["address"], data.get("lat"), data.get("lng")))
                customer_id = cur.lastrowid

        order_num = f"BMS{datetime.now().strftime('%Y%m%d%H%M%S')}"
        total = sum(item["price"] * item["qty"] for item in data["items"])

        if pg:
            cur.execute(f"""INSERT INTO orders (order_number,customer_id,customer_name,customer_phone,
                          delivery_address,lat,lng,total_amount,notes) VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p}) RETURNING id""",
                        (order_num, customer_id, data["name"], data["phone"], data["address"],
                         data.get("lat"), data.get("lng"), total, data.get("notes","")))
            order_id = cur.fetchone()[0]
        else:
            cur.execute(f"""INSERT INTO orders (order_number,customer_id,customer_name,customer_phone,
                          delivery_address,lat,lng,total_amount,notes) VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p})""",
                        (order_num, customer_id, data["name"], data["phone"], data["address"],
                         data.get("lat"), data.get("lng"), total, data.get("notes","")))
            order_id = cur.lastrowid

        for item in data["items"]:
            cur.execute(f"INSERT INTO order_items (order_id,material_id,material_name,quantity,unit,price) VALUES ({p},{p},{p},{p},{p},{p})",
                        (order_id, item["id"], item["name"], item["qty"], item["unit"], item["price"]))
            cur.execute(f"UPDATE materials SET stock=stock-{p} WHERE id={p} AND stock>={p}",
                        (item["qty"], item["id"], item["qty"]))

        conn.commit(); cur.close(); conn.close()
        return jsonify({"success": True, "order_number": order_num, "total": float(total)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/order/track", methods=["POST"])
def track_order():
    try:
        data = request.json
        conn, pg = get_db()
        cur = conn.cursor()
        p = ph(pg)
        sep = "||" if pg else "||"
        grp = "STRING_AGG" if pg else "GROUP_CONCAT"

        if pg:
            cur.execute(f"""SELECT o.*, STRING_AGG(
                            oi.material_name||'|'||oi.quantity||'|'||oi.unit||'|'||oi.price::text, ';;') as items_raw
                          FROM orders o LEFT JOIN order_items oi ON o.id=oi.order_id
                          WHERE o.order_number={p} OR o.customer_phone={p}
                          GROUP BY o.id ORDER BY o.created_at DESC LIMIT 10""",
                        (data.get("order_number","__"), data.get("phone","__")))
        else:
            cur.execute(f"""SELECT o.*, GROUP_CONCAT(
                            oi.material_name||'|'||oi.quantity||'|'||oi.unit||'|'||oi.price, ';;') as items_raw
                          FROM orders o LEFT JOIN order_items oi ON o.id=oi.order_id
                          WHERE o.order_number={p} OR o.customer_phone={p}
                          GROUP BY o.id ORDER BY o.created_at DESC LIMIT 10""",
                        (data.get("order_number","__"), data.get("phone","__")))

        orders = []
        for row in cur.fetchall():
            o = dict(row) if pg else dict(row)
            items = []
            if o.get("items_raw"):
                for item_str in o["items_raw"].split(";;"):
                    parts = item_str.split("|")
                    if len(parts) == 4:
                        items.append({"name":parts[0],"qty":parts[1],"unit":parts[2],"price":parts[3]})
            o["items"] = items
            o.pop("items_raw", None)
            o["created_at"] = str(o.get("created_at",""))
            o["updated_at"] = str(o.get("updated_at",""))
            orders.append(o)
        cur.close(); conn.close()
        return jsonify({"success": True, "data": orders})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ── ADMIN ROUTES ─────────────────────────────────────────
@app.route("/admin")
def admin_login_page():
    if session.get("admin"): return redirect("/admin/dashboard")
    return render_template("admin/login.html")

@app.route("/admin/login", methods=["POST"])
def admin_login():
    try:
        data = request.json
        conn, pg = get_db()
        cur = conn.cursor()
        p = ph(pg)
        cur.execute(f"SELECT * FROM admin WHERE username={p} AND password={p}",
                    (data["username"], hash_pw(data["password"])))
        admin = fetchone(cur, pg)
        cur.close(); conn.close()
        if admin:
            session["admin"] = True
            session["admin_user"] = data["username"]
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "Invalid credentials"}), 401
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/admin/logout")
def admin_logout():
    session.clear(); return redirect("/admin")

@app.route("/admin/dashboard")
def admin_dashboard():
    if not session.get("admin"): return redirect("/admin")
    return render_template("admin/dashboard.html")

@app.route("/api/admin/stats")
def admin_stats():
    if not session.get("admin"): return jsonify({"error":"Unauthorized"}), 401
    try:
        conn, pg = get_db()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as total, SUM(total_amount) as revenue FROM orders WHERE status!='cancelled'")
        o = fetchone(cur, pg)
        cur.execute("SELECT COUNT(*) as total FROM customers")
        c = fetchone(cur, pg)
        cur.execute("SELECT COUNT(*) as total FROM materials WHERE active=1")
        m = fetchone(cur, pg)
        cur.execute("SELECT COUNT(*) as total FROM orders WHERE status='pending'")
        pend = fetchone(cur, pg)
        cur.execute("SELECT COUNT(*) as total FROM materials WHERE active=1 AND stock<50")
        ls = fetchone(cur, pg)
        if pg:
            cur.execute("""SELECT date(created_at) as date, SUM(total_amount) as revenue, COUNT(*) as orders
                          FROM orders WHERE status!='cancelled' AND created_at >= NOW() - INTERVAL '7 days'
                          GROUP BY date(created_at) ORDER BY date""")
        else:
            cur.execute("""SELECT date(created_at) as date, SUM(total_amount) as revenue, COUNT(*) as orders
                          FROM orders WHERE status!='cancelled' AND created_at >= date('now','-7 days')
                          GROUP BY date(created_at) ORDER BY date""")
        chart = fetchall(cur, pg)
        cur.close(); conn.close()
        return jsonify({"success":True,
                        "total_orders": o["total"] or 0,
                        "revenue": float(o["revenue"] or 0),
                        "total_customers": c["total"] or 0,
                        "total_materials": m["total"] or 0,
                        "pending_orders": pend["total"] or 0,
                        "low_stock": ls["total"] or 0,
                        "chart": [{**r, "revenue": float(r["revenue"] or 0), "date": str(r["date"])} for r in chart]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/orders")
def admin_orders():
    if not session.get("admin"): return jsonify({"error":"Unauthorized"}), 401
    try:
        conn, pg = get_db()
        cur = conn.cursor()
        p = ph(pg)
        status = request.args.get("status","")
        if pg:
            query = """SELECT o.*, STRING_AGG(oi.material_name||'|'||oi.quantity||'|'||oi.unit||'|'||oi.price::text,';;') as items_raw
                      FROM orders o LEFT JOIN order_items oi ON o.id=oi.order_id"""
        else:
            query = """SELECT o.*, GROUP_CONCAT(oi.material_name||'|'||oi.quantity||'|'||oi.unit||'|'||oi.price,';;') as items_raw
                      FROM orders o LEFT JOIN order_items oi ON o.id=oi.order_id"""
        params = []
        if status:
            query += f" WHERE o.status={p}"; params.append(status)
        query += " GROUP BY o.id ORDER BY o.created_at DESC"
        cur.execute(query, params)
        orders = []
        for row in cur.fetchall():
            o = dict(row)
            items = []
            if o.get("items_raw"):
                for item_str in o["items_raw"].split(";;"):
                    parts = item_str.split("|")
                    if len(parts)==4:
                        items.append({"name":parts[0],"qty":parts[1],"unit":parts[2],"price":parts[3]})
            o["items"] = items
            o.pop("items_raw", None)
            o["created_at"] = str(o.get("created_at",""))
            o["updated_at"] = str(o.get("updated_at",""))
            o["total_amount"] = float(o.get("total_amount") or 0)
            orders.append(o)
        cur.close(); conn.close()
        return jsonify({"success": True, "data": orders})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/order/status", methods=["PUT"])
def update_order_status():
    if not session.get("admin"): return jsonify({"error":"Unauthorized"}), 401
    try:
        data = request.json
        conn, pg = get_db()
        cur = conn.cursor()
        p = ph(pg)
        cur.execute(f"UPDATE orders SET status={p}, updated_at=CURRENT_TIMESTAMP WHERE id={p}",
                    (data["status"], data["order_id"]))
        conn.commit(); cur.close(); conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/materials")
def admin_materials():
    if not session.get("admin"): return jsonify({"error":"Unauthorized"}), 401
    try:
        conn, pg = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM materials ORDER BY category, name")
        rows = fetchall(cur, pg)
        for r in rows: r["price"] = float(r.get("price") or 0)
        cur.close(); conn.close()
        return jsonify({"success": True, "data": rows})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/material", methods=["POST"])
def add_material():
    if not session.get("admin"): return jsonify({"error":"Unauthorized"}), 401
    try:
        data = request.json
        conn, pg = get_db()
        cur = conn.cursor()
        p = ph(pg)
        if pg:
            cur.execute(f"INSERT INTO materials (name,category,price,unit,stock,image_url,description) VALUES ({p},{p},{p},{p},{p},{p},{p}) RETURNING id",
                        (data["name"],data["category"],data["price"],data["unit"],data["stock"],data.get("image_url",""),data.get("description","")))
            new_id = cur.fetchone()[0]
        else:
            cur.execute(f"INSERT INTO materials (name,category,price,unit,stock,image_url,description) VALUES ({p},{p},{p},{p},{p},{p},{p})",
                        (data["name"],data["category"],data["price"],data["unit"],data["stock"],data.get("image_url",""),data.get("description","")))
            new_id = cur.lastrowid
        conn.commit(); cur.close(); conn.close()
        return jsonify({"success": True, "id": new_id})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/material/<int:mid>", methods=["PUT"])
def update_material(mid):
    if not session.get("admin"): return jsonify({"error":"Unauthorized"}), 401
    try:
        data = request.json
        conn, pg = get_db()
        cur = conn.cursor()
        p = ph(pg)
        cur.execute(f"""UPDATE materials SET name={p},category={p},price={p},unit={p},
                      stock={p},image_url={p},description={p},active={p} WHERE id={p}""",
                    (data["name"],data["category"],data["price"],data["unit"],
                     data["stock"],data.get("image_url",""),data.get("description",""),
                     data.get("active",1),mid))
        conn.commit(); cur.close(); conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/material/<int:mid>", methods=["DELETE"])
def delete_material(mid):
    if not session.get("admin"): return jsonify({"error":"Unauthorized"}), 401
    try:
        conn, pg = get_db()
        cur = conn.cursor()
        p = ph(pg)
        cur.execute(f"UPDATE materials SET active=0 WHERE id={p}", (mid,))
        conn.commit(); cur.close(); conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/customers")
def admin_customers():
    if not session.get("admin"): return jsonify({"error":"Unauthorized"}), 401
    try:
        conn, pg = get_db()
        cur = conn.cursor()
        cur.execute("""SELECT c.*, COUNT(o.id) as order_count, SUM(o.total_amount) as total_spent
                      FROM customers c LEFT JOIN orders o ON c.id=o.customer_id AND o.status!='cancelled'
                      GROUP BY c.id ORDER BY c.created_at DESC""")
        rows = fetchall(cur, pg)
        for r in rows:
            r["created_at"] = str(r.get("created_at",""))
            r["total_spent"] = float(r.get("total_spent") or 0)
        cur.close(); conn.close()
        return jsonify({"success": True, "data": rows})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ── STARTUP ──────────────────────────────────────────────
init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
