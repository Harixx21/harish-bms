from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_cors import CORS
import mysql.connector
import hashlib
import os
from datetime import datetime

app = Flask(__name__)
app.secret_key = "bms_secret_key_2024"
CORS(app)

# ─── DB CONFIG ───────────────────────────────────────────
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "your_password",   # change this
    "database": "harish_bms"
}

def get_db():
    return mysql.connector.connect(**DB_CONFIG)

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

# ─── INIT DB ─────────────────────────────────────────────
def init_db():
    conn = mysql.connector.connect(
        host=DB_CONFIG["host"],
        user=DB_CONFIG["user"],
        password=DB_CONFIG["password"]
    )
    cur = conn.cursor()
    cur.execute("CREATE DATABASE IF NOT EXISTS harish_bms")
    cur.execute("USE harish_bms")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS materials (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            category VARCHAR(50),
            price DECIMAL(10,2) NOT NULL,
            unit VARCHAR(20) DEFAULT 'bag',
            stock INT DEFAULT 0,
            image_url VARCHAR(255),
            description TEXT,
            active TINYINT DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id INT AUTO_INCREMENT PRIMARY KEY,
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
            id INT AUTO_INCREMENT PRIMARY KEY,
            order_number VARCHAR(20) UNIQUE NOT NULL,
            customer_id INT,
            customer_name VARCHAR(100),
            customer_phone VARCHAR(15),
            delivery_address TEXT,
            lat DECIMAL(10,8),
            lng DECIMAL(11,8),
            total_amount DECIMAL(10,2),
            status ENUM('pending','confirmed','processing','out_for_delivery','delivered','cancelled') DEFAULT 'pending',
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE SET NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS order_items (
            id INT AUTO_INCREMENT PRIMARY KEY,
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
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(50) UNIQUE NOT NULL,
            password VARCHAR(64) NOT NULL
        )
    """)

    # Default admin
    cur.execute("SELECT id FROM admin WHERE username='admin'")
    if not cur.fetchone():
        cur.execute("INSERT INTO admin (username, password) VALUES ('admin', %s)",
                    (hash_pw("admin123"),))

    # Sample materials
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
        cur.executemany(
            "INSERT INTO materials (name, category, price, unit, stock, image_url, description) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            materials
        )

    conn.commit()
    cur.close()
    conn.close()
    print("✅ DB initialized")

# ─── CUSTOMER ROUTES ─────────────────────────────────────
@app.route("/")
def index():
    return render_template("customer/index.html")

@app.route("/api/materials")
def get_materials():
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)
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
        return jsonify({"success": True, "data": materials})
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
        cur = conn.cursor(dictionary=True)

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
                          VALUES (%s,%s,%s,%s,%s,%s)""",
                        (data["name"], data["phone"], data.get("email",""), data["address"],
                         data.get("lat"), data.get("lng")))
            customer_id = cur.lastrowid

        # Generate order number
        order_num = f"BMS{datetime.now().strftime('%Y%m%d%H%M%S')}"

        # Calculate total
        total = sum(item["price"] * item["qty"] for item in data["items"])

        cur.execute("""INSERT INTO orders
                      (order_number, customer_id, customer_name, customer_phone,
                       delivery_address, lat, lng, total_amount, notes)
                      VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (order_num, customer_id, data["name"], data["phone"],
                     data["address"], data.get("lat"), data.get("lng"), total, data.get("notes","")))
        order_id = cur.lastrowid

        # Order items
        for item in data["items"]:
            cur.execute("""INSERT INTO order_items
                          (order_id, material_id, material_name, quantity, unit, price)
                          VALUES (%s,%s,%s,%s,%s,%s)""",
                        (order_id, item["id"], item["name"], item["qty"], item["unit"], item["price"]))
            # Reduce stock
            cur.execute("UPDATE materials SET stock=stock-%s WHERE id=%s AND stock>=%s",
                        (item["qty"], item["id"], item["qty"]))

        conn.commit()
        cur.close(); conn.close()
        return jsonify({"success": True, "order_number": order_num, "total": float(total)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/order/track", methods=["POST"])
def track_order():
    try:
        data = request.json
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        cur.execute("""SELECT o.*, GROUP_CONCAT(
                        CONCAT(oi.material_name,'|',oi.quantity,'|',oi.unit,'|',oi.price)
                        SEPARATOR ';;') as items_raw
                      FROM orders o
                      LEFT JOIN order_items oi ON o.id=oi.order_id
                      WHERE o.order_number=%s OR (o.customer_phone=%s)
                      GROUP BY o.id ORDER BY o.created_at DESC LIMIT 10""",
                    (data.get("order_number","__"), data.get("phone","__")))
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
@app.route("/admin")
def admin_login_page():
    if session.get("admin"):
        return redirect("/admin/dashboard")
    return render_template("admin/login.html")

@app.route("/admin/login", methods=["POST"])
def admin_login():
    try:
        data = request.json
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT * FROM admin WHERE username=%s AND password=%s",
                    (data["username"], hash_pw(data["password"])))
        admin = cur.fetchone()
        cur.close(); conn.close()
        if admin:
            session["admin"] = True
            session["admin_user"] = admin["username"]
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "Invalid credentials"}), 401
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect("/admin")

@app.route("/admin/dashboard")
def admin_dashboard():
    if not session.get("admin"):
        return redirect("/admin")
    return render_template("admin/dashboard.html")

@app.route("/api/admin/stats")
def admin_stats():
    if not session.get("admin"):
        return jsonify({"error": "Unauthorized"}), 401
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT COUNT(*) as total, SUM(total_amount) as revenue FROM orders WHERE status!='cancelled'")
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
        cur.execute("""SELECT DATE(created_at) as date, SUM(total_amount) as revenue,
                      COUNT(*) as orders FROM orders
                      WHERE status!='cancelled' AND created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
                      GROUP BY DATE(created_at) ORDER BY date""")
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
    if not session.get("admin"):
        return jsonify({"error": "Unauthorized"}), 401
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        status = request.args.get("status", "")
        query = """SELECT o.*, GROUP_CONCAT(
                    CONCAT(oi.material_name,'|',oi.quantity,'|',oi.unit,'|',oi.price)
                    SEPARATOR ';;') as items_raw
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
    if not session.get("admin"):
        return jsonify({"error": "Unauthorized"}), 401
    try:
        data = request.json
        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE orders SET status=%s WHERE id=%s",
                    (data["status"], data["order_id"]))
        conn.commit()
        cur.close(); conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/materials")
