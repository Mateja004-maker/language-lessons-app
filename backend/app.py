import os
from pathlib import Path
from functools import wraps

from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager, create_access_token,
    jwt_required, get_jwt, get_jwt_identity
)
from werkzeug.security import generate_password_hash, check_password_hash
import mysql.connector
from mysql.connector import Error as MySQLError

from dotenv import load_dotenv


# =========================
# 1) Load .env reliably
# =========================
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env", override=True)  # <-- ključna izmena


# =========================
# 2) Flask app setup
# =========================
app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY", "change_me")
jwt = JWTManager(app)


# =========================
# 3) Helpers
# =========================
def env_required(name: str) -> str:
    """Raise clear error if env var missing."""
    val = os.getenv(name)
    if val is None or str(val).strip() == "":
        raise RuntimeError(f"Missing required env var: {name}. Check backend/.env")
    return val


def get_db_connection():
    host = env_required("MYSQL_HOST")
    port = int(os.getenv("MYSQL_PORT", "3306"))
    user = env_required("MYSQL_USER")
    password = os.getenv("MYSQL_PASSWORD", "")
    database = env_required("MYSQL_DATABASE")

    return mysql.connector.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database
    )


def role_required(roles):
    """JWT claim-based role guard."""
    def decorator(fn):
        @wraps(fn)
        @jwt_required()
        def wrapper(*args, **kwargs):
            claims = get_jwt()
            role = claims.get("role")
            if role not in roles:
                return jsonify({"error": "Forbidden"}), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator


# =========================
# 4) Health endpoints
# =========================
@app.get("/api/health")
def health():
    return jsonify({"ok": True, "message": "API is running"}), 200


@app.get("/api/db-health")
def db_health():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        cur.close()
        conn.close()
        return jsonify({"ok": True, "db": "ok"}), 200
    except Exception as e:
        return jsonify({"ok": False, "db": "error", "message": str(e)}), 500


# =========================
# 5) Auth
# =========================
@app.post("/api/auth/register")
def register():
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    role_name = (data.get("role") or "STUDENT").strip().upper()

    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400

    if role_name not in ("ADMIN", "TEACHER", "STUDENT"):
        return jsonify({"error": "Invalid role"}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)

        # get role id
        cur.execute("SELECT id FROM roles WHERE name=%s", (role_name,))
        role_row = cur.fetchone()
        if not role_row:
            return jsonify({"error": "Role not found in DB"}), 400

        # check email exists
        cur.execute("SELECT id FROM users WHERE email=%s", (email,))
        if cur.fetchone():
            return jsonify({"error": "Email already exists"}), 409

        pw_hash = generate_password_hash(password)

        cur2 = conn.cursor()
        cur2.execute(
            "INSERT INTO users (email, password_hash, role_id) VALUES (%s, %s, %s)",
            (email, pw_hash, role_row["id"])
        )
        conn.commit()

        cur2.close()
        cur.close()
        conn.close()
        return jsonify({"message": "Registered"}), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/api/auth/login")
