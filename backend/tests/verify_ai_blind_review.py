"""Provera slepog ocenjivanja AI predloga (pitanja i objasnjenja).

Pokretanje (iz foldera backend/):
    python tests/verify_ai_blind_review.py

Gadja stvarne rute kroz app.test_client() nad stvarnom bazom iz backend/.env.
Prvi deo SAMO CITA postojece predloge i korisnike. Drugi deo (drugi
ocenjivac, tacka E) pravi privremene nastavnike, seriju i predloge (lazni
provajder - pravi AI servis se ne poziva) i sve brise po zabelezenim
id-jevima. Oba dela proveravaju da su brojevi redova isti pre i posle.
JWT tokeni se prave u procesu (create_access_token) - bez kljuceva u fajlu.
Slucajevi drugog ocenjivaca koji traze db/migration_second_rater.sql se
pre migracije oznacavaju kao PRESKOCENO.
"""
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402
from flask_jwt_extended import create_access_token  # noqa: E402

import ai_provider  # noqa: E402
from app import app, get_db_connection, in_second_rating_sample, second_rater_enabled  # noqa: E402

MODEL_FIELDS = ("provider", "model_name")
ORDER_FIELDS = ("created_at", "generation_run_id")
DECIDED = ("prihvaceno", "prihvaceno_izmena", "odbaceno")
# Kljucevi koji bi otkrili model ako se pojave bilo gde u odgovoru
MODEL_KEYS = {"provider", "model_name", "model", "model_id", "model_version", "tokens_used", "params_used", "default_params"}
COUNT_TABLES = (
    "ai_generated_artifacts", "ai_generation_runs", "ai_evaluations", "ai_models",
    "ai_prompts", "ai_rubric_definitions", "evaluation_batches", "exam_questions", "exam_answers",
)

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


def row_counts():
    return {t: db_all(f"SELECT COUNT(*) AS n FROM {t}")[0]["n"] for t in COUNT_TABLES}


def headers(user_id, role):
    with app.app_context():
        token = create_access_token(identity=str(user_id), additional_claims={"role": role, "email": f"verify-{user_id}"})
    return {"Authorization": f"Bearer {token}"}


def get(url, h):
    r = client.get(url, headers=h)
    return r.status_code, r.get_json()


def record(case, expected, got, ok):
    results.append((case, expected, got, "OK" if ok else "PALO"))


def skip(case, why):
    results.append((case, "-", why, "PRESKOCENO"))


def present(row, fields):
    return [f for f in fields if f in row]


def check_hidden(case, rows, fields):
    leaked = sorted({f for row in rows for f in present(row, fields)})
    record(case, f"{len(rows)} redova, bez {'/'.join(fields)}", f"{len(rows)} redova, procurelo: {leaked or 'nista'}", bool(rows) and not leaked)


def check_shown(case, rows, fields):
    missing = sorted({f for row in rows for f in fields if f not in row})
    record(case, f"{len(rows)} redova, sa {'/'.join(fields)}", f"{len(rows)} redova, nedostaje: {missing or 'nista'}", bool(rows) and not missing)


