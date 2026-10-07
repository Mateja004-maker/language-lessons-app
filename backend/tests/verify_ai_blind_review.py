"""Provera slepog ocenjivanja AI predloga (pitanja i objasnjenja).

Pokretanje (iz foldera backend/):
    python tests/verify_ai_blind_review.py

Gadja stvarne rute kroz app.test_client() nad stvarnom bazom iz backend/.env.
SAMO CITA: koristi postojece predloge i korisnike, ne pravi privremene
podatke; na kraju proverava da su brojevi redova u bazi isti kao na pocetku.
JWT tokeni se prave u procesu (create_access_token) - bez kljuceva u fajlu.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask_jwt_extended import create_access_token  # noqa: E402

from app import app, get_db_connection  # noqa: E402

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
    run()
    sys.exit(1 if print_table() else 0)
