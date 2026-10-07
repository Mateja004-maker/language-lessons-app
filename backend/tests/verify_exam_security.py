"""Provera bezbednosnih popravki za testove (submit_exam / publish_exam).

Pokretanje (iz foldera backend/):
    python tests/verify_exam_security.py

Gadja stvarne rute kroz app.test_client() nad stvarnom bazom iz backend/.env.
JWT tokeni se prave u procesu (create_access_token) za privremene korisnike -
skript ne sadrzi nikakve kljuceve ni lozinke. Svi privremeni podaci se prave
ovde, njihovi id-jevi se belezi i na kraju se brisu (i kad provera padne).
"""
import os
import sys
import threading
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask_jwt_extended import create_access_token  # noqa: E402

from app import app, get_db_connection  # noqa: E402

ROLE_IDS = {"ADMIN": 1, "TEACHER": 2, "STUDENT": 3}

created = {
    "subjects": [],
    "users": [],
    "exams": [],
    "questions": [],
}
results = []


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


def db_one(sql, params=()):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        return cur.fetchone()
    finally:
        cur.close()
        conn.close()


def db_all(sql, params=()):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


# ---------- privremeni podaci ----------

TAG = uuid.uuid4().hex[:6]


def make_subject(label):
    sid = db_exec("INSERT INTO subjects (code, name) VALUES (%s, %s)", (f"T{label}{TAG}"[:10], f"tmp-verify {label} {TAG}"))
    created["subjects"].append(sid)
    return sid


def make_user(role, label, subject_ids=()):
    uid = db_exec(
        "INSERT INTO users (email, password_hash, role_id, display_name, is_active) VALUES (%s, '!', %s, %s, 1)",
        (f"tmp-verify-{TAG}-{label}@example.invalid", ROLE_IDS[role], f"tmp {label}"),
    )
    created["users"].append(uid)
    table, column = {"STUDENT": ("student_subjects", "student_id"), "TEACHER": ("teacher_subjects", "teacher_id")}.get(role, (None, None))
    for sid in subject_ids:
        db_exec(f"INSERT INTO {table} ({column}, subject_id) VALUES (%s, %s)", (uid, sid))
    with app.app_context():
        token = create_access_token(identity=str(uid), additional_claims={"role": role, "email": f"tmp-{label}"})
    return {"id": uid, "headers": {"Authorization": f"Bearer {token}"}}


def make_exam(subject_id, created_by, published, open_sql="NULL", close_sql="NULL", duration=30):
    # open_sql/close_sql su SQL izrazi (npr. NOW() + INTERVAL 1 DAY) da vreme bude isto kao u bazi.
    eid = db_exec(
        f"""INSERT INTO exams (title, subject_id, level, duration_minutes, open_at, close_at, is_published, created_by)
            VALUES (%s, %s, 'A1', %s, {open_sql}, {close_sql}, %s, %s)""",
        (f"tmp-verify {TAG}", subject_id, duration, 1 if published else 0, created_by),
    )
    created["exams"].append(eid)
    return eid


def make_question(subject_id, points, answers):
    """answers: lista (tekst, is_correct). Vraca (question_id, [answer_id, ...])."""
    qid = db_exec(
        "INSERT INTO exam_questions (subject_id, question_text, points) VALUES (%s, %s, %s)",
        (subject_id, f"tmp-verify pitanje {TAG}", points),
    )
    created["questions"].append(qid)
    answer_ids = [
        db_exec("INSERT INTO exam_answers (question_id, answer_text, is_correct) VALUES (%s, %s, %s)", (qid, text, int(ok)))
        for text, ok in answers
    ]
    return qid, answer_ids


def attach(exam_id, question_id, order_no):
    db_exec("INSERT INTO exam_test_questions (exam_id, question_id, order_no) VALUES (%s, %s, %s)", (exam_id, question_id, order_no))


def cleanup():
    exams = created["exams"]
    questions = created["questions"]
    users = created["users"]
    subjects = created["subjects"]

    def ph(ids):
        return ",".join(["%s"] * len(ids))

    if exams:
        db_exec(f"DELETE eaa FROM exam_attempt_answers eaa JOIN exam_attempts ea ON ea.id = eaa.attempt_id WHERE ea.exam_id IN ({ph(exams)})", exams)
        db_exec(f"DELETE FROM exam_attempts WHERE exam_id IN ({ph(exams)})", exams)
        db_exec(f"DELETE FROM exam_test_questions WHERE exam_id IN ({ph(exams)})", exams)
    if questions:
        db_exec(f"DELETE FROM exam_test_questions WHERE question_id IN ({ph(questions)})", questions)
        db_exec(f"DELETE FROM exam_answers WHERE question_id IN ({ph(questions)})", questions)
        db_exec(f"DELETE FROM exam_questions WHERE id IN ({ph(questions)})", questions)
    if exams:
        db_exec(f"DELETE FROM exams WHERE id IN ({ph(exams)})", exams)
    if users:
        db_exec(f"DELETE FROM student_subjects WHERE student_id IN ({ph(users)})", users)
        db_exec(f"DELETE FROM teacher_subjects WHERE teacher_id IN ({ph(users)})", users)
        db_exec(f"DELETE FROM users WHERE id IN ({ph(users)})", users)
    if subjects:
        db_exec(f"DELETE FROM subjects WHERE id IN ({ph(subjects)})", subjects)


