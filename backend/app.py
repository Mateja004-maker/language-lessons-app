# Podesavanje aplikacije - osnova da ceo backend radi kako treba
import os
import json
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
from datetime import timedelta
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

# ai_provider i explanation_prompts čitaju konfiguraciju iz environment-a na
# nivou modula, pa importi moraju doći POSLE load_dotenv().
import ai_provider
import prompt_templates
import explanation_prompts
import code_executor
import explanation_review
import explanation_rating


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

# Pomoćne funkcije za many-to-many predmete (student_subjects / teacher_subjects).
# Nisu jos pozvane ni na jednom endpointu - dodato da se ne bi ponavljao isti upit na vise mesta.
def _subject_table_and_column(role):
    if role == "STUDENT":
        return "student_subjects", "student_id"
    if role == "TEACHER":
        return "teacher_subjects", "teacher_id"
    return None, None


def get_user_subject_ids(user_id, role):
    table, id_column = _subject_table_and_column(role)
    if not table:
        return []

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            f"SELECT subject_id FROM {table} WHERE {id_column} = %s",
            (user_id,),
        )
        return [row["subject_id"] for row in cur.fetchall()]
    finally:
        cur.close()
        conn.close()


def user_has_subject(user_id, subject_id, role):
    table, id_column = _subject_table_and_column(role)
    if not table or subject_id is None:
        return False

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            f"SELECT 1 FROM {table} WHERE {id_column} = %s AND subject_id = %s LIMIT 1",
            (user_id, subject_id),
        )
        return cur.fetchone() is not None
    finally:
        cur.close()
        conn.close()


