"""Provera javne registracije (POST /api/auth/register): ADMIN se ne može izabrati,
STUDENT i TEACHER i dalje rade, a odobravanje naloga je nepromenjeno.

Pokretanje (iz foldera backend/):
    python tests/verify_registration.py

Pravi privremene naloge (@example.invalid), briše ih po email oznaci i poredi
broj korisnika pre i posle. Bez AI poziva.
"""
import os
import sys
import uuid

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

from app import app, get_db_connection  # noqa: E402
from flask_jwt_extended import create_access_token  # noqa: E402

TAG = uuid.uuid4().hex[:6]
PASSWORD = "Lozinka-" + TAG
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
    finally:
        cur.close()
        conn.close()


def email(label):
    return f"tmp-reg-{TAG}-{label}@example.invalid"


def user(label):
    rows = db_all("SELECT u.id, u.is_active, r.name AS role FROM users u JOIN roles r ON r.id = u.role_id WHERE u.email = %s",
                  (email(label),))
    return rows[0] if rows else None


def register(label, **body):
    payload = {"email": email(label), "password": PASSWORD, "display_name": f"tmp {label}", **body}
    resp = client.post("/api/auth/register", json=payload)
    return resp.status_code, (resp.get_json(silent=True) or {})


def record(case, expected, got, ok):
    results.append((case, expected, got, "OK" if ok else "PALO"))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    users_before = db_all("SELECT COUNT(*) AS n FROM users")[0]["n"]
    try:
        # --- uloga ADMIN se odbija, u svim zapisima ---
        for label, role in (("admin", "ADMIN"), ("admin-lower", "admin"), ("admin-space", " Admin ")):
            code, body = register(label, role=role)
            error = body.get("error", "")
            record(f"registracija role={role!r}", "400, poruka o ulozi, nalog nije napravljen",
                   f"{code}, {error[:60]!r}, nalog: {'DA' if user(label) else 'ne'}",
                   code == 400 and "ADMIN" in error and "STUDENT" in error and user(label) is None)

        # --- dozvoljene uloge rade kao pre (neaktivan nalog, čeka odobrenje) ---
        for label, body_role, expected_role in (("student", {"role": "STUDENT"}, "STUDENT"),
                                                ("teacher", {"role": "TEACHER"}, "TEACHER"),
                                                ("teacher-lower", {"role": "teacher"}, "TEACHER"),
                                                ("default", {}, "STUDENT")):
            code, body = register(label, **body_role)
            u = user(label) or {}
            record(f"registracija {body_role or 'bez uloge'}", f"201, {expected_role}, neaktivan",
                   f"{code}, {u.get('role')}, is_active={u.get('is_active')}",
                   code == 201 and u.get("role") == expected_role and u.get("is_active") == 0
                   and body.get("message") == "Registration sent. Waiting for admin approval.")

        # --- ostale greške nepromenjene ---
        code, body = register("unknown", role="SUPERUSER")
        record("nepoznata uloga", "400 Invalid role", f"{code} {body.get('error')}", code == 400 and body.get("error") == "Invalid role")
        code, body = register("nopass", password="")
        record("bez lozinke", "400 Email and password required", f"{code} {body.get('error')}",
               code == 400 and body.get("error") == "Email and password required")
        code, body = register("student", role="STUDENT")
        record("isti email ponovo", "409 Email already exists", f"{code} {body.get('error')}",
               code == 409 and body.get("error") == "Email already exists")

        # --- odobravanje nepromenjeno: neaktivan -> 403, posle odobrenja ADMIN-a -> 200 ---
        login = {"email": email("teacher"), "password": PASSWORD}
        before = client.post("/api/auth/login", json=login).status_code
        admin_id = db_all("SELECT u.id FROM users u JOIN roles r ON r.id = u.role_id WHERE r.name = 'ADMIN' ORDER BY u.id LIMIT 1")[0]["id"]
        with app.app_context():
            token = create_access_token(identity=str(admin_id), additional_claims={"role": "ADMIN", "email": "verify"})
        approve = client.patch(f"/api/users/{user('teacher')['id']}/approve", headers={"Authorization": f"Bearer {token}"}).status_code
        resp = client.post("/api/auth/login", json=login)
        after_role = (resp.get_json(silent=True) or {}).get("role")
        record("prijava pre odobrenja / odobrenje / prijava posle", "403 / 200 / 200 TEACHER",
               f"{before} / {approve} / {resp.status_code} {after_role}",
               before == 403 and approve == 200 and resp.status_code == 200 and after_role == "TEACHER")
    finally:
        db_exec("DELETE FROM users WHERE email LIKE %s", (f"tmp-reg-{TAG}-%",))
    users_after = db_all("SELECT COUNT(*) AS n FROM users")[0]["n"]
    record("broj korisnika pre = posle", users_before, users_after, users_before == users_after)

    width = max(len(r[0]) for r in results)
    for case, expected, got, status in results:
        print(f"{status:4}  {case:<{width}}  ocekivano: {expected}  dobijeno: {got}")
    failed = sum(r[3] == "PALO" for r in results)
    print(f"\n{len(results) - failed}/{len(results)} OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
