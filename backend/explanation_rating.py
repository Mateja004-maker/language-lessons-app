"""
Studentsko ocenjivanje korisnosti odobrenih predloga objasnjenja (Andrejev
modul) - "student-facing" strana dual-sided evaluacije iz specifikacije
zadatka (nastavnik ocenjuje kvalitet/tacnost, student ocenjuje korisnost).
Odvojeno od explanation_review.py (koji pokriva nastavnicki pregled) po
istom principu razdvojenih odgovornosti - obe funkcije upisuju u istu
deljenu ai_evaluations tabelu, ali razlicitim evaluator_role vrednostima
i razlicitim skupom dozvoljenih dimenzija (STUDENT vs TEACHER).
"""


class ArtifactNotFoundError(Exception):
    """Artifact sa datim id-jem ne postoji (ruta treba da vrati 404)."""


class ArtifactNotApprovedError(Exception):
    """Artifact jos nije odobren/izmenjen od strane nastavnika - studenti ne
    smeju da ga vide/ocene dok je u statusu 'predlog' ili 'odbaceno' (ruta
    treba da vrati 409)."""


class AlreadyRatedError(Exception):
    """Ovaj student je vec ocenio ovaj artifact (ruta treba da vrati 409)."""


class RatingValidationError(Exception):
    """Nevalidan ulaz (ruta treba da vrati 400)."""


_APPROVED_STATUSES = ("prihvaceno", "prihvaceno_izmena")


def get_final_text(artifact_row: dict) -> str:
    """Vraca tekst koji se stvarno prikazuje studentu: edited_text ako
    postoji (nastavnik je izmenio predlog), inace original_text."""
    return artifact_row.get("edited_text") or artifact_row["original_text"]


def submit_student_rating(
    conn,
    artifact_id: int,
    student_id: int,
    scores: list[dict] | None,
) -> dict:
    """
    Upisuje studentsku ocenu korisnosti (STUDENT rubrika: korisnost, jasnoca,
    percepcija_naucenog - applies_to='explanation') za odobren/izmenjen
    predlog objasnjenja. Zahteva potpun skup od tacno tih dimenzija (isto
    pravilo potpunosti kao kod nastavnickog pregleda). Jedan student moze da
    oceni isti artifact samo jednom.

    Vraca {"artifact_id", "evaluation_ids"} pri uspehu. Baca
    ArtifactNotFoundError / ArtifactNotApprovedError / AlreadyRatedError /
    RatingValidationError - ruta ih mapira na 404 / 409 / 409 / 400.
    """
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT id, status, artifact_type
        FROM ai_generated_artifacts
        WHERE id = %s
        """,
        (artifact_id,),
    )
    artifact = cursor.fetchone()
    if not artifact:
        cursor.close()
        raise ArtifactNotFoundError(f"Artifact {artifact_id} ne postoji")

    if artifact["artifact_type"] != "explanation":
        cursor.close()
        raise RatingValidationError(
            "Ova funkcija ocenjuje samo artifact_type='explanation'"
        )

    if artifact["status"] not in _APPROVED_STATUSES:
        cursor.close()
        raise ArtifactNotApprovedError(
            f"Artifact {artifact_id} nije jos odobren od strane nastavnika "
            f"(status='{artifact['status']}') - studenti ne mogu da ocenjuju "
            "predloge koji nisu prosli pregled"
        )

    cursor.execute(
        """
        SELECT COUNT(*) AS cnt FROM ai_evaluations
        WHERE artifact_id = %s AND evaluator_id = %s AND evaluator_role = 'STUDENT'
        """,
        (artifact_id, student_id),
    )
    if cursor.fetchone()["cnt"] > 0:
        cursor.close()
        raise AlreadyRatedError(
            f"Student {student_id} je vec ocenio artifact {artifact_id}"
        )

    cursor.execute(
        """
        SELECT id, dimension_key, scale_min, scale_max
        FROM ai_rubric_definitions
        WHERE applies_to = 'explanation' AND evaluator_role = 'STUDENT'
        """
    )
    valid_dims = {row["dimension_key"]: row for row in cursor.fetchall()}

    scores = scores or []
    provided_keys = set()
    for item in scores:
        key = item.get("dimension_key")
        if key not in valid_dims:
            cursor.close()
            raise RatingValidationError(f"Nepoznat dimension_key: {key!r}")
        if key in provided_keys:
            cursor.close()
            raise RatingValidationError(f"Duplirana ocena za dimension_key: {key!r}")
        provided_keys.add(key)

        dim = valid_dims[key]
        score = item.get("score")
        if not isinstance(score, int) or isinstance(score, bool) \
                or not (dim["scale_min"] <= score <= dim["scale_max"]):
            cursor.close()
            raise RatingValidationError(
                f"score za {key!r} mora biti ceo broj izmedju "
                f"{dim['scale_min']} i {dim['scale_max']}"
            )

    missing = set(valid_dims.keys()) - provided_keys
    if missing:
        cursor.close()
        raise RatingValidationError(
            "Nedostaju ocene za STUDENT dimenzije: " + ", ".join(sorted(missing))
        )

    evaluation_ids = []
    for item in scores:
        dim = valid_dims[item["dimension_key"]]
        cursor.execute(
            """
            INSERT INTO ai_evaluations
            (artifact_id, rubric_definition_id, evaluator_id, evaluator_role,
             score, comment)
            VALUES (%s, %s, %s, 'STUDENT', %s, %s)
            """,
            (artifact_id, dim["id"], student_id, item["score"], item.get("comment")),
        )
        evaluation_ids.append(cursor.lastrowid)

    conn.commit()
    cursor.close()

    return {"artifact_id": artifact_id, "evaluation_ids": evaluation_ids}