def scan_for_model(obj, model_names, path="$"):
    """Vraca listu putanja gde se u (ugnezdenom) JSON-u pojavljuje kljuc ili naziv modela."""
    hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in MODEL_KEYS:
                hits.append(f"{path}.{k}")
            hits += scan_for_model(v, model_names, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits += scan_for_model(v, model_names, f"{path}[{i}]")
    elif isinstance(obj, str):
        low = obj.lower()
        hits += [f"{path} ~ '{m}'" for m in model_names if m.lower() in low]
    return hits


def pick_teacher():
    """Nastavnik ciji predmet ima i predlog pitanja u statusu 'predlog' i odluceni predlog."""
    rows = db_all("""
        SELECT ts.teacher_id,
               SUM(a.status = 'predlog') AS pending,
               SUM(a.status <> 'predlog') AS decided
        FROM teacher_subjects ts
        JOIN users u ON u.id = ts.teacher_id AND u.is_active = 1
        JOIN roles ro ON ro.id = u.role_id AND ro.name = 'TEACHER'
        JOIN exam_questions q ON q.subject_id = ts.subject_id
        JOIN ai_generation_runs r ON r.source_question_id = q.id
        JOIN ai_generated_artifacts a ON a.generation_run_id = r.id AND a.artifact_type = 'question'
        GROUP BY ts.teacher_id
        ORDER BY (SUM(a.status = 'predlog') > 0 AND SUM(a.status <> 'predlog') > 0) DESC, COUNT(*) DESC
        LIMIT 1
    """)
    return rows[0] if rows else None


def run():
    counts_before = row_counts()
    model_names = [r["model_name"] for r in db_all("SELECT DISTINCT model_name FROM ai_models")]
    admin_id = db_all("SELECT u.id FROM users u JOIN roles r ON r.id = u.role_id WHERE r.name = 'ADMIN' ORDER BY u.id LIMIT 1")[0]["id"]
    admin = headers(admin_id, "ADMIN")

    teacher_row = pick_teacher()
    teacher = headers(teacher_row["teacher_id"], "TEACHER") if teacher_row else None

    # ---------- predlozi pitanja ----------
    all_fields = MODEL_FIELDS + ORDER_FIELDS
    if teacher:
        _, pending = get("/api/ai/artifacts?status=predlog", teacher)
        check_hidden("TEACHER lista pitanja, 'predlog'", pending or [], all_fields)
        if pending:
            aid = pending[0]["id"]
            _, d = get(f"/api/ai/artifacts/{aid}", teacher)
            check_hidden(f"TEACHER detalj pitanja #{aid}, 'predlog'", [d], all_fields)
            _, d = get(f"/api/ai/artifacts/{aid}?reveal=1", teacher)
            check_hidden(f"TEACHER detalj #{aid} sa ?reveal=1 (ne sme da otkrije)", [d], all_fields)
            _, lst = get("/api/ai/artifacts?status=predlog&reveal=1", teacher)
            check_hidden("TEACHER lista 'predlog' sa ?reveal=1 (ne sme da otkrije)", lst or [], all_fields)

        decided_rows = []
        for s in DECIDED:
            _, lst = get(f"/api/ai/artifacts?status={s}", teacher)
            decided_rows += lst or []
        if decided_rows:
            check_shown("TEACHER lista pitanja, zavrseni (posle odluke)", decided_rows, all_fields)
            aid = decided_rows[0]["id"]
            _, d = get(f"/api/ai/artifacts/{aid}", teacher)
            check_shown(f"TEACHER detalj pitanja #{aid}, status '{d.get('status')}'", [d], all_fields)
        else:
            skip("TEACHER vidi model za zavrsene", "nastavnik nema odlucenih predloga pitanja")
    else:
        skip("TEACHER provere za pitanja", "nijedan nastavnik nema predloge pitanja u svom predmetu")

    _, pending_admin = get("/api/ai/artifacts?status=predlog", admin)
    check_hidden("ADMIN lista pitanja 'predlog' bez ?reveal=1", pending_admin or [], all_fields)
    _, revealed = get("/api/ai/artifacts?status=predlog&reveal=1", admin)
    check_shown("ADMIN lista pitanja 'predlog' sa ?reveal=1", revealed or [], all_fields)
    if pending_admin:
        aid = pending_admin[0]["id"]
        _, d = get(f"/api/ai/artifacts/{aid}", admin)
        check_hidden(f"ADMIN detalj pitanja #{aid} bez ?reveal=1", [d], all_fields)
        _, d = get(f"/api/ai/artifacts/{aid}?reveal=1", admin)
        db_model = db_all("""SELECT m.provider, m.model_name FROM ai_generated_artifacts a
                             JOIN ai_generation_runs r ON r.id = a.generation_run_id
                             JOIN ai_models m ON m.id = r.model_id WHERE a.id = %s""", (aid,))[0]
        same = d.get("provider") == db_model["provider"] and d.get("model_name") == db_model["model_name"]
        record(f"ADMIN detalj pitanja #{aid} sa ?reveal=1", f"{db_model['provider']} / {db_model['model_name']}",
               f"{d.get('provider')} / {d.get('model_name')}", same and not [f for f in ORDER_FIELDS if f not in d])

    # ---------- predlozi objasnjenja ----------
    exp_teacher = teacher or headers(db_all("SELECT u.id FROM users u JOIN roles r ON r.id = u.role_id WHERE r.name = 'TEACHER' ORDER BY u.id LIMIT 1")[0]["id"], "TEACHER")
    _, exp_pending = get("/api/ai-artifacts/explanation?status=predlog", exp_teacher)
    check_hidden("TEACHER lista objasnjenja, 'predlog'", exp_pending or [], ORDER_FIELDS)
    if exp_pending:
        aid = exp_pending[0]["id"]
        _, d = get(f"/api/ai-artifacts/explanation/{aid}", exp_teacher)
        check_hidden(f"TEACHER detalj objasnjenja #{aid}, 'predlog'", [d["artifact"]], ORDER_FIELDS)
        _, d = get(f"/api/ai-artifacts/explanation/{aid}?reveal=1", admin)
        check_shown(f"ADMIN detalj objasnjenja #{aid} sa ?reveal=1", [d["artifact"]], ("created_at",))
    exp_decided = []
    for s in DECIDED:
        _, lst = get(f"/api/ai-artifacts/explanation?status={s}", exp_teacher)
        exp_decided += lst or []
    check_shown("TEACHER lista objasnjenja, zavrseni", exp_decided, ("created_at",))

    # naziv modela ni u jednom ugnezdenom polju, ni za jednu rutu objasnjenja
    exp_ids = [r["id"] for r in db_all("SELECT id FROM ai_generated_artifacts WHERE artifact_type = 'explanation'")]
    scanned, hits = 0, []
    for h in (exp_teacher, admin):
        for suffix in ("", "&reveal=1"):
            for s in ("predlog",) + DECIDED:
                _, body = get(f"/api/ai-artifacts/explanation?status={s}{suffix}", h)
                scanned += 1
                hits += scan_for_model(body, model_names)
            for aid in exp_ids:
                _, body = get(f"/api/ai-artifacts/explanation/{aid}{'?reveal=1' if suffix else ''}", h)
                scanned += 1
                hits += scan_for_model(body, model_names)
    record("objasnjenja: model ni u jednom ugnezdenom polju", f"0 pogodaka u {scanned} odgovora",
           f"{len(hits)} pogodaka u {scanned} odgovora {hits[:3] if hits else ''}", scanned > 0 and not hits)

    # ---------- redosled ----------
    for label, url, artifact_type in (
        ("pitanja", "/api/ai/artifacts?status=predlog", "question"),
        ("objasnjenja", "/api/ai-artifacts/explanation?status=predlog", "explanation"),
    ):
        _, first = get(url, admin)
        _, second = get(url, admin)
        ids1 = [r["id"] for r in first]
        ids2 = [r["id"] for r in second]
        record(f"redosled liste {label}: dva uzastopna zahteva", "isti redosled", f"{'isti' if ids1 == ids2 else 'RAZLICIT'} ({len(ids1)} redova)", ids1 == ids2)
        expected = sorted(r["id"] for r in db_all(
            "SELECT id FROM ai_generated_artifacts WHERE artifact_type = %s AND status = 'predlog'", (artifact_type,)))
        record(f"redosled liste {label}: filter po statusu ocuvan", f"{len(expected)} id-jeva iz baze",
               f"{len(ids1)} id-jeva, isti skup: {sorted(ids1) == expected}", sorted(ids1) == expected)
        chrono = [r["id"] for r in db_all(
            "SELECT id FROM ai_generated_artifacts WHERE artifact_type = %s AND status = 'predlog' ORDER BY created_at DESC, id DESC", (artifact_type,))]
        if len(ids1) >= 3:
            record(f"redosled liste {label}: nije hronoloski", "razlicit od created_at", "razlicit" if ids1 not in (chrono, chrono[::-1]) else "HRONOLOSKI",
                   ids1 not in (chrono, chrono[::-1]))

    # ---------- baza ----------
    counts_after = row_counts()
    changed = {t: (counts_before[t], counts_after[t]) for t in COUNT_TABLES if counts_before[t] != counts_after[t]}
    record("brojevi redova u bazi pre/posle", "isti", "isti" if not changed else str(changed), not changed)


# ---------- drugi ocenjivac (tacka E) ----------

SECOND_COUNT_TABLES = COUNT_TABLES + ("users", "teacher_subjects")
HIDDEN_FROM_SECOND_RATER = ("status", "edited_text", "rejection_reason", "reviewed_by", "reviewed_at",
                            "created_question_id", "reviewed_difficulty", "reviewed_bloom_level",
                            "reviewed_duplicate", "model_difficulty", "model_bloom_level") + MODEL_FIELDS + ORDER_FIELDS
created = {"users": [], "batches": [], "artifacts": [], "runs": [], "prompts_before": set()}


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


def skip(case, why):
    results.append((case, "-", why, "PRESKOCENO"))


class _FakeResponse:
    def __init__(self, body):
        self.status_code, self.headers, self._body, self.text = 200, {}, body, json.dumps(body)

    def json(self):
        return self._body


def _cleanup_second():
    arts, runs, users = created["artifacts"], created["runs"], created["users"]

    def ph(ids):
        return ",".join(["%s"] * len(ids))

    if arts:
        questions = [r["created_question_id"] for r in db_all(
            f"SELECT created_question_id FROM ai_generated_artifacts WHERE id IN ({ph(arts)}) AND created_question_id IS NOT NULL", arts)]
        if db_all("SHOW TABLES LIKE 'ai_label_evaluations'"):
            db_exec(f"DELETE FROM ai_label_evaluations WHERE artifact_id IN ({ph(arts)})", arts)
        db_exec(f"DELETE FROM ai_evaluations WHERE artifact_id IN ({ph(arts)})", arts)
        db_exec(f"DELETE FROM ai_generated_artifacts WHERE id IN ({ph(arts)})", arts)
        if questions:
            db_exec(f"DELETE FROM exam_answers WHERE question_id IN ({ph(questions)})", questions)
            db_exec(f"DELETE FROM exam_questions WHERE id IN ({ph(questions)})", questions)
    if runs:
        db_exec(f"DELETE FROM ai_generation_runs WHERE id IN ({ph(runs)})", runs)
    if created["batches"]:
        db_exec(f"DELETE FROM evaluation_batches WHERE id IN ({ph(created['batches'])})", created["batches"])
    if users:
        db_exec(f"DELETE FROM teacher_subjects WHERE teacher_id IN ({ph(users)})", users)
        db_exec(f"DELETE FROM users WHERE id IN ({ph(users)})", users)
    for row in db_all("SELECT id FROM ai_prompts"):
        if row["id"] not in created["prompts_before"] and not db_all(
                "SELECT 1 FROM ai_generation_runs WHERE prompt_id = %s LIMIT 1", (row["id"],)):
            db_exec("DELETE FROM ai_prompts WHERE id = %s", (row["id"],))


def run_second_rater():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        enabled = second_rater_enabled(cur)
    finally:
        cur.close()
        conn.close()
    print(f"Migracija db/migration_second_rater.sql: {'POKRENUTA' if enabled else 'NIJE pokrenuta'}")

    tag = uuid.uuid4().hex[:6]
    src = db_all("""SELECT q.id, q.subject_id FROM exam_questions q JOIN exam_answers a ON a.question_id = q.id
                    WHERE q.subject_id IS NOT NULL GROUP BY q.id, q.subject_id
                    HAVING SUM(a.is_correct) = 1 AND COUNT(*) >= 2 ORDER BY q.id DESC LIMIT 1""")[0]
    n = db_all("SELECT COUNT(*) AS n FROM exam_answers WHERE question_id = %s", (src["id"],))[0]["n"]

    def teacher(label):
        uid = db_exec("INSERT INTO users (email, password_hash, role_id, display_name, is_active) VALUES (%s, '!', 2, %s, 1)",
                      (f"tmp-blind-{tag}-{label}@example.invalid", f"tmp {label}"))
        created["users"].append(uid)
        db_exec("INSERT INTO teacher_subjects (teacher_id, subject_id) VALUES (%s, %s)", (uid, src["subject_id"]))
        return uid, headers(uid, "TEACHER")

    a_id, a = teacher("A")      # odlucuje
    b_id, b = teacher("B")      # drugi ocenjivac
    _, c = teacher("C")         # jos nije ocenio
    admin_id = db_all("SELECT u.id FROM users u JOIN roles r ON r.id = u.role_id WHERE r.name = 'ADMIN' ORDER BY u.id LIMIT 1")[0]["id"]
    admin = headers(admin_id, "ADMIN")
    batch = db_exec("INSERT INTO evaluation_batches (name, description) VALUES (%s, 'tmp verify')", (f"tmp-blind-{tag}",))
    created["batches"].append(batch)

    payload = {"question_text": "Probno pitanje za drugu ocenu", "difficulty": "srednje", "bloom_level": "primena",
               "answers": [{"answer_text": f"o{i}", "is_correct": i == 0} for i in range(n)]}
    body = {"choices": [{"message": {"content": json.dumps(payload)}, "finish_reason": "stop"}], "usage": {"total_tokens": 1}}
    real_post = requests.post
    requests.post = lambda *args, **kwargs: _FakeResponse(body)
    try:
        ids = []
        for _ in range(2):
            r = client.post(f"/api/questions/{src['id']}/generate-similar?provider=groq&evaluation_batch_id={batch}", headers=admin)
            data = r.get_json() or {}
            created["runs"].append(data.get("generation_run_id"))
            created["artifacts"].append(data.get("artifact_id"))
            ids.append(data.get("artifact_id"))
    finally:
        requests.post = real_post
    x, y = ids

    def scores_for(art_id, h):
        detail = client.get(f"/api/ai/artifacts/{art_id}/second-rating", headers=h).get_json() or {}
        crit = detail.get("rubric_criteria") or client.get(f"/api/ai/artifacts/{y}", headers=admin).get_json()["rubric_criteria"]
        return [{"rubric_definition_id": c["id"], "score": 4} for c in crit]

    # A donosi odluku o X
    rubric = client.get(f"/api/ai/artifacts/{x}", headers=a).get_json()["rubric_criteria"]
    r = client.post(f"/api/ai/artifacts/{x}/review", headers=a, json={
        "decision": "prihvaceno", "scores": [{"rubric_definition_id": c["id"], "score": 3} for c in rubric],
        "reviewed_difficulty": "srednje", "reviewed_bloom_level": "primena"})
    record("E: A donosi odluku (predlog iz serije)", "200", f"{r.status_code}", r.status_code == 200)

    r = client.get(f"/api/ai/artifacts/{x}", headers=b)
    record("E: B ne vidi odluku ni model pre svoje ocene (detalj)", "403 sa uputom na drugu ocenu",
           f"{r.status_code} second_rating={(r.get_json() or {}).get('second_rating')}",
           r.status_code == 403 and (r.get_json() or {}).get("second_rating") is True)
    listed = [row["id"] for row in client.get("/api/ai/artifacts?status=prihvaceno", headers=b).get_json()]
    record("E: B ne vidi odluku u listi (status=prihvaceno)", "X nije u listi", f"X u listi={x in listed}", x not in listed)
    d = client.get(f"/api/ai/artifacts/{x}", headers=a).get_json() or {}
    record("E: A (ocenio) vidi model posle odluke", "provider/model_name prisutni",
           f"nedostaje: {[f for f in MODEL_FIELDS if f not in d] or 'nista'}", all(f in d for f in MODEL_FIELDS))
    r = client.get(f"/api/ai/artifacts/{x}", headers=admin)
    record("E: ADMIN bez ?reveal=1 (nije ocenio)", "403", f"{r.status_code}", r.status_code == 403)
    d = client.get(f"/api/ai/artifacts/{x}?reveal=1", headers=admin).get_json() or {}
    record("E: ADMIN sa ?reveal=1", "model vidljiv", f"nedostaje: {[f for f in MODEL_FIELDS if f not in d] or 'nista'}",
           all(f in d for f in MODEL_FIELDS))

    if not enabled:
        statuses = [client.get("/api/ai/artifacts/second-rating", headers=b).status_code,
                    client.get(f"/api/ai/artifacts/{x}/second-rating", headers=b).status_code,
                    client.post(f"/api/ai/artifacts/{x}/evaluations", headers=b, json={}).status_code,
                    client.post(f"/api/evaluation-batches/{batch}/close", headers=admin).status_code]
        record("E pre migracije: rute druge ocene i zatvaranja", "409 x 4", f"{statuses}", statuses == [409] * 4)
        for case in ("E: pogled drugog ocenjivaca bez modela i odluke", "E: druga ocena ne menja status",
                     "E: dupla ocena 409", "E: prvi ocenjivac ne moze da bude drugi", "E: B vidi model posle svoje ocene",
                     "E: ko je dao drugu ocenu ne moze da odluci", "E: lista druge ocene = uzorak",
                     "E: posle zatvaranja serije C vidi", "E: posle zatvaranja nema druge ocene"):
            skip(case, "migracija nije pokrenuta")
        return

    view = client.get(f"/api/ai/artifacts/{x}/second-rating", headers=b).get_json() or {}
    leaked = [k for k in HIDDEN_FROM_SECOND_RATER if k in view] + \
             [k for k in ("difficulty", "bloom_level") if k in (view.get("original_text") or {})]
    record("E: pogled drugog ocenjivaca bez modela i odluke", "nema modela, statusa, odluke, izmene, oznaka",
           f"procurelo: {leaked or 'nista'}, labels_required={view.get('labels_required')}", not leaked and view.get("rubric_criteria"))

    before = db_all("SELECT status, edited_text, reviewed_by, reviewed_at FROM ai_generated_artifacts WHERE id = %s", (x,))[0]
    r = client.post(f"/api/ai/artifacts/{x}/evaluations", headers=b,
                    json={"scores": scores_for(x, b), "difficulty": "tesko", "bloom_level": "analiza"})
    after = db_all("SELECT status, edited_text, reviewed_by, reviewed_at FROM ai_generated_artifacts WHERE id = %s", (x,))[0]
    rounds = db_all("SELECT evaluation_round, COUNT(*) AS n FROM ai_evaluations WHERE artifact_id = %s AND evaluator_id = %s GROUP BY 1", (x, b_id))
    labels = db_all("SELECT difficulty, bloom_level FROM ai_label_evaluations WHERE artifact_id = %s AND evaluator_id = %s", (x, b_id))
    record("E: druga ocena ne menja status", "201, status/izmena/reviewed_by isti, runda 2, oznake upisane",
           f"{r.status_code}, isto={before == after}, runde={[(row['evaluation_round'], row['n']) for row in rounds]}, oznake={labels}",
           r.status_code == 201 and before == after and rounds and all(row["evaluation_round"] == 2 for row in rounds)
           and labels == [{"difficulty": "tesko", "bloom_level": "analiza"}])

    r = client.post(f"/api/ai/artifacts/{x}/evaluations", headers=b, json={"scores": scores_for(y, b)})
    record("E: dupla ocena 409", "409", f"{r.status_code} {(r.get_json() or {}).get('error')}", r.status_code == 409)
    r = client.post(f"/api/ai/artifacts/{x}/evaluations", headers=a, json={"scores": scores_for(y, a)})
    record("E: prvi ocenjivac ne moze da bude drugi", "409", f"{r.status_code} {(r.get_json() or {}).get('error')}", r.status_code == 409)
    d = client.get(f"/api/ai/artifacts/{x}", headers=b).get_json() or {}
    record("E: B vidi model posle svoje ocene", "200, model vidljiv",
           f"nedostaje: {[f for f in MODEL_FIELDS if f not in d] or 'nista'}", all(f in d for f in MODEL_FIELDS))

    r1 = client.post(f"/api/ai/artifacts/{y}/evaluations", headers=b,
                     json={"scores": scores_for(y, b), "difficulty": "lako", "bloom_level": "pamcenje"})
    rubric_y = client.get(f"/api/ai/artifacts/{y}", headers=admin).get_json()["rubric_criteria"]
    r2 = client.post(f"/api/ai/artifacts/{y}/review", headers=b, json={
        "decision": "odbaceno", "rejection_reason": "x", "scores": [{"rubric_definition_id": c["id"], "score": 2} for c in rubric_y]})
    record("E: ko je dao drugu ocenu ne moze da odluci", "201, pa 409 pri pregledu",
           f"{r1.status_code}, {r2.status_code} {(r2.get_json() or {}).get('error')}", r1.status_code == 201 and r2.status_code == 409)

    listed = [row["id"] for row in client.get(f"/api/ai/artifacts/second-rating?batch_id={batch}", headers=c).get_json()]
    c_id = created["users"][2]
    expected = [art for art in (x, y) if in_second_rating_sample(c_id, art)]
    record("E: lista druge ocene = uzorak", f"{sorted(expected)} (uzorak 30 %, stabilan)", f"{sorted(listed)}",
           sorted(listed) == sorted(expected))

    r_before = client.get(f"/api/ai/artifacts/{x}", headers=c)
    r_close = client.post(f"/api/evaluation-batches/{batch}/close", headers=admin)
    d = client.get(f"/api/ai/artifacts/{x}", headers=c)
    record("E: posle zatvaranja serije C vidi", "403 pa 200 sa modelom",
           f"{r_before.status_code} -> zatvaranje {r_close.status_code} -> {d.status_code}, model={'da' if all(f in (d.get_json() or {}) for f in MODEL_FIELDS) else 'ne'}",
           r_before.status_code == 403 and r_close.status_code == 200 and d.status_code == 200
           and all(f in d.get_json() for f in MODEL_FIELDS))
    r = client.post(f"/api/ai/artifacts/{x}/evaluations", headers=c, json={"scores": scores_for(y, admin)})
    record("E: posle zatvaranja nema druge ocene", "409", f"{r.status_code} {(r.get_json() or {}).get('error')}", r.status_code == 409)


def print_table():
    headers_row = ("Slucaj", "Ocekivano", "Dobijeno", "")
    rows = [(c, e, g if len(g) <= 80 else g[:77] + "...", s) for c, e, g, s in results]
    widths = [max(len(str(r[i])) for r in rows + [headers_row]) for i in range(4)]
    line = " | ".join(h.ljust(w) for h, w in zip(headers_row, widths))
    print(line)
    print("-" * len(line))
    for r in rows:
        print(" | ".join(str(v).ljust(w) for v, w in zip(r, widths)))
    failed = sum(1 for r in results if r[3] == "PALO")
    skipped = sum(1 for r in results if r[3] == "PRESKOCENO")
    print(f"\nUkupno: {len(results)}, palo: {failed}, preskoceno: {skipped}")
    return failed


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    run()
    real_sleep = ai_provider.time.sleep
    ai_provider.time.sleep = lambda s: None
    created["prompts_before"] = {row["id"] for row in db_all("SELECT id FROM ai_prompts")}
    second_before = {t: db_all(f"SELECT COUNT(*) AS n FROM {t}")[0]["n"] for t in SECOND_COUNT_TABLES}
    try:
        run_second_rater()
    finally:
        ai_provider.time.sleep = real_sleep
        _cleanup_second()
        second_after = {t: db_all(f"SELECT COUNT(*) AS n FROM {t}")[0]["n"] for t in SECOND_COUNT_TABLES}
        changed = {t: (second_before[t], second_after[t]) for t in SECOND_COUNT_TABLES if second_before[t] != second_after[t]}
        record("E: brojevi redova pre/posle (privremeni podaci obrisani)", "isti", "isti" if not changed else str(changed), not changed)
    sys.exit(1 if print_table() else 0)
