"""
Logika za nastavnicki pregled predloga objasnjenja/resenja (Andrejev modul).
Odvojeno od explanation_prompts.py/code_executor.py po istom principu
"razdvojene odgovornosti u kodu" (Plan integracije, odeljak 3, tacka 4) -
ne dira ai_generated_artifacts/ai_evaluations rute koje eventualno postoje
u Andjinom modulu (na 2.9.2026. potvrdjeno grep-om da takve rute ne postoje
ni na main ni na ovoj grani - videti napomenu u app.py komentaru iznad rute).

Sva poslovna logika je namerno izdvojena iz Flask rute u ove cistu funkciju
da bi mogla da se testira nezavisno od HTTP sloja (isti razlog kao za
code_executor.run_against_test_cases).
"""


class ArtifactNotFoundError(Exception):
    """Artifact sa datim id-jem ne postoji (ruta treba da vrati 404)."""


class ArtifactStateError(Exception):
    """Artifact nije u stanju u kome moze da se pregleda (ruta treba da vrati 409)."""


class ReviewValidationError(Exception):
    """Nevalidan ulaz (ruta treba da vrati 400)."""


VALID_ACTIONS = ("approve", "edit", "reject")

_STATUS_BY_ACTION = {
    "approve": "odobreno",
    "edit": "izmenjeno",
    "reject": "odbijeno",
}


def review_explanation_artifact(
    conn,
    artifact_id: int,
    reviewer_id: int,
    action: str,
    edited_text: str | None = None,
    rejection_reason: str | None = None,
    scores: list[dict] | None = None,
) -> dict:
    """
    Primenjuje nastavnicku odluku (odobri/izmeni/odbij) na predlog objasnjenja
    i upisuje TEACHER rubrika ocene u ai_evaluations.

    scores: lista {"dimension_key": str, "score": int, "comment": str|None}.
    Obavezna za action in ("approve", "edit") - mora pokrivati TACNO sve
    TEACHER dimenzije (applies_to='explanation'), bez viska/manjka i bez
    duplikata. Opciona za action='reject' (validira se ako je prosledjena,
    ali se ne zahteva potpunost - nema smisla ocenjivati kvalitet sadrzaja
    koji se u celini odbacuje).

    Elimatorno pravilo (iz specifikacije zadatka, odeljak o tacnosti resenja
    za rezim B): ako je mode == 'mode_b' i accuracy_check_passed == 0
    (mehanicka provera nije prosla), 'approve' i 'edit' su zabranjeni - jedini
    mogudi ishod je 'reject'. Ovo je namerno tvrdo ogranicenje u kodu, ne
    samo preporuka u UI-ju, jer zadatak trazi da je tacnost resenja
    "eliminatoran kriterijum", ne subjektivna ocena.

    Vraca dict {"artifact_id", "new_status", "evaluation_ids"} pri uspehu.
    Baca ArtifactNotFoundError / ArtifactStateError / ReviewValidationError
    pri gresci - ruta ih mapira na 404 / 409 / 400.
    """
    if action not in VALID_ACTIONS:
        raise ReviewValidationError(
            f"action mora biti jedno od {VALID_ACTIONS}, dobijeno: {action!r}"
        )

    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT a.id, a.status, a.artifact_type, a.generation_run_id,
               r.mode, r.accuracy_check_passed
        FROM ai_generated_artifacts a
        JOIN ai_generation_runs r ON r.id = a.generation_run_id
        WHERE a.id = %s
        """,
        (artifact_id,),
    )
    artifact = cursor.fetchone()
    if not artifact:
        cursor.close()
        raise ArtifactNotFoundError(f"Artifact {artifact_id} ne postoji")

    if artifact["artifact_type"] != "explanation":
        cursor.close()
        raise ReviewValidationError(
            "Ova funkcija pregleda samo artifact_type='explanation'"
        )

    if artifact["status"] != "predlog":
        cursor.close()
        raise ArtifactStateError(
            f"Artifact {artifact_id} je vec u statusu '{artifact['status']}' "
            "- ponovni pregled kroz ovu rutu nije podrzan"
        )

    if action in ("approve", "edit") and artifact["mode"] == "mode_b" \
            and artifact["accuracy_check_passed"] == 0:
        cursor.close()
        raise ReviewValidationError(
            "Ne moze se odobriti niti izmeniti - mehanicka provera tacnosti "
            "resenja (mode_b) nije prosla. Tacnost resenja je eliminatoran "
            "kriterijum; jedina dozvoljena akcija je 'reject'."
        )

    if action == "edit" and not (edited_text and edited_text.strip()):
        cursor.close()
        raise ReviewValidationError("edited_text je obavezan za action='edit'")

    if action == "reject" and not (rejection_reason and rejection_reason.strip()):
        cursor.close()
        raise ReviewValidationError(
            "rejection_reason je obavezan za action='reject'"
        )

    cursor.execute(
        """
        SELECT id, dimension_key, scale_min, scale_max
        FROM ai_rubric_definitions
        WHERE applies_to = 'explanation' AND evaluator_role = 'TEACHER'
        """
    )
    valid_dims = {row["dimension_key"]: row for row in cursor.fetchall()}

    scores = scores or []
    provided_keys = set()
    for item in scores:
        key = item.get("dimension_key")
        if key not in valid_dims:
            cursor.close()
            raise ReviewValidationError(f"Nepoznat dimension_key: {key!r}")
        if key in provided_keys:
            cursor.close()
            raise ReviewValidationError(f"Duplirana ocena za dimension_key: {key!r}")
        provided_keys.add(key)

        dim = valid_dims[key]
        score = item.get("score")
        if not isinstance(score, int) or isinstance(score, bool) \
                or not (dim["scale_min"] <= score <= dim["scale_max"]):
            cursor.close()
            raise ReviewValidationError(
                f"score za {key!r} mora biti ceo broj izmedju "
                f"{dim['scale_min']} i {dim['scale_max']}"
            )

    if action in ("approve", "edit"):
        missing = set(valid_dims.keys()) - provided_keys
        if missing:
            cursor.close()
            raise ReviewValidationError(
                "Nedostaju ocene za TEACHER dimenzije: "
                + ", ".join(sorted(missing))
            )

    new_status = _STATUS_BY_ACTION[action]

    cursor.execute(
        """
        UPDATE ai_generated_artifacts
        SET status = %s, edited_text = %s, rejection_reason = %s,
            reviewed_by = %s, reviewed_at = NOW()
        WHERE id = %s
        """,
        (
            new_status,
            edited_text if action == "edit" else None,
            rejection_reason if action == "reject" else None,
            reviewer_id,
            artifact_id,
        ),
    )

    evaluation_ids = []
    for item in scores:
        dim = valid_dims[item["dimension_key"]]
        cursor.execute(
            """
            INSERT INTO ai_evaluations
            (artifact_id, rubric_definition_id, evaluator_id, evaluator_role,
             score, comment)
            VALUES (%s, %s, %s, 'TEACHER', %s, %s)
            """,
            (artifact_id, dim["id"], reviewer_id, item["score"], item.get("comment")),
        )
        evaluation_ids.append(cursor.lastrowid)

    conn.commit()
    cursor.close()

    return {
        "artifact_id": artifact_id,
        "new_status": new_status,
        "evaluation_ids": evaluation_ids,
    }