def admin_materials():
    if not session.get("admin"):
        return jsonify({"error": "Unauthorized"}), 401
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT * FROM materials ORDER BY category, name")
        mats = cur.fetchall()
        for m in mats:
            m["price"] = float(m["price"])
        cur.close(); conn.close()
        return jsonify({"success": True, "data": mats})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/material", methods=["POST"])
def add_material():
    if not session.get("admin"):
        return jsonify({"error": "Unauthorized"}), 401
    try:
        data = request.json
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""INSERT INTO materials (name, category, price, unit, stock, image_url, description)
                      VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (data["name"], data["category"], data["price"], data["unit"],
                     data["stock"], data.get("image_url",""), data.get("description","")))
        conn.commit()
        new_id = cur.lastrowid
        cur.close(); conn.close()
        return jsonify({"success": True, "id": new_id})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/material/<int:mid>", methods=["PUT"])
def update_material(mid):
    if not session.get("admin"):
        return jsonify({"error": "Unauthorized"}), 401
    try:
        data = request.json
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""UPDATE materials SET name=%s, category=%s, price=%s,
                      unit=%s, stock=%s, image_url=%s, description=%s, active=%s
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
    if not session.get("admin"):
        return jsonify({"error": "Unauthorized"}), 401
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE materials SET active=0 WHERE id=%s", (mid,))
        conn.commit()
        cur.close(); conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/admin/customers")
def admin_customers():
    if not session.get("admin"):
        return jsonify({"error": "Unauthorized"}), 401
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        cur.execute("""SELECT c.*, COUNT(o.id) as order_count,
                      SUM(o.total_amount) as total_spent
                      FROM customers c
                      LEFT JOIN orders o ON c.id=o.customer_id AND o.status!='cancelled'
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
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)