def allowed_image(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS


# Pomoćne funkcije za AI generisanje pitanja (ai_generation_runs / ai_generated_artifacts).
def ensure_ai_model(conn, provider, model_name, model_version=None):
    """Vraća id postojećeg reda u ai_models, ili ga kreira ako ne postoji."""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id FROM ai_models
        WHERE provider = %s AND model_name = %s AND model_version <=> %s
        """,
        (provider, model_name, model_version),
    )
    row = cursor.fetchone()
    if row:
        cursor.close()
        return row[0]

    cursor.execute(
        """
        INSERT INTO ai_models (provider, model_name, model_version)
        VALUES (%s, %s, %s)
        """,
        (provider, model_name, model_version),
    )
    conn.commit()
    model_id = cursor.lastrowid
    cursor.close()
    return model_id


# Pomoćne funkcije/konstante za pregled i odobravanje AI predloga
# (ai_generated_artifacts.status / ai_rubric_definitions / ai_evaluations).
ARTIFACT_TYPE_QUESTION = "question"
ARTIFACT_STATUS_PENDING = "predlog"
ARTIFACT_STATUS_ACCEPTED = "prihvaceno"
ARTIFACT_STATUS_ACCEPTED_EDITED = "prihvaceno_izmena"
ARTIFACT_STATUS_REJECTED = "odbaceno"
ARTIFACT_DECISIONS = {
    ARTIFACT_STATUS_ACCEPTED,
    ARTIFACT_STATUS_ACCEPTED_EDITED,
    ARTIFACT_STATUS_REJECTED,
}

# Slepo ocenjivanje: dok je predlog u statusu 'predlog', ocenjivac ne sme da
# vidi koji ga je model generisao. Podaci ostaju u bazi, krije se samo odgovor.
BLIND_REVIEW_MODEL_FIELDS = ("provider", "model_name")


def blind_review_reveal_requested():
    """ADMIN moze da trazi ?reveal=1 da vidi skrivena polja; TEACHER ne."""
    return get_jwt().get("role") == "ADMIN" and request.args.get("reveal") == "1"


def hide_while_pending(row, fields):
    if row.get("status") == ARTIFACT_STATUS_PENDING and not blind_review_reveal_requested():
        for field in fields:
            row.pop(field, None)
    return row

RUBRIC_APPLIES_TO_ALL = "question"
RUBRIC_APPLIES_TO_MC = "question_mc"


def get_applicable_rubric_definitions(cursor, question_type):
    """Vraća redove iz ai_rubric_definitions koji važe za dati question_type
    ('mc' dobija i opšte i MC-specifične kriterijume, 'open' samo opšte)."""
    applies_to_values = [RUBRIC_APPLIES_TO_ALL]
    if question_type == "mc":
        applies_to_values.append(RUBRIC_APPLIES_TO_MC)

    placeholders = ",".join(["%s"] * len(applies_to_values))
    cursor.execute(
        f"""
        SELECT id, applies_to, dimension_key, dimension_label, scale_min, scale_max
        FROM ai_rubric_definitions
        WHERE applies_to IN ({placeholders})
        ORDER BY id ASC
        """,
        tuple(applies_to_values),
    )
    return cursor.fetchall()


def validate_similar_question_payload(parsed, question_type, expected_answer_count):
    """Vraća None ako je JSON iz AI odgovora ispravan za dati tip pitanja,
    inače string sa opisom greške."""
    if not isinstance(parsed, dict):
        return "Odgovor modela mora biti JSON objekat"

    question_text = parsed.get("question_text")
    if not isinstance(question_text, str) or not question_text.strip():
        return "Nedostaje ili je prazan question_text"

    if question_type == "mc":
        answers = parsed.get("answers")
        if not isinstance(answers, list) or len(answers) != expected_answer_count:
            return f"Očekivano je tačno {expected_answer_count} ponuđenih odgovora"

        correct_count = 0
        for a in answers:
            if not isinstance(a, dict):
                return "Svaki ponuđeni odgovor mora biti JSON objekat"
            if not isinstance(a.get("answer_text"), str) or not a["answer_text"].strip():
                return "Ponuđeni odgovor bez teksta"
            if not isinstance(a.get("is_correct"), bool):
                return "is_correct mora biti true/false"
            if a["is_correct"]:
                correct_count += 1

        if correct_count != 1:
            return f"Očekivan je tačno jedan tačan odgovor, pronađeno {correct_count}"

    else:  # "open"
        if "answers" in parsed:
            return "Otvoreno pitanje ne sme imati ponuđene odgovore"

    return None



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

@app.get("/api/subjects") #Prikaz predmeta (many-to-many student/teacher_subjects)
@jwt_required()
def list_subjects():
    try:
        user_id = get_jwt_identity()
        claims = get_jwt()
        role = claims.get("role")

        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)

        if role == "ADMIN":
            cur.execute("SELECT id, code, name FROM subjects ORDER BY name ASC")
            rows = cur.fetchall()
        else:
            subject_ids = get_user_subject_ids(int(user_id), role)
            if not subject_ids:
                rows = []
            else:
                placeholders = ", ".join(["%s"] * len(subject_ids))
                cur.execute(
                    f"SELECT id, code, name FROM subjects WHERE id IN ({placeholders}) ORDER BY name ASC",
                    tuple(subject_ids),
                )
                rows = cur.fetchall()

        cur.close()
        conn.close()
        return jsonify(rows), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/api/subjects/<int:subject_id>/areas") #Prikaz oblasti unutar predmeta
@jwt_required()
def list_areas(subject_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)

        cur.execute("SELECT id FROM subjects WHERE id = %s", (subject_id,))
        if not cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({"error": "Subject not found"}), 404

        cur.execute(
            "SELECT id, subject_id, name FROM areas WHERE subject_id = %s ORDER BY name ASC",
            (subject_id,),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify(rows), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/api/subjects/<int:subject_id>/areas") #Dodavanje oblasti u predmet
@role_required(["TEACHER", "ADMIN"])
def add_area(subject_id):
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()

    if not name:
        return jsonify({"error": "Name is required"}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)

        cur.execute("SELECT id FROM subjects WHERE id = %s", (subject_id,))
        if not cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({"error": "Subject not found"}), 404

        cur.execute(
            "SELECT id FROM areas WHERE subject_id = %s AND name = %s",
            (subject_id, name),
        )
        if cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({"error": "Area already exists for this subject"}), 409

        cur2 = conn.cursor()
        cur2.execute(
            "INSERT INTO areas (subject_id, name) VALUES (%s, %s)",
            (subject_id, name),
        )
        conn.commit()
        area_id = cur2.lastrowid

        cur2.close()
        cur.close()
        conn.close()

        return jsonify({"message": "Area created", "area_id": area_id}), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/api/subjects/<int:subject_id>/questions") #Prikaz banke pitanja za predmet
@role_required(["TEACHER", "ADMIN"])
def list_bank_questions(subject_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)

        cur.execute("SELECT id FROM subjects WHERE id = %s", (subject_id,))
        if not cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({"error": "Subject not found"}), 404

        area_id_raw = request.args.get("area_id")
        area_id = None
        if area_id_raw is not None:
            try:
                area_id = int(area_id_raw)
            except ValueError:
                cur.close()
                conn.close()
                return jsonify({"error": "Invalid area_id"}), 400

        if area_id is not None:
            cur.execute(
                """
                SELECT
                    eq.id, eq.subject_id, eq.area_id, eq.question_text, eq.points,
                    (SELECT COUNT(*) FROM exam_answers ea WHERE ea.question_id = eq.id) AS answer_count,
                    (eq.reference_solution IS NOT NULL AND eq.reference_solution <> '') AS has_reference_solution
                FROM exam_questions eq
                WHERE eq.subject_id = %s AND eq.area_id = %s
                ORDER BY eq.id ASC
                """,
                (subject_id, area_id),
            )
        else:
            cur.execute(
                """
                SELECT
                    eq.id, eq.subject_id, eq.area_id, eq.question_text, eq.points,
                    (SELECT COUNT(*) FROM exam_answers ea WHERE ea.question_id = eq.id) AS answer_count,
                    (eq.reference_solution IS NOT NULL AND eq.reference_solution <> '') AS has_reference_solution
                FROM exam_questions eq
                WHERE eq.subject_id = %s
                ORDER BY eq.id ASC
                """,
                (subject_id,),
            )

        rows = cur.fetchall()
        cur.close()
        conn.close()

        for row in rows:
            row["has_reference_solution"] = bool(row["has_reference_solution"])

        return jsonify(rows), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/api/subjects/<int:subject_id>/questions") #Kreiranje pitanja direktno u banku (bez testa)
@role_required(["TEACHER", "ADMIN"])
def add_bank_question(subject_id):
    data = request.get_json() or {}

    question_text = (data.get("question_text") or "").strip()
    points = data.get("points", 1)
    area_id = data.get("area_id") or None

    if not question_text:
        return jsonify({"error": "Question text is required"}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)

        cur.execute("SELECT id FROM subjects WHERE id = %s", (subject_id,))
        if not cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({"error": "Subject not found"}), 404

        if area_id is not None:
            cur.execute("SELECT subject_id FROM areas WHERE id = %s", (area_id,))
            area_row = cur.fetchone()
            if not area_row:
                cur.close()
                conn.close()
                return jsonify({"error": "Selected area does not exist"}), 400

            if area_row["subject_id"] != subject_id:
                cur.close()
                conn.close()
                return jsonify({"error": "Selected area does not belong to this subject"}), 400

        cur2 = conn.cursor()
        cur2.execute(
            """
            INSERT INTO exam_questions
            (exam_id, subject_id, area_id, question_text, points, order_no)
            VALUES (NULL, %s, %s, %s, %s, 0)
            """,
            (subject_id, area_id, question_text, points),
        )
        conn.commit()
        question_id = cur2.lastrowid

        cur2.close()
        cur.close()
        conn.close()

        return jsonify({
            "message": "Question added to bank successfully",
            "question_id": question_id
        }), 201

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
    subject_ids = data.get("subject_ids") or []

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

        if subject_ids:
            placeholders = ", ".join(["%s"] * len(subject_ids))
            cur.execute(f"SELECT id FROM subjects WHERE id IN ({placeholders})", tuple(subject_ids))
            found_ids = {row["id"] for row in cur.fetchall()}
            if found_ids != {int(s) for s in subject_ids}:
                cur.close()
                conn.close()
                return jsonify({"error": "One or more selected subjects do not exist"}), 400

        pw_hash = generate_password_hash(password)

        cur2 = conn.cursor()
        cur2.execute(
            """
            INSERT INTO users (email, password_hash, role_id, display_name, learning_language_id, is_active)
            VALUES (%s, %s, %s, %s, %s, 1)
            """,
            (email, pw_hash, role_row["id"], display_name, learning_language_id),
        )
        new_user_id = cur2.lastrowid

        if subject_ids:
            table, id_column = _subject_table_and_column(role_name)
            for subject_id in subject_ids:
                cur2.execute(
                    f"INSERT INTO {table} ({id_column}, subject_id) VALUES (%s, %s)",
                    (new_user_id, subject_id),
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

        row["subjects"] = get_user_subject_ids(user_id, row["role"])

        return jsonify(row), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.put("/api/profile") #Izmena profila
@jwt_required()
def update_profile():
    try:
        user_id = get_jwt_identity()
        claims = get_jwt()
        role = claims.get("role")
        data = request.get_json() or {}

        display_name = (data.get("display_name") or "").strip() or None
        learning_language_id = data.get("learning_language_id") or None
        subject_ids = data.get("subject_ids")

        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)

        if learning_language_id:
            cur.execute("SELECT id FROM languages WHERE id = %s", (learning_language_id,))
            if not cur.fetchone():
                cur.close()
                conn.close()
                return jsonify({"error": "Selected language does not exist"}), 400

        if subject_ids:
            placeholders = ", ".join(["%s"] * len(subject_ids))
            cur.execute(f"SELECT id FROM subjects WHERE id IN ({placeholders})", tuple(subject_ids))
            found_ids = {row["id"] for row in cur.fetchall()}
            if found_ids != {int(s) for s in subject_ids}:
                cur.close()
                conn.close()
                return jsonify({"error": "One or more selected subjects do not exist"}), 400

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

        if subject_ids is not None:
            table, id_column = _subject_table_and_column(role)
            if table:
                cur2.execute(f"DELETE FROM {table} WHERE {id_column} = %s", (user_id,))
                for subject_id in subject_ids:
                    cur2.execute(
                        f"INSERT INTO {table} ({id_column}, subject_id) VALUES (%s, %s)",
                        (user_id, subject_id),
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

        for row in rows:
            row["subjects"] = get_user_subject_ids(row["id"], row["role"])

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


@app.put("/api/users/<int:user_id>/subjects") #Izmena predmeta studenta/nastavnika od strane admina
@role_required(["ADMIN"])
def update_user_subjects(user_id):
    data = request.get_json() or {}
    subject_ids = data.get("subject_ids") or []

    try:
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

        table, id_column = _subject_table_and_column(user_row["role"])
        if not table:
            cur.close()
            conn.close()
            return jsonify({"error": "Subjects can be assigned only to TEACHER or STUDENT accounts"}), 400

        if subject_ids:
            placeholders = ", ".join(["%s"] * len(subject_ids))
            cur.execute(f"SELECT id FROM subjects WHERE id IN ({placeholders})", tuple(subject_ids))
            found_ids = {row["id"] for row in cur.fetchall()}
            if found_ids != {int(s) for s in subject_ids}:
                cur.close()
                conn.close()
                return jsonify({"error": "One or more selected subjects do not exist"}), 400

        cur2 = conn.cursor()
        cur2.execute(f"DELETE FROM {table} WHERE {id_column} = %s", (user_id,))
        for subject_id in subject_ids:
            cur2.execute(
                f"INSERT INTO {table} ({id_column}, subject_id) VALUES (%s, %s)",
                (user_id, subject_id),
            )
        conn.commit()

        cur2.close()
        cur.close()
        conn.close()

        return jsonify({"message": "Subjects updated", "subject_ids": subject_ids}), 200

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
            subject_ids = get_user_subject_ids(user_id, role)

            if not subject_ids:
                cur.close()
                conn.close()
                return jsonify([]), 200

            placeholders = ", ".join(["%s"] * len(subject_ids))

            if has_is_active:
                cur.execute(
                    f"""
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
                      AND ls.language_id IN ({placeholders})
                    ORDER BY ls.order_no ASC, ls.id DESC
                    """,
                    tuple(subject_ids),
                )
            else:
                cur.execute(
                    f"""
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
                    WHERE ls.language_id IN ({placeholders})
                    ORDER BY ls.order_no ASC, ls.id DESC
                    """,
                    tuple(subject_ids),
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
            subject_ids = get_user_subject_ids(int(user_id), "STUDENT")

            if not subject_ids:
                cursor.close()
                conn.close()
                return jsonify([]), 200

            placeholders = ", ".join(["%s"] * len(subject_ids))

            cursor.execute(f"""
                SELECT
                    e.*,
                    s.name AS subject_name,
                    s.name AS language_name,

                    ea.id AS attempt_id,
                    ea.score,
                    ea.total_points,
                    ea.status AS attempt_status

                FROM exams e

                JOIN subjects s
                    ON s.id = e.subject_id

                LEFT JOIN exam_attempts ea
                    ON ea.exam_id = e.id
                    AND ea.student_id = %s
                    AND ea.status = 'COMPLETED'

                WHERE e.is_published = 1
                AND e.subject_id IN ({placeholders})

                ORDER BY e.created_at DESC
            """, (user_id, *subject_ids))

        elif role == "TEACHER":
            subject_ids = get_user_subject_ids(int(user_id), "TEACHER")

            if not subject_ids:
                cursor.close()
                conn.close()
                return jsonify([]), 200

            placeholders = ", ".join(["%s"] * len(subject_ids))

            cursor.execute(f"""
                SELECT e.*, s.name AS subject_name, s.name AS language_name
                FROM exams e
                JOIN subjects s ON s.id = e.subject_id
                WHERE e.subject_id IN ({placeholders})
            """, tuple(subject_ids))

        else:
            cursor.execute("""
                SELECT e.*, s.name AS subject_name, s.name AS language_name
                FROM exams e
                LEFT JOIN subjects s ON s.id = e.subject_id
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
    # Test pripada predmetu (exams.subject_id). language_id se jos prima kao
    # rezerva dok frontend ne predje na subject_id (u exams se vise ne upisuje).
    subject_id = data.get("subject_id") or data.get("language_id")
    level = (data.get("level") or "").strip()
    duration_minutes = data.get("duration_minutes", 30)
    open_at = data.get("open_at")
    close_at = data.get("close_at")
    exam_mode = int(data.get("exam_mode", 0))

    created_by = get_jwt_identity()

    if not title or not subject_id or not level:
        return jsonify({"error": "Title, subject and level are required"}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if role == "TEACHER":
            if not user_has_subject(int(created_by), int(subject_id), "TEACHER"):
                cursor.close()
                conn.close()
                return jsonify({"error": "Teacher can create exams only for assigned subjects"}), 403

        cursor.execute("SELECT id FROM subjects WHERE id = %s", (int(subject_id),))
        if not cursor.fetchone():
            cursor.close()
            conn.close()
            return jsonify({"error": "Subject not found"}), 400

        cursor.execute("""
            INSERT INTO exams
            (
                title,
                description,
                subject_id,
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
            int(subject_id),
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
                s.name AS subject_name,
                s.name AS language_name
            FROM exams e
            LEFT JOIN subjects s ON s.id = e.subject_id
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

            if not user_has_subject(int(user_id), exam["subject_id"], "STUDENT"):
                cursor.close()
                conn.close()
                return jsonify({"error": "You can access only exams for your subjects"}), 403

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

        area_id_raw = request.args.get("area_id")
        area_id = None
        if area_id_raw is not None:
            try:
                area_id = int(area_id_raw)
            except ValueError:
                cursor.close()
                conn.close()
                return jsonify({"error": "Invalid area_id"}), 400

        if role == "STUDENT":
            if area_id is not None:
                cursor.execute("""
                    SELECT
                        eq.id,
                        etq.exam_id,
                        eq.area_id,
                        eq.question_text,
                        eq.points,
                        etq.order_no
                    FROM exam_test_questions etq
                    JOIN exam_questions eq ON eq.id = etq.question_id
                    WHERE etq.exam_id = %s AND eq.area_id = %s
                    ORDER BY RAND()
                """, (exam_id, area_id))
            else:
                cursor.execute("""
                    SELECT
                        eq.id,
                        etq.exam_id,
                        eq.area_id,
                        eq.question_text,
                        eq.points,
                        etq.order_no
                    FROM exam_test_questions etq
                    JOIN exam_questions eq ON eq.id = etq.question_id
                    WHERE etq.exam_id = %s
                    ORDER BY RAND()
                """, (exam_id,))
        else:
            if area_id is not None:
                cursor.execute("""
                    SELECT
                        eq.id,
                        etq.exam_id,
                        eq.area_id,
                        eq.question_text,
                        eq.points,
                        etq.order_no
                    FROM exam_test_questions etq
                    JOIN exam_questions eq ON eq.id = etq.question_id
                    WHERE etq.exam_id = %s AND eq.area_id = %s
                    ORDER BY etq.order_no ASC, eq.id ASC
                """, (exam_id, area_id))
            else:
                cursor.execute("""
                    SELECT
                        eq.id,
                        etq.exam_id,
                        eq.area_id,
                        eq.question_text,
                        eq.points,
                        etq.order_no
                    FROM exam_test_questions etq
                    JOIN exam_questions eq ON eq.id = etq.question_id
                    WHERE etq.exam_id = %s
                    ORDER BY etq.order_no ASC, eq.id ASC
                """, (exam_id,))

        questions = cursor.fetchall()

        for question in questions:
            if role == "STUDENT":
                # Student ne sme da dobije is_correct pre predaje testa.
                cursor.execute("""
                    SELECT id, answer_text
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
    area_id = data.get("area_id") or None

    if not question_text:
        return jsonify({"error": "Question text is required"}), 400

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT subject_id FROM exams WHERE id = %s", (exam_id,))
        exam_row = cursor.fetchone()
        if not exam_row:
            cursor.close()
            conn.close()
            return jsonify({"error": "Exam not found"}), 404

        if area_id is not None:
            cursor.execute("SELECT subject_id FROM areas WHERE id = %s", (area_id,))
            area_row = cursor.fetchone()
            if not area_row:
                cursor.close()
                conn.close()
                return jsonify({"error": "Selected area does not exist"}), 400

            if area_row["subject_id"] != exam_row["subject_id"]:
                cursor.close()
                conn.close()
                return jsonify({"error": "Selected area does not belong to this exam's subject"}), 400

        cursor.execute("""
            INSERT INTO exam_questions
            (exam_id, subject_id, area_id, question_text, points, order_no)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (exam_id, exam_row["subject_id"], area_id, question_text, points, order_no))

        question_id = cursor.lastrowid

        cursor.execute("""
            INSERT INTO exam_test_questions
            (exam_id, question_id, order_no)
            VALUES (%s, %s, %s)
        """, (exam_id, question_id, order_no))

        conn.commit()

        cursor.close()
        conn.close()

        return jsonify({
            "message": "Question added successfully",
            "question_id": question_id
        }), 201

    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        return jsonify({"error": str(e)}), 500


@app.post("/api/exams/<int:exam_id>/questions/<int:question_id>") #dodavanje postojeceg bank-pitanja u test
@role_required(["TEACHER", "ADMIN"])
def assign_bank_question_to_exam(exam_id, question_id):
    data = request.get_json() or {}
    order_no = data.get("order_no", 0)

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT subject_id FROM exams WHERE id = %s", (exam_id,))
        exam_row = cursor.fetchone()
        if not exam_row:
            cursor.close()
            conn.close()
            return jsonify({"error": "Exam not found"}), 404

        cursor.execute("SELECT subject_id FROM exam_questions WHERE id = %s", (question_id,))
        question_row = cursor.fetchone()
        if not question_row:
            cursor.close()
            conn.close()
            return jsonify({"error": "Question not found"}), 404

        if question_row["subject_id"] != exam_row["subject_id"]:
            cursor.close()
            conn.close()
            return jsonify({"error": "Question does not belong to this exam's subject"}), 400

        cursor.execute(
            "SELECT 1 FROM exam_test_questions WHERE exam_id = %s AND question_id = %s",
            (exam_id, question_id),
        )
        if cursor.fetchone():
            cursor.close()
            conn.close()
            return jsonify({"error": "Question is already part of this exam"}), 409

        cursor.execute("""
            INSERT INTO exam_test_questions
            (exam_id, question_id, order_no)
            VALUES (%s, %s, %s)
        """, (exam_id, question_id, order_no))

        conn.commit()

        cursor.close()
        conn.close()

        return jsonify({"message": "Question added to exam successfully"}), 201

    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        return jsonify({"error": str(e)}), 500


@app.delete("/api/exams/<int:exam_id>/questions/<int:question_id>") #uklanjanje pitanja samo iz ovog testa
@role_required(["TEACHER", "ADMIN"])
def remove_question_from_exam(exam_id, question_id):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            "SELECT 1 FROM exam_test_questions WHERE exam_id = %s AND question_id = %s",
            (exam_id, question_id),
        )
        if not cursor.fetchone():
            cursor.close()
            conn.close()
            return jsonify({"error": "Question is not part of this exam"}), 404

        cursor.execute(
            "DELETE FROM exam_test_questions WHERE exam_id = %s AND question_id = %s",
            (exam_id, question_id),
        )

        cursor.execute(
            "UPDATE exam_questions SET exam_id = NULL WHERE id = %s AND exam_id = %s",
            (question_id, exam_id),
        )

        conn.commit()

        cursor.close()
        conn.close()

        return jsonify({"message": "Question removed from exam"}), 200

    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        return jsonify({"error": str(e)}), 500


@app.get("/api/questions/<int:question_id>/answers") #prikaz odgovora za pitanje
@role_required(["TEACHER", "ADMIN"])
def list_question_answers(question_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)

        cur.execute(
            "SELECT id, answer_text, is_correct FROM exam_answers WHERE question_id = %s ORDER BY id ASC",
            (question_id,),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify(rows), 200
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

    except MySQLError as e:
        if e.errno == 1451:
            return jsonify({
                "error": "Question is still assigned to one or more exams and cannot be deleted. Remove it from those exams first."
            }), 409
        return jsonify({"error": str(e)}), 500

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


@app.post("/api/questions/<int:question_id>/generate-similar") #AI generisanje slicnog pitanja na osnovu postojeceg
@role_required(["TEACHER", "ADMIN"])
def generate_similar_question(question_id):
    try:
        provider = request.args.get("provider", "groq")
        if provider not in ai_provider.DEFAULT_MODELS:
            return jsonify({"error": f"Nepoznat provider: {provider}"}), 400

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT * FROM exam_questions WHERE id = %s", (question_id,))
        question = cursor.fetchone()

        if not question:
            cursor.close()
            conn.close()
            return jsonify({"error": "Question not found"}), 404

        cursor.execute("""
            SELECT answer_text, is_correct
            FROM exam_answers
            WHERE question_id = %s
            ORDER BY id ASC
        """, (question_id,))
        original_answers = cursor.fetchall()

        subject_name = "Nepoznat predmet"

        if question["subject_id"]:
            cursor.execute("SELECT name FROM subjects WHERE id = %s", (question["subject_id"],))
            subject_row = cursor.fetchone()
            if subject_row:
                subject_name = subject_row["name"]
        elif question["exam_id"]:
            cursor.execute("""
                SELECT s.name AS subject_name
                FROM exams e
                JOIN subjects s ON s.id = e.subject_id
                WHERE e.id = %s
            """, (question["exam_id"],))
            exam_row = cursor.fetchone()
            if exam_row:
                subject_name = exam_row["subject_name"]

        area_name = None

        if question["area_id"]:
            cursor.execute("SELECT name FROM areas WHERE id = %s", (question["area_id"],))
            area_row = cursor.fetchone()
            if area_row:
                area_name = area_row["name"]

        question_type = prompt_templates.detect_question_type(original_answers)
        prompt_id, template_text = prompt_templates.ensure_prompt_synced(conn, question_type)
        prompt_text = prompt_templates.build_similar_question_prompt(
            template_text,
            question["question_text"],
            original_answers,
            subject_name,
            area_name,
        )

        model_name = ai_provider.DEFAULT_MODELS[provider]
        model_id = ensure_ai_model(conn, provider=provider, model_name=model_name)

        options = {"temperature": 0.7}
        result = ai_provider.generate(prompt_text, provider=provider, options=options)

        parsed_result = None
        validation_errors = None

        if not result.get("success"):
            validation_errors = result.get("error", "Nepoznata greška pri pozivu AI modela")
        else:
            try:
                parsed_result = json.loads(result["raw_text"])
            except (ValueError, TypeError):
                validation_errors = "Odgovor modela nije validan JSON"

            if parsed_result is not None:
                validation_errors = validate_similar_question_payload(
                    parsed_result, question_type, len(original_answers)
                )

        validation_passed = validation_errors is None and parsed_result is not None

        cursor.execute("""
            INSERT INTO ai_generation_runs
            (model_id, prompt_id, purpose, mode, source_question_id, params_used,
             raw_response, parsed_result, validation_passed, validation_errors,
             response_time_ms, tokens_used, retry_count)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0)
        """, (
            model_id,
            prompt_id,
            prompt_templates.PURPOSE_SIMILAR_QUESTION,
            None,
            question_id,
            json.dumps(options),
            result.get("raw_text"),
            json.dumps(parsed_result) if parsed_result is not None else None,
            1 if validation_passed else 0,
            validation_errors,
            result.get("response_time_ms"),
            result.get("tokens_used"),
        ))
        conn.commit()
        generation_run_id = cursor.lastrowid

        if not validation_passed:
            cursor.close()
            conn.close()
            return jsonify({
                "error": "AI generisanje nije dalo iskoristiv predlog",
                "details": validation_errors,
                "generation_run_id": generation_run_id,
            }), 422

        cursor.execute("""
            INSERT INTO ai_generated_artifacts
            (generation_run_id, artifact_type, status, original_text)
            VALUES (%s, %s, %s, %s)
        """, (
            generation_run_id,
            "question",
            "predlog",
            json.dumps(parsed_result),
        ))
        conn.commit()
        artifact_id = cursor.lastrowid

        cursor.close()
        conn.close()

        return jsonify({
            "message": "Predlog pitanja generisan",
            "generation_run_id": generation_run_id,
            "artifact_id": artifact_id,
            "question_type": question_type,
            "proposed_question": parsed_result,
        }), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/api/ai/artifacts") #lista AI predloga pitanja (podrazumevano status='predlog')
@role_required(["TEACHER", "ADMIN"])
def list_ai_artifacts():
    try:
        status_filter = request.args.get("status", ARTIFACT_STATUS_PENDING)
        user_id = get_jwt_identity()
        claims = get_jwt()
        role = claims.get("role")

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                a.id, a.artifact_type, a.status, a.original_text, a.created_at,
                r.id AS generation_run_id, r.source_question_id, r.purpose,
                m.provider, m.model_name,
                sq.subject_id, sq.area_id,
                s.name AS subject_name, ar.name AS area_name
            FROM ai_generated_artifacts a
            JOIN ai_generation_runs r ON r.id = a.generation_run_id
            JOIN ai_models m ON m.id = r.model_id
            LEFT JOIN exam_questions sq ON sq.id = r.source_question_id
            LEFT JOIN subjects s ON s.id = sq.subject_id
            LEFT JOIN areas ar ON ar.id = sq.area_id
            WHERE a.status = %s AND a.artifact_type = %s
            ORDER BY a.created_at DESC
        """, (status_filter, ARTIFACT_TYPE_QUESTION))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        if role == "TEACHER":
            allowed_subjects = set(get_user_subject_ids(int(user_id), "TEACHER"))
            rows = [row for row in rows if row["subject_id"] in allowed_subjects]

        for row in rows:
            parsed = json.loads(row["original_text"]) if row["original_text"] else None
            row["original_text"] = parsed
            row["question_type"] = prompt_templates.detect_question_type(
                (parsed or {}).get("answers") or []
            )
            hide_while_pending(row, BLIND_REVIEW_MODEL_FIELDS)

        return jsonify(rows), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/api/ai/artifacts/<int:artifact_id>") #detalj AI predloga + primenjivi kriterijumi rubrike
@role_required(["TEACHER", "ADMIN"])
def get_ai_artifact(artifact_id):
    try:
        user_id = get_jwt_identity()
        claims = get_jwt()
        role = claims.get("role")

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                a.id, a.artifact_type, a.status, a.original_text, a.edited_text,
                a.rejection_reason, a.reviewed_by, a.reviewed_at, a.created_question_id,
                a.created_at,
                r.id AS generation_run_id, r.source_question_id, r.purpose,
                m.provider, m.model_name,
                sq.subject_id, sq.area_id, sq.question_text AS source_question_text,
                sq.points AS source_points,
                s.name AS subject_name, ar.name AS area_name
            FROM ai_generated_artifacts a
            JOIN ai_generation_runs r ON r.id = a.generation_run_id
            JOIN ai_models m ON m.id = r.model_id
            LEFT JOIN exam_questions sq ON sq.id = r.source_question_id
            LEFT JOIN subjects s ON s.id = sq.subject_id
            LEFT JOIN areas ar ON ar.id = sq.area_id
            WHERE a.id = %s AND a.artifact_type = %s
        """, (artifact_id, ARTIFACT_TYPE_QUESTION))
        artifact = cursor.fetchone()

        if not artifact:
            cursor.close()
            conn.close()
            return jsonify({"error": "Artifact not found"}), 404

        if role == "TEACHER" and not user_has_subject(int(user_id), artifact["subject_id"], "TEACHER"):
            cursor.close()
            conn.close()
            return jsonify({"error": "Forbidden"}), 403

        cursor.execute("""
            SELECT answer_text, is_correct
            FROM exam_answers
            WHERE question_id = %s
            ORDER BY id ASC
        """, (artifact["source_question_id"],))
        artifact["source_answers"] = cursor.fetchall()

        parsed_original = json.loads(artifact["original_text"]) if artifact["original_text"] else None
        artifact["original_text"] = parsed_original
        artifact["edited_text"] = json.loads(artifact["edited_text"]) if artifact["edited_text"] else None

        question_type = prompt_templates.detect_question_type((parsed_original or {}).get("answers") or [])
        artifact["question_type"] = question_type
        artifact["rubric_criteria"] = get_applicable_rubric_definitions(cursor, question_type)
        hide_while_pending(artifact, BLIND_REVIEW_MODEL_FIELDS)

        cursor.close()
        conn.close()

        return jsonify(artifact), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/api/ai/artifacts/<int:artifact_id>/review") #upis ocena rubrike + odluke o AI predlogu
@role_required(["TEACHER", "ADMIN"])
def review_ai_artifact(artifact_id):
    try:
        data = request.get_json() or {}
        decision = data.get("decision")
        comment = (data.get("comment") or "").strip() or None
        scores = data.get("scores")
        edited_text = data.get("edited_text")
        rejection_reason = (data.get("rejection_reason") or "").strip() or None

        if decision not in ARTIFACT_DECISIONS:
            return jsonify({
                "error": "decision mora biti 'prihvaceno', 'prihvaceno_izmena' ili 'odbaceno'"
            }), 400

        if not isinstance(scores, list) or not scores:
            return jsonify({"error": "scores je obavezno i mora biti neprazan niz"}), 400

        if decision == ARTIFACT_STATUS_ACCEPTED_EDITED and not isinstance(edited_text, dict):
            return jsonify({"error": "edited_text je obavezan za odluku 'prihvaceno_izmena'"}), 400

        if decision == ARTIFACT_STATUS_REJECTED and not rejection_reason:
            return jsonify({"error": "rejection_reason je obavezan za odluku 'odbaceno'"}), 400

        user_id = get_jwt_identity()
        claims = get_jwt()
        role = claims.get("role")

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT a.id, a.status, a.original_text, a.generation_run_id,
                   r.source_question_id
            FROM ai_generated_artifacts a
            JOIN ai_generation_runs r ON r.id = a.generation_run_id
            WHERE a.id = %s AND a.artifact_type = %s
        """, (artifact_id, ARTIFACT_TYPE_QUESTION))
        artifact = cursor.fetchone()

        if not artifact:
            cursor.close()
            conn.close()
            return jsonify({"error": "Artifact not found"}), 404

        if artifact["status"] != ARTIFACT_STATUS_PENDING:
            cursor.close()
            conn.close()
            return jsonify({"error": "Predlog je već pregledan"}), 409

        cursor.execute("SELECT * FROM exam_questions WHERE id = %s", (artifact["source_question_id"],))
        source_question = cursor.fetchone()

        if role == "TEACHER":
            source_subject_id = source_question["subject_id"] if source_question else None
            if not user_has_subject(int(user_id), source_subject_id, "TEACHER"):
                cursor.close()
                conn.close()
                return jsonify({"error": "Forbidden"}), 403

        original_parsed = json.loads(artifact["original_text"])
        question_type = prompt_templates.detect_question_type(original_parsed.get("answers") or [])
        expected_answer_count = len(original_parsed.get("answers") or [])

        rubric_rows = get_applicable_rubric_definitions(cursor, question_type)
        rubric_by_id = {row["id"]: row for row in rubric_rows}

        score_by_id = {}
        for item in scores:
            if not isinstance(item, dict):
                cursor.close()
                conn.close()
                return jsonify({"error": "Svaki element scores mora biti objekat"}), 400

            rubric_id = item.get("rubric_definition_id")
            score_value = item.get("score")
            rubric_row = rubric_by_id.get(rubric_id)

            if rubric_row is None:
                cursor.close()
                conn.close()
                return jsonify({
                    "error": f"Nepoznat ili neprimenljiv rubric_definition_id: {rubric_id}"
                }), 400

            if not isinstance(score_value, int) or not (rubric_row["scale_min"] <= score_value <= rubric_row["scale_max"]):
                cursor.close()
                conn.close()
                return jsonify({
                    "error": (
                        f"Ocena za '{rubric_row['dimension_label']}' mora biti ceo broj "
                        f"u opsegu {rubric_row['scale_min']}-{rubric_row['scale_max']}"
                    )
                }), 400

            score_by_id[rubric_id] = score_value

        if set(score_by_id.keys()) != set(rubric_by_id.keys()):
            cursor.close()
            conn.close()
            return jsonify({
                "error": "scores mora sadržati tačno jednu ocenu za svaki primenljivi kriterijum rubrike"
            }), 400

        edited_parsed = None
        if decision == ARTIFACT_STATUS_ACCEPTED_EDITED:
            validation_error = validate_similar_question_payload(
                edited_text, question_type, expected_answer_count
            )
            if validation_error:
                cursor.close()
                conn.close()
                return jsonify({"error": f"edited_text nije validan: {validation_error}"}), 400
            edited_parsed = edited_text

        try:
            for rubric_id, score_value in score_by_id.items():
                cursor.execute("""
                    INSERT INTO ai_evaluations
                    (artifact_id, rubric_definition_id, evaluator_id, evaluator_role, score, comment)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (artifact_id, rubric_id, user_id, role, score_value, comment))

            final_payload = None
            if decision == ARTIFACT_STATUS_ACCEPTED:
                final_payload = original_parsed
            elif decision == ARTIFACT_STATUS_ACCEPTED_EDITED:
                final_payload = edited_parsed

            created_question_id = None
            if final_payload is not None:
                cursor.execute("""
                    INSERT INTO exam_questions (exam_id, subject_id, area_id, question_text, points, order_no)
                    VALUES (NULL, %s, %s, %s, %s, 0)
                """, (
                    source_question["subject_id"] if source_question else None,
                    source_question["area_id"] if source_question else None,
                    final_payload["question_text"],
                    source_question["points"] if source_question else 1,
                ))
                created_question_id = cursor.lastrowid

                if question_type == "mc":
                    for answer in final_payload["answers"]:
                        cursor.execute("""
                            INSERT INTO exam_answers (question_id, answer_text, is_correct)
                            VALUES (%s, %s, %s)
                        """, (
                            created_question_id,
                            answer["answer_text"],
                            1 if answer["is_correct"] else 0,
                        ))

            cursor.execute("""
                UPDATE ai_generated_artifacts
                SET status = %s,
                    edited_text = %s,
                    rejection_reason = %s,
                    reviewed_by = %s,
                    reviewed_at = NOW(),
                    created_question_id = %s
                WHERE id = %s
            """, (
                decision,
                json.dumps(edited_parsed) if edited_parsed is not None else None,
                rejection_reason if decision == ARTIFACT_STATUS_REJECTED else None,
                user_id,
                created_question_id,
                artifact_id,
            ))

            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
            conn.close()

        return jsonify({
            "message": "Pregled sačuvan",
            "artifact_id": artifact_id,
            "status": decision,
            "created_question_id": created_question_id,
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.put("/api/exams/<int:exam_id>/publish") #publishovanje testa
@role_required(["TEACHER", "ADMIN"])
def publish_exam(exam_id):
    try:
        user_id = get_jwt_identity()
        role = get_jwt().get("role")

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT id, subject_id, is_published
            FROM exams
            WHERE id = %s
        """, (exam_id,))
        exam = cursor.fetchone()

        if not exam:
            cursor.close()
            conn.close()
            return jsonify({"error": "Exam not found"}), 404

        # Teacher sme da objavi samo test za svoj predmet (isto kao delete_exam)
        if role == "TEACHER":
            if not user_has_subject(int(user_id), exam["subject_id"], "TEACHER"):
                cursor.close()
                conn.close()
                return jsonify({"error": "You can publish only exams for your assigned subjects"}), 403

        if exam["is_published"] == 1:
            cursor.close()
            conn.close()
            return jsonify({"message": "Exam published"}), 200

        # Ista pravila kao canPublish u ExamDetailsView.vue: bar jedno pitanje,
        # svako pitanje ima bar 2 odgovora i bar jedan tacan.
        cursor.execute("""
            SELECT
                eq.id,
                eq.question_text,
                COUNT(ea.id) AS answer_count,
                COALESCE(SUM(ea.is_correct = 1), 0) AS correct_count
            FROM exam_test_questions etq
            JOIN exam_questions eq ON eq.id = etq.question_id
            LEFT JOIN exam_answers ea ON ea.question_id = eq.id
            WHERE etq.exam_id = %s
            GROUP BY eq.id, eq.question_text, etq.order_no
            ORDER BY etq.order_no ASC, eq.id ASC
        """, (exam_id,))
        questions = cursor.fetchall()

        if not questions:
            cursor.close()
            conn.close()
            return jsonify({"error": "Exam has no questions"}), 400

        for question in questions:
            if question["answer_count"] < 2:
                cursor.close()
                conn.close()
                return jsonify({
                    "error": f"Question {question['id']} ('{question['question_text']}') must have at least 2 answers",
                    "question_id": question["id"],
                }), 400
            if question["correct_count"] < 1:
                cursor.close()
                conn.close()
                return jsonify({
                    "error": f"Question {question['id']} ('{question['question_text']}') has no correct answer",
                    "question_id": question["id"],
                }), 400

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
            SELECT id, subject_id
            FROM exams
            WHERE id = %s
        """, (exam_id,))

        exam = cursor.fetchone()

        if not exam:
            cursor.close()
            conn.close()
            return jsonify({"error": "Exam not found"}), 404

        # Teacher sme da briše samo testove za svoj predmet
        if role == "TEACHER":
            if not user_has_subject(int(user_id), exam["subject_id"], "TEACHER"):
                cursor.close()
                conn.close()
                return jsonify({"error": "You can delete only exams for your assigned subjects"}), 403

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

        # Uklanjamo vezu test<->pitanje (banka pitanja) - sadržaj pitanja
        # (exam_questions, exam_answers) ostaje netaknut, samo se briše
        # zapis da je ovo pitanje bilo deo OVOG testa.
        cursor.execute("""
            DELETE FROM exam_test_questions
            WHERE exam_id = %s
        """, (exam_id,))

        # Otkačinjemo pitanja od ovog testa umesto da ih brišemo - pitanje
        # može biti u banci ili u drugom testu preko exam_test_questions,
        # pa exam_questions/exam_answers ne smeju da nestanu.
        cursor.execute("""
            UPDATE exam_questions
            SET exam_id = NULL
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
    
MAX_TAB_WARNINGS = 1000


def _parse_int_id(value):
    """Pozitivan ceo broj iz JSON vrednosti (int ili string cifara), inace None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.isdigit():
        return int(value) if int(value) > 0 else None
    return None


@app.post("/api/exams/<int:exam_id>/submit") #student kad radi test, da ga submituje
@role_required(["STUDENT"])
def submit_exam(exam_id):
    student_id = get_jwt_identity()

    data = request.get_json(silent=True) or {}

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT id, subject_id, is_published, open_at, close_at, duration_minutes
            FROM exams
            WHERE id = %s
        """, (exam_id,))
        exam = cursor.fetchone()

        if not exam:
            return jsonify({"error": "Exam not found"}), 404

        if exam["is_published"] != 1:
            return jsonify({"error": "Exam is not published"}), 403

        if not user_has_subject(int(student_id), exam["subject_id"], "STUDENT"):
            return jsonify({"error": "You can access only exams for your subjects"}), 403

        # Vreme iz baze (NOW()), isto kao provera u get_exam_details.
        cursor.execute("SELECT NOW() AS now_time")
        now = cursor.fetchone()["now_time"]

        if exam["open_at"] and now < exam["open_at"]:
            return jsonify({"error": "Exam is not open yet"}), 403

        # Student koji je ucitao test pre close_at ima jos trajanje testa + 2 min za predaju.
        if exam["close_at"] and now > exam["close_at"] + timedelta(minutes=exam["duration_minutes"] + 2):
            return jsonify({"error": "Exam has expired"}), 403

        # Validacija ulaza pre bilo kakvog upisa
        if not isinstance(data, dict):
            return jsonify({"error": "Request body must be a JSON object"}), 400

        answers_raw = data.get("answers", {})
        if not isinstance(answers_raw, dict):
            return jsonify({"error": "answers must be an object {question_id: answer_id}"}), 400

        answers = {}
        for question_key, answer_value in answers_raw.items():
            question_id = _parse_int_id(question_key)
            answer_id = _parse_int_id(answer_value)
            if question_id is None or answer_id is None:
                return jsonify({"error": "answers keys and values must be integers"}), 400
            answers[question_id] = answer_id

        tab_warnings = data.get("tab_warnings", 0)
        if isinstance(tab_warnings, bool) or not isinstance(tab_warnings, int) or not 0 <= tab_warnings <= MAX_TAB_WARNINGS:
            return jsonify({"error": f"tab_warnings must be an integer between 0 and {MAX_TAB_WARNINGS}"}), 400

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
            return jsonify({"error": "You already took this exam"}), 400

        # Bodovanje pre upisa: pitanje van testa se preskace (kao ranije),
        # a answer_id koji ne postoji ili ne pripada pitanju odbija celu predaju.
        graded = []
        score = 0

        for question_id, answer_id in answers.items():
            cursor.execute("""
                SELECT eq.id, eq.points
                FROM exam_test_questions etq
                JOIN exam_questions eq ON eq.id = etq.question_id
                WHERE eq.id = %s AND etq.exam_id = %s
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

            if not answer:
                return jsonify({
                    "error": f"Answer {answer_id} does not belong to question {question_id}"
                }), 400

            is_correct = 0
            points_awarded = 0

            if answer["is_correct"] == 1:
                is_correct = 1
                points_awarded = question["points"]
                score += question["points"]

            graded.append((question_id, answer_id, is_correct, points_awarded))

        cursor.execute("""
            SELECT COALESCE(SUM(eq.points), 0) AS total
            FROM exam_test_questions etq
            JOIN exam_questions eq ON eq.id = etq.question_id
            WHERE etq.exam_id = %s
        """, (exam_id,))

        total_row = cursor.fetchone()
        total = total_row["total"] or 0

        # Ceo upis (pokusaj, odgovori, bodovi) u jednoj transakciji
        try:
            cursor.execute("""
                INSERT INTO exam_attempts
                (exam_id, student_id, status)
                VALUES (%s, %s, 'IN_PROGRESS')
            """, (exam_id, student_id))

            attempt_id = cursor.lastrowid

            for question_id, answer_id, is_correct, points_awarded in graded:
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
        except mysql.connector.IntegrityError as e:
            conn.rollback()
            # UNIQUE(exam_id, student_id): istovremena druga predaja je vec upisana
            if e.errno == 1062:
                return jsonify({"error": "You already took this exam"}), 409
            raise
        except Exception:
            conn.rollback()
            raise

        return jsonify({
            "attempt_id": attempt_id,
            "score": score,
            "total": total
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()

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
            cursor.execute("SELECT id, subject_id FROM exams WHERE id = %s", (exam_id,))
            exam_row = cursor.fetchone()

            if not exam_row or not user_has_subject(int(user_id), exam_row["subject_id"], "TEACHER"):
                cursor.close()
                conn.close()
                return jsonify({"error": "You can view results only for your assigned subjects"}), 403

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
            cursor.execute("SELECT id, subject_id FROM exams WHERE id = %s", (exam_id,))
            exam_row = cursor.fetchone()

            if not exam_row or not user_has_subject(int(user_id), exam_row["subject_id"], "TEACHER"):
                cursor.close()
                conn.close()
                return jsonify({"error": "You can export results only for your assigned subjects"}), 403

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


@app.get("/api/my-results/<int:attempt_id>") #detalj jednog zavrsenog pokusaja za studenta, po pitanjima
@role_required(["STUDENT"])
def get_my_result_detail(attempt_id):
    try:
        user_id = int(get_jwt_identity())

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT ea.id, ea.exam_id, ea.student_id, ea.score, ea.total_points AS total,
                   ea.submitted_at, ea.status, e.title
            FROM exam_attempts ea
            JOIN exams e ON e.id = ea.exam_id
            WHERE ea.id = %s
        """, (attempt_id,))
        attempt = cursor.fetchone()

        if not attempt:
            cursor.close()
            conn.close()
            return jsonify({"error": "Attempt not found"}), 404

        if attempt["student_id"] != user_id or attempt["status"] != "COMPLETED":
            cursor.close()
            conn.close()
            return jsonify({"error": "Forbidden"}), 403

        # Pitanja iz testa (exam_test_questions); LEFT JOIN da se vide i pitanja
        # na koja student nije odgovorio.
        cursor.execute("""
            SELECT etq.question_id, etq.order_no, eq.question_text, eq.points,
                   eaa.answer_id, chosen.answer_text AS student_answer_text,
                   eaa.is_correct, eaa.points_awarded
            FROM exam_test_questions etq
            JOIN exam_questions eq ON eq.id = etq.question_id
            LEFT JOIN exam_attempt_answers eaa
                   ON eaa.attempt_id = %s AND eaa.question_id = etq.question_id
            LEFT JOIN exam_answers chosen ON chosen.id = eaa.answer_id
            WHERE etq.exam_id = %s
            ORDER BY etq.order_no ASC, etq.question_id ASC
        """, (attempt_id, attempt["exam_id"]))
        questions = cursor.fetchall()

        # Poslednje ODOBRENO objasnjenje po pitanju - isti izbor (reviewed_at,
        # pa id) kao GET /api/questions/<id>/explanation, da explanation_mode
        # vodi na isti artefakt.
        explanation_by_question = {}
        question_ids = [q["question_id"] for q in questions]
        if question_ids:
            placeholders = ",".join(["%s"] * len(question_ids))
            cursor.execute(f"""
                SELECT a.id AS artifact_id, r.mode, r.source_question_id,
                       EXISTS (
                           SELECT 1 FROM ai_evaluations ev
                           WHERE ev.artifact_id = a.id AND ev.evaluator_id = %s
                             AND ev.evaluator_role = 'STUDENT'
                       ) AS already_rated
                FROM ai_generated_artifacts a
                JOIN ai_generation_runs r ON r.id = a.generation_run_id
                WHERE r.source_question_id IN ({placeholders})
                  AND a.artifact_type = 'explanation'
                  AND a.status IN ('prihvaceno', 'prihvaceno_izmena')
                ORDER BY a.reviewed_at DESC, a.id DESC
            """, (user_id, *question_ids))
            for row in cursor.fetchall():
                explanation_by_question.setdefault(row["source_question_id"], row)

        cursor.close()
        conn.close()

        for q in questions:
            q["answered"] = q["answer_id"] is not None
            q["is_correct"] = bool(q["is_correct"]) if q["answered"] else None
            explanation = explanation_by_question.get(q["question_id"])
            q["explanation_artifact_id"] = explanation["artifact_id"] if explanation else None
            q["explanation_mode"] = explanation["mode"] if explanation else None
            q["already_rated"] = bool(explanation["already_rated"]) if explanation else False

        del attempt["student_id"]
        return jsonify({"attempt": attempt, "questions": questions}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
# =========================
# 9) Run
# =========================


# =====================================================================
# AI generisanje objasnjenja/resenja (Andrejev modul).
# Isti obrazac kao Andjine funkcije za generisanje pitanja (ensure_ai_model /
# ai_generation_runs / ai_generated_artifacts) - NAMERNO odvojena kopija u
# ovoj fazi (svako drzi svoj kod dok se grane ne spoje, Plan integracije
# odeljak 3.4). Pri spajanju grana ensure_ai_model je objedinjen - koristi se
# jedna verzija iz sekcije Helpers. EXPLANATION_DEFAULT_MODELS postaje visak
# u odnosu na Andjin ai_provider.DEFAULT_MODELS
# (isti sadrzaj) - koristiti samo taj jedan izvor istine.
# =====================================================================

EXPLANATION_DEFAULT_MODELS = {
    "groq": "openai/gpt-oss-20b",
    "gemini": "gemini-3.6-flash",
    "mistral": "mistral-small-latest",
    "openrouter": "nvidia/nemotron-3-super-120b-a12b:free",
}


def resolve_explanation_source(cursor, question, mode):
    """Odredjuje tekst zadatka i poznato resenje koje model dobija. Samo cita.
    MC vs otvoreno pitanje se odredjuje isto kao u generate_similar_question
    (prompt_templates.detect_question_type nad exam_answers).

    Vraca {"question_text", "known_solution", "solution_source"} ili
    {"error": poruka} (ruta vraca 400, pre AI poziva).
    - mode_b: MC pitanja nisu podrzana (rezim B trazi Python program).
    - mode_a: reference_solution ima prioritet (ponasanje za programska
      pitanja se ne menja); inace, za MC pitanje sa tacno jednim tacnim
      odgovorom, poznato resenje je taj odgovor, a ponudjeni odgovori se
      dodaju tekstu zadatka.
    """
    cursor.execute(
        "SELECT answer_text, is_correct FROM exam_answers WHERE question_id = %s ORDER BY id ASC",
        (question["id"],),
    )
    answers = cursor.fetchall()
    question_type = prompt_templates.detect_question_type(answers)

    if mode == "mode_b":
        if question_type == "mc":
            return {"error": "Rezim B nije podrzan za MC pitanja"}
        return {"question_text": question["question_text"], "known_solution": None, "solution_source": None}

    if question.get("reference_solution"):
        return {
            "question_text": question["question_text"],
            "known_solution": question["reference_solution"],
            "solution_source": "reference_solution",
        }

    if question_type != "mc":
        return {"error": "Ovo pitanje nema reference_solution - rezim A zahteva poznato tacno resenje"}

    correct = [a for a in answers if a["is_correct"] == 1]
    if not correct:
        return {"error": "MC pitanje nema oznacen tacan odgovor - rezim A zahteva poznato tacno resenje"}
    if len(correct) > 1:
        return {"error": "MC pitanje ima vise oznacenih tacnih odgovora - rezim A zahteva jedno poznato tacno resenje"}

    options_text = "\n".join(f"- {a['answer_text']}" for a in answers)
    return {
        "question_text": f"{question['question_text']}\n\nPonuđeni odgovori:\n{options_text}",
        "known_solution": f"Tačan odgovor: {correct[0]['answer_text']}",
        "solution_source": "mc_correct_answer",
    }


def validate_explanation_payload(parsed, mode):
    """Vraca None ako je JSON iz AI odgovora ispravan za dati rezim, inace
    string sa opisom greske."""
    if not isinstance(parsed, dict):
        return "Odgovor modela mora biti JSON objekat"

    explanation = parsed.get("explanation")
    if not isinstance(explanation, str) or not explanation.strip():
        return "Nedostaje ili je prazno explanation"

    if mode == "mode_b":
        solution = parsed.get("solution")
        if not isinstance(solution, str) or not solution.strip():
            return "Nedostaje ili je prazno solution (obavezno za mode_b)"
    else:  # mode_a
        if "solution" in parsed:
            return "mode_a ne sme da vraca solution (resenje je vec poznato)"

    return None


@app.post("/api/questions/<int:question_id>/generate-explanation")  # AI generisanje objasnjenja/resenja (rezim A/B)
@role_required(["TEACHER", "ADMIN"])
def generate_explanation(question_id):
    try:
        mode = request.args.get("mode")
        if mode not in ("mode_a", "mode_b"):
            return jsonify({"error": "mode mora biti 'mode_a' ili 'mode_b'"}), 400

        provider = request.args.get("provider", "groq")
        if provider not in EXPLANATION_DEFAULT_MODELS:
            return jsonify({"error": f"Nepoznat provider: {provider}"}), 400

        evaluation_batch_id = request.args.get("evaluation_batch_id", type=int)

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if evaluation_batch_id is not None:
            cursor.execute("SELECT id FROM evaluation_batches WHERE id = %s", (evaluation_batch_id,))
            if not cursor.fetchone():
                cursor.close()
                conn.close()
                return jsonify({"error": f"evaluation_batch_id {evaluation_batch_id} ne postoji"}), 400

        cursor.execute("SELECT * FROM exam_questions WHERE id = %s", (question_id,))
        question = cursor.fetchone()

        if not question:
            cursor.close()
            conn.close()
            return jsonify({"error": "Question not found"}), 404

        source = resolve_explanation_source(cursor, question, mode)
        if "error" in source:
            cursor.close()
            conn.close()
            return jsonify({"error": source["error"]}), 400

        subject_name = None
        if question.get("subject_id"):
            cursor.execute("SELECT name FROM subjects WHERE id = %s", (question["subject_id"],))
            subject_row = cursor.fetchone()
            if subject_row:
                subject_name = subject_row["name"]

        area_name = None
        if question.get("area_id"):
            cursor.execute("SELECT name FROM areas WHERE id = %s", (question["area_id"],))
            area_row = cursor.fetchone()
            if area_row:
                area_name = area_row["name"]

        prompt_id, template_text = explanation_prompts.ensure_prompt_synced(conn, mode)
        prompt_text = explanation_prompts.build_explanation_prompt(
            template_text,
            question_text=source["question_text"],
            subject_name=subject_name,
            area_name=area_name,
            correct_solution=source["known_solution"],
        )

        model_name = EXPLANATION_DEFAULT_MODELS[provider]
        model_id = ensure_ai_model(conn, provider=provider, model_name=model_name)

        options = {"temperature": 0.7, "model": model_name}
        result = ai_provider.generate(prompt_text, provider=provider, options=options)

        parsed_result = None
        validation_errors = None

        if not result.get("success"):
            validation_errors = result.get("error", "Nepoznata greska pri pozivu AI modela")
        else:
            try:
                parsed_result = json.loads(result["raw_text"])
            except (ValueError, TypeError):
                validation_errors = "Odgovor modela nije validan JSON"

            if parsed_result is not None:
                validation_errors = validate_explanation_payload(parsed_result, mode)

        validation_passed = validation_errors is None and parsed_result is not None

        accuracy_check_passed = None
        accuracy_check_details = None

        if validation_passed and mode == "mode_b":
            cursor.execute(
                """
                SELECT order_no, input_data, expected_output
                FROM exam_question_test_cases
                WHERE question_id = %s
                ORDER BY order_no ASC
                """,
                (question_id,),
            )
            test_cases = cursor.fetchall()

            if not test_cases:
                accuracy_check_details = "Nema definisanih test primera za ovo pitanje - mehanicka provera nije moguca"
            else:
                check_result = code_executor.run_against_test_cases(
                    parsed_result["solution"], test_cases
                )
                accuracy_check_passed = 1 if check_result["all_passed"] else 0
                accuracy_check_details = json.dumps(check_result["results"], ensure_ascii=False)

        cursor.execute(
            """
            INSERT INTO ai_generation_runs
            (model_id, prompt_id, purpose, mode, source_question_id, params_used,
             raw_response, parsed_result, validation_passed, validation_errors,
             accuracy_check_passed, accuracy_check_details, response_time_ms,
             tokens_used, retry_count, evaluation_batch_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, %s)
            """,
            (
                model_id,
                prompt_id,
                explanation_prompts.PURPOSE_EXPLANATION,
                mode,
                question_id,
                json.dumps({**options, "solution_source": source["solution_source"]}),
                result.get("raw_text"),
                json.dumps(parsed_result, ensure_ascii=False) if parsed_result is not None else None,
                1 if validation_passed else 0,
                validation_errors,
                accuracy_check_passed,
                accuracy_check_details,
                result.get("response_time_ms"),
                result.get("tokens_used"),
                evaluation_batch_id,
            ),
        )
        conn.commit()
        generation_run_id = cursor.lastrowid

        if not validation_passed:
            cursor.close()
            conn.close()
            return jsonify({
                "error": "AI generisanje nije dalo iskoristiv predlog",
                "details": validation_errors,
                "generation_run_id": generation_run_id,
            }), 422

        cursor.execute(
            """
            INSERT INTO ai_generated_artifacts
            (generation_run_id, artifact_type, status, original_text)
            VALUES (%s, %s, %s, %s)
            """,
            (
                generation_run_id,
                "explanation",
                "predlog",
                json.dumps(parsed_result, ensure_ascii=False),
            ),
        )
        conn.commit()
        artifact_id = cursor.lastrowid

        cursor.close()
        conn.close()

        return jsonify({
            "message": "Predlog objasnjenja generisan",
            "generation_run_id": generation_run_id,
            "artifact_id": artifact_id,
            "mode": mode,
            "accuracy_check_passed": accuracy_check_passed,
            "proposed_result": parsed_result,
        }), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =====================================================================
# Nastavnicki pregled predloga objasnjenja/resenja (Andrejev modul).
# Poslovna logika je u explanation_review.py (testirana nezavisno od
# Flask sloja) - ove rute su tanak HTTP omotac oko nje.
# =====================================================================

@app.get("/api/ai-artifacts/explanation")  # lista predloga objasnjenja za pregled (podrazumevano status=predlog)
@role_required(["TEACHER", "ADMIN"])
def list_explanation_artifacts():
    status = request.args.get("status", "predlog")
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT a.id, a.status, a.created_at, a.reviewed_at,
               r.mode, r.source_question_id, r.accuracy_check_passed,
               q.question_text
        FROM ai_generated_artifacts a
        JOIN ai_generation_runs r ON r.id = a.generation_run_id
        LEFT JOIN exam_questions q ON q.id = r.source_question_id
        WHERE a.artifact_type = 'explanation' AND a.status = %s
        ORDER BY a.created_at ASC
        """,
        (status,),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify(rows), 200


@app.get("/api/ai-artifacts/explanation/<int:artifact_id>")  # detalji jednog predloga + TEACHER rubrika za formu ocenjivanja
@role_required(["TEACHER", "ADMIN"])
def get_explanation_artifact(artifact_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT a.id, a.status, a.original_text, a.edited_text,
               a.rejection_reason, a.reviewed_by, a.reviewed_at, a.created_at,
               r.mode, r.source_question_id, r.accuracy_check_passed,
               r.accuracy_check_details, q.question_text
        FROM ai_generated_artifacts a
        JOIN ai_generation_runs r ON r.id = a.generation_run_id
        LEFT JOIN exam_questions q ON q.id = r.source_question_id
        WHERE a.id = %s AND a.artifact_type = 'explanation'
        """,
        (artifact_id,),
    )
    artifact = cursor.fetchone()
    if not artifact:
        cursor.close()
        conn.close()
        return jsonify({"error": "Artifact not found"}), 404

    cursor.execute(
        """
        SELECT dimension_key, dimension_label, scale_min, scale_max
        FROM ai_rubric_definitions
        WHERE applies_to = 'explanation' AND evaluator_role = 'TEACHER'
        """
    )
    rubric_definitions = cursor.fetchall()
    cursor.close()
    conn.close()

    return jsonify({
        "artifact": artifact,
        "rubric_definitions": rubric_definitions,
    }), 200


