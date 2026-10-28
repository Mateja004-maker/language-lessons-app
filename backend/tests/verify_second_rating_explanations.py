"""Provera druge ocene za predloge OBJASNJENJA (Andrejev modul), iste rute kao za pitanja:
GET /api/ai/artifacts/second-rating, GET /api/ai/artifacts/<id>/second-rating,
POST /api/ai/artifacts/<id>/evaluations.

Pokretanje (iz foldera backend/):
    python tests/verify_second_rating_explanations.py

Bez AI poziva: izmisljeni korisnici, pitanja, serija, run-ovi i predlozi se upisuju
direktno u bazu. Sve se brise po zabelezenim id-jevima i porede se brojevi redova
pre i posle. Uzorak po ocenjivacu (SECOND_RATING_SAMPLE) se racuna istom funkcijom
kao u ruti (in_second_rating_sample).
"""
import json
import os
import sys
import uuid

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

from app import app, get_db_connection, in_second_rating_sample  # noqa: E402
from flask_jwt_extended import create_access_token  # noqa: E402

COUNT_TABLES = ("ai_generated_artifacts", "ai_generation_runs", "ai_evaluations", "ai_label_evaluations", "users",
                "exam_questions", "exam_answers", "teacher_subjects", "evaluation_batches")
TAG = uuid.uuid4().hex[:6]
HIDDEN_KEYS = ("status", "reviewed_by", "reviewed_at", "edited_text", "rejection_reason", "provider", "model_name",
               "model_id", "created_at", "generation_run_id")

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
                  (f"tmp-sr-{name}-{TAG}@example.invalid", f"TmpSr{name}{TAG}"))
    created["users"].append(uid)
    return uid


def make_question(subject_id, text, answers=()):
    qid = db_exec("INSERT INTO exam_questions (subject_id, question_text, points, order_no) VALUES (%s, %s, 1, 0)",
                  (subject_id, text))
    created["questions"].append(qid)
    for answer_text, correct in answers:
        db_exec("INSERT INTO exam_answers (question_id, answer_text, is_correct) VALUES (%s, %s, %s)", (qid, answer_text, correct))
    return qid


def make_explanation(model_id, prompt_id, question_id, batch_id, mode="mode_a", body=None, accuracy=None, details=None):
    rid = db_exec("""
        INSERT INTO ai_generation_runs (model_id, prompt_id, purpose, mode, source_question_id, params_used,
               validation_passed, accuracy_check_passed, accuracy_check_details, evaluation_batch_id)
        VALUES (%s, %s, 'explanation', %s, %s, %s, 1, %s, %s, %s)
    """, (model_id, prompt_id, mode, question_id, json.dumps({"attempts": 1}), accuracy, details, batch_id))
    created["runs"].append(rid)
    aid = db_exec("INSERT INTO ai_generated_artifacts (generation_run_id, artifact_type, status, original_text) "
                  "VALUES (%s, 'explanation', 'predlog', %s)",
                  (rid, json.dumps(body or {"explanation": f"Izmisljeno objasnjenje {TAG}"})))
    created["artifacts"].append(aid)
    return aid


def make_explanation_in_sample(user_id, *args, **kwargs):
    """Pravi predloge dok jedan ne upadne u uzorak datog ocenjivaca; vraca (u_uzorku, svi_napravljeni)."""
    made = []
    for _ in range(40):
        aid = make_explanation(*args, **kwargs)
        made.append(aid)
        if in_second_rating_sample(user_id, aid):
            return aid, made
    raise SystemExit("Nije pronadjen predlog u uzorku (40 pokusaja)")


def cleanup():
    def ph(ids):
        return ",".join(["%s"] * len(ids))
    arts, runs = created["artifacts"], created["runs"]
    if arts:
        db_exec(f"DELETE FROM ai_label_evaluations WHERE artifact_id IN ({ph(arts)})", arts)
        db_exec(f"DELETE FROM ai_evaluations WHERE artifact_id IN ({ph(arts)})", arts)
        db_exec(f"DELETE FROM ai_generated_artifacts WHERE id IN ({ph(arts)})", arts)
    if runs:
        db_exec(f"DELETE FROM ai_generation_runs WHERE id IN ({ph(runs)})", runs)
    if created["batches"]:
        db_exec(f"DELETE FROM evaluation_batches WHERE id IN ({ph(created['batches'])})", created["batches"])
    if created["questions"]:
        db_exec(f"DELETE FROM exam_answers WHERE question_id IN ({ph(created['questions'])})", created["questions"])
        db_exec(f"DELETE FROM exam_questions WHERE id IN ({ph(created['questions'])})", created["questions"])
    if created["users"]:
        # teacher_subjects se brise kaskadno (fk_ts_teacher ON DELETE CASCADE)
        db_exec(f"DELETE FROM users WHERE id IN ({ph(created['users'])})", created["users"])


