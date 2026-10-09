"""Provera ADMIN rada sa predmetima: dodavanje, izmena naziva, brisanje (zaštićeno)
i broj lekcija u listi predmeta.

Pokretanje (iz foldera backend/):
    python tests/verify_subjects_crud.py

Pravi privremene predmete, korisnike, oblast, lekciju, pitanje, test i referentni
skup (oznaka tmp-sc-*), sve briše na kraju i poredi broj redova pre i posle. Bez AI poziva.
"""
import os
import sys
import uuid

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

from app import app, get_db_connection  # noqa: E402
from flask_jwt_extended import create_access_token  # noqa: E402

TAG = uuid.uuid4().hex[:5]
PREFIX = f"tmp-sc-{TAG}"
COUNTED = ("subjects", "users", "teacher_subjects", "student_subjects", "areas", "lessons",
           "exam_questions", "exams", "reference_sets")
MISSING = 999999999
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


def subject(name):
    rows = db_all("SELECT id, code, name FROM subjects WHERE name = %s", (name,))
    return rows[0] if rows else None


def call(method, url, headers, body=None):
    resp = getattr(client, method)(url, json=body, headers=headers)
    return resp.status_code, (resp.get_json(silent=True) or {})


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    before = counts()
    try:
        _, admin = make_user("admin", "ADMIN")
        teacher_id, teacher = make_user("teacher", "TEACHER")
        student_id, student = make_user("student", "STUDENT")

        # --- dodavanje ---
        name1 = f"{PREFIX} Predmet"
        code, body = call("post", "/api/subjects", admin, {"name": name1, "code": f"a{TAG}"})
        row = subject(name1)
        record("ADMIN: dodavanje predmeta", "201, predmet u bazi, lesson_count 0",
               f"{code}, {'u bazi' if row else 'NEMA'}, {body.get('lesson_count')}",
               code == 201 and row is not None and body.get("id") == row["id"] and body.get("lesson_count") == 0)
        for label, payload in (("isti naziv drugim slovima", {"name": name1.upper(), "code": f"b{TAG}"}),
                               ("isti naziv sa razmacima", {"name": f"  {name1.lower()}  ", "code": f"c{TAG}"}),
                               ("ista oznaka", {"name": f"{PREFIX} Drugi", "code": f"A{TAG}"})):
            code, body = call("post", "/api/subjects", admin, payload)
            record(f"duplikat: {label}", "409, poruka na srpskom, nije dodat",
                   f"{code} {body.get('error')!r}",
                   code == 409 and "već postoji" in (body.get("error") or "")
                   and len(db_all("SELECT id FROM subjects WHERE name LIKE %s", (f"%{TAG}%",))) == 1)
        for label, payload in (("prazan naziv", {"name": "   ", "code": f"d{TAG}"}),
                               ("bez oznake", {"name": f"{PREFIX} Bez oznake"}),
                               ("predugacak naziv", {"name": "x" * 81, "code": f"e{TAG}"})):
            code, body = call("post", "/api/subjects", admin, payload)
            record(f"odbijeno: {label}", "400", f"{code} {body.get('error')!r}", code == 400)

        # --- izmena naziva ---
        sid = subject(name1)["id"]
        name2 = f"{PREFIX} Novi naziv"
        code, body = call("put", f"/api/subjects/{sid}", admin, {"name": name2})
        record("ADMIN: izmena naziva", f"200, naziv {name2!r}", f"{code}, {(subject(name2) or {}).get('id') == sid}",
               code == 200 and subject(name2) is not None and subject(name2)["id"] == sid)
        code, body = call("put", f"/api/subjects/{sid}", admin, {"name": name2.upper()})
        record("izmena: isti predmet, druga velika/mala slova", "200 (nije duplikat samog sebe)", code, code == 200)
        call("put", f"/api/subjects/{sid}", admin, {"name": name2})
        other = db_all("SELECT name FROM subjects WHERE name NOT LIKE %s ORDER BY id LIMIT 1", (f"%{TAG}%",))[0]["name"]
        code, body = call("put", f"/api/subjects/{sid}", admin, {"name": other.lower()})
        record("izmena: naziv drugog predmeta", f"409, naziv ostaje {name2!r}", f"{code} {body.get('error')!r}",
               code == 409 and subject(name2) is not None)
        code, _ = call("put", f"/api/subjects/{sid}", admin, {"name": ""})
        record("izmena: prazan naziv", "400", code, code == 400)
        code, _ = call("put", f"/api/subjects/{MISSING}", admin, {"name": f"{PREFIX} x"})
        record("izmena nepostojeceg predmeta", "404", code, code == 404)

        # --- samo ADMIN ---
        for who, headers in (("TEACHER", teacher), ("STUDENT", student)):
            codes = [call("post", "/api/subjects", headers, {"name": f"{PREFIX} {who}", "code": f"t{TAG}"})[0],
                     call("put", f"/api/subjects/{sid}", headers, {"name": f"{PREFIX} {who}"})[0],
                     call("delete", f"/api/subjects/{sid}", headers)[0]]
            record(f"{who}: dodavanje / izmena / brisanje", "403 / 403 / 403, nista se ne menja", codes,
                   codes == [403, 403, 403] and subject(f"{PREFIX} {who}") is None and subject(name2) is not None)

        # --- brisanje praznog predmeta ---
        code, body = call("delete", f"/api/subjects/{sid}", admin)
        record("ADMIN: brisanje praznog predmeta", "200, obrisan", f"{code}, {'OSTAO' if subject(name2) else 'obrisan'}",
               code == 200 and subject(name2) is None)
        code, _ = call("delete", f"/api/subjects/{MISSING}", admin)
        record("brisanje nepostojeceg predmeta", "404", code, code == 404)

        # --- brisanje zauzetog predmeta: svaka vrsta upotrebe posebno ---
        busy_name = f"{PREFIX} Zauzet"
        call("post", "/api/subjects", admin, {"name": busy_name, "code": f"z{TAG}"})
        busy = subject(busy_name)["id"]
        usages = (
            ("nastavnici", lambda: db_exec("INSERT INTO teacher_subjects (teacher_id, subject_id) VALUES (%s, %s)", (teacher_id, busy)),
             lambda: db_exec("DELETE FROM teacher_subjects WHERE subject_id = %s", (busy,))),
            ("studenti", lambda: db_exec("INSERT INTO student_subjects (student_id, subject_id) VALUES (%s, %s)", (student_id, busy)),
             lambda: db_exec("DELETE FROM student_subjects WHERE subject_id = %s", (busy,))),
            ("oblasti", lambda: db_exec("INSERT INTO areas (subject_id, name) VALUES (%s, %s)", (busy, f"{PREFIX} oblast")),
             lambda: db_exec("DELETE FROM areas WHERE subject_id = %s", (busy,))),
            ("lekcije", lambda: db_exec("INSERT INTO lessons (subject_id, level, title) VALUES (%s, '', %s)", (busy, f"{PREFIX} lekcija")),
             lambda: db_exec("DELETE FROM lessons WHERE subject_id = %s", (busy,))),
            ("pitanja", lambda: db_exec("INSERT INTO exam_questions (subject_id, question_text) VALUES (%s, %s)", (busy, f"{PREFIX} pitanje")),
             lambda: db_exec("DELETE FROM exam_questions WHERE subject_id = %s", (busy,))),
            ("testovi", lambda: db_exec("INSERT INTO exams (subject_id, title, level) VALUES (%s, %s, 'A1')", (busy, f"{PREFIX} test")),
             lambda: db_exec("DELETE FROM exams WHERE subject_id = %s", (busy,))),
            ("referentni skupovi", lambda: db_exec("INSERT INTO reference_sets (subject_id, name) VALUES (%s, %s)", (busy, f"{PREFIX} skup")),
             lambda: db_exec("DELETE FROM reference_sets WHERE subject_id = %s", (busy,))),
        )
        for label, add, remove in usages:
            add()
            code, body = call("delete", f"/api/subjects/{busy}", admin)
            error = body.get("error") or ""
            record(f"brisanje zauzetog predmeta: {label}", f"409, poruka navodi '{label} (1)', predmet ostaje",
                   f"{code} {error!r}",
                   code == 409 and f"{label} (1)" in error and body.get("usage") == [{"what": label, "count": 1}]
                   and subject(busy_name) is not None)
            remove()

        # vise upotreba odjednom: poruka navodi sve, sa brojem
        usages[0][1]()
        usages[3][1]()
        db_exec("INSERT INTO lessons (subject_id, level, title) VALUES (%s, '', %s)", (busy, f"{PREFIX} lekcija 2"))
        code, body = call("delete", f"/api/subjects/{busy}", admin)
        error = body.get("error") or ""
        record("brisanje zauzetog: vise upotreba", "409, 'nastavnici (1), lekcije (2)'", f"{code} {error!r}",
               code == 409 and "nastavnici (1), lekcije (2)" in error and subject(busy_name) is not None)

        # --- broj lekcija u listi predmeta (ADMIN sve, nastavnik svoje) ---
        code, body = call("get", "/api/subjects", admin)
        expected = {r["id"]: r["n"] for r in db_all(
            "SELECT s.id, (SELECT COUNT(*) FROM lessons l WHERE l.subject_id = s.id) AS n FROM subjects s")}
        got = {r["id"]: r.get("lesson_count") for r in body} if isinstance(body, list) else {}
        record("ADMIN lista predmeta: lesson_count za svaki predmet", "isto kao u bazi",
               f"{code}, {len(got)} predmeta, {'isto' if got == expected else 'RAZLIKUJE SE'}", code == 200 and got == expected)
        record("lesson_count zauzetog predmeta", 2, got.get(busy), got.get(busy) == 2)
        code, body = call("get", "/api/subjects", teacher)
        record("nastavnik: lista samo svojih predmeta, sa lesson_count", f"200, [{busy}] sa 2 lekcije",
               f"{code}, {[(r['id'], r.get('lesson_count')) for r in body] if isinstance(body, list) else body}",
               code == 200 and [(r["id"], r.get("lesson_count")) for r in body] == [(busy, 2)])
        for _, _, remove in usages:
            remove()
        code, _ = call("delete", f"/api/subjects/{busy}", admin)
        record("brisanje posle uklanjanja svih upotreba", "200", code, code == 200 and subject(busy_name) is None)
    finally:
        tmp_subjects = [r["id"] for r in db_all("SELECT id FROM subjects WHERE name LIKE %s OR code LIKE %s",
                                                (f"{PREFIX}%", f"%{TAG}"))]
        for sid in tmp_subjects:
            for table in ("reference_sets", "exams", "exam_questions", "lessons", "areas", "student_subjects", "teacher_subjects"):
                db_exec(f"DELETE FROM {table} WHERE subject_id = %s", (sid,))
            db_exec("DELETE FROM subjects WHERE id = %s", (sid,))
        db_exec("DELETE FROM users WHERE email LIKE %s", (f"{PREFIX}-%",))
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
