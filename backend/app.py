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
from datetime import date, timedelta
import hashlib
import hmac
import csv
from io import StringIO
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
import question_validation
import edit_distance
import question_similarity
import generation_failures
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
# Posredni signali: redosled generisanja moze da oda model (npr. ako su
# modeli pokretani jedan za drugim), pa se i oni kriju dok je 'predlog'.
BLIND_REVIEW_ORDER_FIELDS = ("created_at", "generation_run_id")
# Težina/Blumov nivo koje je model predložio (v3): nastavnik bira svoje
# NE videvši modelove, pa se i one kriju dok je 'predlog'.
BLIND_REVIEW_LABEL_FIELDS = ("model_difficulty", "model_bloom_level")


def blind_review_reveal_requested():
    """ADMIN moze da trazi ?reveal=1 da vidi skrivena polja; TEACHER ne."""
    return get_jwt().get("role") == "ADMIN" and request.args.get("reveal") == "1"


def blind_review_order(rows, user_id):
    """Slucajan redosled liste predloga, stabilan za istog korisnika u toku dana.
    Kljuc je hash(user_id, datum, id), pa novi ili odluceni predlog ne
    premesta ostale; filter po statusu se radi pre ovoga, u SQL-u."""
    seed = f"{user_id}:{date.today().isoformat()}"
    return sorted(
        rows,
        key=lambda row: hashlib.sha256(f"{seed}:{row['id']}".encode()).hexdigest(),
    )


# Kolone iz db/migration_question_labels.sql. Kod radi i pre migracije:
# modelove oznake su ionako u original_text, a kolone se pišu samo ako postoje.
QUESTION_LABEL_COLUMNS = {
    "ai_generated_artifacts": ("model_difficulty", "model_bloom_level",
                               "reviewed_difficulty", "reviewed_bloom_level"),
    "exam_questions": ("difficulty", "bloom_level"),
}


def table_columns_exist(cursor, table, columns):
    """True kad tabela ima sve navedene kolone (provera pri svakom pozivu, bez keša,
    pa posle ručno pokrenute migracije nije potreban restart)."""
    placeholders = ", ".join(["%s"] * len(columns))
    cursor.execute(
        f"""SELECT COUNT(*) AS n FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME IN ({placeholders})""",
        (table, *columns),
    )
    row = cursor.fetchone()
    return (row["n"] if isinstance(row, dict) else row[0]) == len(columns)


# db/migration_failure_type_retry.sql (tačka I)
FAILURE_COLUMNS = ("failure_type", "first_attempt_passed", "format_retries")


# db/migration_edit_distance.sql (tačka B)
EDIT_DISTANCE_COLUMNS = ("edit_distance", "edit_distance_norm")


# db/migration_duplicate_check.sql (tačka C)
DUPLICATE_COLUMNS = ("max_similarity", "similar_source", "similar_question_id",
                     "similar_artifact_id", "reviewed_duplicate")


def duplicate_check_enabled(cursor):
    return table_columns_exist(cursor, "ai_generated_artifacts", DUPLICATE_COLUMNS)


def _question_payloads(cursor, question_ids):
    """{id: {'question_text', 'answers'}} za pitanja iz banke."""
    if not question_ids:
        return {}
    placeholders = ", ".join(["%s"] * len(question_ids))
    cursor.execute(f"SELECT id, question_text FROM exam_questions WHERE id IN ({placeholders})", tuple(question_ids))
    payloads = {row["id"]: {"question_text": row["question_text"], "answers": []} for row in cursor.fetchall()}
    cursor.execute(
        f"SELECT question_id, answer_text, is_correct FROM exam_answers WHERE question_id IN ({placeholders}) ORDER BY id",
        tuple(question_ids),
    )
    for row in cursor.fetchall():
        payloads[row["question_id"]]["answers"].append(
            {"answer_text": row["answer_text"], "is_correct": bool(row["is_correct"])}
        )
    return payloads


def compute_artifact_similarity(cursor, artifact_id):
    """Najsličnije pitanje/predlog za AI predlog pitanja (question_similarity).
    Poredi se sa: izvornim pitanjem, pitanjima iz banke istog predmeta (bez
    pitanja nastalih iz ovog i kasnijih predloga) i ranijim predlozima istog
    predmeta - pa ponovni izračun daje isto što i izračun pri generisanju.
    Vraća {'score', 'source', 'id'} ili None."""
    cursor.execute("""
        SELECT a.original_text, a.generation_run_id, r.source_question_id, r.params_used, sq.subject_id
        FROM ai_generated_artifacts a
        JOIN ai_generation_runs r ON r.id = a.generation_run_id
        LEFT JOIN exam_questions sq ON sq.id = r.source_question_id
        WHERE a.id = %s AND a.artifact_type = %s
    """, (artifact_id, ARTIFACT_TYPE_QUESTION))
    artifact = cursor.fetchone()
    if not artifact or not artifact["original_text"]:
        return None
    candidate = json.loads(artifact["original_text"])
    subject_id = artifact["subject_id"]
    # Izvorna pitanja: jedno pitanje, ili ceo ulazni skup kod generisanja iz skupa (tačka J)
    source_ids = input_question_ids_of_run(artifact["params_used"]) or (
        [artifact["source_question_id"]] if artifact["source_question_id"] else [])

    bank_ids = []
    earlier = []
    if subject_id is not None:
        cursor.execute("""
            SELECT q.id FROM exam_questions q
            WHERE q.subject_id = %s
              AND q.id NOT IN (
                  SELECT a.created_question_id FROM ai_generated_artifacts a
                  WHERE a.id >= %s AND a.created_question_id IS NOT NULL)
        """, (subject_id, artifact_id))
        bank_ids = [row["id"] for row in cursor.fetchall() if row["id"] not in source_ids]
        # raniji predlozi istog predmeta + ostali predlozi istog run-a (skup daje više predloga)
        cursor.execute("""
            SELECT a.id, a.original_text
            FROM ai_generated_artifacts a
            JOIN ai_generation_runs r ON r.id = a.generation_run_id
            JOIN exam_questions sq ON sq.id = r.source_question_id
            WHERE a.artifact_type = %s AND a.id <> %s AND (a.id < %s OR a.generation_run_id = %s)
              AND sq.subject_id = %s AND a.original_text IS NOT NULL
        """, (ARTIFACT_TYPE_QUESTION, artifact_id, artifact_id, artifact["generation_run_id"], subject_id))
        earlier = [("artifact", row["id"], json.loads(row["original_text"])) for row in cursor.fetchall()]

    payloads = _question_payloads(cursor, source_ids + bank_ids)
    pool = [("source", qid, payloads[qid]) for qid in source_ids if qid in payloads]
    pool += [("bank", qid, payloads[qid]) for qid in bank_ids if qid in payloads]
    pool += earlier
    return question_similarity.find_most_similar(candidate, pool)


def input_question_ids_of_run(params_used):
    """Ulazni skup pitanja iz params_used run-a generisanja iz skupa; [] za jedno pitanje."""
    try:
        params = json.loads(params_used) if isinstance(params_used, str) else (params_used or {})
    except ValueError:
        return []
    ids = params.get("input_question_ids") if isinstance(params, dict) else None
    return [int(i) for i in ids] if isinstance(ids, list) else []


def load_input_questions(cursor, artifact_id):
    """[{id, question_text}] ulaznog skupa za predlog iz skupa; [] za jedno pitanje."""
    cursor.execute("""
        SELECT r.params_used FROM ai_generated_artifacts a
        JOIN ai_generation_runs r ON r.id = a.generation_run_id WHERE a.id = %s
    """, (artifact_id,))
    row = cursor.fetchone()
    ids = input_question_ids_of_run(row["params_used"]) if row else []
    if not ids:
        return []
    placeholders = ", ".join(["%s"] * len(ids))
    cursor.execute(f"SELECT id, question_text FROM exam_questions WHERE id IN ({placeholders})", tuple(ids))
    texts = {r["id"]: r["question_text"] for r in cursor.fetchall()}
    return [{"id": qid, "question_text": texts.get(qid)} for qid in ids]


def store_artifact_similarity(cursor, artifact_id):
    """Izračuna i upiše max_similarity / similar_* (reviewed_duplicate se ne dira)."""
    best = compute_artifact_similarity(cursor, artifact_id)
    cursor.execute("""
        UPDATE ai_generated_artifacts
        SET max_similarity = %s, similar_source = %s, similar_question_id = %s, similar_artifact_id = %s
        WHERE id = %s
    """, (
        best["score"] if best else None,
        best["source"] if best else None,
        best["id"] if best and best["source"] in ("source", "bank") else None,
        best["id"] if best and best["source"] == "artifact" else None,
        artifact_id,
    ))
    return best


