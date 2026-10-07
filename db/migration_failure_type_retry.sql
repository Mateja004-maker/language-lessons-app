-- Migracija: vrsta pada i ponovni zahtev posle lošeg formata (tačka I)
-- Ne pokretati automatski - pokreće se ručno (phpMyAdmin ili mysql klijent).
--
-- ai_generation_runs (za generisanje sličnih pitanja; backend/generation_failures.py):
--   failure_type          NULL = uspeh; inače network | http_4xx | rate_limit | http_5xx
--                         (model nije odgovorio) ili empty | invalid_json | schema
--   first_attempt_passed  1 = prvi odgovor modela je prošao validaciju, 0 = nije
--   format_retries        broj ponovnih zahteva posle lošeg formata (0 ili 1)
-- validation_passed i raw_response se odnose na KONAČAN ishod; sirov odgovor
-- prvog pokušaja je u params_used.first_attempt kada je bilo ponavljanja.
--
-- Pre migracije: generisanje (sa ponovnim zahtevom) radi, ove kolone se samo
-- ne upisuju - sve tri vrednosti mogu da se izvedu iz postojećih podataka.
-- Posle migracije za stare run-ove pokrenuti (iz backend/):
--   python tools/backfill_failure_type.py --dry-run
--   python tools/backfill_failure_type.py

ALTER TABLE ai_generation_runs
  ADD COLUMN failure_type VARCHAR(12) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NULL DEFAULT NULL,
  ADD COLUMN first_attempt_passed TINYINT(1) NULL DEFAULT NULL,
  ADD COLUMN format_retries TINYINT UNSIGNED NULL DEFAULT NULL,
  ADD CONSTRAINT chk_runs_failure_type
    CHECK (failure_type IS NULL OR failure_type NOT LIKE '% ' AND failure_type IN
           ('network', 'http_4xx', 'rate_limit', 'http_5xx', 'empty', 'invalid_json', 'schema')),
  ADD CONSTRAINT chk_runs_first_attempt_passed
    CHECK (first_attempt_passed IS NULL OR first_attempt_passed IN (0, 1)),
  ADD CONSTRAINT chk_runs_format_retries
    CHECK (format_retries IS NULL OR format_retries <= 5);

-- Rollback (briše kolone i vrednosti u njima):
-- ALTER TABLE ai_generation_runs
--   DROP CONSTRAINT chk_runs_failure_type,
--   DROP CONSTRAINT chk_runs_first_attempt_passed,
--   DROP CONSTRAINT chk_runs_format_retries,
--   DROP COLUMN failure_type,
--   DROP COLUMN first_attempt_passed,
--   DROP COLUMN format_retries;
