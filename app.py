# app.py
import sqlite3
from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, session, g, abort
)
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "todo_app.db")
SCHEMA_PATH = os.path.join(BASE_DIR, "schema.sql")

app = Flask(__name__)
app.secret_key = "replace_this_with_a_random_secret_in_production"  # change for production

# ----------------------
# Database helpers
# ----------------------
def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
    return db

@app.teardown_appcontext
def close_connection(exc):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()

def init_db():
    if not os.path.exists(DB_PATH):
        with app.app_context():
            db = get_db()
            with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
                db.executescript(f.read())
            db.commit()

# call init on startup
init_db()

# ----------------------
# Auth helpers
# ----------------------
def create_user(username, password):
    db = get_db()
    now = datetime.utcnow().isoformat()
    try:
        db.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (username, generate_password_hash(password), now),
        )
        db.commit()
        return True
    except sqlite3.IntegrityError:
        return False

def authenticate(username, password):
    db = get_db()
    cur = db.execute("SELECT id, password_hash FROM users WHERE username = ?", (username,))
    row = cur.fetchone()
    if row and check_password_hash(row["password_hash"], password):
        return row["id"]
    return None

def login_required(fn):
    from functools import wraps
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)
    return wrapper

# ----------------------
# Routes: auth
# ----------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        password2 = request.form.get("password2", "")
        if not username or not password:
            flash("Username and password are required.", "danger")
            return redirect(url_for("register"))
        if password != password2:
            flash("Passwords do not match.", "danger")
            return redirect(url_for("register"))
        ok = create_user(username, password)
        if not ok:
            flash("Username already taken.", "danger")
            return redirect(url_for("register"))
        flash("Account created. Please login.", "success")
        return redirect(url_for("login"))
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user_id = authenticate(username, password)
        if user_id:
            session.clear()
            session["user_id"] = user_id
            session["username"] = username
            flash("Logged in successfully.", "success")
            next_page = request.args.get("next")
            return redirect(next_page or url_for("dashboard"))
        flash("Invalid username or password.", "danger")
        return redirect(url_for("login"))
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "info")
    return redirect(url_for("login"))

# ----------------------
# Todo CRUD & search
# ----------------------
@app.route("/", methods=["GET"])
@login_required
def dashboard():
    search = request.args.get("q", "").strip()
    db = get_db()
    if search:
        like = f"%{search}%"
        cur = db.execute(
            "SELECT * FROM todos WHERE user_id = ? AND (title LIKE ? OR description LIKE ?) ORDER BY done, created_at DESC",
            (session["user_id"], like, like),
        )
    else:
        cur = db.execute(
            "SELECT * FROM todos WHERE user_id = ? ORDER BY done, created_at DESC",
            (session["user_id"],)
        )
    todos = cur.fetchall()
    return render_template("dashboard.html", todos=todos, q=search)

@app.route("/task/new", methods=["GET", "POST"])
@login_required
def add_task():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        due_date = request.form.get("due_date", "").strip() or None
        if not title:
            flash("Title is required.", "danger")
            return redirect(url_for("add_task"))
        db = get_db()
        db.execute(
            "INSERT INTO todos (user_id, title, description, due_date, done, created_at) VALUES (?, ?, ?, ?, 0, ?)",
            (session["user_id"], title, description, due_date, datetime.utcnow().isoformat())
        )
        db.commit()
        flash("Task added.", "success")
        return redirect(url_for("dashboard"))
    return render_template("task_form.html", action="Add", task=None)

@app.route("/task/<int:task_id>/edit", methods=["GET", "POST"])
@login_required
def edit_task(task_id):
    db = get_db()
    cur = db.execute("SELECT * FROM todos WHERE id = ? AND user_id = ?", (task_id, session["user_id"]))
    task = cur.fetchone()
    if not task:
        abort(404)
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        due_date = request.form.get("due_date", "").strip() or None
        done = 1 if request.form.get("done") == "on" else 0
        if not title:
            flash("Title is required.", "danger")
            return redirect(url_for("edit_task", task_id=task_id))
        db.execute(
            "UPDATE todos SET title = ?, description = ?, due_date = ?, done = ? WHERE id = ?",
            (title, description, due_date, done, task_id)
        )
        db.commit()
        flash("Task updated.", "success")
        return redirect(url_for("dashboard"))
    return render_template("task_form.html", action="Edit", task=task)

@app.route("/task/<int:task_id>/delete", methods=["POST"])
@login_required
def delete_task(task_id):
    db = get_db()
    db.execute("DELETE FROM todos WHERE id = ? AND user_id = ?", (task_id, session["user_id"]))
    db.commit()
    flash("Task deleted.", "info")
    return redirect(url_for("dashboard"))

@app.route("/task/<int:task_id>/toggle", methods=["POST"])
@login_required
def toggle_task(task_id):
    db = get_db()
    cur = db.execute("SELECT done FROM todos WHERE id = ? AND user_id = ?", (task_id, session["user_id"]))
    row = cur.fetchone()
    if not row:
        abort(404)
    new_done = 0 if row["done"] else 1
    db.execute("UPDATE todos SET done = ? WHERE id = ?", (new_done, task_id))
    db.commit()
    return redirect(url_for("dashboard"))

# ----------------------
# Run
# ----------------------
if __name__ == "__main__":
    # in dev use debug=True; do not use in production
    app.run(debug=True, host="127.0.0.1", port=5000)