@app.post("/api/ai-artifacts/explanation/<int:artifact_id>/review")  # nastavnicka odluka: approve/edit/reject + rubrika ocene
@role_required(["TEACHER", "ADMIN"])
def review_explanation_artifact_route(artifact_id):
    try:
        data = request.get_json(silent=True) or {}
        action = data.get("action")
        edited_text = data.get("edited_text")
        rejection_reason = data.get("rejection_reason")
        scores = data.get("scores")

        # Isti obrazac za id ulogovanog korisnika kao ostale @role_required
        # rute u app.py (npr. create_lesson, generate_explanation).
        reviewer_id = get_jwt_identity()

        conn = get_db_connection()
        try:
            result = explanation_review.review_explanation_artifact(
                conn,
                artifact_id=artifact_id,
                reviewer_id=reviewer_id,
                action=action,
                edited_text=edited_text,
                rejection_reason=rejection_reason,
                scores=scores,
            )
        finally:
            conn.close()

        return jsonify({
            "message": "Pregled sacuvan",
            **result,
        }), 200

    except explanation_review.ArtifactNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except explanation_review.ArtifactStateError as e:
        return jsonify({"error": str(e)}), 409
    except explanation_review.ReviewValidationError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =====================================================================
# Studentsko ocenjivanje korisnosti odobrenih predloga (Andrejev modul).
# Poslovna logika je u explanation_rating.py (testirana nezavisno od
# Flask sloja) - ove rute su tanak HTTP omotac oko nje. Isti obrazac za
# identitet korisnika (get_jwt_identity()) kao u vec ugradjenoj
# review_explanation_artifact_route - vec potvrdjen u prethodnom koraku,
# nema potrebe za ponovnom proverom.
# =====================================================================

