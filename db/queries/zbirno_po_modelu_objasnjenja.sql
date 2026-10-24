-- Zbirni prikaz po provajderu, modelu i rezimu (mode_a / mode_b): AI predlozi OBJASNJENJA (artifact_type = 'explanation')
-- Pokrece se rucno (phpMyAdmin). Samo citanje.
--
-- Kolone:
--   rezim              - ai_generation_runs.mode (mode_a / mode_b)
--   broj_pokusaja      - svi pozivi modela (ai_generation_runs, purpose = 'explanation')
--   neuspeli_pokusaji  - pozivi koji nisu dali iskoristiv predlog (validation_passed = 0;
--                        za njih ne postoji red u ai_generated_artifacts)
--   pala_mehanicka_provera - rezim B: resenje modela nije proslo test primere
--                        (accuracy_check_passed = 0); predlog ipak postoji
--   prosek_vreme_odziva_ms - prosecno response_time_ms
--   stopa_iz_prve      - SUM(first_attempt_passed = 1) / broj_pokusaja (0..1); run-ovi bez
--                        first_attempt_passed (NULL, pre upisa failure_type) racunaju se kao 0
--   formalna_ispravnost_iz_prve - isto, ali samo nad pozivima u kojima je model odgovorio
--                        (bez infrastrukturnih padova network/http_4xx/rate_limit/http_5xx i bez
--                        run-ova sa NULL first_attempt_passed), kao u eksperiment_po_modelu.sql
--   broj_predloga      - nastali predlozi (ai_generated_artifacts)
--   prihvaceno / prihvaceno_izmena / odbaceno / na_cekanju - odluke nastavnika
--   prosek_*           - prosecna ocena po kriterijumu rubrike (skala 1-5); kriterijumi
--                        nastavnika i studenata (student_*) iz ai_rubric_definitions,
--                        applies_to = 'explanation'
--   broj_ocena_nastavnika / broj_ocena_studenata - broj pojedinacnih ocena po vrsti rubrike
--   korisnost_1 .. korisnost_5 - raspodela pojedinacnih studentskih ocena korisnosti
--   broj_parova        - predlozi koji imaju i studentsku korisnost i nastavnicku tacnost
--                        objasnjenja (runda 1); korisnost = prosek svih studenata za predlog
--   broj_rizicnih_slucajeva - parovi sa korisnost >= 4 i tacnost <= 2 (uverljivo, ali netacno;
--                        Zadatak, odeljak 5.2 i 6.2)
--   korelacija_korisnost_tacnost - Pearsonov r nad parovima; NULL ako je broj_parova < 2
--                        ili nema rasipanja (imenilac 0)
--
-- EKSPERIMENT: ukljuceni su samo pozivi iz evaluacione serije (evaluation_batch_id).
-- Za jednu seriju zameniti uslov sa: AND r.evaluation_batch_id = <id>

