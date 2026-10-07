-- Zbirni prikaz po provajderu i modelu: AI predlozi PITANJA (artifact_type = 'question')
-- Pokrece se rucno (phpMyAdmin). Samo citanje.
--
-- Kolone:
--   broj_pokusaja      - svi pozivi modela (ai_generation_runs, purpose = 'similar_question')
--   neuspeli_pokusaji  - pozivi koji nisu dali iskoristiv predlog (validation_passed = 0;
--                        za njih ne postoji red u ai_generated_artifacts)
--   broj_predloga      - nastali predlozi (ai_generated_artifacts)
--   prihvaceno / prihvaceno_izmena / odbaceno / na_cekanju - odluke nastavnika
--   prosek_*           - prosecna ocena po kriterijumu rubrike (skala 1-5), svi ocenjivaci;
--                        kljucevi su iz ai_rubric_definitions (applies_to 'question' i 'question_mc')
--   broj_ocena         - ukupan broj pojedinacnih ocena (ai_evaluations)
--
-- EKSPERIMENT: ukljuceni su samo pozivi iz evaluacione serije (evaluation_batch_id).
-- Za jednu seriju zameniti uslov sa: AND r.evaluation_batch_id = <id>

WITH runs AS (
    SELECT r.id, r.model_id, r.validation_passed
    FROM ai_generation_runs r
    WHERE r.purpose = 'similar_question'
      AND r.evaluation_batch_id IS NOT NULL  -- FILTER_EKSPERIMENT
),
per_model AS (
    SELECT
        runs.model_id,
        COUNT(*)                              AS broj_pokusaja,
        SUM(runs.validation_passed = 0)       AS neuspeli_pokusaji,
        COUNT(a.id)                           AS broj_predloga,
        SUM(a.status = 'prihvaceno')          AS prihvaceno,
        SUM(a.status = 'prihvaceno_izmena')   AS prihvaceno_izmena,
        SUM(a.status = 'odbaceno')            AS odbaceno,
        SUM(a.status = 'predlog')             AS na_cekanju
    FROM runs
    LEFT JOIN ai_generated_artifacts a
           ON a.generation_run_id = runs.id AND a.artifact_type = 'question'
    GROUP BY runs.model_id
),
per_model_scores AS (
    SELECT
        runs.model_id,
        ROUND(AVG(CASE WHEN d.dimension_key = 'strucna_tacnost'      THEN e.score END), 2) AS prosek_strucna_tacnost,
        ROUND(AVG(CASE WHEN d.dimension_key = 'odgovorljivost'       THEN e.score END), 2) AS prosek_odgovorljivost,
        ROUND(AVG(CASE WHEN d.dimension_key = 'relevantnost'         THEN e.score END), 2) AS prosek_relevantnost,
        ROUND(AVG(CASE WHEN d.dimension_key = 'kvalitet_distraktora' THEN e.score END), 2) AS prosek_kvalitet_distraktora,
        ROUND(AVG(CASE WHEN d.dimension_key = 'kalibracija_tezine'   THEN e.score END), 2) AS prosek_kalibracija_tezine,
        ROUND(AVG(CASE WHEN d.dimension_key = 'kognitivni_nivo'      THEN e.score END), 2) AS prosek_kognitivni_nivo,
        ROUND(AVG(CASE WHEN d.dimension_key = 'originalnost'         THEN e.score END), 2) AS prosek_originalnost,
        ROUND(AVG(CASE WHEN d.dimension_key = 'jezicka_ispravnost'   THEN e.score END), 2) AS prosek_jezicka_ispravnost,
        COUNT(e.id) AS broj_ocena
    FROM runs
    JOIN ai_generated_artifacts a
      ON a.generation_run_id = runs.id AND a.artifact_type = 'question'
    JOIN ai_evaluations e        ON e.artifact_id = a.id
    JOIN ai_rubric_definitions d ON d.id = e.rubric_definition_id
                                AND d.applies_to IN ('question', 'question_mc')
    GROUP BY runs.model_id
)
SELECT
    m.provider,
    m.model_name,
    pm.broj_pokusaja,
    pm.neuspeli_pokusaji,
    pm.broj_predloga,
    pm.prihvaceno,
    pm.prihvaceno_izmena,
    pm.odbaceno,
    pm.na_cekanju,
    ps.prosek_strucna_tacnost,
    ps.prosek_odgovorljivost,
    ps.prosek_relevantnost,
    ps.prosek_kvalitet_distraktora,
    ps.prosek_kalibracija_tezine,
    ps.prosek_kognitivni_nivo,
    ps.prosek_originalnost,
    ps.prosek_jezicka_ispravnost,
    COALESCE(ps.broj_ocena, 0) AS broj_ocena
FROM per_model pm
JOIN ai_models m ON m.id = pm.model_id
LEFT JOIN per_model_scores ps ON ps.model_id = pm.model_id
ORDER BY m.provider, m.model_name;