def student_completed_question(student_id, question_id):
    """True ako student ima zavrsen (COMPLETED) pokusaj testa koji sadrzi dato
    pitanje (preko exam_test_questions). Objasnjenje MC pitanja otkriva tacan
    odgovor, pa ga student sme da vidi/oceni tek posle svog zavrsenog pokusaja."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT 1
            FROM exam_attempts ea
            JOIN exam_test_questions etq ON etq.exam_id = ea.exam_id
            WHERE ea.student_id = %s
              AND ea.status = 'COMPLETED'
              AND etq.question_id = %s
            LIMIT 1
            """,
            (student_id, question_id),
        )
        return cur.fetchone() is not None
    finally:
        cur.close()
        conn.close()


@app.get("/api/questions/<int:question_id>/explanation")  # odobren/izmenjen sadrzaj objasnjenja za dati rezim - ono sto student stvarno vidi
@role_required(["STUDENT", "TEACHER", "ADMIN"])
def get_question_explanation(question_id):
    mode = request.args.get("mode")
    if mode not in ("mode_a", "mode_b"):
        return jsonify({"error": "mode mora biti 'mode_a' ili 'mode_b'"}), 400

    if get_jwt().get("role") == "STUDENT" and not student_completed_question(int(get_jwt_identity()), question_id):
        return jsonify({"error": "Forbidden"}), 403

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT a.id AS artifact_id, a.status, a.original_text, a.edited_text
        FROM ai_generated_artifacts a
        JOIN ai_generation_runs r ON r.id = a.generation_run_id
        WHERE r.source_question_id = %s
          AND r.mode = %s
          AND a.artifact_type = 'explanation'
          AND a.status IN ('prihvaceno', 'prihvaceno_izmena')
        ORDER BY a.reviewed_at DESC, a.id DESC
        LIMIT 1
        """,
        (question_id, mode),
    )
    artifact = cursor.fetchone()
    if not artifact:
        cursor.close()
        conn.close()
        return jsonify({
            "error": "Nema prihvacenog predloga objasnjenja za ovo pitanje/rezim"
        }), 404

    final_text = explanation_rating.get_final_text(artifact)
    content = json.loads(final_text)

    cursor.execute(
        """
        SELECT dimension_key, dimension_label, scale_min, scale_max
        FROM ai_rubric_definitions
        WHERE applies_to = 'explanation' AND evaluator_role = 'STUDENT'
        """
    )
    rubric_definitions = cursor.fetchall()
    cursor.close()
    conn.close()

    return jsonify({
        "artifact_id": artifact["artifact_id"],
        "mode": mode,
        "content": content,
        "rubric_definitions": rubric_definitions,
    }), 200


@app.post("/api/ai-artifacts/explanation/<int:artifact_id>/rate")  # studentska ocena korisnosti (STUDENT rubrika)
@role_required(["STUDENT"])
def rate_explanation_artifact_route(artifact_id):
    try:
        data = request.get_json(silent=True) or {}
        scores = data.get("scores")
        student_id = get_jwt_identity()

        conn = get_db_connection()
        try:
            # Pitanje artefakta; ako artefakt ne postoji, submit_student_rating
            # ispod vraca 404 kao i ranije.
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT r.source_question_id
                FROM ai_generated_artifacts a
                JOIN ai_generation_runs r ON r.id = a.generation_run_id
                WHERE a.id = %s
                """,
                (artifact_id,),
            )
            row = cursor.fetchone()
            cursor.close()
            if row and not student_completed_question(int(student_id), row["source_question_id"]):
                return jsonify({"error": "Forbidden"}), 403

            result = explanation_rating.submit_student_rating(
                conn,
                artifact_id=artifact_id,
                student_id=student_id,
                scores=scores,
            )
        finally:
            conn.close()

        return jsonify({
            "message": "Ocena sacuvana",
            **result,
        }), 200

    except explanation_rating.ArtifactNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except (explanation_rating.ArtifactNotApprovedError, explanation_rating.AlreadyRatedError) as e:
        return jsonify({"error": str(e)}), 409
    except explanation_rating.RatingValidationError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =====================================================================
