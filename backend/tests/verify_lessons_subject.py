"""Provera veze lekcija ↔ predmet (lessons.subject_id) kroz rute lekcija.

Pokretanje (iz foldera backend/):
    python tests/verify_lessons_subject.py

Pravi privremeni jezik, predmete, nastavnika, studente i lekcije (oznaka tmp-ls-*),
sve briše na kraju i poredi broj redova pre i posle. Bez AI poziva.

Namerno pravi lekciju čiji se language_id NE poklapa sa subject_id, i studenta
upisanog u predmet čiji je id jednak tom language_id: filtriranje mora da ide
preko subject_id, pa taj student lekciju ne sme da vidi.
"""
import os
import sys
import uuid

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

from app import app, get_db_connection  # noqa: E402
from flask_jwt_extended import create_access_token  # noqa: E402

TAG = uuid.uuid4().hex[:5]
PREFIX = f"tmp-ls-{TAG}"
COUNTED = ("lessons", "subjects", "languages", "users", "teacher_subjects", "student_subjects", "favorite_lessons")
MISSING_SUBJECT = 999999999
results = []
client = app.test_client()


def db_all(sql, params=()):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


def db_exec(sql, params=()):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        conn.commit()
        return cur.lastrowid
    finally:
        cur.close()
        conn.close()


def counts():
    return {t: db_all(f"SELECT COUNT(*) AS n FROM {t}")[0]["n"] for t in COUNTED}


def record(case, expected, got, ok):
    results.append((case, expected, got, "OK" if ok else "PALO"))


def make_user(label, role):
    role_id = db_all("SELECT id FROM roles WHERE name = %s", (role,))[0]["id"]
    user_id = db_exec("INSERT INTO users (email, password_hash, role_id, display_name, is_active) VALUES (%s, 'x', %s, %s, 1)",
                      (f"{PREFIX}-{label}@example.invalid", role_id, f"{PREFIX} {label}"))
    with app.app_context():
        token = create_access_token(identity=str(user_id), additional_claims={"role": role, "email": "verify"})
    return user_id, {"Authorization": f"Bearer {token}"}


def lesson_row(title):
    rows = db_all("SELECT id, language_id, subject_id FROM lessons WHERE title = %s", (title,))
    return rows[0] if rows else None


def lesson_body(title, language_id, subject_id=None):
    body = {"language_id": language_id, "title": title, "content": "<p>proba</p>"}
    if subject_id is not None:
        body["subject_id"] = subject_id
    return body


