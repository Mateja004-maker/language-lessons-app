# Podesavanje aplikacije - osnova da ceo backend radi kako treba
import os
from pathlib import Path
from functools import wraps

from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    jwt_required,
    get_jwt,
    get_jwt_identity,
)
from werkzeug.security import generate_password_hash, check_password_hash
import mysql.connector
from mysql.connector import Error as MySQLError
from dotenv import load_dotenv
from werkzeug.utils import secure_filename
from flask import send_from_directory
import uuid
from io import BytesIO
from flask import send_file
from openpyxl import Workbook


# =========================
# 1) Load .env reliably
# =========================
BASE_DIR = Path(__file__).resolve().parent
UPLOAD_FOLDER = BASE_DIR / "uploads" / "profile_images"
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
LESSON_IMAGE_FOLDER = BASE_DIR / "uploads" / "lesson_images"
LESSON_IMAGE_FOLDER.mkdir(parents=True, exist_ok=True)

ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
load_dotenv(BASE_DIR / ".env", override=True)


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
    val = os.getenv(name)
    if val is None or str(val).strip() == "":
        raise RuntimeError(f"Missing required env var: {name}. Check backend/.env")
    return val

# Konekcija sa bazom
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
        database=database,
    )

# Funkcija za proveru role, ukoliko imamo nesto sto samo sme da radi admin/student/teacher
def role_required(roles):
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


