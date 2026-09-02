-- Migracija: proširenje zajedničke AI šeme za Andrejev modul
-- (generisanje rešenja i objašnjenja, režimi A i B).
--
-- Nadovezuje se na db/migration_ai_generation_base_VERIFIED.sql (potvrđeno
-- 2026-09-02 preko SHOW CREATE TABLE na Andrejevoj lokalnoj bazi). Ne
-- pokretati automatski - runs se ručno kroz phpMyAdmin (ili run_migration.py).
--
-- Sve izmene su aditivne - ne diraju nijednu postojeću kolonu niti ponašanje
-- Anđinog modula (generisanje pitanja): nove kolone su nullable/DEFAULT, novi
-- redovi u ai_rubric_definitions imaju applies_to='explanation' koji njena
-- get_applicable_rubric_definitions ionako ne bira (traži samo 'question' i
-- 'question_mc').
--
-- artifact_type='explanation' koristi POSTOJEĆU original_text/edited_text
-- (mediumtext) kolonu, samo sa drugačijim JSON sadržajem upisanim kao string:
--   režim A: {"explanation": "..."}
--   režim B: {"solution": "...", "explanation": "..."}
-- purpose='explanation' za oba režima; mode='mode_a'|'mode_b' ih razlikuje
-- (generation_runs.mode postoji u šemi i nigde se ne koristi - upravo za ovo).

-- =====================================================================
-- 1) Rubrika za studentsku ocenu korisnosti objašnjenja (zadatak, 5.1)
-- =====================================================================
INSERT INTO ai_rubric_definitions
  (applies_to, dimension_key, dimension_label, scale_min, scale_max, evaluator_role)
VALUES
  ('explanation', 'korisnost', 'Korisnost', 1, 5, 'STUDENT'),
  ('explanation', 'jasnoca', 'Jasnoća', 1, 5, 'STUDENT'),
  ('explanation', 'percepcija_naucenog', 'Percepcija naučenog', 1, 5, 'STUDENT');

-- =====================================================================
-- 2) Rubrika za nastavničku ocenu ispravnosti i kvaliteta (zadatak, 5.2)
-- NAPOMENA: "Tačnost rešenja" (5.2, tačka 1) NIJE ovde - eliminaciona je i
-- proverava se MEHANIČKI (režim B), ne ručnom Likert ocenom. Vidi tačku 3.
-- =====================================================================
INSERT INTO ai_rubric_definitions
  (applies_to, dimension_key, dimension_label, scale_min, scale_max, evaluator_role)
VALUES
  ('explanation', 'tacnost_objasnjenja', 'Tačnost objašnjenja', 1, 5, 'TEACHER'),
  ('explanation', 'vernost', 'Vernost (faithfulness)', 1, 5, 'TEACHER'),
  ('explanation', 'potpunost', 'Potpunost', 1, 5, 'TEACHER'),
  ('explanation', 'pedagoska_vrednost', 'Pedagoška vrednost', 1, 5, 'TEACHER'),
  ('explanation', 'jezicka_ispravnost', 'Jezička ispravnost', 1, 5, 'TEACHER');

-- =====================================================================
-- 3) Mehanička provera tačnosti rešenja - samo režim B (zadatak, 5.2.1 i
-- 8.2). Nullable tinyint, isti obrazac kao postojeći validation_passed:
-- NULL = nije primenjivo/još nije provereno, 1 = tačno, 0 = netačno.
-- Aditivno na ai_generation_runs - postojeći redovi (Anđin modul) ostaju
-- NULL, ništa im se ne menja.
-- =====================================================================
ALTER TABLE ai_generation_runs
  ADD COLUMN accuracy_check_passed tinyint(1) DEFAULT NULL
    COMMENT 'relevantno samo za mode=mode_b; NULL = nije primenjivo/nije provereno' AFTER validation_errors,
  ADD COLUMN accuracy_check_details text DEFAULT NULL
    COMMENT 'npr. koji automatski test/poredjenje je koriscen i rezultat' AFTER accuracy_check_passed;

-- =====================================================================
-- 4) evaluation_batches - razdvaja razvojne probe od jedne, konačne
-- evaluacije koja ulazi u rad (Vodič, 6.5; zadatak, odeljak 7, tačka 1-2).
-- =====================================================================
CREATE TABLE IF NOT EXISTS evaluation_batches (
  id int(10) unsigned NOT NULL AUTO_INCREMENT,
  name varchar(150) NOT NULL,
  description text DEFAULT NULL,
  is_final tinyint(1) NOT NULL DEFAULT 0,
  created_at timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (id),
  UNIQUE KEY uq_evaluation_batches_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

ALTER TABLE ai_generation_runs
  ADD COLUMN evaluation_batch_id int(10) unsigned DEFAULT NULL
    COMMENT 'NULL = razvojna proba, van formalne evaluacije' AFTER retry_count,
  ADD CONSTRAINT fk_run_evaluation_batch
    FOREIGN KEY (evaluation_batch_id) REFERENCES evaluation_batches(id);

-- =====================================================================
-- OTVORENA PITANJA ZA ANĐU (ukloniti kad se usaglasi)
-- =====================================================================
-- a) generation_runs.mode postoji u šemi ali se nigde ne koristi - da li je
--    ostavljen namenski za moj režim A/B? Koristim 'mode_a' / 'mode_b'.
-- b) Slažeš li se da accuracy_check_passed/details idu kao kolone na
--    ai_generation_runs (deljena tabela)?
-- c) evaluation_batches - ok da ovo dodam kao zajedničku tabelu?
-- d) Da li je ova osnovna šema (6 ai_ tabela) identična kod tebe - da
--    potvrdimo pre nego što se baze na kraju spoje? (Znam da tvoja verzija
--    ima dodatno created_question_id na ai_generated_artifacts, iz
--    migration_ai_review.sql - to ostaje samo tvoje, meni ne treba.)