def listed_ids(headers):
    resp = client.get("/api/lessons", headers=headers)
    return resp.status_code, {r["id"] for r in (resp.get_json(silent=True) or [])}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    before = counts()
    try:
        # id X je isti za privremeni jezik i predmet (rezerva subject_id = language_id)
        x = max(db_all("SELECT COALESCE(MAX(id), 0) AS m FROM languages")[0]["m"],
                db_all("SELECT COALESCE(MAX(id), 0) AS m FROM subjects")[0]["m"]) + 1
        db_exec("INSERT INTO languages (id, code, name) VALUES (%s, %s, %s)", (x, f"l{TAG}", f"{PREFIX} jezik"))
        db_exec("INSERT INTO subjects (id, code, name) VALUES (%s, %s, %s)", (x, f"x{TAG}", f"{PREFIX} predmet X"))
        subj_a = db_exec("INSERT INTO subjects (code, name) VALUES (%s, %s)", (f"a{TAG}", f"{PREFIX} predmet A"))
        subj_b = db_exec("INSERT INTO subjects (code, name) VALUES (%s, %s)", (f"b{TAG}", f"{PREFIX} predmet B"))

        _, admin = make_user("admin", "ADMIN")
        teacher_id, teacher = make_user("teacher", "TEACHER")
        student_a_id, student_a = make_user("student-a", "STUDENT")
        student_x_id, student_x = make_user("student-x", "STUDENT")
        for s in (subj_a, x):
            db_exec("INSERT INTO teacher_subjects (teacher_id, subject_id) VALUES (%s, %s)", (teacher_id, s))
        db_exec("INSERT INTO student_subjects (student_id, subject_id) VALUES (%s, %s)", (student_a_id, subj_a))
        db_exec("INSERT INTO student_subjects (student_id, subject_id) VALUES (%s, %s)", (student_x_id, x))

        # --- dodavanje sa predmetom (language_id X, subject_id A: namerno se ne poklapaju) ---
        t1 = f"{PREFIX}-1"
        resp = client.post("/api/lessons", json=lesson_body(t1, x, subj_a), headers=admin)
        body = resp.get_json(silent=True) or {}
        row = lesson_row(t1) or {}
        record("ADMIN: dodavanje sa subject_id", f"201, u bazi subject_id={subj_a}, language_id={x}, naziv predmeta u odgovoru",
               f"{resp.status_code}, subject_id={row.get('subject_id')}, language_id={row.get('language_id')}, {body.get('subject_name')!r}",
               resp.status_code == 201 and row.get("subject_id") == subj_a and row.get("language_id") == x
               and body.get("subject_id") == subj_a and body.get("subject_name") == f"{PREFIX} predmet A")

        # --- rezerva: frontend šalje samo language_id ---
        t2 = f"{PREFIX}-2"
        resp = client.post("/api/lessons", json=lesson_body(t2, x), headers=admin)
        row = lesson_row(t2) or {}
        record("dodavanje samo sa language_id (rezerva)", f"201, subject_id={x}",
               f"{resp.status_code}, subject_id={row.get('subject_id')}",
               resp.status_code == 201 and row.get("subject_id") == x)

        # --- nepostojeći predmet se odbija ---
        t3 = f"{PREFIX}-3"
        resp = client.post("/api/lessons", json=lesson_body(t3, x, MISSING_SUBJECT), headers=admin)
        record("dodavanje sa nepostojecim predmetom", "400 Subject not found, lekcija nije napravljena",
               f"{resp.status_code} {(resp.get_json(silent=True) or {}).get('error')}, lekcija: {'DA' if lesson_row(t3) else 'ne'}",
               resp.status_code == 400 and lesson_row(t3) is None)
        resp = client.put(f"/api/lessons/{lesson_row(t1)['id']}", json=lesson_body(t1, x, MISSING_SUBJECT), headers=admin)
        record("izmena na nepostojeci predmet", f"400, subject_id ostaje {subj_a}",
               f"{resp.status_code}, subject_id={lesson_row(t1)['subject_id']}",
               resp.status_code == 400 and lesson_row(t1)["subject_id"] == subj_a)
        resp = client.put("/api/lessons/999999999", json=lesson_body(t1, x, subj_a), headers=admin)
        record("izmena nepostojece lekcije", "404", resp.status_code, resp.status_code == 404)

        # --- nastavnik: samo predmeti koje predaje ---
        t4 = f"{PREFIX}-4"
        resp = client.post("/api/lessons", json=lesson_body(t4, x, subj_b), headers=teacher)
        record("TEACHER: dodavanje za predmet koji ne predaje", "403, lekcija nije napravljena",
               f"{resp.status_code}, lekcija: {'DA' if lesson_row(t4) else 'ne'}",
               resp.status_code == 403 and lesson_row(t4) is None)
        t5 = f"{PREFIX}-5"
        resp = client.post("/api/lessons", json=lesson_body(t5, x, subj_a), headers=teacher)
        record("TEACHER: dodavanje za svoj predmet", f"201, subject_id={subj_a}",
               f"{resp.status_code}, subject_id={(lesson_row(t5) or {}).get('subject_id')}",
               resp.status_code == 201 and (lesson_row(t5) or {}).get("subject_id") == subj_a)

        t6 = f"{PREFIX}-6"
        client.post("/api/lessons", json=lesson_body(t6, x, subj_b), headers=admin)
        id6 = lesson_row(t6)["id"]
        resp = client.put(f"/api/lessons/{id6}", json=lesson_body(t6, x, subj_a), headers=teacher)
        record("TEACHER: izmena tudje lekcije (prebacivanje u svoj predmet)", f"403, subject_id ostaje {subj_b}",
               f"{resp.status_code}, subject_id={lesson_row(t6)['subject_id']}",
               resp.status_code == 403 and lesson_row(t6)["subject_id"] == subj_b)
        id5 = lesson_row(t5)["id"]
        resp = client.put(f"/api/lessons/{id5}", json=lesson_body(t5, x, subj_b), headers=teacher)
        record("TEACHER: izmena svoje lekcije u predmet koji ne predaje", f"403, subject_id ostaje {subj_a}",
               f"{resp.status_code}, subject_id={lesson_row(t5)['subject_id']}",
               resp.status_code == 403 and lesson_row(t5)["subject_id"] == subj_a)
        resp = client.put(f"/api/lessons/{id5}", json={**lesson_body(t5, x, x), "content": "<p>izmena</p>"}, headers=teacher)
        body = resp.get_json(silent=True) or {}
        record("TEACHER: izmena svoje lekcije u drugi svoj predmet", f"200, subject_id={x}, naziv u odgovoru",
               f"{resp.status_code}, subject_id={lesson_row(t5)['subject_id']}, {body.get('subject_name')!r}",
               resp.status_code == 200 and lesson_row(t5)["subject_id"] == x and body.get("subject_name") == f"{PREFIX} predmet X")
        resp = client.put(f"/api/lessons/{id6}", json={**lesson_body(t6, x, subj_a), "content": "<p>izmena</p>"}, headers=admin)
        record("ADMIN: izmena bilo koje lekcije", f"200, subject_id={subj_a}",
               f"{resp.status_code}, subject_id={lesson_row(t6)['subject_id']}",
               resp.status_code == 200 and lesson_row(t6)["subject_id"] == subj_a)

        # --- filtriranje po subject_id ---
        id1, id2 = lesson_row(t1)["id"], lesson_row(t2)["id"]
        code, ids_a = listed_ids(student_a)
        record("student predmeta A vidi lekcije predmeta A", f"{id1}, {id6} da; {id2}, {id5} ne",
               f"{code}, {sorted(ids_a & {id1, id2, id5, id6})}",
               code == 200 and {id1, id6} <= ids_a and not ({id2, id5} & ids_a))
        code, ids_x = listed_ids(student_x)
        record(f"student predmeta X (id = language_id lekcije {id1}) ne vidi je", f"{id2}, {id5} da; {id1}, {id6} ne",
               f"{code}, {sorted(ids_x & {id1, id2, id5, id6})}",
               code == 200 and {id2, id5} <= ids_x and not ({id1, id6} & ids_x))
        code, ids_t = listed_ids(teacher)
        record("nastavnik (A i X) vidi sve cetiri", "sve cetiri", f"{code}, {sorted(ids_t & {id1, id2, id5, id6})}",
               code == 200 and {id1, id2, id5, id6} <= ids_t)

        # --- predmet u odgovorima: lista, detalj, omiljene ---
        resp = client.get("/api/lessons", headers=student_a)
        item = next((r for r in resp.get_json() if r["id"] == id1), {})
        record("lista: subject_id, subject_name, language_id", f"{subj_a}, predmet A, {x}",
               f"{item.get('subject_id')}, {item.get('subject_name')!r}, {item.get('language_id')}",
               item.get("subject_id") == subj_a and item.get("subject_name") == f"{PREFIX} predmet A" and item.get("language_id") == x)
        resp = client.get(f"/api/lessons/{id1}", headers=student_a)
        item = resp.get_json(silent=True) or {}
        record("detalj: subject_id, subject_name, language_id", f"200, {subj_a}, predmet A, {x}",
               f"{resp.status_code}, {item.get('subject_id')}, {item.get('subject_name')!r}, {item.get('language_id')}",
               resp.status_code == 200 and item.get("subject_id") == subj_a
               and item.get("subject_name") == f"{PREFIX} predmet A" and item.get("language_id") == x)
        client.post(f"/api/lessons/{id1}/favorite", headers=student_a)
        resp = client.get("/api/favorites", headers=student_a)
        item = next((r for r in (resp.get_json(silent=True) or []) if r["id"] == id1), {})
        record("omiljene: subject_id, subject_name, language_id", f"200, {subj_a}, predmet A, {x}",
               f"{resp.status_code}, {item.get('subject_id')}, {item.get('subject_name')!r}, {item.get('language_id')}",
               resp.status_code == 200 and item.get("subject_id") == subj_a
               and item.get("subject_name") == f"{PREFIX} predmet A" and item.get("language_id") == x)
    finally:
        lesson_ids = [r["id"] for r in db_all("SELECT id FROM lessons WHERE title LIKE %s", (f"{PREFIX}-%",))]
        for lesson_id in lesson_ids:
            db_exec("DELETE FROM favorite_lessons WHERE lesson_id = %s", (lesson_id,))
            db_exec("DELETE FROM lessons WHERE id = %s", (lesson_id,))
        db_exec("DELETE FROM users WHERE email LIKE %s", (f"{PREFIX}-%",))
        db_exec("DELETE FROM subjects WHERE name LIKE %s", (f"{PREFIX} %",))
        db_exec("DELETE FROM languages WHERE name LIKE %s", (f"{PREFIX} %",))
    after = counts()
    record("brojevi redova pre = posle", before, after, before == after)

    width = max(len(r[0]) for r in results)
    for case, expected, got, status in results:
        print(f"{status:4}  {case:<{width}}  ocekivano: {expected}  dobijeno: {got}")
    failed = sum(r[3] == "PALO" for r in results)
    print(f"\n{len(results) - failed}/{len(results)} OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
