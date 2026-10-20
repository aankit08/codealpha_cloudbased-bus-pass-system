import os, sqlite3, secrets, hashlib
from datetime import datetime, date
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, g, abort

APP_SECRET = os.environ.get("SECRET_KEY", "dev-only-change-this-secret-before-deploying")
DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(os.path.dirname(__file__), "buspass.db"))
app = Flask(__name__)
app.secret_key = APP_SECRET
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, timeout=15)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA journal_mode = WAL")
    return g.db

@app.teardown_appcontext
def close_db(exc):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
      email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS routes (
      id INTEGER PRIMARY KEY AUTOINCREMENT, origin TEXT NOT NULL,
      destination TEXT NOT NULL, departure TEXT NOT NULL,
      fare_paise INTEGER NOT NULL CHECK(fare_paise >= 0),
      seats_total INTEGER NOT NULL CHECK(seats_total > 0),
      active INTEGER NOT NULL DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS bookings (
      id INTEGER PRIMARY KEY AUTOINCREMENT, booking_ref TEXT NOT NULL UNIQUE,
      user_id INTEGER NOT NULL REFERENCES users(id),
      route_id INTEGER NOT NULL REFERENCES routes(id),
      passenger_name TEXT NOT NULL, seats INTEGER NOT NULL CHECK(seats > 0),
      unit_fare_paise INTEGER NOT NULL, total_paise INTEGER NOT NULL,
      status TEXT NOT NULL DEFAULT 'CONFIRMED',
      created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_routes_search ON routes(origin, destination, departure);
    CREATE INDEX IF NOT EXISTS idx_bookings_user ON bookings(user_id, created_at);
    """)
    count = conn.execute("SELECT COUNT(*) FROM routes").fetchone()[0]
    if count == 0:
        today = date.today()
        samples = [
          ("Jaipur", "Delhi", f"{today}T08:30", 45000, 40),
          ("Jaipur", "Agra", f"{today}T10:00", 38000, 35),
          ("Delhi", "Jaipur", f"{today}T17:30", 47000, 40),
          ("Noida", "Jaipur", f"{today}T09:15", 42000, 32),
          ("Jaipur", "Udaipur", f"{today}T21:00", 65000, 30),
        ]
        conn.executemany("INSERT INTO routes(origin,destination,departure,fare_paise,seats_total) VALUES(?,?,?,?,?)", samples)
    conn.commit()
    conn.close()

def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please sign in to continue.", "warning")
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)
    return wrapped

@app.template_filter("rupees")
def rupees(paise):
    return "₹{:,.2f}".format((paise or 0) / 100)

@app.route("/")
def index():
    origin = request.args.get("origin", "").strip()
    destination = request.args.get("destination", "").strip()
    day = request.args.get("day", "").strip()
    query = "SELECT * FROM routes WHERE active=1 AND departure >= ?"
    params = [datetime.now().strftime("%Y-%m-%dT%H:%M")]
    if origin:
        query += " AND lower(origin)=lower(?)"; params.append(origin)
    if destination:
        query += " AND lower(destination)=lower(?)"; params.append(destination)
    if day:
        query += " AND substr(departure,1,10)=?"; params.append(day)
    query += " ORDER BY departure LIMIT 100"
    routes = db().execute(query, params).fetchall()
    return render_template("index.html", routes=routes, origin=origin, destination=destination, day=day)

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not name or len(name) > 100 or "@" not in email or len(password) < 8:
            flash("Enter a name, valid email, and password of at least 8 characters.", "danger")
            return render_template("register.html")
        hashed = hashlib.pbkdf2_hmac("sha256", password.encode(), APP_SECRET.encode(), 180000).hex()
        try:
            db().execute("INSERT INTO users(name,email,password_hash,created_at) VALUES(?,?,?,?)",
                         (name, email, hashed, datetime.utcnow().isoformat()))
            db().commit()
        except sqlite3.IntegrityError:
            flash("That email is already registered. Please sign in.", "warning")
            return render_template("register.html")
        flash("Account created. Please sign in.", "success")
        return redirect(url_for("login"))
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = db().execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        hashed = hashlib.pbkdf2_hmac("sha256", password.encode(), APP_SECRET.encode(), 180000).hex()
        if user and secrets.compare_digest(user["password_hash"], hashed):
            session.clear()
            session["user_id"] = user["id"]
            session["name"] = user["name"]
            return redirect(request.args.get("next") or url_for("index"))
        flash("Email or password is incorrect.", "danger")
    return render_template("login.html")

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have signed out.", "success")
    return redirect(url_for("index"))

@app.route("/book/<int:route_id>", methods=["GET", "POST"])
@login_required
def book(route_id):
    route = db().execute("SELECT * FROM routes WHERE id=? AND active=1", (route_id,)).fetchone()
    if route is None: abort(404)
    if request.method == "POST":
        passenger = request.form.get("passenger_name", "").strip()
        try: seats = int(request.form.get("seats", "1"))
        except ValueError: seats = 0
        if not passenger or len(passenger) > 100 or seats < 1 or seats > 6:
            flash("Enter passenger name and choose 1–6 seats.", "danger")
            return render_template("book.html", route=route)
        conn = db()
        try:
            # Lock the write transaction and count confirmed seats before booking.
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute("SELECT * FROM routes WHERE id=? AND active=1", (route_id,)).fetchone()
            used = conn.execute("SELECT COALESCE(SUM(seats),0) FROM bookings WHERE route_id=? AND status='CONFIRMED'", (route_id,)).fetchone()[0]
            if current is None or used + seats > current["seats_total"]:
                conn.rollback()
                flash("Not enough seats remain. Please select fewer seats or another bus.", "danger")
                return render_template("book.html", route=route)
            # Price is read from the server-side route record; client prices are ignored.
            fare = current["fare_paise"]
            ref = "BP-" + secrets.token_hex(5).upper()
            conn.execute("""INSERT INTO bookings(booking_ref,user_id,route_id,passenger_name,seats,unit_fare_paise,total_paise,status,created_at)
                            VALUES(?,?,?,?,?,?,?,'CONFIRMED',?)""",
                         (ref, session["user_id"], route_id, passenger, seats, fare, fare * seats, datetime.utcnow().isoformat()))
            conn.commit()
            return redirect(url_for("ticket", booking_ref=ref))
        except sqlite3.Error:
            conn.rollback()
            app.logger.exception("Booking transaction failed")
            flash("Booking could not be completed. Please try again.", "danger")
    return render_template("book.html", route=route)

@app.route("/ticket/<booking_ref>")
@login_required
def ticket(booking_ref):
    booking = db().execute("""SELECT b.*, r.origin, r.destination, r.departure
        FROM bookings b JOIN routes r ON r.id=b.route_id
        WHERE b.booking_ref=? AND b.user_id=?""", (booking_ref, session["user_id"])).fetchone()
    if not booking: abort(404)
    return render_template("ticket.html", booking=booking)

@app.route("/my-bookings")
@login_required
def my_bookings():
    bookings = db().execute("""SELECT b.*, r.origin, r.destination, r.departure FROM bookings b
        JOIN routes r ON r.id=b.route_id WHERE b.user_id=? ORDER BY b.created_at DESC""",
        (session["user_id"],)).fetchall()
    return render_template("my_bookings.html", bookings=bookings)

@app.route("/health")
def health():
    try:
        db().execute("SELECT 1").fetchone()
        return {"status": "ok", "database": "reachable"}, 200
    except sqlite3.Error:
        return {"status": "error", "database": "unavailable"}, 503

@app.errorhandler(404)
def not_found(err):
    return render_template("error.html", code=404, message="The page or ticket could not be found."), 404

@app.errorhandler(500)
def server_error(err):
    app.logger.exception("Unhandled server error")
    return render_template("error.html", code=500, message="Something went wrong. Please try again."), 500

with app.app_context():
    init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=False)
