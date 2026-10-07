-- Zbirni prikaz po provajderu i modelu: AI predlozi OBJASNJENJA (artifact_type = 'explanation')
-- Pokrece se rucno (phpMyAdmin). Samo citanje.
--
-- Kolone:
--   broj_pokusaja      - svi pozivi modela (ai_generation_runs, purpose = 'explanation')
--   neuspeli_pokusaji  - pozivi koji nisu dali iskoristiv predlog (validation_passed = 0;
--                        za njih ne postoji red u ai_generated_artifacts)
--   pala_mehanicka_provera - rezim B: resenje modela nije proslo test primere
--                        (accuracy_check_passed = 0); predlog ipak postoji
--   broj_predloga      - nastali predlozi (ai_generated_artifacts)
--   prihvaceno / prihvaceno_izmena / odbaceno / na_cekanju - odluke nastavnika
--   prosek_*           - prosecna ocena po kriterijumu rubrike (skala 1-5); kriterijumi
--                        nastavnika i studenata (student_*) iz ai_rubric_definitions,
--                        applies_to = 'explanation'
--   broj_ocena_nastavnika / broj_ocena_studenata - broj pojedinacnih ocena po vrsti rubrike
--
-- EKSPERIMENT: ukljuceni su samo pozivi iz evaluacione serije (evaluation_batch_id).
-- Za jednu seriju zameniti uslov sa: AND r.evaluation_batch_id = <id>

WITH runs AS (
    SELECT r.id, r.model_id, r.validation_passed, r.accuracy_check_passed
    FROM ai_generation_runs r
    WHERE r.purpose = 'explanation'
      AND r.evaluation_batch_id IS NOT NULL  -- FILTER_EKSPERIMENT
),
per_model AS (
    SELECT
        runs.model_id,
        COUNT(*)                              AS broj_pokusaja,
        SUM(runs.validation_passed = 0)       AS neuspeli_pokusaji,
        SUM(runs.accuracy_check_passed = 0)   AS pala_mehanicka_provera,
        COUNT(a.id)                           AS broj_predloga,
        SUM(a.status = 'prihvaceno')          AS prihvaceno,
        SUM(a.status = 'prihvaceno_izmena')   AS prihvaceno_izmena,
        SUM(a.status = 'odbaceno')            AS odbaceno,
        SUM(a.status = 'predlog')             AS na_cekanju
    FROM runs
    LEFT JOIN ai_generated_artifacts a
           ON a.generation_run_id = runs.id AND a.artifact_type = 'explanation'
    GROUP BY runs.model_id
),
per_model_scores AS (
    SELECT
        runs.model_id,
        -- rubrika nastavnika
        ROUND(AVG(CASE WHEN d.evaluator_role = 'TEACHER' AND d.dimension_key = 'tacnost_objasnjenja' THEN e.score END), 2) AS prosek_tacnost_objasnjenja,
        ROUND(AVG(CASE WHEN d.evaluator_role = 'TEACHER' AND d.dimension_key = 'vernost'             THEN e.score END), 2) AS prosek_vernost,
        ROUND(AVG(CASE WHEN d.evaluator_role = 'TEACHER' AND d.dimension_key = 'potpunost'           THEN e.score END), 2) AS prosek_potpunost,
        ROUND(AVG(CASE WHEN d.evaluator_role = 'TEACHER' AND d.dimension_key = 'pedagoska_vrednost'  THEN e.score END), 2) AS prosek_pedagoska_vrednost,
        ROUND(AVG(CASE WHEN d.evaluator_role = 'TEACHER' AND d.dimension_key = 'jezicka_ispravnost'  THEN e.score END), 2) AS prosek_jezicka_ispravnost,
        -- rubrika studenata
        ROUND(AVG(CASE WHEN d.evaluator_role = 'STUDENT' AND d.dimension_key = 'korisnost'           THEN e.score END), 2) AS prosek_student_korisnost,
        ROUND(AVG(CASE WHEN d.evaluator_role = 'STUDENT' AND d.dimension_key = 'jasnoca'             THEN e.score END), 2) AS prosek_student_jasnoca,
        ROUND(AVG(CASE WHEN d.evaluator_role = 'STUDENT' AND d.dimension_key = 'percepcija_naucenog' THEN e.score END), 2) AS prosek_student_percepcija_naucenog,
        SUM(d.evaluator_role = 'TEACHER') AS broj_ocena_nastavnika,
        SUM(d.evaluator_role = 'STUDENT') AS broj_ocena_studenata
    FROM runs
    JOIN ai_generated_artifacts a
      ON a.generation_run_id = runs.id AND a.artifact_type = 'explanation'
    JOIN ai_evaluations e        ON e.artifact_id = a.id
    JOIN ai_rubric_definitions d ON d.id = e.rubric_definition_id
                                AND d.applies_to = 'explanation'
    GROUP BY runs.model_id
)
SELECT
    m.provider,
    m.model_name,
    pm.broj_pokusaja,
    pm.neuspeli_pokusaji,
    pm.pala_mehanicka_provera,
    pm.broj_predloga,
    pm.prihvaceno,
    pm.prihvaceno_izmena,
    pm.odbaceno,
    pm.na_cekanju,
    ps.prosek_tacnost_objasnjenja,
    ps.prosek_vernost,
    ps.prosek_potpunost,
    ps.prosek_pedagoska_vrednost,
    ps.prosek_jezicka_ispravnost,
    ps.prosek_student_korisnost,
    ps.prosek_student_jasnoca,
    ps.prosek_student_percepcija_naucenog,
    COALESCE(ps.broj_ocena_nastavnika, 0) AS broj_ocena_nastavnika,
    COALESCE(ps.broj_ocena_studenata, 0)  AS broj_ocena_studenata
FROM per_model pm
JOIN ai_models m ON m.id = pm.model_id
LEFT JOIN per_model_scores ps ON ps.model_id = pm.model_id
ORDER BY m.provider, m.model_name;