def load_duplicate_info(cursor, artifact_ids, with_text=False):
    """{artifact_id: podaci o mogućem duplikatu}; prazno ako migracija nije pokrenuta."""
    if not artifact_ids or not duplicate_check_enabled(cursor):
        return {}
    placeholders = ", ".join(["%s"] * len(artifact_ids))
    cursor.execute(f"""
        SELECT a.id, a.max_similarity, a.similar_source, a.similar_question_id, a.reviewed_duplicate,
               sq.question_text AS similar_bank_text, sa.original_text AS similar_artifact_text
        FROM ai_generated_artifacts a
        LEFT JOIN exam_questions sq ON sq.id = a.similar_question_id
        LEFT JOIN ai_generated_artifacts sa ON sa.id = a.similar_artifact_id
        WHERE a.id IN ({placeholders})
    """, tuple(artifact_ids))
    info = {}
    for row in cursor.fetchall():
        item = {"reviewed_duplicate": row["reviewed_duplicate"]}
        if row["max_similarity"] is not None:
            item.update({
                "max_similarity": float(row["max_similarity"]),
                "possible_duplicate": question_similarity.is_possible_duplicate(row["max_similarity"]),
                "similar_source": row["similar_source"],
            })
            # id samo za pitanje iz banke / izvorno; za drugi AI predlog samo tekst
            if row["similar_source"] in ("source", "bank"):
                item["similar_question_id"] = row["similar_question_id"]
            if with_text:
                text = row["similar_bank_text"]
                if row["similar_source"] == "artifact" and row["similar_artifact_text"]:
                    text = (json.loads(row["similar_artifact_text"]) or {}).get("question_text")
                item["similar_question_text"] = text
        info[row["id"]] = item
    return info


def attach_duplicate_info(row, info):
    """Dodaje podatke o duplikatu u odgovor rute samo ako postoje (v2/pre migracije odgovor ostaje isti)."""
    if not info:
        return
    for key, value in info.items():
        if key == "reviewed_duplicate":
            if value is not None:
                row[key] = bool(value)
        elif value is not None or key == "similar_question_text":
            row[key] = value


def question_labels_enabled(cursor):
    """True kad postoje sve kolone iz db/migration_question_labels.sql.
    Proverava se pri svakom pozivu (bez keša), pa posle migracije nije
    potreban restart."""
    conditions = " OR ".join(
        f"(TABLE_NAME = %s AND COLUMN_NAME IN ({', '.join(['%s'] * len(cols))}))"
        for cols in QUESTION_LABEL_COLUMNS.values()
    )
    params = [value for table, cols in QUESTION_LABEL_COLUMNS.items() for value in (table, *cols)]
    cursor.execute(
        f"SELECT COUNT(*) AS n FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND ({conditions})",
        params,
    )
    row = cursor.fetchone()
    count = row["n"] if isinstance(row, dict) else row[0]
    return count == sum(len(cols) for cols in QUESTION_LABEL_COLUMNS.values())


def move_model_labels(row, parsed):
    """v3 predlog: difficulty/bloom_level iz odgovora modela premešta iz
    original_text u model_difficulty/model_bloom_level (koja se kriju dok je
    'predlog') i označava da pregled traži nastavnikove oznake. v2 predlog
    (bez oznaka) ostaje nepromenjen."""
    if not isinstance(parsed, dict) or not any(k in parsed for k in question_validation.LABEL_FIELDS):
        return
    row["model_difficulty"] = parsed.pop("difficulty", None)
    row["model_bloom_level"] = parsed.pop("bloom_level", None)
    row["labels_required"] = True


# --- Drugi ocenjivač i slepo ocenjivanje u seriji (tačka E, db/migration_second_rater.sql) ---

def batch_review_context(cursor, artifact_ids, user_id):
    """{artifact_id: {'batch_id', 'batch_open', 'user_rated'}}.
    Serija je otvorena dok nema closed_at (pre migracije sve serije su otvorene).
    user_rated: trenutni korisnik je već ocenio predlog (kao onaj koji odlučuje ili kao drugi)."""
    if not artifact_ids:
        return {}
    placeholders = ", ".join(["%s"] * len(artifact_ids))
    closed = "b.closed_at" if table_columns_exist(cursor, "evaluation_batches", ("closed_at",)) else "NULL"
    cursor.execute(f"""
        SELECT a.id, r.evaluation_batch_id, {closed} AS closed_at
        FROM ai_generated_artifacts a
        JOIN ai_generation_runs r ON r.id = a.generation_run_id
        LEFT JOIN evaluation_batches b ON b.id = r.evaluation_batch_id
        WHERE a.id IN ({placeholders})
    """, tuple(artifact_ids))
    rows = cursor.fetchall()
    cursor.execute(f"""
        SELECT DISTINCT artifact_id FROM ai_evaluations
        WHERE evaluator_id = %s AND artifact_id IN ({placeholders})
    """, (user_id, *artifact_ids))
    rated = {row["artifact_id"] for row in cursor.fetchall()}
    return {
        row["id"]: {
            "batch_id": row["evaluation_batch_id"],
            "batch_open": row["evaluation_batch_id"] is not None and row["closed_at"] is None,
            "user_rated": row["id"] in rated,
        }
        for row in rows
    }


def decision_hidden(row, context):
    """Odlučen predlog iz otvorene serije koji korisnik još nije ocenio: ne sme
    da vidi ni model ni odluku (ADMIN ?reveal=1 sme)."""
    return (row.get("status") != ARTIFACT_STATUS_PENDING
            and bool(context and context["batch_open"] and not context["user_rated"])
            and not blind_review_reveal_requested())


def hide_for_blind_review(row, context, fields):
    """Slepo ocenjivanje predloga pitanja: polja se kriju dok je predlog 'predlog',
    ili dok je u otvorenoj seriji, a korisnik ga još nije ocenio (ADMIN ?reveal=1 vidi)."""
    if blind_review_reveal_requested():
        return row
    if row.get("status") == ARTIFACT_STATUS_PENDING or decision_hidden(row, context):
        for field in fields:
            row.pop(field, None)
    return row


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


