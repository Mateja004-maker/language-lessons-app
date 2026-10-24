"""Provera nastavnicke odluke o predlogu objasnjenja: isti korisnik ne sme da
bude i drugi ocenjivac i onaj koji odlucuje (Andrejev modul, explanation_review).

Pokretanje (iz foldera backend/):
    python tests/verify_explanation_review.py

Bez AI poziva: izmisljeni korisnici, run i predlozi se upisuju direktno u bazu.
Sve se brise po zabelezenim id-jevima i porede se brojevi redova pre i posle.
"""
import json
import os
import sys
import uuid

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

from app import app, get_db_connection  # noqa: E402
from flask_jwt_extended import create_access_token  # noqa: E402

import explanation_review  # noqa: E402

COUNT_TABLES = ("ai_generated_artifacts", "ai_generation_runs", "ai_evaluations", "users")
TAG = uuid.uuid4().hex[:6]

results = []
created = {"users": [], "runs": [], "artifacts": []}
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


def row_counts():
    return {t: db_all(f"SELECT COUNT(*) AS n FROM {t}")[0]["n"] for t in COUNT_TABLES}


def record(case, expected, got, ok):
    results.append((case, expected, got, "OK" if ok else "PALO"))


def headers(user_id, role):
    with app.app_context():
        token = create_access_token(identity=str(user_id), additional_claims={"role": role, "email": f"verify-{user_id}"})
    return {"Authorization": f"Bearer {token}"}


def make_user(name):
    uid = db_exec("INSERT INTO users (email, password_hash, role_id, display_name, is_active) VALUES (%s, '!', 2, %s, 1)",
                  (f"tmp-rev-{name}-{TAG}@example.invalid", f"TmpRev{name}{TAG}"))
    created["users"].append(uid)
    return uid


def make_pending_explanation(model_id, prompt_id):
    rid = db_exec("""
        INSERT INTO ai_generation_runs (model_id, prompt_id, purpose, mode, params_used, validation_passed)
        VALUES (%s, %s, 'explanation', 'mode_a', %s, 1)
    """, (model_id, prompt_id, json.dumps({"attempts": 1})))
    created["runs"].append(rid)
    aid = db_exec("INSERT INTO ai_generated_artifacts (generation_run_id, artifact_type, status, original_text) "
                  "VALUES (%s, 'explanation', 'predlog', %s)", (rid, json.dumps({"explanation": f"Izmisljeno {TAG}"})))
    created["artifacts"].append(aid)
    return aid


def artifact_state(aid):
    row = db_all("SELECT status FROM ai_generated_artifacts WHERE id = %s", (aid,))[0]
    n = db_all("SELECT COUNT(*) AS n FROM ai_evaluations WHERE artifact_id = %s", (aid,))[0]["n"]
    return row["status"], n


def cleanup():
    def ph(ids):
        return ",".join(["%s"] * len(ids))
    arts, runs = created["artifacts"], created["runs"]
    if arts:
        db_exec(f"DELETE FROM ai_evaluations WHERE artifact_id IN ({ph(arts)})", arts)
        db_exec(f"DELETE FROM ai_generated_artifacts WHERE id IN ({ph(arts)})", arts)
    if runs:
        db_exec(f"DELETE FROM ai_generation_runs WHERE id IN ({ph(runs)})", runs)
    if created["users"]:
        db_exec(f"DELETE FROM users WHERE id IN ({ph(created['users'])})", created["users"])


class _SkipPrecheckCursor:
    """Kursor koji preskace proveru 'vec ste ocenili' - simulira istovremeni zahtev
    (provera prosla, a INSERT naleti na UNIQUE ogranicenje)."""
    def __init__(self, inner):
        self._inner = inner

    def execute(self, sql, params=None):
        if sql.startswith("SELECT 1 FROM ai_evaluations WHERE artifact_id"):
            return self._inner.execute("SELECT 1 FROM DUAL WHERE 1 = 0")
        return self._inner.execute(sql, params)

    def __getattr__(self, name):
        return getattr(self._inner, name)