WITH runs AS (
    SELECT r.id, r.model_id, r.mode, r.validation_passed, r.accuracy_check_passed,
           r.response_time_ms, r.first_attempt_passed, r.failure_type
    FROM ai_generation_runs r
    WHERE r.purpose = 'explanation'
      AND r.evaluation_batch_id IS NOT NULL  -- FILTER_EKSPERIMENT
),
per_model AS (
    SELECT
        runs.model_id,
        runs.mode,
        COUNT(*)                              AS broj_pokusaja,
        SUM(runs.validation_passed = 0)       AS neuspeli_pokusaji,
        SUM(runs.accuracy_check_passed = 0)   AS pala_mehanicka_provera,
        ROUND(AVG(runs.response_time_ms))     AS prosek_vreme_odziva_ms,
        ROUND(SUM(COALESCE(runs.first_attempt_passed = 1, 0)) / COUNT(*), 3) AS stopa_iz_prve,
        ROUND(SUM(COALESCE(runs.first_attempt_passed = 1, 0))
              / NULLIF(SUM(runs.first_attempt_passed IS NOT NULL
                           AND (runs.failure_type IS NULL
                                OR runs.failure_type IN ('empty', 'invalid_json', 'schema'))), 0), 3)
                                              AS formalna_ispravnost_iz_prve,
        COUNT(a.id)                           AS broj_predloga,
        SUM(a.status = 'prihvaceno')          AS prihvaceno,
        SUM(a.status = 'prihvaceno_izmena')   AS prihvaceno_izmena,
        SUM(a.status = 'odbaceno')            AS odbaceno,
        SUM(a.status = 'predlog')             AS na_cekanju
    FROM runs
    LEFT JOIN ai_generated_artifacts a
           ON a.generation_run_id = runs.id AND a.artifact_type = 'explanation'
    GROUP BY runs.model_id, runs.mode
),
per_model_scores AS (
    SELECT
        runs.model_id,
        runs.mode,
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
        SUM(d.evaluator_role = 'STUDENT') AS broj_ocena_studenata,
        -- raspodela studentskih ocena korisnosti
        SUM(d.evaluator_role = 'STUDENT' AND d.dimension_key = 'korisnost' AND e.score = 1) AS korisnost_1,
        SUM(d.evaluator_role = 'STUDENT' AND d.dimension_key = 'korisnost' AND e.score = 2) AS korisnost_2,
        SUM(d.evaluator_role = 'STUDENT' AND d.dimension_key = 'korisnost' AND e.score = 3) AS korisnost_3,
        SUM(d.evaluator_role = 'STUDENT' AND d.dimension_key = 'korisnost' AND e.score = 4) AS korisnost_4,
        SUM(d.evaluator_role = 'STUDENT' AND d.dimension_key = 'korisnost' AND e.score = 5) AS korisnost_5
    FROM runs
    JOIN ai_generated_artifacts a
      ON a.generation_run_id = runs.id AND a.artifact_type = 'explanation'
    JOIN ai_evaluations e        ON e.artifact_id = a.id
    JOIN ai_rubric_definitions d ON d.id = e.rubric_definition_id
                                AND d.applies_to = 'explanation'
    GROUP BY runs.model_id, runs.mode
),
-- po predlogu: prosecna studentska korisnost i nastavnicka tacnost objasnjenja (runda 1)
per_artifact AS (
    SELECT
        runs.model_id,
        runs.mode,
        a.id AS artifact_id,
        AVG(CASE WHEN d.evaluator_role = 'STUDENT' AND d.dimension_key = 'korisnost' THEN e.score END) AS avg_korisnost,
        AVG(CASE WHEN d.evaluator_role = 'TEACHER' AND d.dimension_key = 'tacnost_objasnjenja'
                  AND e.evaluation_round = 1 THEN e.score END) AS tacnost_round1
    FROM runs
    JOIN ai_generated_artifacts a
      ON a.generation_run_id = runs.id AND a.artifact_type = 'explanation'
    JOIN ai_evaluations e        ON e.artifact_id = a.id
    JOIN ai_rubric_definitions d ON d.id = e.rubric_definition_id
                                AND d.applies_to = 'explanation'
    GROUP BY runs.model_id, runs.mode, a.id
),
per_model_risk AS (
    SELECT
        model_id,
        mode,
        COUNT(*)                                            AS n,
        SUM(avg_korisnost >= 4 AND tacnost_round1 <= 2)     AS broj_rizicnih_slucajeva,
        SUM(avg_korisnost)                                  AS sx,
        SUM(tacnost_round1)                                 AS sy,
        SUM(avg_korisnost * tacnost_round1)                 AS sxy,
        SUM(avg_korisnost * avg_korisnost)                  AS sxx,
        SUM(tacnost_round1 * tacnost_round1)                AS syy
    FROM per_artifact
    WHERE avg_korisnost IS NOT NULL AND tacnost_round1 IS NOT NULL
    GROUP BY model_id, mode
)
SELECT
    m.provider,
    m.model_name,
    pm.mode AS rezim,
    pm.broj_pokusaja,
    pm.neuspeli_pokusaji,
    pm.pala_mehanicka_provera,
    pm.prosek_vreme_odziva_ms,
    pm.stopa_iz_prve,
    pm.formalna_ispravnost_iz_prve,
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
    COALESCE(ps.broj_ocena_studenata, 0)  AS broj_ocena_studenata,
    COALESCE(ps.korisnost_1, 0) AS korisnost_1,
    COALESCE(ps.korisnost_2, 0) AS korisnost_2,
    COALESCE(ps.korisnost_3, 0) AS korisnost_3,
    COALESCE(ps.korisnost_4, 0) AS korisnost_4,
    COALESCE(ps.korisnost_5, 0) AS korisnost_5,
    COALESCE(pr.n, 0)                       AS broj_parova,
    COALESCE(pr.broj_rizicnih_slucajeva, 0) AS broj_rizicnih_slucajeva,
    CASE WHEN pr.n >= 2 THEN
        ROUND((pr.n * pr.sxy - pr.sx * pr.sy)
              / NULLIF(SQRT((pr.n * pr.sxx - pr.sx * pr.sx) * (pr.n * pr.syy - pr.sy * pr.sy)), 0), 3)
    END AS korelacija_korisnost_tacnost
FROM per_model pm
JOIN ai_models m ON m.id = pm.model_id
LEFT JOIN per_model_scores ps ON ps.model_id = pm.model_id AND ps.mode <=> pm.mode
LEFT JOIN per_model_risk pr   ON pr.model_id = pm.model_id AND pr.mode <=> pm.mode
ORDER BY m.provider, m.model_name, pm.mode;