def column_exists(table_name, column_name):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = %s
              AND COLUMN_NAME = %s
            """,
            (env_required("MYSQL_DATABASE"), table_name, column_name),
        )
        row = cur.fetchone()
        return int(row["cnt"]) > 0
    finally:
        cur.close()
        conn.close()

def allowed_image(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS



# =========================
# 4) Health endpoints 
# =========================
@app.get("/api/health") #Da li backend radi
def health():
    return jsonify({"ok": True, "message": "API is running"}), 200


@app.get("/api/db-health") #Da li je uspostavljena konekcija sa bazom
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

@app.get("/uploads/profile_images/<filename>")
def uploaded_profile_image(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.get("/uploads/lesson_images/<filename>")
def uploaded_lesson_image(filename):
    return send_from_directory(LESSON_IMAGE_FOLDER, filename)

# =========================
# 5) Auth
# =========================
@app.post("/api/auth/register") #Registracija 
def register():
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    display_name = (data.get("display_name") or "").strip() or None
    role_name = (data.get("role") or "STUDENT").strip().upper()

    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400

    if role_name not in ("ADMIN", "TEACHER", "STUDENT"):
        return jsonify({"error": "Invalid role"}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)

        cur.execute("SELECT id FROM roles WHERE name = %s", (role_name,))
        role_row = cur.fetchone()
        if not role_row:
            cur.close()
            conn.close()
            return jsonify({"error": "Role not found in DB"}), 400

        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        if cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({"error": "Email already exists"}), 409

        pw_hash = generate_password_hash(password)

        cur2 = conn.cursor()
        cur2.execute(
            """
            INSERT INTO users (email, password_hash, role_id, display_name, is_active)
            VALUES (%s, %s, %s, %s, 0)
            """,
            (email, pw_hash, role_row["id"], display_name),
        )
        conn.commit()

        cur2.close()
        cur.close()
        conn.close()
        return jsonify({"message": "Registration sent. Waiting for admin approval."}), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/api/auth/login") #login
def login():
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)

        cur.execute(
            """
            SELECT u.id, u.email, u.password_hash, u.is_active, r.name AS role
            FROM users u
            JOIN roles r ON r.id = u.role_id
            WHERE u.email = %s
            LIMIT 1
            """,
            (email,),
        )
        user = cur.fetchone()

        cur.close()
        conn.close()

        if not user or not check_password_hash(user["password_hash"], password):
            return jsonify({"error": "Invalid credentials"}), 401

        if int(user.get("is_active", 1)) != 1:
            return jsonify({"error": "User account is inactive"}), 403
        
        #Kreiranje JWT tokena
        access_token = create_access_token(
            identity=str(user["id"]),
            additional_claims={"role": user["role"], "email": user["email"]},
        )

        return jsonify(
            {
                "access_token": access_token,
                "role": user["role"],
                "email": user["email"],
            }
        ), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/api/auth/me") #Provera prijavljenog korisnika, sluzi da frontend proveri ko je trenutno prijavljen 
@jwt_required()
def me():
    claims = get_jwt()
    return jsonify(
        {
            "user_id": get_jwt_identity(),
            "email": claims.get("email"),
            "role": claims.get("role"),
        }
    ), 200


# =========================
# 6) Languages
# =========================
@app.get("/api/languages") #Prikaz jezika
@jwt_required()
def list_languages():
    try:
        has_is_active = column_exists("languages", "is_active")

        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)

        if has_is_active:
            claims = get_jwt()
            role = claims.get("role")
            include_inactive = request.args.get("include_inactive") == "1"

            if role == "ADMIN" and include_inactive:
                cur.execute(
                    """
                    SELECT id, code, name, is_active
                    FROM languages
                    ORDER BY is_active DESC, id ASC
                    """
                )
            else:
                cur.execute(
                    """
                    SELECT id, code, name, is_active
                    FROM languages
                    WHERE is_active = 1
                    ORDER BY id ASC
                    """
                )
        else:
            cur.execute(
                """
                SELECT id, code, name, 1 AS is_active
                FROM languages
                ORDER BY id ASC
                """
            )

        rows = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify(rows), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/api/languages") #Dodavanje jezika
@role_required(["ADMIN"])
def add_language():
    data = request.get_json() or {}
    code = (data.get("code") or "").strip().lower()
    name = (data.get("name") or "").strip()

    if not code or not name:
        return jsonify({"error": "code and name required"}), 400

    try:
        has_is_active = column_exists("languages", "is_active")

        conn = get_db_connection()
        cur = conn.cursor()

        if has_is_active:
            cur.execute(
                "INSERT INTO languages (code, name, is_active) VALUES (%s, %s, 1)",
                (code, name),
            )
        else:
            cur.execute(
                "INSERT INTO languages (code, name) VALUES (%s, %s)",
                (code, name),
            )

        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"message": "Language created"}), 201

    except MySQLError as e:
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/api/languages/<int:language_id>/lessons-count") #Brojanje koliko lekcija postoji za koj jezik
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




@app.delete("/api/languages/<int:language_id>") #Brisanje jezika
@role_required(["ADMIN"])
def delete_language(language_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)

        cur.execute(
            "SELECT COUNT(*) AS cnt FROM lessons WHERE language_id = %s",
            (language_id,)
        )
        row = cur.fetchone()

        if int(row["cnt"]) > 0:
            cur.close()
            conn.close()
            return jsonify({
                "error": "Ne možeš da obrišeš jezik koji ima lekcije. Prvo obriši lessons za taj jezik."
            }), 400

        cur2 = conn.cursor()
        cur2.execute("DELETE FROM languages WHERE id = %s", (language_id,))
        conn.commit()

        if cur2.rowcount == 0:
            cur2.close()
            cur.close()
            conn.close()
            return jsonify({"error": "Language not found"}), 404

        cur2.close()
        cur.close()
        conn.close()
        return jsonify({"message": "Language deleted"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# =========================
# 7) Users / Profile
# =========================
@app.post("/api/users") #Kreiranje korisnika od strane admina
@role_required(["ADMIN"])
def create_user():
    data = request.get_json() or {}

    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    display_name = (data.get("display_name") or "").strip() or None
    role_name = (data.get("role") or "STUDENT").strip().upper()
    learning_language_id = data.get("learning_language_id") or None

    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400

    if role_name not in ("TEACHER", "STUDENT"):
        return jsonify({"error": "Role must be TEACHER or STUDENT"}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)

        cur.execute("SELECT id FROM roles WHERE name = %s", (role_name,))
        role_row = cur.fetchone()
        if not role_row:
            cur.close()
            conn.close()
            return jsonify({"error": "Role not found"}), 400

        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        if cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({"error": "Email already exists"}), 409

        if learning_language_id:
            cur.execute("SELECT id FROM languages WHERE id = %s", (learning_language_id,))
            if not cur.fetchone():
                cur.close()
                conn.close()
                return jsonify({"error": "Selected language does not exist"}), 400

        pw_hash = generate_password_hash(password)

        cur2 = conn.cursor()
        cur2.execute(
            """
            INSERT INTO users (email, password_hash, role_id, display_name, learning_language_id, is_active)
            VALUES (%s, %s, %s, %s, %s, 1)
            """,
            (email, pw_hash, role_row["id"], display_name, learning_language_id),
        )
        conn.commit()

        cur2.close()
        cur.close()
        conn.close()

        return jsonify({"message": "User created"}), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/api/profile") #Prikaz profila
@jwt_required()
def get_profile():
    try:
        user_id = get_jwt_identity()

        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)

        cur.execute(
            """
            SELECT
                u.id,
                u.email,
                u.display_name,
                u.profile_image,
                u.learning_language_id,
                r.name AS role,
                l.code AS learning_language_code,
                l.name AS learning_language_name
            FROM users u
            JOIN roles r ON r.id = u.role_id
            LEFT JOIN languages l ON l.id = u.learning_language_id
            WHERE u.id = %s
            LIMIT 1
            """,
            (user_id,),
        )
        row = cur.fetchone()

        cur.close()
        conn.close()

        if not row:
            return jsonify({"error": "User not found"}), 404

        return jsonify(row), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.put("/api/profile") #Izmena profila
@jwt_required()
def update_profile():
    try:
        user_id = get_jwt_identity()
        data = request.get_json() or {}

        display_name = (data.get("display_name") or "").strip() or None
        learning_language_id = data.get("learning_language_id") or None

        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)

        if learning_language_id:
            cur.execute("SELECT id FROM languages WHERE id = %s", (learning_language_id,))
            if not cur.fetchone():
                cur.close()
                conn.close()
                return jsonify({"error": "Selected language does not exist"}), 400

        cur2 = conn.cursor()
        cur2.execute(
            """
            UPDATE users
            SET display_name = %s,
                learning_language_id = %s
            WHERE id = %s
            """,
            (display_name, learning_language_id, user_id),
        )
        conn.commit()

        cur2.close()
        cur.close()
        conn.close()

        return jsonify({"message": "Profile updated"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    

@app.post("/api/profile/image") #Postavljanje profilne slike
@jwt_required()
def upload_profile_image():
    try:
        user_id = get_jwt_identity()

        if "image" not in request.files:
            return jsonify({"error": "No image uploaded"}), 400

        image = request.files["image"]

        if image.filename == "":
            return jsonify({"error": "No selected file"}), 400

        if not allowed_image(image.filename):
            return jsonify({"error": "Only png, jpg, jpeg and webp images are allowed"}), 400

        original_filename = secure_filename(image.filename)
        extension = original_filename.rsplit(".", 1)[1].lower()
        filename = f"user_{user_id}_{uuid.uuid4().hex}.{extension}"

        save_path = UPLOAD_FOLDER / filename
        image.save(save_path)

        image_url = f"/uploads/profile_images/{filename}"

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE users
            SET profile_image = %s
            WHERE id = %s
            """,
            (image_url, user_id),
        )
        conn.commit()

        cur.close()
        conn.close()

        return jsonify({
            "message": "Profile image uploaded",
            "profile_image": image_url
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.get("/api/users") #API ruta koja vraca listu korisnika
@role_required(["ADMIN"])
def list_users():
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)

        cur.execute(
            """
            SELECT
                u.id,
                u.email,
                u.display_name,
                u.learning_language_id,
                u.is_active,
                r.name AS role,
                l.name AS learning_language_name
            FROM users u
            JOIN roles r ON r.id = u.role_id
            LEFT JOIN languages l ON l.id = u.learning_language_id
            ORDER BY u.id ASC
            """
        )
        rows = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify(rows), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.patch("/api/users/<int:user_id>/approve") #Odobravanje korisnika od strane ADMINA 
@role_required(["ADMIN"])
def approve_user(user_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            "UPDATE users SET is_active = 1 WHERE id = %s",
            (user_id,)
        )
        conn.commit()

        if cur.rowcount == 0:
            cur.close()
            conn.close()
            return jsonify({"error": "User not found"}), 404

        cur.close()
        conn.close()

        return jsonify({"message": "User approved"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.delete("/api/users/<int:user_id>") #Brisanje korisnika
@role_required(["ADMIN"])
def delete_user(user_id):
    try:
        current_user_id = int(get_jwt_identity())

        if user_id == current_user_id:
            return jsonify({"error": "Ne možeš da obrišeš svoj nalog dok si ulogovan."}), 400

        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)

        cur.execute(
            """
            SELECT u.id, r.name AS role
            FROM users u
            JOIN roles r ON r.id = u.role_id
            WHERE u.id = %s
            LIMIT 1
            """,
            (user_id,),
        )
        user_row = cur.fetchone()

        if not user_row:
            cur.close()
            conn.close()
            return jsonify({"error": "User not found"}), 404

        if user_row["role"] == "ADMIN":
            cur.close()
            conn.close()
            return jsonify({"error": "Brisanje ADMIN naloga nije dozvoljeno."}), 400

        cur2 = conn.cursor()
        cur2.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()

        cur2.close()
        cur.close()
        conn.close()

        return jsonify({"message": "User deleted"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =========================
# 8) Lessons
# =========================
@app.get("/api/lessons") #prikaz svih lekcija
@jwt_required()
def list_lessons():
    try:
        user_id = int(get_jwt_identity())
        claims = get_jwt()
        role = claims.get("role")

        has_is_active = column_exists("languages", "is_active")

        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)

        if role in ["STUDENT", "TEACHER"]:
            cur.execute(
                """
                SELECT learning_language_id
                FROM users
                WHERE id = %s
                LIMIT 1
                """,
                (user_id,),
            )
            user_row = cur.fetchone()

            if not user_row or not user_row.get("learning_language_id"):
                cur.close()
                conn.close()
                return jsonify([]), 200

            user_language_id = user_row["learning_language_id"]

            if has_is_active:
                cur.execute(
                    """
                    SELECT
                        ls.id,
                        ls.language_id,
                        l.code AS language_code,
                        ls.level,
                        ls.title,
                        ls.content_html AS content,
                        ls.tips,
                        ls.important_info,
                        ls.order_no,
                        ls.created_by,
                        ls.created_at,
                        ls.updated_at
                    FROM lessons ls
                    JOIN languages l ON l.id = ls.language_id
                    WHERE l.is_active = 1
                      AND ls.language_id = %s
                    ORDER BY ls.order_no ASC, ls.id DESC
                    """,
                    (user_language_id,),
                )
            else:
                cur.execute(
                    """
                    SELECT
                        ls.id,
                        ls.language_id,
                        l.code AS language_code,
                        ls.level,
                        ls.title,
                        ls.content_html AS content,
                        ls.tips,
                        ls.important_info,
                        ls.order_no,
                        ls.created_by,
                        ls.created_at,
                        ls.updated_at
                    FROM lessons ls
                    JOIN languages l ON l.id = ls.language_id
                    WHERE ls.language_id = %s
                    ORDER BY ls.order_no ASC, ls.id DESC
                    """,
                    (user_language_id,),
                )

        else:
            if has_is_active:
                cur.execute(
                    """
                    SELECT
                        ls.id,
                        ls.language_id,
                        l.code AS language_code,
                        ls.level,
                        ls.title,
                        ls.content_html AS content,
                        ls.tips,
                        ls.important_info,
                        ls.order_no,
                        ls.created_by,
                        ls.created_at,
                        ls.updated_at
                    FROM lessons ls
                    JOIN languages l ON l.id = ls.language_id
                    WHERE l.is_active = 1
                    ORDER BY ls.order_no ASC, ls.id DESC
                    """
                )
            else:
                cur.execute(
                    """
                    SELECT
                        ls.id,
                        ls.language_id,
                        l.code AS language_code,
                        ls.level,
                        ls.title,
                        ls.content_html AS content,
                        ls.tips,
                        ls.important_info,
                        ls.order_no,
                        ls.created_by,
                        ls.created_at,
                        ls.updated_at
                    FROM lessons ls
                    JOIN languages l ON l.id = ls.language_id
                    ORDER BY ls.order_no ASC, ls.id DESC
                    """
                )

        rows = cur.fetchall()
        cur.close()
        conn.close()

        return jsonify(rows), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
@app.get("/api/lessons/<int:lesson_id>") #Detalji lekcije
@jwt_required()
def lesson_detail(lesson_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)

        cur.execute(
            """
            SELECT
                ls.id,
                ls.language_id,
                l.code AS language_code,
                ls.level,
                ls.title,
                ls.content_html AS content,
                ls.tips,
                ls.important_info,
                ls.order_no,
                ls.created_by,
                ls.created_at,
                ls.updated_at
            FROM lessons ls
            JOIN languages l ON l.id = ls.language_id
            WHERE ls.id = %s
            LIMIT 1
            """,
            (lesson_id,),
        )
        row = cur.fetchone()

        cur.close()
        conn.close()

        if not row:
            return jsonify({"error": "Lesson not found"}), 404

        return jsonify(row), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/api/lessons") #Kreiranje lekcije
@role_required(["TEACHER", "ADMIN"])
def create_lesson():
    data = request.get_json() or {}

    language_id = data.get("language_id")
    level = (data.get("level") or "").strip()
    title = (data.get("title") or "").strip()
    content_html = (data.get("content_html") or data.get("content") or "").strip()
    tips = (data.get("tips") or "").strip()
    important_info = (data.get("important_info") or "").strip()
    order_no = data.get("order_no", 0)
    created_by = get_jwt_identity()

    if not language_id or not level or not title or not content_html:
        return jsonify({"error": "language_id, level, title, content required"}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO lessons (language_id, level, title, content_html, tips, important_info, order_no, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (language_id, level, title, content_html, tips, important_info, order_no, created_by),
        )
        conn.commit()

        cur.close()
        conn.close()
        return jsonify({"message": "Lesson created"}), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.put("/api/lessons/<int:lesson_id>") #Izmena lekcije
@role_required(["TEACHER", "ADMIN"])
def update_lesson(lesson_id):
    data = request.get_json() or {}

    language_id = data.get("language_id")
    level = (data.get("level") or "").strip()
    title = (data.get("title") or "").strip()
    content_html = (data.get("content_html") or data.get("content") or "").strip()
    tips = (data.get("tips") or "").strip()
    important_info = (data.get("important_info") or "").strip()

    if not language_id or not level or not title or not content_html:
        return jsonify({"error": "language_id, level, title, content required"}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """
            UPDATE lessons
            SET
                language_id = %s,
                level = %s,
                title = %s,
                content_html = %s,
                tips = %s,
                important_info = %s
            WHERE id = %s
            """,
            (
                language_id,
                level,
                title,
                content_html,
                tips,
                important_info,
                lesson_id,
            ),
        )

        conn.commit()

        if cur.rowcount == 0:
            cur.close()
            conn.close()
            return jsonify({"error": "Lesson not found"}), 404

        cur.close()
        conn.close()

        return jsonify({"message": "Lesson updated"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.delete("/api/lessons/<int:lesson_id>") #Brisanje lekcije
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

@app.post("/api/lessons/<int:lesson_id>/favorite") #Dodavanje lekcije u favorite
@role_required(["STUDENT"])
def add_favorite_lesson(lesson_id):
    user_id = get_jwt_identity()

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """
            INSERT IGNORE INTO favorite_lessons (user_id, lesson_id)
            VALUES (%s, %s)
            """,
            (user_id, lesson_id),
        )
        conn.commit()

        cur.close()
        conn.close()
        return jsonify({"message": "Lesson added to favorites"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.delete("/api/lessons/<int:lesson_id>/favorite") #Uklanjanje iz favorita
@role_required(["STUDENT"])
def remove_favorite_lesson(lesson_id):
    user_id = get_jwt_identity()

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """
            DELETE FROM favorite_lessons
            WHERE user_id = %s AND lesson_id = %s
            """,
            (user_id, lesson_id),
        )
        conn.commit()

        cur.close()
        conn.close()
        return jsonify({"message": "Lesson removed from favorites"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/api/favorites") #prikaz favorita
@role_required(["STUDENT"])
def list_favorite_lessons():
    user_id = get_jwt_identity()

    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)

        cur.execute(
            """
            SELECT
                ls.id,
                ls.language_id,
                l.code AS language_code,
                ls.level,
                ls.title,
                ls.content_html AS content,
                ls.tips,
                ls.important_info,
                fl.created_at AS favorited_at
            FROM favorite_lessons fl
            JOIN lessons ls ON ls.id = fl.lesson_id
            JOIN languages l ON l.id = ls.language_id
            WHERE fl.user_id = %s
            ORDER BY fl.created_at DESC
            """,
            (user_id,),
        )

        rows = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify(rows), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.post("/api/progress/<int:lesson_id>") #Student moze da oznaci lekciju da je pregledao 
@role_required(["STUDENT"])
def mark_lesson_viewed(lesson_id):
    user_id = get_jwt_identity()

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """
            INSERT IGNORE INTO lesson_progress (user_id, lesson_id)
            VALUES (%s, %s)
            """,
            (user_id, lesson_id),
        )
        conn.commit()

        cur.close()
        conn.close()

        return jsonify({"message": "Lesson marked as viewed"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.delete("/api/progress/<int:lesson_id>") #Student moze da oznaci da nije video lekciju, ako mu je bilo cekirano
@role_required(["STUDENT"])
def unmark_lesson_viewed(lesson_id):
    user_id = get_jwt_identity()

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """
            DELETE FROM lesson_progress
            WHERE user_id = %s AND lesson_id = %s
            """,
            (user_id, lesson_id),
        )
        conn.commit()

        cur.close()
        conn.close()

        return jsonify({"message": "Lesson unmarked as viewed"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/api/progress") #Racunanje progresa, kolko je lekcija video student od ukupnog broja
@role_required(["STUDENT"])
def get_lesson_progress():
    user_id = get_jwt_identity()

    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)

        cur.execute(
            """
            SELECT lesson_id, viewed_at
            FROM lesson_progress
            WHERE user_id = %s
            """,
            (user_id,),
        )

        rows = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify(rows), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    

@app.post("/api/lesson-images")
@role_required(["TEACHER", "ADMIN"])
def upload_lesson_image():
    try:
        if "image" not in request.files:
            return jsonify({"error": "No image uploaded"}), 400

        image = request.files["image"]

        if image.filename == "":
            return jsonify({"error": "No selected file"}), 400

        if not allowed_image(image.filename):
            return jsonify({"error": "Only png, jpg, jpeg and webp images are allowed"}), 400

        original_filename = secure_filename(image.filename)
        extension = original_filename.rsplit(".", 1)[1].lower()
        filename = f"lesson_{uuid.uuid4().hex}.{extension}"

        save_path = LESSON_IMAGE_FOLDER / filename
        image.save(save_path)

        image_url = f"/uploads/lesson_images/{filename}"

        return jsonify({
            "message": "Lesson image uploaded",
            "image_url": image_url
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# =========================
# 9) Exam logika
# =========================

@app.get("/api/exams") #prikaz testova
@jwt_required()
def get_exams():
    claims = get_jwt()
    role = claims.get("role")
    user_id = get_jwt_identity()

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if role == "STUDENT":
            cursor.execute("""
                SELECT 
                    e.*,
                    l.name AS language_name,

                    ea.id AS attempt_id,
                    ea.score,
                    ea.total_points,
                    ea.status AS attempt_status

                FROM exams e

                JOIN languages l 
                    ON e.language_id = l.id

                JOIN users u 
                    ON u.id = %s

                LEFT JOIN exam_attempts ea
                    ON ea.exam_id = e.id
                    AND ea.student_id = %s
                    AND ea.status = 'COMPLETED'

                WHERE e.is_published = 1
                AND e.language_id = u.learning_language_id

                ORDER BY e.created_at DESC
            """, (user_id, user_id))

        elif role == "TEACHER":
            cursor.execute("""
                SELECT e.*, l.name AS language_name
                FROM exams e
                JOIN languages l ON e.language_id = l.id
                JOIN users u ON u.id = %s
                WHERE e.language_id = u.learning_language_id
            """, (user_id,))

        else:
            cursor.execute("""
                SELECT e.*, l.name AS language_name
                FROM exams e
                JOIN languages l ON e.language_id = l.id
            """)

        exams = cursor.fetchall()

        cursor.close()
        conn.close()

        return jsonify(exams), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.post("/api/exams") #kreiranje testa
@role_required(["TEACHER", "ADMIN"])
def create_exam():
    data = request.get_json() or {}
    claims = get_jwt()
    role = claims.get("role")

    title = (data.get("title") or "").strip()
    description = (data.get("description") or "").strip()
    language_id = data.get("language_id")
    level = (data.get("level") or "").strip()
    duration_minutes = data.get("duration_minutes", 30)
    open_at = data.get("open_at")
    close_at = data.get("close_at")
    exam_mode = int(data.get("exam_mode", 0))

    created_by = get_jwt_identity()

    if not title or not language_id or not level:
        return jsonify({"error": "Title, language and level are required"}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if role == "TEACHER":
            cursor.execute("""
                SELECT learning_language_id
                FROM users
                WHERE id = %s
            """, (created_by,))

            teacher = cursor.fetchone()

            if not teacher or int(language_id) != int(teacher["learning_language_id"]):
                cursor.close()
                conn.close()
                return jsonify({"error": "Teacher can create exams only for assigned language"}), 403

        cursor.execute("""
            INSERT INTO exams
            (
                title,
                description,
                language_id,
                level,
                duration_minutes,
                open_at,
                close_at,
                exam_mode,
                is_published,
                created_by
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0, %s)
        """, (
            title,
            description,
            language_id,
            level,
            duration_minutes,
            open_at,
            close_at,
            exam_mode,
            created_by
        ))

        conn.commit()
        exam_id = cursor.lastrowid

        cursor.close()
        conn.close()

        return jsonify({
            "message": "Exam created successfully",
            "exam_id": exam_id
        }), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    

@app.get("/api/exams/<int:exam_id>")
@role_required(["TEACHER", "ADMIN", "STUDENT"])
def get_exam_details(exam_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                e.*,
                l.name AS language_name
            FROM exams e
            JOIN languages l ON e.language_id = l.id
            WHERE e.id = %s
        """, (exam_id,))

        exam = cursor.fetchone()

        if not exam:
            cursor.close()
            conn.close()
            return jsonify({"error": "Exam not found"}), 404

        claims = get_jwt()
        role = claims.get("role")
        user_id = get_jwt_identity()

        if role == "STUDENT":

            if exam["is_published"] != 1:
                cursor.close()
                conn.close()
                return jsonify({"error": "Exam is not published"}), 403

            cursor.execute("""
                SELECT learning_language_id
                FROM users
                WHERE id = %s
            """, (user_id,))

            student = cursor.fetchone()

            if not student or student["learning_language_id"] != exam["language_id"]:
                cursor.close()
                conn.close()
                return jsonify({"error": "You can access only exams for your language"}), 403

            cursor.execute("""
                SELECT NOW() AS now_time
            """)

            time_row = cursor.fetchone()
            now = time_row["now_time"]

            if exam["open_at"] and now < exam["open_at"]:
                cursor.close()
                conn.close()
                return jsonify({"error": "Exam is not open yet"}), 403

            if exam["close_at"] and now > exam["close_at"]:
                cursor.close()
                conn.close()
                return jsonify({"error": "Exam has expired"}), 403

        if role == "STUDENT":
            cursor.execute("""
                SELECT *
                FROM exam_questions
                WHERE exam_id = %s
                ORDER BY RAND()
            """, (exam_id,))
        else:
            cursor.execute("""
                SELECT *
                FROM exam_questions
                WHERE exam_id = %s
                ORDER BY order_no ASC, id ASC
            """, (exam_id,))

        questions = cursor.fetchall()

        for question in questions:
            if role == "STUDENT":
                cursor.execute("""
                    SELECT id, answer_text, is_correct
                    FROM exam_answers
                    WHERE question_id = %s
                    ORDER BY RAND()
                """, (question["id"],))
            else:
                cursor.execute("""
                    SELECT id, answer_text, is_correct
                    FROM exam_answers
                    WHERE question_id = %s
                    ORDER BY id ASC
                """, (question["id"],))

            question["answers"] = cursor.fetchall()

        cursor.close()
        conn.close()

        exam["questions"] = questions

        return jsonify(exam), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/api/exams/<int:exam_id>/questions") #dodavanje pitanja
@role_required(["TEACHER", "ADMIN"])
def add_exam_question(exam_id):
    data = request.get_json() or {}

    question_text = (data.get("question_text") or "").strip()
    points = data.get("points", 1)
    order_no = data.get("order_no", 0)

    if not question_text:
        return jsonify({"error": "Question text is required"}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO exam_questions
            (exam_id, question_text, points, order_no)
            VALUES (%s, %s, %s, %s)
        """, (exam_id, question_text, points, order_no))

        conn.commit()
        question_id = cursor.lastrowid

        cursor.close()
        conn.close()

        return jsonify({
            "message": "Question added successfully",
            "question_id": question_id
        }), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/api/questions/<int:question_id>/answers") #dodavanje odgovora na pitanje
@role_required(["TEACHER", "ADMIN"])
def add_question_answer(question_id):
    data = request.get_json() or {}

    answer_text = (data.get("answer_text") or "").strip()
    is_correct = int(data.get("is_correct", 0))

    if not answer_text:
        return jsonify({"error": "Answer text is required"}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        if is_correct == 1:
            cursor.execute("""
                UPDATE exam_answers
                SET is_correct = 0
                WHERE question_id = %s
            """, (question_id,))

        cursor.execute("""
            INSERT INTO exam_answers
            (question_id, answer_text, is_correct)
            VALUES (%s, %s, %s)
        """, (question_id, answer_text, is_correct))

        conn.commit()
        answer_id = cursor.lastrowid

        cursor.close()
        conn.close()

        return jsonify({
            "message": "Answer added successfully",
            "answer_id": answer_id
        }), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    

@app.delete("/api/questions/<int:question_id>")#brisanje pitanja
@role_required(["TEACHER", "ADMIN"])
def delete_question(question_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM exam_questions WHERE id = %s", (question_id,))
        conn.commit()

        cursor.close()
        conn.close()

        return jsonify({"message": "Question deleted"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    

@app.delete("/api/answers/<int:answer_id>") #brisanje odgovora
@role_required(["TEACHER", "ADMIN"])
def delete_answer(answer_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM exam_answers WHERE id = %s", (answer_id,))
        conn.commit()

        cursor.close()
        conn.close()

        return jsonify({"message": "Answer deleted"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.put("/api/questions/<int:question_id>") #izmena pitanja
@role_required(["TEACHER", "ADMIN"])
def update_question(question_id):
    data = request.get_json() or {}

    question_text = (data.get("question_text") or "").strip()
    points = data.get("points", 1)

    if not question_text:
        return jsonify({"error": "Question text is required"}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE exam_questions
            SET question_text = %s, points = %s
            WHERE id = %s
        """, (question_text, points, question_id))

        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({"message": "Question updated"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.put("/api/answers/<int:answer_id>") #izmena odgovora
@role_required(["TEACHER", "ADMIN"])
def update_answer(answer_id):
    data = request.get_json() or {}

    answer_text = (data.get("answer_text") or "").strip()
    is_correct = int(data.get("is_correct", 0))

    if not answer_text:
        return jsonify({"error": "Answer text is required"}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        if is_correct == 1:
            cursor.execute("""
                UPDATE exam_answers
                SET is_correct = 0
                WHERE question_id = (
                    SELECT question_id FROM exam_answers WHERE id = %s
                )
            """, (answer_id,))

        cursor.execute("""
            UPDATE exam_answers
            SET answer_text = %s, is_correct = %s
            WHERE id = %s
        """, (answer_text, is_correct, answer_id))

        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({"message": "Answer updated"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.put("/api/exams/<int:exam_id>/publish") #publishovanje testa
@role_required(["TEACHER", "ADMIN"])
def publish_exam(exam_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE exams
            SET is_published = 1
            WHERE id = %s
        """, (exam_id,))

        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({"message": "Exam published"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.delete("/api/exams/<int:exam_id>") #brisanje testa
@role_required(["TEACHER", "ADMIN"])
def delete_exam(exam_id):
    try:
        user_id = get_jwt_identity()
        claims = get_jwt()
        role = claims.get("role")

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Provera da li test postoji
        cursor.execute("""
            SELECT id, language_id
            FROM exams
            WHERE id = %s
        """, (exam_id,))

        exam = cursor.fetchone()

        if not exam:
            cursor.close()
            conn.close()
            return jsonify({"error": "Exam not found"}), 404

        # Teacher sme da briše samo testove za svoj jezik
        if role == "TEACHER":
            cursor.execute("""
                SELECT learning_language_id
                FROM users
                WHERE id = %s
            """, (user_id,))

            teacher = cursor.fetchone()

            if not teacher or teacher["learning_language_id"] != exam["language_id"]:
                cursor.close()
                conn.close()
                return jsonify({"error": "You can delete only exams for your assigned language"}), 403

        # Prvo brišemo odgovore studenata za pokušaje tog testa
        cursor.execute("""
            DELETE eaa
            FROM exam_attempt_answers eaa
            JOIN exam_attempts ea ON eaa.attempt_id = ea.id
            WHERE ea.exam_id = %s
        """, (exam_id,))

        # Zatim brišemo pokušaje testa
        cursor.execute("""
            DELETE FROM exam_attempts
            WHERE exam_id = %s
        """, (exam_id,))

        # Zatim brišemo ponuđene odgovore za pitanja tog testa
        cursor.execute("""
            DELETE ea
            FROM exam_answers ea
            JOIN exam_questions eq ON ea.question_id = eq.id
            WHERE eq.exam_id = %s
        """, (exam_id,))

        # Zatim brišemo pitanja
        cursor.execute("""
            DELETE FROM exam_questions
            WHERE exam_id = %s
        """, (exam_id,))

        # Na kraju brišemo test
        cursor.execute("""
            DELETE FROM exams
            WHERE id = %s
        """, (exam_id,))

        conn.commit()

        cursor.close()
        conn.close()

        return jsonify({"message": "Exam deleted successfully"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.post("/api/exams/<int:exam_id>/submit") #student kad radi test, da ga submituje
@jwt_required()
def submit_exam(exam_id):
    student_id = get_jwt_identity()

    data = request.get_json() or {}
    answers = data.get("answers", {})
    tab_warnings = int(data.get("tab_warnings", 0))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Provera da li je student već završio ovaj test
    cursor.execute("""
        SELECT id
        FROM exam_attempts
        WHERE exam_id = %s 
          AND student_id = %s
          AND status = 'COMPLETED'
    """, (exam_id, student_id))

    existing = cursor.fetchone()

    if existing:
        cursor.close()
        conn.close()
        return jsonify({"error": "You already took this exam"}), 400

    # Kreiranje attempt-a
    cursor.execute("""
        INSERT INTO exam_attempts 
        (exam_id, student_id, status)
        VALUES (%s, %s, 'IN_PROGRESS')
    """, (exam_id, student_id))

    attempt_id = cursor.lastrowid

    score = 0

    cursor.execute("""
        SELECT COALESCE(SUM(points), 0) AS total
        FROM exam_questions
        WHERE exam_id = %s
    """, (exam_id,))

    total_row = cursor.fetchone()
    total = total_row["total"] or 0

    for question_id, answer_id in answers.items():
        cursor.execute("""
            SELECT id, points
            FROM exam_questions
            WHERE id = %s AND exam_id = %s
        """, (question_id, exam_id))

        question = cursor.fetchone()

        if not question:
            continue

        

        cursor.execute("""
            SELECT id, is_correct
            FROM exam_answers
            WHERE id = %s AND question_id = %s
        """, (answer_id, question_id))

        answer = cursor.fetchone()

        is_correct = 0
        points_awarded = 0

        if answer and answer["is_correct"] == 1:
            is_correct = 1
            points_awarded = question["points"]
            score += question["points"]

        cursor.execute("""
            INSERT INTO exam_attempt_answers
            (attempt_id, question_id, answer_id, is_correct, points_awarded)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            attempt_id,
            question_id,
            answer_id,
            is_correct,
            points_awarded
        ))

    # Završavanje attempt-a
    cursor.execute("""
        UPDATE exam_attempts
        SET 
            submitted_at = CURRENT_TIMESTAMP,
            score = %s,
            total_points = %s,
            status = 'COMPLETED',
            tab_warnings = %s
        WHERE id = %s
    """, (
        score,
        total,
        tab_warnings,
        attempt_id
    ))

    conn.commit()

    cursor.close()
    conn.close()

    return jsonify({
        "attempt_id": attempt_id,
        "score": score,
        "total": total
    }), 200

@app.get("/api/exams/<int:exam_id>/results") #Pregled rezultata za jedan test
@role_required(["TEACHER", "ADMIN"])
def get_exam_results(exam_id):
    try:
        user_id = get_jwt_identity()
        claims = get_jwt()
        role = claims.get("role")

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if role == "TEACHER":
            cursor.execute("""
                SELECT e.id
                FROM exams e
                JOIN users u ON u.id = %s
                WHERE e.id = %s
                  AND e.language_id = u.learning_language_id
            """, (user_id, exam_id))

            allowed_exam = cursor.fetchone()

            if not allowed_exam:
                cursor.close()
                conn.close()
                return jsonify({"error": "You can view results only for your assigned language"}), 403

        cursor.execute("""
            SELECT 
                ea.id,
                ea.exam_id,
                ea.student_id,
                ea.score,
                ea.total_points AS total,
                ea.submitted_at,
                ea.status,
                ea.tab_warnings,
                u.display_name,
                u.email
            FROM exam_attempts ea
            JOIN users u ON ea.student_id = u.id
            WHERE ea.exam_id = %s
              AND ea.status = 'COMPLETED'
            ORDER BY ea.submitted_at DESC
        """, (exam_id,))

        results = cursor.fetchall()

        cursor.close()
        conn.close()

        return jsonify(results), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    

@app.get("/api/exams/<int:exam_id>/results/export") #export u excel
@role_required(["TEACHER", "ADMIN"])
def export_exam_results(exam_id):
    try:
        user_id = get_jwt_identity()
        claims = get_jwt()
        role = claims.get("role")

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if role == "TEACHER":
            cursor.execute("""
                SELECT e.id
                FROM exams e
                JOIN users u ON u.id = %s
                WHERE e.id = %s
                  AND e.language_id = u.learning_language_id
            """, (user_id, exam_id))

            allowed_exam = cursor.fetchone()

            if not allowed_exam:
                cursor.close()
                conn.close()
                return jsonify({"error": "You can export results only for your assigned language"}), 403

        cursor.execute("""
            SELECT title
            FROM exams
            WHERE id = %s
        """, (exam_id,))

        exam = cursor.fetchone()

        cursor.execute("""
            SELECT 
                ea.id,
                ea.score,
                ea.total_points AS total,
                ea.submitted_at,
                ea.status,
                ea.tab_warnings,
                u.display_name,
                u.email
            FROM exam_attempts ea
            JOIN users u ON ea.student_id = u.id
            WHERE ea.exam_id = %s
              AND ea.status = 'COMPLETED'
            ORDER BY ea.submitted_at DESC
        """, (exam_id,))

        results = cursor.fetchall()

        cursor.close()
        conn.close()

        wb = Workbook()
        ws = wb.active
        ws.title = "Exam Results"

        ws.append([
            "Student",
            "Email",
            "Score",
            "Total",
            "Percentage",
            "Passed / Failed",
            "Tab Warnings",
            "Submitted At"
        ])

        for r in results:
            score = r["score"] or 0
            total = r["total"] or 0
            percentage = round((score / total) * 100, 2) if total > 0 else 0
            passed_status = "Passed" if total > 0 and score >= total * 0.5 else "Failed"

            ws.append([
                r["display_name"],
                r["email"],
                score,
                total,
                f"{percentage}%",
                passed_status,
                r["tab_warnings"] or 0,
                r["submitted_at"]
            ])

        for column in ws.columns:
            max_length = 0
            column_letter = column[0].column_letter

            for cell in column:
                value = str(cell.value) if cell.value is not None else ""
                if len(value) > max_length:
                    max_length = len(value)

            ws.column_dimensions[column_letter].width = max_length + 2

        output = BytesIO()
        wb.save(output)
        output.seek(0)

        filename = f"exam_{exam_id}_results.xlsx"

        return send_file(
            output,
            as_attachment=True,
            download_name=filename,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.get("/api/my-results") #prikaz rezultata za studenta
@jwt_required()
def get_my_results():
    try:
        user_id = get_jwt_identity()

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT 
                ea.id,
                ea.exam_id,
                ea.score,
                ea.total_points AS total,
                ea.submitted_at,
                ea.status,
                e.title
            FROM exam_attempts ea
            JOIN exams e ON ea.exam_id = e.id
            WHERE ea.student_id = %s
              AND ea.status = 'COMPLETED'
            ORDER BY ea.submitted_at DESC
        """, (user_id,))

        results = cursor.fetchall()

        cursor.close()
        conn.close()

        return jsonify(results), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
# =========================
# 9) Run
# =========================


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)