class _SkipPrecheckConn:
    def __init__(self, inner):
        self._inner = inner

    def cursor(self, *args, **kwargs):
        return _SkipPrecheckCursor(self._inner.cursor(*args, **kwargs))

    def __getattr__(self, name):
        return getattr(self._inner, name)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    model = db_all("SELECT id FROM ai_models ORDER BY id LIMIT 1")[0]["id"]
    prompt = db_all("SELECT id FROM ai_prompts WHERE purpose = 'explanation' ORDER BY id LIMIT 1")[0]["id"]
    dims = db_all("SELECT id, dimension_key FROM ai_rubric_definitions "
                  "WHERE applies_to = 'explanation' AND evaluator_role = 'TEACHER' ORDER BY id")
    scores = [{"dimension_key": d["dimension_key"], "score": 4} for d in dims]
    tacnost = next(d["id"] for d in dims if d["dimension_key"] == "tacnost_objasnjenja")

    before = row_counts()
    try:
        rater, decider, racer = make_user("A"), make_user("B"), make_user("C")

        # 1) korisnik vec ima ocenu (runda 2) -> odluka 409, nista se ne menja
        a1 = make_pending_explanation(model, prompt)
        db_exec("INSERT INTO ai_evaluations (artifact_id, rubric_definition_id, evaluator_id, evaluator_role, score, evaluation_round) "
                "VALUES (%s, %s, %s, 'TEACHER', 3, 2)", (a1, tacnost, rater))
        state_before = artifact_state(a1)
        resp = client.post(f"/api/ai-artifacts/explanation/{a1}/review", headers=headers(rater, "TEACHER"),
                           json={"action": "approve", "scores": scores})
        body = resp.get_json() or {}
        record("vec ocenio -> odluka", 409, resp.status_code, resp.status_code == 409)
        record("vec ocenio -> poruka", "Već ste ocenili ... drugi ocenjivač", body.get("error"),
               "Već ste ocenili ovaj predlog (kao drugi ocenjivač)" in (body.get("error") or ""))
        state_after = artifact_state(a1)
        record("vec ocenio -> status i broj ocena nepromenjeni", state_before, state_after,
               state_after == state_before == ("predlog", 1))

        # 2) drugi nastavnik (bez ocene) i dalje moze da odluci
        resp = client.post(f"/api/ai-artifacts/explanation/{a1}/review", headers=headers(decider, "TEACHER"),
                           json={"action": "approve", "scores": scores})
        state = artifact_state(a1)
        record("drugi nastavnik -> odluka", f"200, prihvaceno, {1 + len(dims)} ocena", f"{resp.status_code}, {state[0]}, {state[1]}",
               resp.status_code == 200 and state == ("prihvaceno", 1 + len(dims)))

        # 3) istovremeni zahtev: provera prodje, INSERT naleti na UNIQUE -> ArtifactStateError, rollback statusa
        a2 = make_pending_explanation(model, prompt)
        db_exec("INSERT INTO ai_evaluations (artifact_id, rubric_definition_id, evaluator_id, evaluator_role, score, evaluation_round) "
                "VALUES (%s, %s, %s, 'TEACHER', 3, 2)", (a2, tacnost, racer))
        conn = get_db_connection()
        try:
            explanation_review.review_explanation_artifact(
                _SkipPrecheckConn(conn), artifact_id=a2, reviewer_id=racer, action="approve", scores=scores)
            got = "bez greske"
        except explanation_review.ArtifactStateError as e:
            got = f"ArtifactStateError: {e}"
        except Exception as e:  # noqa: BLE001
            got = f"{type(e).__name__}: {e}"
        finally:
            conn.close()
        record("istovremeni zahtev -> ArtifactStateError (ne 500)", "ArtifactStateError: Već ste ocenili ovaj predlog",
               got, got == "ArtifactStateError: Već ste ocenili ovaj predlog")
        state = artifact_state(a2)
        record("istovremeni zahtev -> rollback (status predlog, 1 ocena)", ("predlog", 1), state, state == ("predlog", 1))
    finally:
        cleanup()
    after = row_counts()
    record("brojevi redova pre = posle", before, after, before == after)

    width = max(len(r[0]) for r in results)
    for case, expected, got, status in results:
        print(f"{status:4}  {case:<{width}}  ocekivano: {expected}  dobijeno: {got}")
    failed = sum(r[3] == "PALO" for r in results)
    print(f"\n{len(results) - failed}/{len(results)} OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