def login():
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)

        cur.execute("""
            SELECT u.id, u.email, u.password_hash, r.name AS role
            FROM users u
            JOIN roles r ON r.id = u.role_id
            WHERE u.email = %s
            LIMIT 1
        """, (email,))
        user = cur.fetchone()

        cur.close()
        conn.close()

        if not user or not check_password_hash(user["password_hash"], password):
            return jsonify({"error": "Invalid credentials"}), 401

        access_token = create_access_token(
            identity=user["id"],
            additional_claims={"role": user["role"], "email": user["email"]}
        )

        return jsonify({
            "access_token": access_token,
            "role": user["role"],
            "email": user["email"]
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/api/auth/me")
@jwt_required()
def me():
    claims = get_jwt()
    return jsonify({
        "user_id": get_jwt_identity(),
        "email": claims.get("email"),
        "role": claims.get("role")
    }), 200


# =========================
# 6) Languages (admin)
# =========================
@app.get("/api/languages")
@jwt_required()
def list_languages():
    """Admin može i inactive; ostali vide samo active."""
    claims = get_jwt()
    role = claims.get("role")

    include_inactive = request.args.get("include_inactive") == "1"
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)

        if role == "ADMIN" and include_inactive:
            cur.execute("""
                SELECT id, code, name, is_active
                FROM languages
                ORDER BY is_active DESC, id ASC
            """)
        else:
            cur.execute("""
                SELECT id, code, name, is_active
                FROM languages
                WHERE is_active = 1
                ORDER BY id ASC
            """)

        rows = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify(rows), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/api/languages")
@role_required(["ADMIN"])
def add_language():
    data = request.get_json() or {}
    code = (data.get("code") or "").strip().lower()
    name = (data.get("name") or "").strip()

    if not code or not name:
        return jsonify({"error": "code and name required"}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("INSERT INTO languages (code, name, is_active) VALUES (%s, %s, 1)", (code, name))
        conn.commit()

        cur.close()
        conn.close()
        return jsonify({"message": "Language created"}), 201

    except MySQLError as e:
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/api/languages/<int:language_id>/lessons-count")
@role_required(["ADMIN"])
def language_lessons_count(language_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)

        cur.execute("SELECT COUNT(*) AS count FROM lessons WHERE language_id = %s", (language_id,))
        row = cur.fetchone()

        cur.close()
        conn.close()
        return jsonify({"count": int(row["count"])}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.patch("/api/languages/<int:language_id>/deactivate")
@role_required(["ADMIN"])
def deactivate_language(language_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("UPDATE languages SET is_active = 0 WHERE id = %s", (language_id,))
        conn.commit()

        if cur.rowcount == 0:
            cur.close()
            conn.close()
            return jsonify({"error": "Language not found"}), 404

        cur.close()
        conn.close()
        return jsonify({"message": "Language deactivated"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.patch("/api/languages/<int:language_id>/activate")
@role_required(["ADMIN"])
def activate_language(language_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("UPDATE languages SET is_active = 1 WHERE id = %s", (language_id,))
        conn.commit()

        if cur.rowcount == 0:
            cur.close()
            conn.close()
            return jsonify({"error": "Language not found"}), 404

        cur.close()
        conn.close()
        return jsonify({"message": "Language activated"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =========================
# 7) Lessons
# =========================
@app.get("/api/lessons")
@jwt_required()
def list_lessons():
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)

        # pokazujemo code jezika; (opciono) filtriraj po is_active=1
        cur.execute("""
            SELECT ls.id, ls.language_id, l.code AS language_code,
                   ls.level, ls.title, ls.content
            FROM lessons ls
            JOIN languages l ON l.id = ls.language_id
            WHERE l.is_active = 1
            ORDER BY ls.id DESC
        """)
        rows = cur.fetchall()

        cur.close()
        conn.close()
        return jsonify(rows), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/api/lessons/<int:lesson_id>")
@jwt_required()
def lesson_detail(lesson_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)

        cur.execute("""
            SELECT ls.id, ls.language_id, l.code AS language_code,
                   ls.level, ls.title, ls.content
            FROM lessons ls
            JOIN languages l ON l.id = ls.language_id
            WHERE ls.id = %s
            LIMIT 1
        """, (lesson_id,))
        row = cur.fetchone()

        cur.close()
        conn.close()

        if not row:
            return jsonify({"error": "Lesson not found"}), 404

        return jsonify(row), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/api/lessons")
@role_required(["TEACHER", "ADMIN"])
def create_lesson():
    data = request.get_json() or {}
    language_id = data.get("language_id")
    level = (data.get("level") or "").strip()
    title = (data.get("title") or "").strip()
    content = (data.get("content") or "").strip()

    if not language_id or not level or not title or not content:
        return jsonify({"error": "language_id, level, title, content required"}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO lessons (language_id, level, title, content)
            VALUES (%s, %s, %s, %s)
        """, (language_id, level, title, content))
        conn.commit()

        cur.close()
        conn.close()
        return jsonify({"message": "Lesson created"}), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.delete("/api/lessons/<int:lesson_id>")
@role_required(["TEACHER", "ADMIN"])
def delete_lesson(lesson_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("DELETE FROM lessons WHERE id = %s", (lesson_id,))
        conn.commit()

        if cur.rowcount == 0:
            cur.close()
            conn.close()
            return jsonify({"error": "Lesson not found"}), 404

        cur.close()
        conn.close()
        return jsonify({"message": "Lesson deleted"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =========================
# 8) Run
# =========================
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
