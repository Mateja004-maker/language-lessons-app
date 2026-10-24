"""Provera nastavnicke odluke o predlogu objasnjenja (Andrejev modul):
- isti korisnik ne sme da bude i drugi ocenjivac i onaj koji odlucuje (explanation_review);
- detalj i odluka samo za nastavnika predmeta izvornog pitanja (ADMIN bez ogranicenja);
- odluka iz otvorene serije sakrivena od nastavnika koji predlog nije ocenio.

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

COUNT_TABLES = ("ai_generated_artifacts", "ai_generation_runs", "ai_evaluations", "users",
                "exam_questions", "teacher_subjects", "evaluation_batches")
TAG = uuid.uuid4().hex[:6]

results = []
created = {"users": [], "runs": [], "artifacts": [], "questions": [], "batches": []}
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


def make_pending_explanation(model_id, prompt_id, question_id, batch_id=None):
    rid = db_exec("""
        INSERT INTO ai_generation_runs (model_id, prompt_id, purpose, mode, source_question_id, params_used,
               validation_passed, evaluation_batch_id)
        VALUES (%s, %s, 'explanation', 'mode_a', %s, %s, 1, %s)
    """, (model_id, prompt_id, question_id, json.dumps({"attempts": 1}), batch_id))
    created["runs"].append(rid)
    aid = db_exec("INSERT INTO ai_generated_artifacts (generation_run_id, artifact_type, status, original_text) "
                  "VALUES (%s, 'explanation', 'predlog', %s)", (rid, json.dumps({"explanation": f"Izmisljeno {TAG}"})))
    created["artifacts"].append(aid)
    return aid


def list_ids(user_id, role, status="predlog"):
    resp = client.get(f"/api/ai-artifacts/explanation?status={status}", headers=headers(user_id, role))
    return {row["id"] for row in (resp.get_json() or [])} if resp.status_code == 200 else None


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
    if created["batches"]:
        db_exec(f"DELETE FROM evaluation_batches WHERE id IN ({ph(created['batches'])})", created["batches"])
    if created["questions"]:
        db_exec(f"DELETE FROM exam_questions WHERE id IN ({ph(created['questions'])})", created["questions"])
    if created["users"]:
        # teacher_subjects se brise kaskadno (fk_ts_teacher ON DELETE CASCADE)
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

    admin = db_all("SELECT id FROM users WHERE role_id = 1 ORDER BY id LIMIT 1")[0]["id"]
    subject = db_all("SELECT id FROM subjects ORDER BY id LIMIT 1")[0]["id"]

    before = row_counts()
    try:
        rater, decider, racer, third, outsider = (make_user(n) for n in ("A", "B", "C", "D", "E"))
        for uid in (rater, decider, racer, third):  # outsider nema nijedan predmet
            db_exec("INSERT INTO teacher_subjects (teacher_id, subject_id) VALUES (%s, %s)", (uid, subject))
        question = db_exec("INSERT INTO exam_questions (subject_id, question_text, points, order_no) VALUES (%s, %s, 1, 0)",
                           (subject, f"Izmisljeno pitanje {TAG}"))
        created["questions"].append(question)

        # 1) korisnik vec ima ocenu (runda 2) -> odluka 409, nista se ne menja
        a1 = make_pending_explanation(model, prompt, question)
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
        a2 = make_pending_explanation(model, prompt, question)
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

        # 4) predmet: nastavnik van predmeta ne vidi detalj i ne moze da odluci; ADMIN moze
        a3 = make_pending_explanation(model, prompt, question)
        resp = client.get(f"/api/ai-artifacts/explanation/{a3}", headers=headers(outsider, "TEACHER"))
        record("van predmeta -> detalj", "403 Forbidden", f"{resp.status_code} {(resp.get_json() or {}).get('error')}",
               resp.status_code == 403 and (resp.get_json() or {}).get("error") == "Forbidden")
        resp = client.get(f"/api/ai-artifacts/explanation/{a3}", headers=headers(third, "TEACHER"))
        record("u predmetu -> detalj", 200, resp.status_code, resp.status_code == 200)
        resp = client.get(f"/api/ai-artifacts/explanation/{a3}", headers=headers(admin, "ADMIN"))
        record("ADMIN -> detalj", 200, resp.status_code, resp.status_code == 200)
        state_before = artifact_state(a3)
        resp = client.post(f"/api/ai-artifacts/explanation/{a3}/review", headers=headers(outsider, "TEACHER"),
                           json={"action": "approve", "scores": scores})
        state_after = artifact_state(a3)
        record("van predmeta -> odluka 403, bez upisa", f"403 {state_before}", f"{resp.status_code} {state_after}",
               resp.status_code == 403 and state_after == state_before == ("predlog", 0))
        resp = client.post(f"/api/ai-artifacts/explanation/999999999/review", headers=headers(outsider, "TEACHER"),
                           json={"action": "approve", "scores": scores})
        record("nepostojeci predlog -> 404 (i za nastavnika van predmeta)", 404, resp.status_code, resp.status_code == 404)

        # 4b) lista: isti filter po predmetu kao detalj
        seen = {name: a3 in (list_ids(uid, role) or set())
                for name, uid, role in (("van predmeta", outsider, "TEACHER"), ("u predmetu", third, "TEACHER"), ("ADMIN", admin, "ADMIN"))}
        record("lista: van predmeta ne vidi, u predmetu i ADMIN vide", {"van predmeta": False, "u predmetu": True, "ADMIN": True},
               seen, seen == {"van predmeta": False, "u predmetu": True, "ADMIN": True})

        # 4c) pitanje bez predmeta (kao #60): nastavnik ga ne vidi ni u listi ni u detalju, ADMIN vidi oba
        orphan_q = db_exec("INSERT INTO exam_questions (subject_id, question_text, points, order_no) VALUES (NULL, %s, 1, 0)",
                           (f"Izmisljeno bez predmeta {TAG}",))
        created["questions"].append(orphan_q)
        a5 = make_pending_explanation(model, prompt, orphan_q)
        t_list = a5 in (list_ids(third, "TEACHER") or set())
        t_detail = client.get(f"/api/ai-artifacts/explanation/{a5}", headers=headers(third, "TEACHER")).status_code
        a_list = a5 in (list_ids(admin, "ADMIN") or set())
        a_detail = client.get(f"/api/ai-artifacts/explanation/{a5}", headers=headers(admin, "ADMIN")).status_code
        record("bez predmeta: TEACHER lista/detalj, ADMIN lista/detalj", "False/403, True/200",
               f"{t_list}/{t_detail}, {a_list}/{a_detail}",
               (t_list, t_detail, a_list, a_detail) == (False, 403, True, 200))

        # 5) odluka iz otvorene serije: sakrivena od nastavnika koji nije ocenio, vidljiva
        #    odlucivacu, drugom ocenjivacu i ADMIN-u; posle zatvaranja serije vidljiva svima u predmetu
        batch = db_exec("INSERT INTO evaluation_batches (name) VALUES (%s)", (f"tmp-rev-{TAG}",))
        created["batches"].append(batch)
        a4 = make_pending_explanation(model, prompt, question, batch)
        db_exec("INSERT INTO ai_evaluations (artifact_id, rubric_definition_id, evaluator_id, evaluator_role, score, evaluation_round) "
                "VALUES (%s, %s, %s, 'TEACHER', 3, 2)", (a4, tacnost, rater))
        resp = client.get(f"/api/ai-artifacts/explanation/{a4}", headers=headers(third, "TEACHER"))
        record("serija, 'predlog' -> detalj vidljiv", 200, resp.status_code, resp.status_code == 200)
        resp = client.post(f"/api/ai-artifacts/explanation/{a4}/review", headers=headers(decider, "TEACHER"),
                           json={"action": "reject", "rejection_reason": "proba", "scores": scores})
        record("serija: odluka odlucivaca", 200, resp.status_code, resp.status_code == 200)
        resp = client.get(f"/api/ai-artifacts/explanation/{a4}", headers=headers(third, "TEACHER"))
        body = resp.get_json() or {}
        record("otvorena serija, odluceno -> treci nastavnik 403, bez odluke u odgovoru", "403, bez 'artifact'",
               f"{resp.status_code}, {'artifact' in body}", resp.status_code == 403 and "artifact" not in body
               and "odbaceno" not in json.dumps(body))
        visible = {}
        for name, uid, role in (("odlucivac", decider, "TEACHER"), ("drugi ocenjivac", rater, "TEACHER"), ("ADMIN", admin, "ADMIN")):
            resp = client.get(f"/api/ai-artifacts/explanation/{a4}", headers=headers(uid, role))
            visible[name] = f"{resp.status_code} {((resp.get_json() or {}).get('artifact') or {}).get('status')}"
        record("otvorena serija, odluceno -> vidljivo", "200 odbaceno x3", visible,
               all(v == "200 odbaceno" for v in visible.values()))
        in_list = {name: a4 in (list_ids(uid, role, "odbaceno") or set())
                   for name, uid, role in (("treci", third, "TEACHER"), ("odlucivac", decider, "TEACHER"),
                                           ("drugi ocenjivac", rater, "TEACHER"), ("ADMIN", admin, "ADMIN"))}
        record("otvorena serija, lista 'odbaceno': treci ne vidi, ostali vide",
               {"treci": False, "odlucivac": True, "drugi ocenjivac": True, "ADMIN": True}, in_list,
               in_list == {"treci": False, "odlucivac": True, "drugi ocenjivac": True, "ADMIN": True})

        # lista i detalj se slazu: svaka stavka iz liste otvara se bez 403, za svakog nastavnika i status
        mismatches, checked = [], 0
        for uid in (third, outsider, decider, rater):
            for status in ("predlog", "prihvaceno", "prihvaceno_izmena", "odbaceno"):
                for aid in list_ids(uid, "TEACHER", status) or set():
                    checked += 1
                    code = client.get(f"/api/ai-artifacts/explanation/{aid}", headers=headers(uid, "TEACHER")).status_code
                    if code != 200:
                        mismatches.append((uid, status, aid, code))
        record("lista i detalj se slazu (stavka iz liste -> detalj 200)", "0 neslaganja",
               f"{len(mismatches)} od {checked} {mismatches[:3]}", checked > 0 and not mismatches)
        db_exec("UPDATE evaluation_batches SET closed_at = NOW() WHERE id = %s", (batch,))
        resp = client.get(f"/api/ai-artifacts/explanation/{a4}", headers=headers(third, "TEACHER"))
        record("zatvorena serija -> treci nastavnik vidi odluku", "200 odbaceno",
               f"{resp.status_code} {((resp.get_json() or {}).get('artifact') or {}).get('status')}",
               resp.status_code == 200 and (resp.get_json() or {}).get("artifact", {}).get("status") == "odbaceno")
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
