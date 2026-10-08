-- Eksperiment generisanja pitanja: pokazatelji po modelu i režimu (tačka G)
-- Pokreće se ručno (phpMyAdmin). Samo čitanje. Dva upita: (A) po pozivu modela,
-- (B) po predlogu. Režim: similar_question = jedno pitanje, similar_question_set = skup.
--
-- Uključeni su SAMO run-ovi iz evaluacionih serija (evaluation_batch_id); probni
-- run-ovi (bez serije) i razvojne probe se ne računaju.
-- Za jednu seriju zameniti uslov sa: AND r.evaluation_batch_id = <id>
--
-- Vrste pada (failure_type): network, http_4xx, rate_limit, http_5xx = model NIJE
-- odgovorio (infrastruktura); empty, invalid_json, schema = odgovor neupotrebljiv.
-- Stopa formalne ispravnosti iz prve računa se samo nad pozivima u kojima je
-- model odgovorio (bez infrastrukturnih padova).
-- NULL u uslovu (npr. failure_type uspešnog poziva) se u stopama računa kao 0 (COALESCE),
-- inače bi AVG preskočio uspešne pozive.
-- Vreme: response_time_ms (poslednji HTTP pokušaj; kod ponovnog zahteva zbir dva odgovora).

-- (A) Po pozivu modela
WITH runs AS (
    SELECT r.*, m.provider, m.model_name
    FROM ai_generation_runs r
    JOIN ai_models m ON m.id = r.model_id
    WHERE r.purpose IN ('similar_question', 'similar_question_set')
      AND r.evaluation_batch_id IS NOT NULL  -- FILTER_SERIJA
),
with_median AS (
    SELECT runs.*,
           MEDIAN(response_time_ms) OVER (PARTITION BY provider, model_name, purpose) AS median_ms
    FROM runs
)
SELECT
    provider,
    model_name,
    purpose                                                         AS rezim,
    COUNT(*)                                                        AS pokusaja,
    SUM(validation_passed = 1)                                      AS uspesnih,
    ROUND(100 * AVG(COALESCE(validation_passed = 1, 0)), 1)         AS stopa_uspeha_pct,
    SUM(first_attempt_passed = 1)                                   AS prosao_iz_prve,
    SUM(format_retries > 0)                                         AS sa_ponovnim_zahtevom,
    ROUND(100 * SUM(first_attempt_passed = 1)
          / NULLIF(SUM(failure_type IS NULL OR failure_type IN ('empty', 'invalid_json', 'schema')), 0), 1)
                                                                    AS formalna_ispravnost_iz_prve_pct,
    SUM(failure_type = 'network')                                   AS pad_network,
    SUM(failure_type = 'http_4xx')                                  AS pad_http_4xx,
    SUM(failure_type = 'rate_limit')                                AS pad_rate_limit,
    SUM(failure_type = 'http_5xx')                                  AS pad_http_5xx,
    SUM(failure_type = 'empty')                                     AS pad_empty,
    SUM(failure_type = 'invalid_json')                              AS pad_invalid_json,
    SUM(failure_type = 'schema')                                    AS pad_schema,
    ROUND(100 * AVG(COALESCE(failure_type IN ('network', 'http_4xx', 'rate_limit', 'http_5xx'), 0)), 1)
                                                                    AS bez_odgovora_pct,
    ROUND(AVG(response_time_ms))                                    AS prosek_ms,
    MAX(median_ms)                                                  AS medijana_ms,
    ROUND(AVG(tokens_used))                                         AS prosek_tokena
FROM with_median
GROUP BY provider, model_name, purpose
ORDER BY provider, model_name, purpose;

-- (B) Po predlogu: odluke, razdaljina izmene, duplikati, raspodela oznaka
-- (model = šta je model predložio, nast = šta je nastavnik izabrao pri pregledu).
-- Mogući duplikat: max_similarity >= 0.90 (question_similarity.DUPLICATE_THRESHOLD).
WITH arts AS (
    SELECT a.*, r.purpose, m.provider, m.model_name
    FROM ai_generated_artifacts a
    JOIN ai_generation_runs r ON r.id = a.generation_run_id
    JOIN ai_models m ON m.id = r.model_id
    WHERE a.artifact_type = 'question'
      AND r.evaluation_batch_id IS NOT NULL  -- FILTER_SERIJA
)
SELECT
    provider,
    model_name,
    purpose                                                         AS rezim,
    COUNT(*)                                                        AS predloga,
    SUM(status = 'prihvaceno')                                      AS prihvaceno,
    SUM(status = 'prihvaceno_izmena')                               AS prihvaceno_izmena,
    SUM(status = 'odbaceno')                                        AS odbaceno,
    SUM(status = 'predlog')                                         AS na_cekanju,
    ROUND(100 * SUM(status = 'prihvaceno') / NULLIF(SUM(status <> 'predlog'), 0), 1)        AS prihvaceno_pct,
    ROUND(100 * SUM(status = 'prihvaceno_izmena') / NULLIF(SUM(status <> 'predlog'), 0), 1) AS izmena_pct,
    ROUND(100 * SUM(status = 'odbaceno') / NULLIF(SUM(status <> 'predlog'), 0), 1)          AS odbaceno_pct,
    ROUND(AVG(CASE WHEN status = 'prihvaceno_izmena' THEN edit_distance END), 1)             AS prosek_razdaljine,
    ROUND(AVG(CASE WHEN status = 'prihvaceno_izmena' THEN edit_distance_norm END), 4)        AS prosek_razdaljine_norm,
    SUM(max_similarity >= 0.90)                                     AS mogucih_duplikata,
    SUM(reviewed_duplicate = 1)                                     AS potvrdjenih_duplikata,
    SUM(model_difficulty = 'lako')        AS model_lako,
    SUM(model_difficulty = 'srednje')     AS model_srednje,
    SUM(model_difficulty = 'tesko')       AS model_tesko,
    SUM(model_bloom_level = 'pamcenje')    AS model_pamcenje,
    SUM(model_bloom_level = 'razumevanje') AS model_razumevanje,
    SUM(model_bloom_level = 'primena')     AS model_primena,
    SUM(model_bloom_level = 'analiza')     AS model_analiza,
    SUM(model_bloom_level = 'vrednovanje') AS model_vrednovanje,
    SUM(model_bloom_level = 'stvaranje')   AS model_stvaranje,
    SUM(reviewed_difficulty = 'lako')     AS nast_lako,
    SUM(reviewed_difficulty = 'srednje')  AS nast_srednje,
    SUM(reviewed_difficulty = 'tesko')    AS nast_tesko,
    SUM(reviewed_bloom_level = 'pamcenje')    AS nast_pamcenje,
    SUM(reviewed_bloom_level = 'razumevanje') AS nast_razumevanje,
    SUM(reviewed_bloom_level = 'primena')     AS nast_primena,
    SUM(reviewed_bloom_level = 'analiza')     AS nast_analiza,
    SUM(reviewed_bloom_level = 'vrednovanje') AS nast_vrednovanje,
    SUM(reviewed_bloom_level = 'stvaranje')   AS nast_stvaranje
FROM arts
GROUP BY provider, model_name, purpose
ORDER BY provider, model_name, purpose;
