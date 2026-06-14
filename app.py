from flask import Flask, render_template, request, jsonify, session, redirect
import sqlite3
import hashlib
import os
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "bms_secret_key_2024")

if os.environ.get("VERCEL"):
    DB_PATH = os.path.join("/tmp", "harish_bms.db")
else:
    DB_PATH = os.path.join(os.path.dirname(__file__), "harish_bms.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def init_db():
    conn = get_db()
    cur = conn.cursor()

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
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
        status TEXT DEFAULT 'pending',
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

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

    cur.execute("SELECT id FROM admin WHERE username='admin'")
    if not cur.fetchone():
        cur.execute("INSERT INTO admin (username, password) VALUES ('admin', ?)", (hash_pw("admin123"),))

    cur.execute("SELECT COUNT(*) FROM materials")
    if cur.fetchone()[0] == 0:
        materials = [
            ("Cement (OPC 53 Grade)", "Cement", 380.00, "bag", 500, "https://images.unsplash.com/photo-1504307651254-35680f356dfd?w=400", "Premium quality OPC 53 Grade cement"),
            ("River Sand", "Sand", 55.00, "cft", 1000, "https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=400", "Clean river sand for construction"),
            ("M-Sand (Manufactured)", "Sand", 42.00, "cft", 800, "https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=400", "Eco-friendly manufactured sand"),
            ("Red Bricks", "Bricks", 8.50, "piece", 5000, "https://images.unsplash.com/photo-1587582423116-ec07293f0395?w=400", "Standard red clay bricks"),
            ("Fly Ash Bricks", "Bricks", 7.00, "piece", 3000, "https://images.unsplash.com/photo-1587582423116-ec07293f0395?w=400", "Lightweight fly ash bricks"),
            ("TMT Steel Bar (8mm)", "Steel", 68.00, "kg", 2000, "https://images.unsplash.com/photo-1504307651254-35680f356dfd?w=400", "Fe500D grade TMT bars"),
            ("TMT Steel Bar (12mm)", "Steel", 72.00, "kg", 1500, "https://images.unsplash.com/photo-1504307651254-35680f356dfd?w=400", "Fe500D grade TMT bars"),
            ("20mm Blue Metal", "Aggregate", 48.00, "cft", 600, "https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=400", "Crushed granite aggregate"),
            ("40mm Blue Metal", "Aggregate", 44.00, "cft", 600, "https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=400", "Crushed granite aggregate"),
            ("Wall Putty", "Finishing", 320.00, "bag", 200, "https://images.unsplash.com/photo-1562259929-b4e1fd3aef09?w=400", "Smooth finish wall putty"),
        ]
        cur.executemany("INSERT INTO materials (name,category,price,unit,stock,image_url,description) VALUES (?,?,?,?,?,?,?)", materials)

    conn.commit()
    conn.close()

# ── CUSTOMER ROUTES ──────────────────────────────────────
@app.route("/")
def index():
    return render_template("customer/index.html")

@app.route("/api/materials")
def get_materials():
    try:
        conn = get_db(); cur = conn.cursor()
        category = request.args.get("category","")
        search = request.args.get("search","")
        query = "SELECT * FROM materials WHERE active=1"
        params = []
        if category: query += " AND category=?"; params.append(category)
        if search: query += " AND name LIKE ?"; params.append(f"%{search}%")
        query += " ORDER BY category, name"
        cur.execute(query, params)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return jsonify({"success": True, "data": rows})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/categories")
def get_categories():
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT DISTINCT category FROM materials WHERE active=1 ORDER BY category")
        cats = [r[0] for r in cur.fetchall()]
        conn.close()
        return jsonify({"success": True, "data": cats})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/order", methods=["POST"])
def place_order():
    try:
        data = request.json
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT id FROM customers WHERE phone=?", (data["phone"],))
        existing = cur.fetchone()
        if existing:
            cur.execute("UPDATE customers SET name=?,address=?,lat=?,lng=? WHERE phone=?",
                        (data["name"],data["address"],data.get("lat"),data.get("lng"),data["phone"]))
            customer_id = existing["id"]
        else:
            cur.execute("INSERT INTO customers (name,phone,email,address,lat,lng) VALUES (?,?,?,?,?,?)",
                        (data["name"],data["phone"],data.get("email",""),data["address"],data.get("lat"),data.get("lng")))
            customer_id = cur.lastrowid

        order_num = f"BMS{datetime.now().strftime('%Y%m%d%H%M%S')}"
        total = sum(item["price"] * item["qty"] for item in data["items"])
        cur.execute("""INSERT INTO orders (order_number,customer_id,customer_name,customer_phone,
                      delivery_address,lat,lng,total_amount,notes) VALUES (?,?,?,?,?,?,?,?,?)""",
                    (order_num,customer_id,data["name"],data["phone"],data["address"],
                     data.get("lat"),data.get("lng"),total,data.get("notes","")))
        order_id = cur.lastrowid
        for item in data["items"]:
            cur.execute("INSERT INTO order_items (order_id,material_id,material_name,quantity,unit,price) VALUES (?,?,?,?,?,?)",
                        (order_id,item["id"],item["name"],item["qty"],item["unit"],item["price"]))
            cur.execute("UPDATE materials SET stock=stock-? WHERE id=? AND stock>=?",
                        (item["qty"],item["id"],item["qty"]))
        conn.commit(); conn.close()
        return jsonify({"success": True, "order_number": order_num, "total": float(total)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/order/track", methods=["POST"])
def track_order():
    try:
        data = request.json
        conn = get_db(); cur = conn.cursor()
        cur.execute("""SELECT o.*, GROUP_CONCAT(
                        oi.material_name||'|'||oi.quantity||'|'||oi.unit||'|'||oi.price, ';;') as items_raw
                      FROM orders o LEFT JOIN order_items oi ON o.id=oi.order_id
                      WHERE o.order_number=? OR o.customer_phone=?
                      GROUP BY o.id ORDER BY o.created_at DESC LIMIT 10""",
                    (data.get("order_number","__"), data.get("phone","__")))
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
            del o["items_raw"]
            orders.append(o)
        conn.close()
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
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT * FROM admin WHERE username=? AND password=?",
                    (data["username"], hash_pw(data["password"])))
        admin = cur.fetchone(); conn.close()
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
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as total, SUM(total_amount) as revenue FROM orders WHERE status!='cancelled'")
        o = dict(cur.fetchone())
        cur.execute("SELECT COUNT(*) as total FROM customers"); c = dict(cur.fetchone())
        cur.execute("SELECT COUNT(*) as total FROM materials WHERE active=1"); m = dict(cur.fetchone())
        cur.execute("SELECT COUNT(*) as total FROM orders WHERE status='pending'"); p = dict(cur.fetchone())
        cur.execute("SELECT COUNT(*) as total FROM materials WHERE active=1 AND stock<50"); ls = dict(cur.fetchone())
        cur.execute("""SELECT date(created_at) as date, SUM(total_amount) as revenue, COUNT(*) as orders
                      FROM orders WHERE status!='cancelled' AND created_at >= date('now','-7 days')
                      GROUP BY date(created_at) ORDER BY date""")
        chart = [dict(r) for r in cur.fetchall()]
        conn.close()
        return jsonify({"success":True,"total_orders":o["total"],"revenue":float(o["revenue"] or 0),
                        "total_customers":c["total"],"total_materials":m["total"],
                        "pending_orders":p["total"],"low_stock":ls["total"],"chart":chart})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/orders")
def admin_orders():
    if not session.get("admin"): return jsonify({"error":"Unauthorized"}), 401
    try:
        conn = get_db(); cur = conn.cursor()
        status = request.args.get("status","")
        query = """SELECT o.*, GROUP_CONCAT(oi.material_name||'|'||oi.quantity||'|'||oi.unit||'|'||oi.price,';;') as items_raw
                  FROM orders o LEFT JOIN order_items oi ON o.id=oi.order_id"""
        params = []
        if status: query += " WHERE o.status=?"; params.append(status)
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
            del o["items_raw"]
            orders.append(o)
        conn.close()
        return jsonify({"success": True, "data": orders})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/order/status", methods=["PUT"])
def update_order_status():
    if not session.get("admin"): return jsonify({"error":"Unauthorized"}), 401
    try:
        data = request.json
        conn = get_db(); cur = conn.cursor()
        cur.execute("UPDATE orders SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (data["status"], data["order_id"]))
        conn.commit(); conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/materials")
def admin_materials():
    if not session.get("admin"): return jsonify({"error":"Unauthorized"}), 401
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT * FROM materials ORDER BY category, name")
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return jsonify({"success": True, "data": rows})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/material", methods=["POST"])
def add_material():
    if not session.get("admin"): return jsonify({"error":"Unauthorized"}), 401
    try:
        data = request.json
        conn = get_db(); cur = conn.cursor()
        cur.execute("INSERT INTO materials (name,category,price,unit,stock,image_url,description) VALUES (?,?,?,?,?,?,?)",
                    (data["name"],data["category"],data["price"],data["unit"],
                     data["stock"],data.get("image_url",""),data.get("description","")))
        conn.commit(); new_id = cur.lastrowid; conn.close()
        return jsonify({"success": True, "id": new_id})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/material/<int:mid>", methods=["PUT"])
def update_material(mid):
    if not session.get("admin"): return jsonify({"error":"Unauthorized"}), 401
    try:
        data = request.json
        conn = get_db(); cur = conn.cursor()
        cur.execute("""UPDATE materials SET name=?,category=?,price=?,unit=?,
                      stock=?,image_url=?,description=?,active=? WHERE id=?""",
                    (data["name"],data["category"],data["price"],data["unit"],
                     data["stock"],data.get("image_url",""),data.get("description",""),
                     data.get("active",1),mid))
        conn.commit(); conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/material/<int:mid>", methods=["DELETE"])
def delete_material(mid):
    if not session.get("admin"): return jsonify({"error":"Unauthorized"}), 401
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("UPDATE materials SET active=0 WHERE id=?", (mid,))
        conn.commit(); conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/customers")
def admin_customers():
    if not session.get("admin"): return jsonify({"error":"Unauthorized"}), 401
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("""SELECT c.*, COUNT(o.id) as order_count, SUM(o.total_amount) as total_spent
                      FROM customers c LEFT JOIN orders o ON c.id=o.customer_id AND o.status!='cancelled'
                      GROUP BY c.id ORDER BY c.created_at DESC""")
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return jsonify({"success": True, "data": rows})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
