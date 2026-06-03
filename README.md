# 🏗️ Harish BMS — Building Material Supply App

A full-stack web application for managing building material orders.
Built with **Python Flask + MySQL + HTML/CSS/JS** — mobile responsive.

---

## ✅ Features

### Customer Side
- Browse & search materials (Cement, Sand, Bricks, Steel, etc.)
- Filter by category
- Add to cart, adjust quantity
- Place order with delivery address + Google Maps pin
- Track order status (real-time timeline)

### Admin / Owner Side
- Dashboard with revenue stats & charts
- Manage orders — view details, update status
- Manage materials — add, edit, remove, stock control
- View all customers with order history
- Low stock alerts

---

## 🚀 Setup Instructions

### Step 1 — Install Python (if not installed)
Download from https://python.org (Python 3.10+)

### Step 2 — Install dependencies
```bash
pip install -r requirements.txt
```

### Step 3 — Setup MySQL
- Install MySQL from https://dev.mysql.com/downloads/
- Open MySQL, create a user or use root
- Update `app.py` line 15 — change `your_password` to your MySQL password:
```python
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "your_password",   # ← change this
    "database": "harish_bms"
}
```

### Step 4 — Run the app
```bash
python app.py
```

### Step 5 — Open in browser
- **Customer store:** http://localhost:5000
- **Admin panel:** http://localhost:5000/admin

---

## 🔐 Default Admin Login
- Username: `admin`
- Password: `admin123`

> Change this in `app.py` → `init_db()` function after first login

---

## 📁 Project Structure
```
harish-bms/
├── app.py                  # Flask backend (all APIs)
├── requirements.txt        # Python dependencies
├── templates/
│   ├── customer/
│   │   └── index.html      # Customer store page
│   └── admin/
│       ├── login.html      # Admin login
│       └── dashboard.html  # Admin dashboard
└── static/                 # (for future images/CSS files)
```

---

## 🛠️ Tech Stack
- **Backend:** Python, Flask, MySQL
- **Frontend:** HTML, CSS, JavaScript (Vanilla)
- **Database:** MySQL (auto-created on first run)
- **Maps:** Google Maps Embed (free, no API key needed)
- **Icons:** Font Awesome

---

## 📱 Mobile Support
Fully responsive — works on all screen sizes.

---

## 👤 Author
**Harishkumar R** — Python Backend Developer  
GitHub: https://github.com/Harixx21  
LinkedIn: https://linkedin.com/in/Harixx21