def generate_similar_for_question(question_id, provider, evaluation_batch_id=None):
    """Generiše jedan predlog sličnog pitanja i beleži run - zajednička logika
    rute POST /api/questions/<id>/generate-similar i pokretača eksperimenta
    (backend/tools/run_experiment.py). Vraća (telo_odgovora, http_status);
    izuzetke prepušta pozivaocu (ruta ih vraća kao 500)."""
    if provider not in ai_provider.DEFAULT_MODELS:
        return ({"error": f"Nepoznat provider: {provider}"}), 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if evaluation_batch_id is not None:
        cursor.execute("SELECT id FROM evaluation_batches WHERE id = %s", (evaluation_batch_id,))
        if not cursor.fetchone():
            cursor.close()
            conn.close()
            return ({"error": f"evaluation_batch_id {evaluation_batch_id} ne postoji"}), 400

    cursor.execute("SELECT * FROM exam_questions WHERE id = %s", (question_id,))
    question = cursor.fetchone()

    if not question:
        cursor.close()
        conn.close()
        return ({"error": "Question not found"}), 404

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
    prompt_version = prompt_templates.template_version(template_text)

    def ask_model():
        answer = ai_provider.generate(prompt_text, provider=provider, options=options)
        return (answer, *generation_failures.evaluate_similar_question(
            answer, question_type, len(original_answers), prompt_version))

    result, parsed_result, validation_errors, failure_type = ask_model()
    first_attempt_passed = failure_type is None
    total_time_ms = result.get("response_time_ms")
    total_tokens = result.get("tokens_used")

    # Ponovni zahtev posle lošeg formata (tačka I): isti prompt i parametri za sve
    # modele. Infrastrukturne padove ovde ne ponavljamo - to već radi ai_provider.
    # Konačan ishod ide u kolone run-a; prvi pokušaj ostaje u params_used.first_attempt.
    format_retries = 0
    first_attempt = None
    while failure_type in generation_failures.FORMAT_FAILURES and format_retries < generation_failures.MAX_FORMAT_RETRIES:
        first_attempt = {
            "raw_response": result.get("raw_text"),
            "validation_errors": validation_errors,
            "failure_type": failure_type,
            "attempts": result.get("attempts"),
            "finish_reason": result.get("finish_reason"),
            "response_time_ms": result.get("response_time_ms"),
            "tokens_used": result.get("tokens_used"),
        }
        format_retries += 1
        result, parsed_result, validation_errors, failure_type = ask_model()
        # vreme i tokeni se sabiraju preko pokušaja
        times = [t for t in (total_time_ms, result.get("response_time_ms")) if t is not None]
        tokens = [t for t in (total_tokens, result.get("tokens_used")) if t is not None]
        total_time_ms = sum(times) if times else None
        total_tokens = sum(tokens) if tokens else None

    validation_passed = failure_type is None

    cursor.execute("""
        INSERT INTO ai_generation_runs
        (model_id, prompt_id, purpose, mode, source_question_id, params_used,
         raw_response, parsed_result, validation_passed, validation_errors,
         response_time_ms, tokens_used, retry_count, evaluation_batch_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, %s)
    """, (
        model_id,
        prompt_id,
        prompt_templates.PURPOSE_SIMILAR_QUESTION,
        None,
        question_id,
        # attempts/finish_reason nisu kolone - cuvaju se uz parametre poziva
        json.dumps({
            **options,
            "attempts": result.get("attempts"),
            "finish_reason": result.get("finish_reason"),
            **({"first_attempt": first_attempt} if first_attempt else {}),
        }),
        result.get("raw_text"),
        json.dumps(parsed_result) if parsed_result is not None else None,
        1 if validation_passed else 0,
        validation_errors,
        total_time_ms,
        total_tokens,
        evaluation_batch_id,
    ))
    generation_run_id = cursor.lastrowid
    if table_columns_exist(cursor, "ai_generation_runs", FAILURE_COLUMNS):
        cursor.execute("""
            UPDATE ai_generation_runs
            SET failure_type = %s, first_attempt_passed = %s, format_retries = %s
            WHERE id = %s
        """, (failure_type, 1 if first_attempt_passed else 0, format_retries, generation_run_id))
    conn.commit()

    if not validation_passed:
        cursor.close()
        conn.close()
        # razumljiva poruka korisniku; sirov razlog ostaje u run-u (validation_errors)
        return ({
            "error": "AI generisanje nije dalo iskoristiv predlog",
            "details": generation_failures.user_message(failure_type),
            "failure_type": failure_type,
            "first_attempt_passed": first_attempt_passed,
            "format_retries": format_retries,
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
    artifact_id = cursor.lastrowid

    # v3: kopija modelovih oznaka u kolone (radi SQL upita), ako je migracija pokrenuta
    if "difficulty" in parsed_result and question_labels_enabled(cursor):
        cursor.execute("""
            UPDATE ai_generated_artifacts
            SET model_difficulty = %s, model_bloom_level = %s
            WHERE id = %s
        """, (parsed_result["difficulty"], parsed_result["bloom_level"], artifact_id))

    # Mogući duplikat (tačka C), ako je migracija pokrenuta; stari se računaju
    # sa tools/recompute_similarity.py
    if duplicate_check_enabled(cursor):
        store_artifact_similarity(cursor, artifact_id)
    conn.commit()

    cursor.close()
    conn.close()

    return ({
        "message": "Predlog pitanja generisan",
        "generation_run_id": generation_run_id,
        "artifact_id": artifact_id,
        "question_type": question_type,
        "first_attempt_passed": first_attempt_passed,
        "format_retries": format_retries,
        # bez modelove težine/Blumovog nivoa - nastavnik ih bira pri pregledu ne videvši ih
        "proposed_question": {
            k: v for k, v in parsed_result.items() if k not in question_validation.LABEL_FIELDS
        },
    }), 201


@app.post("/api/questions/<int:question_id>/generate-similar") #AI generisanje slicnog pitanja na osnovu postojeceg
@role_required(["TEACHER", "ADMIN"])
def generate_similar_question(question_id):
    try:
        # Opciono: oznaka evaluacione serije (eksperiment); bez nje run je razvojna proba.
        body, status = generate_similar_for_question(
            question_id,
            request.args.get("provider", "groq"),
            request.args.get("evaluation_batch_id", type=int),
        )
        return jsonify(body), status

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
        duplicate_info = load_duplicate_info(cursor, [row["id"] for row in rows])
        batch_context = batch_review_context(cursor, [row["id"] for row in rows], user_id)
        cursor.close()
        conn.close()

        if role == "TEACHER":
            allowed_subjects = set(get_user_subject_ids(int(user_id), "TEACHER"))
            rows = [row for row in rows if row["subject_id"] in allowed_subjects]

        # Odlučen predlog iz otvorene serije koji korisnik nije ocenio: sam status
        # bi otkrio odluku, pa se ne prikazuje (do zatvaranja serije ili sopstvene ocene)
        rows = [row for row in rows if not decision_hidden(row, batch_context.get(row["id"]))]

        for row in rows:
            parsed = json.loads(row["original_text"]) if row["original_text"] else None
            attach_duplicate_info(row, duplicate_info.get(row["id"]))
            move_model_labels(row, parsed)
            row["original_text"] = parsed
            row["question_type"] = prompt_templates.detect_question_type(
                (parsed or {}).get("answers") or []
            )
            hide_for_blind_review(row, batch_context.get(row["id"]),
                                  BLIND_REVIEW_MODEL_FIELDS + BLIND_REVIEW_ORDER_FIELDS + BLIND_REVIEW_LABEL_FIELDS)

        return jsonify(blind_review_order(rows, user_id)), 200

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

        batch_context = batch_review_context(cursor, [artifact_id], user_id).get(artifact_id)
        if decision_hidden(artifact, batch_context):
            cursor.close()
            conn.close()
            return jsonify({
                "error": "Predlog je deo otvorene evaluacione serije i već je pregledan - "
                         "ocenite ga kao drugi ocenjivač (odluka i model se vide posle vaše ocene "
                         "ili zatvaranja serije)",
                "second_rating": True,
            }), 403

        cursor.execute("""
            SELECT answer_text, is_correct
            FROM exam_answers
            WHERE question_id = %s
            ORDER BY id ASC
        """, (artifact["source_question_id"],))
        artifact["source_answers"] = cursor.fetchall()

        parsed_original = json.loads(artifact["original_text"]) if artifact["original_text"] else None
        move_model_labels(artifact, parsed_original)
        artifact["original_text"] = parsed_original
        artifact["edited_text"] = json.loads(artifact["edited_text"]) if artifact["edited_text"] else None

        # Mogući duplikat (tačka C): ocena, sličan tekst i nastavnikova potvrda
        attach_duplicate_info(artifact, load_duplicate_info(cursor, [artifact_id], with_text=True).get(artifact_id))

        # Predlog iz skupa (tačka J): sva ulazna pitanja (izvorno pitanje je prvo iz skupa)
        input_questions = load_input_questions(cursor, artifact_id)
        if input_questions:
            artifact["input_questions"] = input_questions

        # Nastavnikove oznake (posle odluke); samo ako je migracija pokrenuta i ako postoje
        if question_labels_enabled(cursor):
            cursor.execute("""
                SELECT reviewed_difficulty, reviewed_bloom_level
                FROM ai_generated_artifacts WHERE id = %s
            """, (artifact_id,))
            for key, value in (cursor.fetchone() or {}).items():
                if value is not None:
                    artifact[key] = value

        question_type = prompt_templates.detect_question_type((parsed_original or {}).get("answers") or [])
        artifact["question_type"] = question_type
        artifact["rubric_criteria"] = get_applicable_rubric_definitions(cursor, question_type)
        hide_for_blind_review(artifact, batch_context,
                              BLIND_REVIEW_MODEL_FIELDS + BLIND_REVIEW_ORDER_FIELDS + BLIND_REVIEW_LABEL_FIELDS)

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
        # Nastavnikova težina i Blumov nivo (bira ih ne videvši modelove)
        reviewed_labels = {
            "difficulty": data.get("reviewed_difficulty"),
            "bloom_level": data.get("reviewed_bloom_level"),
        }
        # Nastavnikova potvrda mogućeg duplikata (tačka C): true / false / null
        reviewed_duplicate = data.get("reviewed_duplicate")
        if reviewed_duplicate is not None and not isinstance(reviewed_duplicate, bool):
            return jsonify({"error": "reviewed_duplicate mora biti true, false ili null"}), 400

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
                   r.source_question_id, p.version AS prompt_version
            FROM ai_generated_artifacts a
            JOIN ai_generation_runs r ON r.id = a.generation_run_id
            LEFT JOIN ai_prompts p ON p.id = r.prompt_id
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

        cursor.execute("SELECT 1 FROM ai_evaluations WHERE artifact_id = %s AND evaluator_id = %s LIMIT 1",
                       (artifact_id, user_id))
        if cursor.fetchone():
            cursor.close()
            conn.close()
            return jsonify({"error": "Već ste ocenili ovaj predlog (kao drugi ocenjivač) - odluku donosi drugi nastavnik"}), 409

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
            # Izmena se proverava po istoj verziji prompta kao original
            # Oznake nisu deo izmene - nastavnik ih bira posebno (reviewed_*)
            validation = question_validation.validate(
                edited_text, question_type, expected_answer_count, artifact["prompt_version"],
                require_labels=False,
            )
            if not validation.passed:
                cursor.close()
                conn.close()
                return jsonify({"error": f"edited_text nije validan: {'; '.join(validation.errors)}"}), 400
            edited_parsed = edited_text

        # v3 predlog: oznake obavezne za prihvatanje i izmenu, opcione za odbacivanje;
        # v2 predlog: opcione
        labels_v3 = question_validation.strict_fields_enabled(artifact["prompt_version"])
        if labels_v3 and decision != ARTIFACT_STATUS_REJECTED and None in reviewed_labels.values():
            cursor.close()
            conn.close()
            return jsonify({
                "error": "reviewed_difficulty i reviewed_bloom_level su obavezni za prihvatanje ovog predloga"
            }), 400

        for field_name, value in reviewed_labels.items():
            allowed = question_validation.LABEL_FIELDS[field_name]
            if value is not None and value not in allowed:
                cursor.close()
                conn.close()
                return jsonify({
                    "error": f"reviewed_{field_name} mora biti jedno od: {', '.join(allowed)}"
                }), 400

        labels_given = any(value is not None for value in reviewed_labels.values())
        if labels_given and not question_labels_enabled(cursor):
            cursor.close()
            conn.close()
            return jsonify({
                "error": "Kolone za težinu i Blumov nivo ne postoje - pokrenite migraciju db/migration_question_labels.sql"
            }), 409

        if reviewed_duplicate is not None and not duplicate_check_enabled(cursor):
            cursor.close()
            conn.close()
            return jsonify({
                "error": "Kolone za proveru duplikata ne postoje - pokrenite migraciju db/migration_duplicate_check.sql"
            }), 409

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

                if labels_given:
                    cursor.execute("""
                        UPDATE exam_questions SET difficulty = %s, bloom_level = %s WHERE id = %s
                    """, (reviewed_labels["difficulty"], reviewed_labels["bloom_level"], created_question_id))

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

            if labels_given:
                cursor.execute("""
                    UPDATE ai_generated_artifacts
                    SET reviewed_difficulty = %s, reviewed_bloom_level = %s
                    WHERE id = %s
                """, (reviewed_labels["difficulty"], reviewed_labels["bloom_level"], artifact_id))

            if reviewed_duplicate is not None:
                cursor.execute("UPDATE ai_generated_artifacts SET reviewed_duplicate = %s WHERE id = %s",
                               (1 if reviewed_duplicate else 0, artifact_id))

            # Obim intervencije (tačka B), samo za izmenu i samo ako je migracija pokrenuta;
            # stari/propušteni se dopunjuju sa tools/backfill_edit_distance.py
            if (decision == ARTIFACT_STATUS_ACCEPTED_EDITED
                    and table_columns_exist(cursor, "ai_generated_artifacts", EDIT_DISTANCE_COLUMNS)):
                distance = edit_distance.edit_distance(original_parsed, edited_parsed)
                cursor.execute("""
                    UPDATE ai_generated_artifacts
                    SET edit_distance = %s, edit_distance_norm = %s
                    WHERE id = %s
                """, (distance["total"], distance["normalized"], artifact_id))

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
                # attempts/finish_reason nisu kolone - cuvaju se uz parametre poziva
                json.dumps({
                    **options,
                    "solution_source": source["solution_source"],
                    "attempts": result.get("attempts"),
                    "finish_reason": result.get("finish_reason"),
                }),
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
    for row in rows:
        hide_while_pending(row, BLIND_REVIEW_ORDER_FIELDS)
    return jsonify(blind_review_order(rows, get_jwt_identity())), 200


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

    hide_while_pending(artifact, BLIND_REVIEW_ORDER_FIELDS)

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


# =====================================================================
# Referentni skup pitanja (tačka D): zamrznut spisak izvornih pitanja
# jednog predmeta koji ulazi u svaki model istim redosledom. Tabele su iz
# db/migration_reference_sets.sql; pre migracije rute vraćaju 409.
# Pokretač eksperimenta: backend/tools/run_experiment.py.
# =====================================================================

def reference_sets_enabled(cursor):
    """True kad postoje tabele/kolona iz db/migration_reference_sets.sql."""
    cursor.execute("""
        SELECT COUNT(*) AS n FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND ((TABLE_NAME = 'reference_sets' AND COLUMN_NAME = 'id')
            OR (TABLE_NAME = 'reference_set_questions' AND COLUMN_NAME = 'question_id')
            OR (TABLE_NAME = 'evaluation_batches' AND COLUMN_NAME = 'reference_set_id'))
    """)
    row = cursor.fetchone()
    return (row["n"] if isinstance(row, dict) else row[0]) == 3


REFERENCE_SETS_MIGRATION_ERROR = (
    "Tabele za referentni skup ne postoje - pokrenite migraciju db/migration_reference_sets.sql"
)


@app.post("/api/reference-sets")  # pravljenje referentnog skupa (samo pitanja iz predmeta skupa)
@role_required(["ADMIN"])
def create_reference_set():
    data = request.get_json(silent=True) or {}
    name = data.get("name")
    subject_id = data.get("subject_id")
    question_ids = data.get("question_ids")

    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 150:
        return jsonify({"error": "name je obavezan (najviše 150 znakova)"}), 400
    if isinstance(subject_id, bool) or not isinstance(subject_id, int):
        return jsonify({"error": "subject_id je obavezan ceo broj"}), 400
    if (not isinstance(question_ids, list) or not question_ids
            or any(isinstance(q, bool) or not isinstance(q, int) or q <= 0 for q in question_ids)):
        return jsonify({"error": "question_ids mora biti neprazan niz pozitivnih celih brojeva"}), 400
    duplicates = sorted({q for q in question_ids if question_ids.count(q) > 1})
    if duplicates:
        return jsonify({"error": f"Pitanja se ponavljaju u skupu: {duplicates}"}), 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id FROM subjects WHERE id = %s", (subject_id,))
        if not cursor.fetchone():
            return jsonify({"error": f"subject_id {subject_id} ne postoji"}), 400

        placeholders = ", ".join(["%s"] * len(question_ids))
        cursor.execute(
            f"SELECT id, subject_id FROM exam_questions WHERE id IN ({placeholders})",
            tuple(question_ids),
        )
        found = {row["id"]: row["subject_id"] for row in cursor.fetchall()}
        missing = [q for q in question_ids if q not in found]
        if missing:
            return jsonify({"error": f"Pitanja ne postoje: {missing}"}), 400
        outside = [q for q in question_ids if found[q] != subject_id]
        if outside:
            return jsonify({
                "error": f"Pitanja nisu iz predmeta skupa (subject_id {subject_id}): {outside}",
                "question_ids": outside,
            }), 400

        if not reference_sets_enabled(cursor):
            return jsonify({"error": REFERENCE_SETS_MIGRATION_ERROR}), 409

        try:
            cursor.execute(
                "INSERT INTO reference_sets (name, subject_id) VALUES (%s, %s)",
                (name.strip(), subject_id),
            )
            set_id = cursor.lastrowid
            for order_no, question_id in enumerate(question_ids, start=1):
                cursor.execute("""
                    INSERT INTO reference_set_questions (reference_set_id, question_id, order_no)
                    VALUES (%s, %s, %s)
                """, (set_id, question_id, order_no))
            conn.commit()
        except mysql.connector.IntegrityError as e:
            conn.rollback()
            if e.errno == 1062:
                return jsonify({"error": f"Referentni skup sa imenom '{name.strip()}' već postoji"}), 409
            raise
        except Exception:
            conn.rollback()
            raise

        return jsonify({
            "id": set_id,
            "name": name.strip(),
            "subject_id": subject_id,
            "questions": [
                {"question_id": question_id, "order_no": order_no}
                for order_no, question_id in enumerate(question_ids, start=1)
            ],
        }), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.get("/api/reference-sets")  # lista referentnih skupova
@role_required(["ADMIN"])
def list_reference_sets():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        if not reference_sets_enabled(cursor):
            return jsonify({"error": REFERENCE_SETS_MIGRATION_ERROR}), 409
        cursor.execute("""
            SELECT rs.id, rs.name, rs.subject_id, s.name AS subject_name, rs.created_at,
                   (SELECT COUNT(*) FROM reference_set_questions q WHERE q.reference_set_id = rs.id) AS question_count,
                   (SELECT COUNT(*) FROM evaluation_batches b WHERE b.reference_set_id = rs.id) AS batch_count
            FROM reference_sets rs
            JOIN subjects s ON s.id = rs.subject_id
            ORDER BY rs.id DESC
        """)
        return jsonify(cursor.fetchall()), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.get("/api/reference-sets/<int:set_id>")  # detalj skupa: pitanja po redu i serije koje ga koriste
@role_required(["ADMIN"])
def get_reference_set(set_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        if not reference_sets_enabled(cursor):
            return jsonify({"error": REFERENCE_SETS_MIGRATION_ERROR}), 409
        cursor.execute("""
            SELECT rs.id, rs.name, rs.subject_id, s.name AS subject_name, rs.created_at
            FROM reference_sets rs JOIN subjects s ON s.id = rs.subject_id
            WHERE rs.id = %s
        """, (set_id,))
        reference_set = cursor.fetchone()
        if not reference_set:
            return jsonify({"error": "Reference set not found"}), 404

        cursor.execute("""
            SELECT rq.question_id, rq.order_no, q.question_text, q.area_id,
                   (SELECT COUNT(*) FROM exam_answers a WHERE a.question_id = q.id) AS answer_count
            FROM reference_set_questions rq
            JOIN exam_questions q ON q.id = rq.question_id
            WHERE rq.reference_set_id = %s
            ORDER BY rq.order_no ASC, rq.question_id ASC
        """, (set_id,))
        reference_set["questions"] = cursor.fetchall()

        cursor.execute(
            "SELECT id, name, is_final FROM evaluation_batches WHERE reference_set_id = %s ORDER BY id",
            (set_id,),
        )
        reference_set["batches"] = cursor.fetchall()
        return jsonify(reference_set), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


# =====================================================================
# Drugi ocenjivač (tačka E): zasebna ocena istog predloga, bez odluke,
# radi saglasnosti ocenjivača. Tabele/kolone iz db/migration_second_rater.sql;
# pre migracije rute vraćaju 409. Drugi ocenjivač vidi samo original_text,
# izvorno pitanje, rubriku i sličnost - ne vidi model, status/odluku, izmenu,
# razlog odbacivanja ni tuđe ocene.
# =====================================================================

SECOND_RATING_SAMPLE = 0.30  # udeo predloga iz serije koji se nudi svakom ocenjivaču

SECOND_RATER_MIGRATION_ERROR = (
    "Druga ocena nije dostupna - pokrenite migraciju db/migration_second_rater.sql"
)


def second_rater_enabled(cursor):
    return (table_columns_exist(cursor, "ai_evaluations", ("evaluation_round",))
            and table_columns_exist(cursor, "evaluation_batches", ("closed_at",))
            and table_columns_exist(cursor, "ai_label_evaluations", ("artifact_id", "difficulty", "bloom_level")))


def _stable_fraction(*parts):
    digest = hashlib.sha256(":".join(str(p) for p in parts).encode()).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def in_second_rating_sample(user_id, artifact_id):
    """Stabilan (ne menja se iz dana u dan) nasumičan uzorak po ocenjivaču."""
    return _stable_fraction("second-rating", user_id, artifact_id) < SECOND_RATING_SAMPLE


def _load_rating_artifact(cursor, artifact_id):
    cursor.execute("""
        SELECT a.id, a.original_text, r.evaluation_batch_id, b.closed_at, p.version AS prompt_version,
               r.source_question_id, sq.subject_id, sq.area_id, sq.question_text AS source_question_text,
               s.name AS subject_name, ar.name AS area_name
        FROM ai_generated_artifacts a
        JOIN ai_generation_runs r ON r.id = a.generation_run_id
        LEFT JOIN evaluation_batches b ON b.id = r.evaluation_batch_id
        LEFT JOIN ai_prompts p ON p.id = r.prompt_id
        LEFT JOIN exam_questions sq ON sq.id = r.source_question_id
        LEFT JOIN subjects s ON s.id = sq.subject_id
        LEFT JOIN areas ar ON ar.id = sq.area_id
        WHERE a.id = %s AND a.artifact_type = %s
    """, (artifact_id, ARTIFACT_TYPE_QUESTION))
    return cursor.fetchone()


def _second_rating_access_error(cursor, artifact, user_id, role):
    """(poruka, status) ako korisnik ne sme da da drugu ocenu ovom predlogu, inače None."""
    if not artifact:
        return "Artifact not found", 404
    if role == "TEACHER" and not user_has_subject(int(user_id), artifact["subject_id"], "TEACHER"):
        return "Forbidden", 403
    if artifact["evaluation_batch_id"] is None:
        return "Predlog nije deo evaluacione serije - druga ocena je samo za serije", 400
    if artifact["closed_at"] is not None:
        return "Serija je zatvorena - ocena više ne bi bila slepa", 409
    cursor.execute("SELECT 1 FROM ai_evaluations WHERE artifact_id = %s AND evaluator_id = %s LIMIT 1",
                   (artifact["id"], user_id))
    if cursor.fetchone():
        return "Već ste ocenili ovaj predlog", 409
    return None


def _rating_view(artifact):
    """Ono što drugi ocenjivač sme da vidi o predlogu."""
    parsed = json.loads(artifact["original_text"]) if artifact["original_text"] else None
    view = {"id": artifact["id"], "batch_id": artifact["evaluation_batch_id"]}
    move_model_labels(view, parsed)          # oznake modela se izdvajaju ...
    view.pop("model_difficulty", None)       # ... i ne vraćaju
    view.pop("model_bloom_level", None)
    view.update({
        "original_text": parsed,
        "question_type": prompt_templates.detect_question_type((parsed or {}).get("answers") or []),
        "subject_name": artifact["subject_name"],
        "area_name": artifact["area_name"],
    })
    return view


def validate_rubric_scores(cursor, question_type, scores):
    """(score_by_id, None) ili (None, poruka) - ista pravila kao pri pregledu."""
    if not isinstance(scores, list) or not scores:
        return None, "scores je obavezno i mora biti neprazan niz"
    rubric_by_id = {row["id"]: row for row in get_applicable_rubric_definitions(cursor, question_type)}
    score_by_id = {}
    for item in scores:
        if not isinstance(item, dict):
            return None, "Svaki element scores mora biti objekat"
        rubric_row = rubric_by_id.get(item.get("rubric_definition_id"))
        if rubric_row is None:
            return None, f"Nepoznat ili neprimenljiv rubric_definition_id: {item.get('rubric_definition_id')}"
        value = item.get("score")
        if isinstance(value, bool) or not isinstance(value, int) or not (rubric_row["scale_min"] <= value <= rubric_row["scale_max"]):
            return None, (f"Ocena za '{rubric_row['dimension_label']}' mora biti ceo broj "
                          f"u opsegu {rubric_row['scale_min']}-{rubric_row['scale_max']}")
        score_by_id[rubric_row["id"]] = value
    if set(score_by_id) != set(rubric_by_id):
        return None, "scores mora sadržati tačno jednu ocenu za svaki primenljivi kriterijum rubrike"
    return score_by_id, None


@app.get("/api/ai/artifacts/second-rating")  # predlozi iz otvorenih serija za drugu ocenu (uzorak po ocenjivaču)
@role_required(["TEACHER", "ADMIN"])
def list_second_rating():
    user_id = get_jwt_identity()
    role = get_jwt().get("role")
    batch_id = request.args.get("batch_id", type=int)
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        if not second_rater_enabled(cursor):
            return jsonify({"error": SECOND_RATER_MIGRATION_ERROR}), 409
        cursor.execute(f"""
            SELECT a.id, a.original_text, r.evaluation_batch_id, NULL AS closed_at, sq.subject_id,
                   s.name AS subject_name, ar.name AS area_name
            FROM ai_generated_artifacts a
            JOIN ai_generation_runs r ON r.id = a.generation_run_id
            JOIN evaluation_batches b ON b.id = r.evaluation_batch_id AND b.closed_at IS NULL
            LEFT JOIN exam_questions sq ON sq.id = r.source_question_id
            LEFT JOIN subjects s ON s.id = sq.subject_id
            LEFT JOIN areas ar ON ar.id = sq.area_id
            WHERE a.artifact_type = %s
              {"AND r.evaluation_batch_id = %s" if batch_id is not None else ""}
              AND NOT EXISTS (SELECT 1 FROM ai_evaluations e WHERE e.artifact_id = a.id AND e.evaluator_id = %s)
        """, (ARTIFACT_TYPE_QUESTION, *([batch_id] if batch_id is not None else []), user_id))
        rows = cursor.fetchall()
        if role == "TEACHER":
            allowed = set(get_user_subject_ids(int(user_id), "TEACHER"))
            rows = [row for row in rows if row["subject_id"] in allowed]
        rows = [row for row in rows if in_second_rating_sample(user_id, row["id"])]
        rows.sort(key=lambda row: _stable_fraction("second-rating-order", user_id, row["id"]))
        return jsonify([_rating_view(row) for row in rows]), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.get("/api/ai/artifacts/<int:artifact_id>/second-rating")  # predlog za drugu ocenu (bez modela i odluke)
@role_required(["TEACHER", "ADMIN"])
def get_second_rating(artifact_id):
    user_id = get_jwt_identity()
    role = get_jwt().get("role")
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        if not second_rater_enabled(cursor):
            return jsonify({"error": SECOND_RATER_MIGRATION_ERROR}), 409
        artifact = _load_rating_artifact(cursor, artifact_id)
        denied = _second_rating_access_error(cursor, artifact, user_id, role)
        if denied:
            return jsonify({"error": denied[0]}), denied[1]

        view = _rating_view(artifact)
        cursor.execute("SELECT answer_text, is_correct FROM exam_answers WHERE question_id = %s ORDER BY id",
                       (artifact["source_question_id"],))
        view["source_question_text"] = artifact["source_question_text"]
        view["source_answers"] = cursor.fetchall()
        view["rubric_criteria"] = get_applicable_rubric_definitions(cursor, view["question_type"])
        input_questions = load_input_questions(cursor, artifact_id)
        if input_questions:
            view["input_questions"] = input_questions
        similarity = load_duplicate_info(cursor, [artifact_id], with_text=True).get(artifact_id) or {}
        similarity.pop("reviewed_duplicate", None)  # odluka prvog ocenjivača
        attach_duplicate_info(view, similarity)
        return jsonify(view), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.post("/api/ai/artifacts/<int:artifact_id>/evaluations")  # druga ocena: samo rubrika i težina/Blum, bez odluke
@role_required(["TEACHER", "ADMIN"])
def submit_second_rating(artifact_id):
    user_id = get_jwt_identity()
    role = get_jwt().get("role")
    data = request.get_json(silent=True) or {}
    comment = data.get("comment")
    comment = (comment.strip() or None) if isinstance(comment, str) else None
    labels = {"difficulty": data.get("difficulty"), "bloom_level": data.get("bloom_level")}

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        if not second_rater_enabled(cursor):
            return jsonify({"error": SECOND_RATER_MIGRATION_ERROR}), 409
        artifact = _load_rating_artifact(cursor, artifact_id)
        denied = _second_rating_access_error(cursor, artifact, user_id, role)
        if denied:
            return jsonify({"error": denied[0]}), denied[1]

        view = _rating_view(artifact)
        score_by_id, error = validate_rubric_scores(cursor, view["question_type"], data.get("scores"))
        if error:
            return jsonify({"error": error}), 400

        if question_validation.strict_fields_enabled(artifact["prompt_version"]) and None in labels.values():
            return jsonify({"error": "difficulty i bloom_level su obavezni za ovaj predlog"}), 400
        for field_name, value in labels.items():
            allowed = question_validation.LABEL_FIELDS[field_name]
            if value is not None and value not in allowed:
                return jsonify({"error": f"{field_name} mora biti jedno od: {', '.join(allowed)}"}), 400

        try:
            for rubric_id, score in score_by_id.items():
                cursor.execute("""
                    INSERT INTO ai_evaluations
                    (artifact_id, rubric_definition_id, evaluator_id, evaluator_role, score, comment, evaluation_round)
                    VALUES (%s, %s, %s, %s, %s, %s, 2)
                """, (artifact_id, rubric_id, user_id, role, score, comment))
            if any(value is not None for value in labels.values()):
                cursor.execute("""
                    INSERT INTO ai_label_evaluations (artifact_id, evaluator_id, evaluator_role, difficulty, bloom_level)
                    VALUES (%s, %s, %s, %s, %s)
                """, (artifact_id, user_id, role, labels["difficulty"], labels["bloom_level"]))
            conn.commit()
        except mysql.connector.IntegrityError as e:
            conn.rollback()
            if e.errno == 1062:
                return jsonify({"error": "Već ste ocenili ovaj predlog"}), 409
            raise
        except Exception:
            conn.rollback()
            raise

        return jsonify({"message": "Ocena sačuvana", "artifact_id": artifact_id,
                        "evaluation_round": 2, "scores": len(score_by_id)}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.post("/api/evaluation-batches/<int:batch_id>/close")  # zatvaranje serije: model i odluke postaju vidljivi
@role_required(["ADMIN"])
def close_evaluation_batch(batch_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        if not table_columns_exist(cursor, "evaluation_batches", ("closed_at",)):
            return jsonify({"error": SECOND_RATER_MIGRATION_ERROR}), 409
        cursor.execute("SELECT id, closed_at FROM evaluation_batches WHERE id = %s", (batch_id,))
        batch = cursor.fetchone()
        if not batch:
            return jsonify({"error": "Batch not found"}), 404
        if batch["closed_at"] is None:
            cursor.execute("UPDATE evaluation_batches SET closed_at = NOW() WHERE id = %s", (batch_id,))
            conn.commit()
            cursor.execute("SELECT closed_at FROM evaluation_batches WHERE id = %s", (batch_id,))
            batch = cursor.fetchone()
        return jsonify({"id": batch_id, "closed_at": batch["closed_at"]}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


# =====================================================================
# Generisanje iz SKUPA pitanja (tačka J): jedan poziv modela -> do K predloga.
# Dodatni način rada uz generisanje iz jednog pitanja; ista validacija po
# stavci, isti ponovni zahtev posle lošeg formata, isto beleženje, slepo
# ocenjivanje, druga ocena, duplikati i razdaljina izmene (po predlogu).
# Bez nove šeme: purpose = 'similar_question_set', source_question_id = prvo
# pitanje skupa (predmet, oblast, poeni, dozvole), a ulaz i ishod po stavkama
# su u params_used (input_question_ids, k, input, set_items).
# =====================================================================

SET_MAX_INPUT_QUESTIONS = 20
SET_MAX_K = 10


def generate_similar_set(question_ids, provider, k, evaluation_batch_id=None, input_source=None):
    """Vraća (telo_odgovora, http_status); izuzetke prepušta pozivaocu."""
    if provider not in ai_provider.DEFAULT_MODELS:
        return {"error": f"Nepoznat provider: {provider}"}, 400
    if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= SET_MAX_K:
        return {"error": f"k mora biti ceo broj od 1 do {SET_MAX_K}"}, 400
    question_ids = [int(q) for q in question_ids]
    if not question_ids:
        return {"error": "Skup nema pitanja"}, 400
    if len(question_ids) > SET_MAX_INPUT_QUESTIONS:
        return {"error": f"Skup ima {len(question_ids)} pitanja; najviše {SET_MAX_INPUT_QUESTIONS} po pozivu"}, 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        if evaluation_batch_id is not None:
            cursor.execute("SELECT id FROM evaluation_batches WHERE id = %s", (evaluation_batch_id,))
            if not cursor.fetchone():
                return {"error": f"evaluation_batch_id {evaluation_batch_id} ne postoji"}, 400

        placeholders = ", ".join(["%s"] * len(question_ids))
        cursor.execute(f"SELECT id, subject_id FROM exam_questions WHERE id IN ({placeholders})", tuple(question_ids))
        subjects = {row["id"]: row["subject_id"] for row in cursor.fetchall()}
        missing = [q for q in question_ids if q not in subjects]
        if missing:
            return {"error": f"Pitanja ne postoje: {missing}"}, 404
        subject_ids = set(subjects.values())
        if len(subject_ids) != 1 or None in subject_ids:
            return {"error": "Sva pitanja skupa moraju biti iz istog predmeta"}, 400
        cursor.execute("SELECT name FROM subjects WHERE id = %s", (subject_ids.pop(),))
        subject_row = cursor.fetchone()
        subject_name = subject_row["name"] if subject_row else "Nepoznat predmet"

        payloads = _question_payloads(cursor, question_ids)
        prompt_id, template_text, prompt_version = prompt_templates.ensure_set_prompt_synced(conn)
        prompt_text = prompt_templates.build_set_prompt(
            template_text, [payloads[q] for q in question_ids], k, subject_name)

        model_name = ai_provider.DEFAULT_MODELS[provider]
        model_id = ensure_ai_model(conn, provider=provider, model_name=model_name)
        options = {"temperature": 0.7}

        def ask_model():
            answer = ai_provider.generate(prompt_text, provider=provider, options=options)
            return (answer, *generation_failures.evaluate_similar_set(answer, k, prompt_version))

        result, parsed, validation, validation_errors, failure_type = ask_model()
        first_attempt_passed = failure_type is None
        total_time_ms = result.get("response_time_ms")
        total_tokens = result.get("tokens_used")

        # Ponovni zahtev samo kad je CEO odgovor neupotrebljiv (isto pravilo kao za jedno pitanje)
        format_retries = 0
        first_attempt = None
        while failure_type in generation_failures.FORMAT_FAILURES and format_retries < generation_failures.MAX_FORMAT_RETRIES:
            first_attempt = {
                "raw_response": result.get("raw_text"), "validation_errors": validation_errors,
                "failure_type": failure_type, "attempts": result.get("attempts"),
                "finish_reason": result.get("finish_reason"),
                "response_time_ms": result.get("response_time_ms"), "tokens_used": result.get("tokens_used"),
            }
            format_retries += 1
            result, parsed, validation, validation_errors, failure_type = ask_model()
            times = [t for t in (total_time_ms, result.get("response_time_ms")) if t is not None]
            tokens = [t for t in (total_tokens, result.get("tokens_used")) if t is not None]
            total_time_ms = sum(times) if times else None
            total_tokens = sum(tokens) if tokens else None

        validation_passed = failure_type is None
        set_items = None
        if validation is not None and validation.items:
            set_items = {
                "requested": k,
                "returned": len(validation.items),
                "accepted": len(validation.accepted),
                "rejected": [{"index": r.index, "failure_type": "schema", "errors": r.errors} for r in validation.rejected],
            }

        cursor.execute("""
            INSERT INTO ai_generation_runs
            (model_id, prompt_id, purpose, mode, source_question_id, params_used,
             raw_response, parsed_result, validation_passed, validation_errors,
             response_time_ms, tokens_used, retry_count, evaluation_batch_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, %s)
        """, (
            model_id, prompt_id, prompt_templates.PURPOSE_SIMILAR_QUESTION_SET, None, question_ids[0],
            json.dumps({
                **options,
                "attempts": result.get("attempts"),
                "finish_reason": result.get("finish_reason"),
                "input_question_ids": question_ids,
                "k": k,
                **({"input": input_source} if input_source else {}),
                **({"set_items": set_items} if set_items else {}),
                **({"first_attempt": first_attempt} if first_attempt else {}),
            }),
            result.get("raw_text"),
            json.dumps(parsed) if parsed is not None else None,
            1 if validation_passed else 0,
            validation_errors,
            total_time_ms,
            total_tokens,
            evaluation_batch_id,
        ))
        generation_run_id = cursor.lastrowid
        if table_columns_exist(cursor, "ai_generation_runs", FAILURE_COLUMNS):
            cursor.execute("""
                UPDATE ai_generation_runs SET failure_type = %s, first_attempt_passed = %s, format_retries = %s
                WHERE id = %s
            """, (failure_type, 1 if first_attempt_passed else 0, format_retries, generation_run_id))
        conn.commit()

        if not validation_passed:
            return {
                "error": "AI generisanje nije dalo iskoristiv predlog",
                "details": generation_failures.user_message(failure_type),
                "failure_type": failure_type,
                "first_attempt_passed": first_attempt_passed,
                "format_retries": format_retries,
                "generation_run_id": generation_run_id,
            }, 422

        labels_on = question_labels_enabled(cursor)
        artifact_ids = []
        for item in validation.accepted:
            cursor.execute("""
                INSERT INTO ai_generated_artifacts (generation_run_id, artifact_type, status, original_text)
                VALUES (%s, %s, %s, %s)
            """, (generation_run_id, ARTIFACT_TYPE_QUESTION, ARTIFACT_STATUS_PENDING, json.dumps(item.item)))
            artifact_id = cursor.lastrowid
            artifact_ids.append(artifact_id)
            if labels_on:
                cursor.execute("""
                    UPDATE ai_generated_artifacts SET model_difficulty = %s, model_bloom_level = %s WHERE id = %s
                """, (item.item["difficulty"], item.item["bloom_level"], artifact_id))
        # Duplikati tek kad su svi predlozi run-a upisani (porede se i međusobno)
        if duplicate_check_enabled(cursor):
            for artifact_id in artifact_ids:
                store_artifact_similarity(cursor, artifact_id)
        conn.commit()

        return {
            "message": "Predlozi pitanja generisani",
            "generation_run_id": generation_run_id,
            "artifact_ids": artifact_ids,
            "requested": k,
            "accepted": len(artifact_ids),
            "rejected": len(validation.rejected),
            "first_attempt_passed": first_attempt_passed,
            "format_retries": format_retries,
        }, 201
    finally:
        cursor.close()
        conn.close()


@app.post("/api/exams/<int:exam_id>/generate-similar")  # AI: K novih pitanja na osnovu pitanja iz testa
@role_required(["TEACHER", "ADMIN"])
def generate_similar_from_exam(exam_id):
    try:
        user_id = get_jwt_identity()
        role = get_jwt().get("role")
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT id, subject_id FROM exams WHERE id = %s", (exam_id,))
            exam = cursor.fetchone()
            if not exam:
                return jsonify({"error": "Exam not found"}), 404
            if role == "TEACHER" and not user_has_subject(int(user_id), exam["subject_id"], "TEACHER"):
                return jsonify({"error": "Forbidden"}), 403
            cursor.execute("""
                SELECT question_id FROM exam_test_questions WHERE exam_id = %s ORDER BY order_no ASC, question_id ASC
            """, (exam_id,))
            question_ids = [row["question_id"] for row in cursor.fetchall()]
        finally:
            cursor.close()
            conn.close()
        if not question_ids:
            return jsonify({"error": "Test nema pitanja"}), 400

        k = request.args.get("k", 3, type=int)
        body, status = generate_similar_set(
            question_ids,
            request.args.get("provider", "groq"),
            k,
            request.args.get("evaluation_batch_id", type=int),
            input_source={"type": "exam", "id": exam_id},
        )
        return jsonify(body), status
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =====================================================================
# CSV izvoz evaluacione serije (tačka G) - ulaz za tools/analyze_experiment.py.
# kind=artifacts: jedan red po predlogu (model, prompt, oznake, ocene
#   nastavnika (runda 1) i prve druge ocene (runda 2), odluka, razdaljina, duplikat);
# kind=runs: jedan red po pozivu modela (vrsta pada, ponovni zahtev, vreme, tokeni);
# kind=evaluations: jedan red po pojedinačnoj oceni (svi ocenjivači, za alfu).
# Korisnici (nastavnici, drugi ocenjivači, studenti) su samo HMAC heš id-ja -
# bez imena i email adresa. Samo run-ovi iz serije (probe bez serije ne ulaze).
# =====================================================================

EXPORT_KINDS = ("artifacts", "runs", "evaluations")
EXPORT_REQUIRED_COLUMNS = {
    "ai_generation_runs": FAILURE_COLUMNS,
    "ai_generated_artifacts": ("model_difficulty", "reviewed_difficulty", "edit_distance", "max_similarity", "reviewed_duplicate"),
    "ai_evaluations": ("evaluation_round",),
    "ai_label_evaluations": ("difficulty",),
}


def anonymize_user(user_id):
    """Stabilan pseudonim korisnika (HMAC-SHA256 sa tajnim ključem aplikacije)."""
    if user_id is None:
        return ""
    key = str(app.config["JWT_SECRET_KEY"]).encode()
    return "u_" + hmac.new(key, f"user:{user_id}".encode(), hashlib.sha256).hexdigest()[:12]


def _export_artifacts(cursor, batch_id):
    cursor.execute("""
        SELECT a.id AS artifact_id, a.artifact_type, r.id AS run_id, r.purpose, m.provider, m.model_name,
               p.version AS prompt_version, r.source_question_id, r.params_used, a.original_text, a.status,
               a.reviewed_by, a.model_difficulty, a.model_bloom_level, a.reviewed_difficulty, a.reviewed_bloom_level,
               a.edit_distance, a.edit_distance_norm, a.max_similarity, a.similar_source, a.reviewed_duplicate,
               r.first_attempt_passed, r.format_retries, r.response_time_ms, r.tokens_used
        FROM ai_generated_artifacts a
        JOIN ai_generation_runs r ON r.id = a.generation_run_id
        JOIN ai_models m ON m.id = r.model_id
        LEFT JOIN ai_prompts p ON p.id = r.prompt_id
        WHERE r.evaluation_batch_id = %s
        ORDER BY a.id
    """, (batch_id,))
    artifacts = cursor.fetchall()
    ids = [a["artifact_id"] for a in artifacts]
    scores, labels2, dims = {}, {}, []
    if ids:
        placeholders = ", ".join(["%s"] * len(ids))
        cursor.execute(f"""
            SELECT e.artifact_id, e.evaluator_id, e.evaluation_round, d.dimension_key, e.score
            FROM ai_evaluations e JOIN ai_rubric_definitions d ON d.id = e.rubric_definition_id
            WHERE e.artifact_id IN ({placeholders}) AND d.evaluator_role <> 'STUDENT'
            ORDER BY e.evaluator_id
        """, tuple(ids))
        for row in cursor.fetchall():
            scores.setdefault(row["artifact_id"], []).append(row)
            if row["dimension_key"] not in dims:
                dims.append(row["dimension_key"])
        cursor.execute(f"""
            SELECT artifact_id, evaluator_id, difficulty, bloom_level FROM ai_label_evaluations
            WHERE artifact_id IN ({placeholders}) ORDER BY evaluator_id
        """, tuple(ids))
        for row in cursor.fetchall():
            labels2.setdefault((row["artifact_id"], row["evaluator_id"]), row)

    columns = ["batch_id", "artifact_id", "artifact_type", "run_id", "mode", "provider", "model_name", "prompt_version",
               "source_question_id", "input_question_ids", "question_type", "status", "decider",
               "model_difficulty", "model_bloom_level", "reviewed_difficulty", "reviewed_bloom_level",
               "second_rater", "second_raters_count", "second_difficulty", "second_bloom_level",
               "edit_distance", "edit_distance_norm", "max_similarity", "similar_source", "possible_duplicate",
               "reviewed_duplicate", "first_attempt_passed", "format_retries", "response_time_ms", "tokens_used"]
    columns += [f"r1_{d}" for d in dims] + [f"r2_{d}" for d in dims]
    rows = []
    for a in artifacts:
        own = scores.get(a["artifact_id"], [])
        round1 = {s["dimension_key"]: s["score"] for s in own if s["evaluation_round"] == 1 and s["evaluator_id"] == a["reviewed_by"]}
        second_ids = sorted({s["evaluator_id"] for s in own if s["evaluation_round"] == 2})
        first_second = second_ids[0] if second_ids else None
        round2 = {s["dimension_key"]: s["score"] for s in own if s["evaluation_round"] == 2 and s["evaluator_id"] == first_second}
        label2 = labels2.get((a["artifact_id"], first_second)) or {}
        parsed = json.loads(a["original_text"]) if a["original_text"] else {}
        row = {
            "batch_id": batch_id, "artifact_id": a["artifact_id"], "artifact_type": a["artifact_type"], "run_id": a["run_id"],
            "mode": "set" if a["purpose"] == prompt_templates.PURPOSE_SIMILAR_QUESTION_SET else
                    ("single" if a["purpose"] == prompt_templates.PURPOSE_SIMILAR_QUESTION else a["purpose"]),
            "provider": a["provider"], "model_name": a["model_name"], "prompt_version": a["prompt_version"],
            "source_question_id": a["source_question_id"],
            "input_question_ids": ";".join(str(q) for q in input_question_ids_of_run(a["params_used"])),
            "question_type": ("mc" if isinstance(parsed, dict) and parsed.get("answers") else "open")
                             if a["artifact_type"] == ARTIFACT_TYPE_QUESTION else "",
            "status": a["status"], "decider": anonymize_user(a["reviewed_by"]),
            "model_difficulty": a["model_difficulty"], "model_bloom_level": a["model_bloom_level"],
            "reviewed_difficulty": a["reviewed_difficulty"], "reviewed_bloom_level": a["reviewed_bloom_level"],
            "second_rater": anonymize_user(first_second), "second_raters_count": len(second_ids),
            "second_difficulty": label2.get("difficulty"), "second_bloom_level": label2.get("bloom_level"),
            "edit_distance": a["edit_distance"], "edit_distance_norm": a["edit_distance_norm"],
            "max_similarity": a["max_similarity"], "similar_source": a["similar_source"],
            "possible_duplicate": "" if a["max_similarity"] is None else int(question_similarity.is_possible_duplicate(a["max_similarity"])),
            "reviewed_duplicate": a["reviewed_duplicate"], "first_attempt_passed": a["first_attempt_passed"],
            "format_retries": a["format_retries"], "response_time_ms": a["response_time_ms"], "tokens_used": a["tokens_used"],
        }
        row.update({f"r1_{d}": round1.get(d) for d in dims})
        row.update({f"r2_{d}": round2.get(d) for d in dims})
        rows.append(row)
    return columns, rows


def _export_runs(cursor, batch_id):
    cursor.execute("""
        SELECT r.id AS run_id, r.purpose, m.provider, m.model_name, p.version AS prompt_version, r.source_question_id,
               r.params_used, r.validation_passed, r.failure_type, r.first_attempt_passed, r.format_retries,
               r.response_time_ms, r.tokens_used, r.created_at,
               (SELECT COUNT(*) FROM ai_generated_artifacts a WHERE a.generation_run_id = r.id) AS artifacts
        FROM ai_generation_runs r
        JOIN ai_models m ON m.id = r.model_id
        LEFT JOIN ai_prompts p ON p.id = r.prompt_id
        WHERE r.evaluation_batch_id = %s
        ORDER BY r.id
    """, (batch_id,))
    columns = ["batch_id", "run_id", "purpose", "provider", "model_name", "prompt_version", "source_question_id",
               "input_question_ids", "validation_passed", "failure_type", "first_attempt_passed", "format_retries",
               "attempts", "finish_reason", "response_time_ms", "tokens_used", "artifacts", "set_accepted",
               "set_rejected", "created_at"]
    rows = []
    for r in cursor.fetchall():
        params = json.loads(r["params_used"]) if r["params_used"] else {}
        set_items = params.get("set_items") or {}
        rows.append({
            "batch_id": batch_id, "run_id": r["run_id"], "purpose": r["purpose"], "provider": r["provider"],
            "model_name": r["model_name"], "prompt_version": r["prompt_version"], "source_question_id": r["source_question_id"],
            "input_question_ids": ";".join(str(q) for q in input_question_ids_of_run(r["params_used"])),
            "validation_passed": r["validation_passed"], "failure_type": r["failure_type"],
            "first_attempt_passed": r["first_attempt_passed"], "format_retries": r["format_retries"],
            "attempts": params.get("attempts"), "finish_reason": params.get("finish_reason"),
            "response_time_ms": r["response_time_ms"], "tokens_used": r["tokens_used"], "artifacts": r["artifacts"],
            "set_accepted": set_items.get("accepted", ""), "set_rejected": len(set_items.get("rejected") or []) if set_items else "",
            "created_at": r["created_at"],
        })
    return columns, rows


def _export_evaluations(cursor, batch_id):
    cursor.execute("""
        SELECT e.artifact_id, a.artifact_type, m.provider, m.model_name, e.evaluator_id, e.evaluator_role,
               e.evaluation_round, d.dimension_key, d.evaluator_role AS rubric_role, e.score
        FROM ai_evaluations e
        JOIN ai_rubric_definitions d ON d.id = e.rubric_definition_id
        JOIN ai_generated_artifacts a ON a.id = e.artifact_id
        JOIN ai_generation_runs r ON r.id = a.generation_run_id
        JOIN ai_models m ON m.id = r.model_id
        WHERE r.evaluation_batch_id = %s
        ORDER BY e.artifact_id, e.evaluator_id, d.dimension_key
    """, (batch_id,))
    rows = [{**{k: v for k, v in r.items() if k != "evaluator_id"}, "evaluator": anonymize_user(r["evaluator_id"]),
             "value": r["score"], "level": "ordinal"} for r in cursor.fetchall()]
    # kategorije: nastavnik koji odlučuje (runda 1) i drugi ocenjivači (runda 2)
    cursor.execute("""
        SELECT a.id AS artifact_id, a.artifact_type, m.provider, m.model_name, a.reviewed_by AS evaluator_id,
               a.reviewed_difficulty AS difficulty, a.reviewed_bloom_level AS bloom_level, 1 AS evaluation_round
        FROM ai_generated_artifacts a
        JOIN ai_generation_runs r ON r.id = a.generation_run_id JOIN ai_models m ON m.id = r.model_id
        WHERE r.evaluation_batch_id = %s AND a.reviewed_difficulty IS NOT NULL
        UNION ALL
        SELECT l.artifact_id, a.artifact_type, m.provider, m.model_name, l.evaluator_id, l.difficulty, l.bloom_level, 2
        FROM ai_label_evaluations l
        JOIN ai_generated_artifacts a ON a.id = l.artifact_id
        JOIN ai_generation_runs r ON r.id = a.generation_run_id JOIN ai_models m ON m.id = r.model_id
        WHERE r.evaluation_batch_id = %s
    """, (batch_id, batch_id))
    for r in cursor.fetchall():
        for key in ("difficulty", "bloom_level"):
            if r[key] is not None:
                rows.append({"artifact_id": r["artifact_id"], "artifact_type": r["artifact_type"], "provider": r["provider"],
                             "model_name": r["model_name"], "evaluator_role": "TEACHER",
                             "evaluation_round": r["evaluation_round"], "dimension_key": f"label_{key}",
                             "rubric_role": "TEACHER", "score": "", "evaluator": anonymize_user(r["evaluator_id"]),
                             "value": r[key], "level": "nominal"})
    columns = ["batch_id", "artifact_id", "artifact_type", "provider", "model_name", "evaluator", "evaluator_role",
               "evaluation_round", "dimension_key", "rubric_role", "level", "value"]
    for row in rows:
        row["batch_id"] = batch_id
    return columns, rows


@app.get("/api/evaluation-batches/<int:batch_id>/export.csv")  # CSV izvoz serije za analizu (samo ADMIN)
@role_required(["ADMIN"])
def export_evaluation_batch(batch_id):
    kind = request.args.get("kind", "artifacts")
    if kind not in EXPORT_KINDS:
        return jsonify({"error": f"kind mora biti jedno od: {', '.join(EXPORT_KINDS)}"}), 400
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        missing = [t for t, cols in EXPORT_REQUIRED_COLUMNS.items() if not table_columns_exist(cursor, t, cols)]
        if missing:
            return jsonify({"error": f"Za izvoz nedostaju kolone/tabele ({', '.join(missing)}) - pokrenite migracije iz db/"}), 409
        cursor.execute("SELECT id FROM evaluation_batches WHERE id = %s", (batch_id,))
        if not cursor.fetchone():
            return jsonify({"error": "Batch not found"}), 404
        builder = {"artifacts": _export_artifacts, "runs": _export_runs, "evaluations": _export_evaluations}[kind]
        columns, rows = builder(cursor, batch_id)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: ("" if v is None else v) for k, v in row.items()})
    return app.response_class(
        "\ufeff" + buffer.getvalue(),  # BOM: Excel ispravno čita č/ć/š
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=serija_{batch_id}_{kind}.csv"},
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)