def list_ids(user_id, role, batch_id):
    resp = client.get(f"/api/ai/artifacts/second-rating?batch_id={batch_id}", headers=headers(user_id, role))
    return resp, {row["id"]: row for row in (resp.get_json() or [])} if resp.status_code == 200 else {}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    model = db_all("SELECT id, provider, model_name FROM ai_models ORDER BY id LIMIT 1")[0]
    prompt = db_all("SELECT id FROM ai_prompts WHERE purpose = 'explanation' ORDER BY id LIMIT 1")[0]["id"]
    admin = db_all("SELECT id FROM users WHERE role_id = 1 ORDER BY id LIMIT 1")[0]["id"]
    subject = db_all("SELECT id FROM subjects ORDER BY id LIMIT 1")[0]["id"]
    expl_dims = {r["id"]: r["dimension_key"] for r in db_all(
        "SELECT id, dimension_key FROM ai_rubric_definitions WHERE applies_to = 'explanation' AND evaluator_role = 'TEACHER'")}
    question_dim = db_all("SELECT id FROM ai_rubric_definitions WHERE applies_to = 'question' ORDER BY id LIMIT 1")[0]["id"]

    before = row_counts()
    try:
        rater, decider, outsider = make_user("A"), make_user("B"), make_user("C")
        for uid in (rater, decider):  # outsider nema nijedan predmet
            db_exec("INSERT INTO teacher_subjects (teacher_id, subject_id) VALUES (%s, %s)", (uid, subject))
        question = make_question(subject, f"Izmisljeno MC pitanje {TAG}", (("Pariz", 1), ("London", 0)))
        orphan = make_question(None, f"Izmisljeno bez predmeta {TAG}")  # kao pitanje #60
        batch = db_exec("INSERT INTO evaluation_batches (name) VALUES (%s)", (f"tmp-sr-{TAG}",))
        created["batches"].append(batch)

        # predlog u uzorku ocenjivaca A: rezim B, MC, sa mehanickom proverom
        mc_body = {"selected_option": 1, "explanation": f"Pariz je glavni grad {TAG}"}
        mc_details = json.dumps({"selected_option": 1, "selected_answer": "Pariz", "correct_answer": "Pariz"})
        a_mc, _ = make_explanation_in_sample(rater, model["id"], prompt, question, batch,
                                             mode="mode_b", body=mc_body, accuracy=1, details=mc_details)
        # predlog bez predmeta u uzorku ADMIN-a
        a_orphan, _ = make_explanation_in_sample(admin, model["id"], prompt, orphan, batch)
        # predlog koji odlucuje B (posle toga ga A ocenjuje kao drugi)
        a_dec, _ = make_explanation_in_sample(rater, model["id"], prompt, question, batch)
        scores_by_key = [{"dimension_key": k, "score": 4} for k in expl_dims.values()]
        resp = client.post(f"/api/ai-artifacts/explanation/{a_dec}/review", headers=headers(decider, "TEACHER"),
                           json={"action": "reject", "rejection_reason": f"razlog {TAG}", "scores": scores_by_key})
        record("priprema: odluka B (odbaceno)", 200, resp.status_code, resp.status_code == 200)

        # ---------- lista ----------
        expl_in_batch = {r["id"] for r in db_all("""SELECT a.id FROM ai_generated_artifacts a
                         JOIN ai_generation_runs r ON r.id = a.generation_run_id WHERE r.evaluation_batch_id = %s""", (batch,))}
        resp, listed = list_ids(rater, "TEACHER", batch)
        expected = {aid for aid in expl_in_batch if in_second_rating_sample(rater, aid)}
        expected_rater = {aid for aid in expected if db_all("""SELECT q.subject_id FROM ai_generated_artifacts a
                          JOIN ai_generation_runs r ON r.id = a.generation_run_id
                          JOIN exam_questions q ON q.id = r.source_question_id WHERE a.id = %s""", (aid,))[0]["subject_id"] == subject}
        record("lista A (u predmetu): tacno njegov uzorak iz predmeta", sorted(expected_rater), sorted(listed),
               resp.status_code == 200 and set(listed) == expected_rater and a_mc in listed and a_dec in listed)
        row = listed.get(a_mc, {})
        record("lista: stavka je objasnjenje, rezim i provera, bez modela i odluke",
               "artifact_type=explanation mode_b acc=1, bez skrivenih kljuceva",
               f"{row.get('artifact_type')} {row.get('mode')} acc={row.get('accuracy_check_passed')} "
               f"skriveni={[k for k in HIDDEN_KEYS if k in row]}",
               row.get("artifact_type") == "explanation" and row.get("mode") == "mode_b"
               and row.get("accuracy_check_passed") == 1 and not [k for k in HIDDEN_KEYS if k in row])
        resp, listed_out = list_ids(outsider, "TEACHER", batch)
        record("lista van predmeta: prazna", [], sorted(listed_out), resp.status_code == 200 and not listed_out)
        record("lista A: predlog bez predmeta se ne vidi", False, a_orphan in listed, a_orphan not in listed)
        resp, listed_admin = list_ids(admin, "ADMIN", batch)
        record("lista ADMIN: vidi predlog bez predmeta (iz svog uzorka)", True, a_orphan in listed_admin,
               resp.status_code == 200 and a_orphan in listed_admin)

        # ---------- detalj ----------
        resp = client.get(f"/api/ai/artifacts/{a_mc}/second-rating", headers=headers(rater, "TEACHER"))
        view = resp.get_json() or {}
        rubric_keys = sorted(c["dimension_key"] for c in view.get("rubric_criteria") or [])
        record("detalj A: 200, rubrika = 5 TEACHER kriterijuma objasnjenja", sorted(expl_dims.values()), rubric_keys,
               resp.status_code == 200 and rubric_keys == sorted(expl_dims.values()))
        record("detalj A: sadrzaj (izabrana opcija, objasnjenje, izvorno pitanje i odgovori, provera)",
               "selected_option 1, 2 odgovora, acc 1",
               f"{(view.get('original_text') or {}).get('selected_option')}, {len(view.get('source_answers') or [])} odgovora, "
               f"acc {view.get('accuracy_check_passed')}, details {bool(view.get('accuracy_check_details'))}",
               (view.get("original_text") or {}).get("selected_option") == 1 and len(view.get("source_answers") or []) == 2
               and view.get("source_question_text", "").startswith("Izmisljeno MC") and view.get("accuracy_check_passed") == 1
               and view.get("accuracy_check_details") == mc_details and view.get("mode") == "mode_b")
        resp = client.get(f"/api/ai/artifacts/{a_dec}/second-rating", headers=headers(rater, "TEACHER"))
        text = resp.get_data(as_text=True)
        leaks = [k for k in HIDDEN_KEYS if f'"{k}"' in text] + [s for s in (model["model_name"], f"razlog {TAG}", "odbaceno") if s in text]
        record("detalj odlucenog predloga: bez odluke, razloga i modela", "200, []", f"{resp.status_code}, {leaks}",
               resp.status_code == 200 and not leaks)
        codes = {name: client.get(f"/api/ai/artifacts/{aid}/second-rating", headers=headers(uid, role)).status_code
                 for name, aid, uid, role in (("van predmeta", a_mc, outsider, "TEACHER"),
                                              ("A, bez predmeta", a_orphan, rater, "TEACHER"),
                                              ("ADMIN, bez predmeta", a_orphan, admin, "ADMIN"))}
        record("detalj: van predmeta 403, bez predmeta 403 za nastavnika, 200 za ADMIN",
               {"van predmeta": 403, "A, bez predmeta": 403, "ADMIN, bez predmeta": 200}, codes,
               codes == {"van predmeta": 403, "A, bez predmeta": 403, "ADMIN, bez predmeta": 200})

        # ---------- upis druge ocene ----------
        scores = [{"rubric_definition_id": rid, "score": 3} for rid in expl_dims]
        resp = client.post(f"/api/ai/artifacts/{a_mc}/evaluations", headers=headers(rater, "TEACHER"),
                           json={"scores": scores, "difficulty": "lako"})
        record("oznake tezine/Bluma za objasnjenje -> 400", 400, resp.status_code, resp.status_code == 400)
        resp = client.post(f"/api/ai/artifacts/{a_mc}/evaluations", headers=headers(rater, "TEACHER"),
                           json={"scores": scores[:-1] + [{"rubric_definition_id": question_dim, "score": 3}]})
        record("kriterijum pitanja za objasnjenje -> 400", 400, resp.status_code, resp.status_code == 400)
        resp = client.post(f"/api/ai/artifacts/{a_mc}/evaluations", headers=headers(outsider, "TEACHER"), json={"scores": scores})
        record("upis van predmeta -> 403", 403, resp.status_code, resp.status_code == 403)

        resp = client.post(f"/api/ai/artifacts/{a_mc}/evaluations", headers=headers(rater, "TEACHER"),
                           json={"scores": scores, "comment": "druga ocena"})
        body = resp.get_json() or {}
        stored = db_all("SELECT evaluation_round, evaluator_role, COUNT(*) AS n FROM ai_evaluations "
                        "WHERE artifact_id = %s AND evaluator_id = %s GROUP BY evaluation_round, evaluator_role", (a_mc, rater))
        labels = db_all("SELECT COUNT(*) AS n FROM ai_label_evaluations WHERE artifact_id = %s", (a_mc,))[0]["n"]
        record("upis A: 201, runda 2, 5 ocena, bez oznaka", "201 [(2, TEACHER, 5)] oznaka 0",
               f"{resp.status_code} {[(s['evaluation_round'], s['evaluator_role'], s['n']) for s in stored]} oznaka {labels}",
               resp.status_code == 201 and [(s["evaluation_round"], s["evaluator_role"], s["n"]) for s in stored]
               == [(2, "TEACHER", len(expl_dims))] and labels == 0)
        record("odgovor upisa: bez odluke i modela", ["artifact_id", "evaluation_round", "message", "scores"],
               sorted(body), sorted(body) == ["artifact_id", "evaluation_round", "message", "scores"] and body.get("evaluation_round") == 2)

        resp = client.post(f"/api/ai/artifacts/{a_mc}/evaluations", headers=headers(rater, "TEACHER"), json={"scores": scores})
        record("isti ocenjivac drugi put -> 409 (ne 500)", "409 Već ste ocenili ovaj predlog",
               f"{resp.status_code} {(resp.get_json() or {}).get('error')}",
               resp.status_code == 409 and (resp.get_json() or {}).get("error") == "Već ste ocenili ovaj predlog")
        resp = client.post(f"/api/ai/artifacts/{a_dec}/evaluations", headers=headers(decider, "TEACHER"), json={"scores": scores})
        record("odlucivac kao drugi ocenjivac -> 409", 409, resp.status_code, resp.status_code == 409)
        resp = client.post(f"/api/ai-artifacts/explanation/{a_mc}/review", headers=headers(rater, "TEACHER"),
                           json={"action": "approve", "scores": scores_by_key})
        record("drugi ocenjivac posle ne moze da odluci -> 409", 409, resp.status_code, resp.status_code == 409)
        resp, listed = list_ids(rater, "TEACHER", batch)
        record("posle ocene predlog nestaje iz liste A", False, a_mc in listed, resp.status_code == 200 and a_mc not in listed)

        # drugi ocenjivac sad sme da vidi odluku u obicnom detalju (kao kod pitanja)
        resp = client.get(f"/api/ai-artifacts/explanation/{a_dec}", headers=headers(rater, "TEACHER"))
        record("pre ocene odlucenog predloga: obican detalj sakriven za A", 403, resp.status_code, resp.status_code == 403)
        client.post(f"/api/ai/artifacts/{a_dec}/evaluations", headers=headers(rater, "TEACHER"), json={"scores": scores})
        resp = client.get(f"/api/ai-artifacts/explanation/{a_dec}", headers=headers(rater, "TEACHER"))
        record("posle ocene: A vidi odluku u obicnom detalju", "200 odbaceno",
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