# Evaluacione serije (evaluation_batches) - Andrejev modul.
# Omogucava obelezavanje generisanja kao dela formalnog, finalnog kruga
# evaluacije (is_final=1), odvojeno od dev/tuning poziva (evaluation_batch_id
# ostaje NULL). Vodic za rad sa Claude-om eksplicitno trazi ovu razdvojenost
# radi naucne validnosti poredjenja modela.
# =====================================================================

@app.post("/api/evaluation-batches")  # napravi novu evaluacionu seriju (npr. finalni krug poredjenja modela)
@role_required(["ADMIN"])
def create_evaluation_batch():
    try:
        data = request.get_json(silent=True) or {}
        name = data.get("name")
        if not isinstance(name, str) or not name.strip():
            return jsonify({"error": "name je obavezan"}), 400

        description = data.get("description")
        is_final = 1 if data.get("is_final") else 0

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO evaluation_batches (name, description, is_final) VALUES (%s, %s, %s)",
            (name.strip(), description, is_final),
        )
        conn.commit()
        batch_id = cursor.lastrowid
        cursor.close()
        conn.close()

        return jsonify({
            "id": batch_id,
            "name": name.strip(),
            "description": description,
            "is_final": bool(is_final),
        }), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/api/evaluation-batches")  # lista svih evaluacionih serija
@role_required(["ADMIN", "TEACHER"])
def list_evaluation_batches():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT id, name, description, is_final, created_at FROM evaluation_batches ORDER BY id DESC"
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify(rows), 200


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)

