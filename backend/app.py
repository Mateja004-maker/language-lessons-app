import os
from datetime import timedelta
from dotenv import load_dotenv

from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required, get_jwt, get_jwt_identity
)
from werkzeug.security import generate_password_hash, check_password_hash
import mysql.connector

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY", "change-me")
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=6)
jwt = JWTManager(app)

def get_db():
    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"),
        database=os.getenv("MYSQL_DATABASE"),
    )

def role_required(*allowed_roles):
    def decorator(fn):
        @jwt_required()
        def wrapper(*args, **kwargs):
            role = get_jwt().get("role")
            if role not in allowed_roles:
                return jsonify({"error": "forbidden"}), 403
            return fn(*args, **kwargs)
        wrapper.__name__ = fn.__name__
        return wrapper
    return decorator

@app.get("/")
def home():
    return "Backend radi. Probaj /api/health", 200

@app.get("/api/health")
def health():
    return jsonify({"ok": True})

@app.get("/api/db-health")
def db_health():
    try:
        db = get_db()
        cur = db.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        cur.close()
        db.close()
        return jsonify({"ok": True, "db": "connected"})
    except Exception as e:
        return jsonify({"ok": False, "db": "error", "message": str(e)}), 500

# ---------- AUTH ----------
@app.post("/api/auth/register")
def register():
    data = request.get_json(force=True)
    email = data.get("email")
    password = data.get("password")
    display_name = data.get("display_name")

    if not email or not password:
        return jsonify({"error": "email and password required"}), 400

    db = get_db()
    cur = db.cursor(dictionary=True)

    cur.execute("SELECT id FROM roles WHERE name=%s", ("STUDENT",))
    role = cur.fetchone()
    if not role:
        cur.close(); db.close()
        return jsonify({"error": "roles not seeded"}), 500

    pw_hash = generate_password_hash(password)

    try:
        cur.execute(
            "INSERT INTO users(email, password_hash, role_id, display_name) VALUES (%s,%s,%s,%s)",
            (email, pw_hash, role["id"], display_name),
        )
        db.commit()
    except mysql.connector.IntegrityError:
        return jsonify({"error": "email already exists"}), 409
    finally:
        cur.close(); db.close()

    return jsonify({"ok": True}), 201

@app.post("/api/auth/login")
def login():
    data = request.get_json(force=True)
    email = data.get("email")
    password = data.get("password")

    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT u.id, u.email, u.password_hash, r.name AS role
        FROM users u
        JOIN roles r ON r.id = u.role_id
        WHERE u.email=%s AND u.is_active=1
    """, (email,))
    user = cur.fetchone()
    cur.close(); db.close()

    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "invalid credentials"}), 401

    token = create_access_token(
        identity=str(user["id"]),
        additional_claims={"role": user["role"], "email": user["email"]}
    )
    return jsonify({
        "access_token": token,
        "user": {"id": user["id"], "email": user["email"], "role": user["role"]}
    })

@app.get("/api/auth/me")
@jwt_required()
def me():
    claims = get_jwt()
    return jsonify({"email": claims.get("email"), "role": claims.get("role"), "user_id": get_jwt_identity()})

# ---------- LANGUAGES ----------
@app.get("/api/languages")
@jwt_required()
def list_languages():
    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT id, code, name FROM languages ORDER BY name")
    rows = cur.fetchall()
    cur.close(); db.close()
    return jsonify(rows)

@app.post("/api/languages")
@role_required("ADMIN")
def create_language():
    data = request.get_json(force=True)
    code = data.get("code")
    name = data.get("name")

    if not code or not name:
        return jsonify({"error": "code and name required"}), 400

    db = get_db()
    cur = db.cursor()
    cur.execute("INSERT INTO languages(code, name) VALUES (%s, %s)", (code, name))
    db.commit()
    new_id = cur.lastrowid
    cur.close(); db.close()

    return jsonify({"id": new_id, "code": code, "name": name}), 201

# ---------- LESSONS ----------
@app.get("/api/lessons")
@jwt_required()
def list_lessons():
    language_id = request.args.get("language_id")
    level = request.args.get("level")

    sql = """
      SELECT l.id, l.language_id, lang.code AS language_code, lang.name AS language_name,
             l.level, l.title, l.order_no, l.created_at, l.updated_at
      FROM lessons l
      JOIN languages lang ON lang.id = l.language_id
      WHERE 1=1
    """
    params = []
    if language_id:
        sql += " AND l.language_id=%s"
        params.append(language_id)
    if level:
        sql += " AND l.level=%s"
        params.append(level)

    sql += " ORDER BY lang.code, l.order_no, l.id"

    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute(sql, tuple(params))
    rows = cur.fetchall()
    cur.close(); db.close()
    return jsonify(rows)

@app.get("/api/lessons/<int:lesson_id>")
@jwt_required()
def get_lesson(lesson_id):
    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("""
      SELECT id, language_id, level, title, content_html, order_no, created_by, created_at, updated_at
      FROM lessons
      WHERE id=%s
    """, (lesson_id,))
    row = cur.fetchone()
    cur.close(); db.close()
    if not row:
        return jsonify({"error": "not found"}), 404
    return jsonify(row)

@app.post("/api/lessons")
@role_required("TEACHER", "ADMIN")
def create_lesson():
    data = request.get_json(force=True)

    language_id = data.get("language_id")
    level = data.get("level")
    title = data.get("title")
    content_html = data.get("content_html", "")
    order_no = int(data.get("order_no", 0))

    if not language_id or not level or not title:
        return jsonify({"error": "language_id, level, title required"}), 400

    db = get_db()
    cur = db.cursor()
    cur.execute("""
      INSERT INTO lessons(language_id, level, title, content_html, order_no, created_by)
      VALUES (%s,%s,%s,%s,%s,NULL)
    """, (language_id, level, title, content_html, order_no))
    db.commit()
    new_id = cur.lastrowid
    cur.close(); db.close()

    return jsonify({"id": new_id}), 201

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)




if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)