# ---------- provere ----------

def record(case, expected, got, ok):
    results.append((case, expected, got, "OK" if ok else "PALO"))


def count_attempts(exam_id, student_id, status=None):
    sql = "SELECT COUNT(*) AS n FROM exam_attempts WHERE exam_id = %s AND student_id = %s"
    params = [exam_id, student_id]
    if status:
        sql += " AND status = %s"
        params.append(status)
    return db_one(sql, params)["n"]


def check_status(case, response, expected_status):
    record(case, str(expected_status), f"{response.status_code} {response.get_json()}", response.status_code == expected_status)


def run():
    client = app.test_client()

    subj_a = make_subject("A")
    subj_b = make_subject("B")

    student = make_user("STUDENT", "student", [subj_a])
    student_conc = make_user("STUDENT", "student-conc", [subj_a])
    teacher = make_user("TEACHER", "teacher", [subj_a])
    admin = make_user("ADMIN", "admin")

    # MC pitanja: q1 = 2 boda (tacan a1_ok), q2 = 3 boda (tacan a2_ok)
    q1, (a1_ok, a1_bad) = make_question(subj_a, 2, [("tacan", True), ("netacan", False)])
    q2, (a2_bad, a2_ok) = make_question(subj_a, 3, [("netacan", False), ("tacan", True)])
    q_no_correct, _ = make_question(subj_a, 1, [("x", False), ("y", False)])
    q_b, (ab_ok, _) = make_question(subj_b, 1, [("tacan", True), ("netacan", False)])

    def mc_exam(subject_id, published, **kw):
        eid = make_exam(subject_id, teacher["id"], published, **kw)
        if subject_id == subj_a:
            attach(eid, q1, 1)
            attach(eid, q2, 2)
        else:
            attach(eid, q_b, 1)
        return eid

    exam_ok = mc_exam(subj_a, True)
    exam_draft = mc_exam(subj_a, False)
    exam_other_subject = mc_exam(subj_b, True)
    exam_future = mc_exam(subj_a, True, open_sql="NOW() + INTERVAL 1 DAY")
    exam_expired = mc_exam(subj_a, True, close_sql="NOW() - INTERVAL 33 MINUTE", duration=30)
    exam_grace = mc_exam(subj_a, True, close_sql="NOW() - INTERVAL 20 MINUTE", duration=30)
    exam_conc = mc_exam(subj_a, True)
    exam_other_subject_draft = mc_exam(subj_b, False)
    exam_no_correct = make_exam(subj_a, teacher["id"], False)
    attach(exam_no_correct, q_no_correct, 1)

    missing_exam = (db_one("SELECT COALESCE(MAX(id), 0) AS m FROM exams")["m"]) + 100000

    good_answers = {str(q1): a1_ok, str(q2): a2_bad}  # q1 tacno (2), q2 netacno (0)

    def submit(exam_id, user, body):
        return client.post(f"/api/exams/{exam_id}/submit", headers=user["headers"], json=body)

    # --- submit_exam ---
    check_status("predaja u draftu", submit(exam_draft, student, {"answers": good_answers}), 403)
    check_status("predaja kao TEACHER", submit(exam_ok, teacher, {"answers": good_answers}), 403)
    check_status("predaja testa tudjeg predmeta", submit(exam_other_subject, student, {"answers": {str(q_b): ab_ok}}), 403)
    check_status("predaja pre open_at", submit(exam_future, student, {"answers": good_answers}), 403)
    check_status("predaja posle close_at + duration + 2 min", submit(exam_expired, student, {"answers": good_answers}), 403)

    before = count_attempts(exam_ok, student["id"])
    r = submit(exam_ok, student, {"answers": {str(q1): a2_ok}})  # odgovor drugog pitanja
    after = count_attempts(exam_ok, student["id"])
    record("answer_id ne pripada pitanju (+ nema novog pokusaja)", "400, pokusaja 0 -> 0",
           f"{r.status_code}, pokusaja {before} -> {after}", r.status_code == 400 and before == after == 0)

    r = submit(exam_ok, student, {"answers": {str(q1): 999999999}})
    after = count_attempts(exam_ok, student["id"])
    record("answer_id ne postoji (+ nema novog pokusaja)", "400, pokusaja 0",
           f"{r.status_code}, pokusaja {after}", r.status_code == 400 and after == 0)

    check_status("answers nije dict", submit(exam_ok, student, {"answers": [a1_ok, a2_ok]}), 400)
    check_status("answers kljuc nije ceo broj", submit(exam_ok, student, {"answers": {"abc": a1_ok}}), 400)
    check_status("tab_warnings negativan", submit(exam_ok, student, {"answers": good_answers, "tab_warnings": -1}), 400)
    check_status("tab_warnings preko maksimuma", submit(exam_ok, student, {"answers": good_answers, "tab_warnings": 1001}), 400)
    check_status("nepostojeci test", submit(missing_exam, student, {"answers": good_answers}), 404)
    record("posle svih odbijenih predaja nema pokusaja", "0", str(count_attempts(exam_ok, student["id"])),
           count_attempts(exam_ok, student["id"]) == 0)

    # --- publish_exam ---
    r = client.put(f"/api/exams/{exam_other_subject_draft}/publish", headers=teacher["headers"])
    still_draft = db_one("SELECT is_published FROM exams WHERE id = %s", (exam_other_subject_draft,))["is_published"] == 0
    record("publish tudjeg testa kao TEACHER", "403, ostaje draft", f"{r.status_code}, draft={still_draft}", r.status_code == 403 and still_draft)

    r = client.put(f"/api/exams/{exam_no_correct}/publish", headers=teacher["headers"])
    record("publish testa bez tacnog odgovora", "400", f"{r.status_code} {r.get_json()}", r.status_code == 400)

    check_status("publish nepostojeceg testa", client.put(f"/api/exams/{missing_exam}/publish", headers=admin["headers"]), 404)

    r = client.put(f"/api/exams/{exam_draft}/publish", headers=teacher["headers"])
    published = db_one("SELECT is_published FROM exams WHERE id = %s", (exam_draft,))["is_published"] == 1
    record("publish ispravnog testa svog predmeta", "200, objavljen", f"{r.status_code}, objavljen={published}", r.status_code == 200 and published)

    r = client.put(f"/api/exams/{exam_draft}/publish", headers=admin["headers"])
    check_status("publish vec objavljenog (idempotentno)", r, 200)

    # --- normalna predaja ---
    r = submit(exam_ok, student, {"answers": good_answers, "tab_warnings": 3})
    body = r.get_json() or {}
    attempt = db_one("SELECT * FROM exam_attempts WHERE id = %s", (body.get("attempt_id"),)) or {}
    rows = db_all(
        "SELECT question_id, answer_id, is_correct, points_awarded FROM exam_attempt_answers WHERE attempt_id = %s ORDER BY question_id",
        (body.get("attempt_id"),),
    )
    expected_rows = sorted([
        {"question_id": q1, "answer_id": a1_ok, "is_correct": 1, "points_awarded": 2},
        {"question_id": q2, "answer_id": a2_bad, "is_correct": 0, "points_awarded": 0},
    ], key=lambda x: x["question_id"])
    ok = (
        r.status_code == 200
        and set(body) == {"attempt_id", "score", "total"}
        # total je SUM() -> Decimal, jsonify ga vraca kao string "5" (tako je bilo i pre popravki)
        and body["score"] == 2 and str(body["total"]) == "5"
        and attempt.get("status") == "COMPLETED" and attempt.get("score") == 2
        and attempt.get("total_points") == 5 and attempt.get("tab_warnings") == 3
        and rows == expected_rows
    )
    record("normalna predaja MC testa", "200 {attempt_id, score:2, total:5}, 2 reda odgovora",
           f"{r.status_code} score={body.get('score')} total={body.get('total')} redova={len(rows)}", ok)

    check_status("ponovna predaja istog testa", submit(exam_ok, student, {"answers": good_answers}), 400)

    r = submit(exam_grace, student, {"answers": good_answers})
    check_status("predaja posle close_at ali unutar duration + 2 min", r, 200)

    # --- dve istovremene predaje ---
    barrier = threading.Barrier(2)
    statuses = []

    def concurrent_submit():
        local_client = app.test_client()
        barrier.wait()
        resp = local_client.post(f"/api/exams/{exam_conc}/submit", headers=student_conc["headers"], json={"answers": good_answers})
        statuses.append(resp.status_code)

    threads = [threading.Thread(target=concurrent_submit) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    completed = count_attempts(exam_conc, student_conc["id"], "COMPLETED")
    total_attempts = count_attempts(exam_conc, student_conc["id"])
    record("dve istovremene predaje istog studenta", "tacno 1 COMPLETED, 0 ostalih",
           f"statusi {sorted(statuses)}, COMPLETED={completed}, ukupno={total_attempts}",
           completed == 1 and total_attempts == 1)


def print_table():
    headers = ("Slucaj", "Ocekivano", "Dobijeno", "")
    rows = [(c, e, g if len(g) <= 90 else g[:87] + "...", s) for c, e, g, s in results]
    widths = [max(len(str(r[i])) for r in rows + [headers]) for i in range(4)]
    line = " | ".join(h.ljust(w) for h, w in zip(headers, widths))
    print(line)
    print("-" * len(line))
    for r in rows:
        print(" | ".join(str(v).ljust(w) for v, w in zip(r, widths)))
    failed = sum(1 for r in results if r[3] != "OK")
    print(f"\nUkupno: {len(results)}, palo: {failed}")
    return failed


if __name__ == "__main__":
    try:
        run()
    finally:
        cleanup()
        leftover = db_one("SELECT COUNT(*) AS n FROM users WHERE email LIKE %s", (f"tmp-verify-{TAG}-%",))["n"]
        print(f"Privremeni podaci obrisani (preostalo korisnika sa tagom {TAG}: {leftover})\n")
    sys.exit(1 if print_table() else 0)
