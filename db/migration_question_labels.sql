-- Migracija: težina i nivo Blumove taksonomije za AI predloge pitanja (v3 prompt)
-- Ne pokretati automatski - pokreće se ručno (phpMyAdmin ili mysql klijent).
--
-- Šta dodaje (sve NULL, postojeći redovi ostaju NULL):
--   ai_generated_artifacts.model_difficulty / model_bloom_level
--       - kopija oznaka koje je model vratio (izvor istine je original_text JSON;
--         kolone su tu radi SQL upita i zbirnih pokazatelja)
--   ai_generated_artifacts.reviewed_difficulty / reviewed_bloom_level
--       - oznake koje nastavnik bira pri pregledu, NE videvši modelove
--   exam_questions.difficulty / bloom_level
--       - oznake pitanja u banci; novo pitanje iz prihvaćenog predloga dobija
--         nastavnikove oznake
--
-- Kolone su utf8mb4_bin: podrazumevana kolacija baze (utf8mb4_general_ci) ne
-- razlikuje dijakritike ni velika slova, pa bi CHECK prihvatio 'teško' i 'Lako'.
-- NOT LIKE '% ' odbija razmak na kraju (VARCHAR poređenje ga inače zanemaruje).
--
-- Vrednosti su bez dijakritika (iste kao u question_validation.py):
--   težina: lako, srednje, tesko
--   Blum:   pamcenje, razumevanje, primena, analiza, vrednovanje, stvaranje
--
-- Pre migracije aplikacija radi: v2 predlozi se pregledaju kao do sada, v3 se
-- generišu (oznake su u original_text), ali se v3 predlog ne može prihvatiti
-- (ruta vraća 409 dok kolone ne postoje). Posle migracije restart backenda
-- nije potreban - prisustvo kolona se proverava pri svakom zahtevu.

ALTER TABLE ai_generated_artifacts
  ADD COLUMN model_difficulty     VARCHAR(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NULL DEFAULT NULL,
  ADD COLUMN model_bloom_level    VARCHAR(12) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NULL DEFAULT NULL,
  ADD COLUMN reviewed_difficulty  VARCHAR(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NULL DEFAULT NULL,
  ADD COLUMN reviewed_bloom_level VARCHAR(12) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NULL DEFAULT NULL,
  ADD CONSTRAINT chk_artifact_model_difficulty
    CHECK (model_difficulty IS NULL OR model_difficulty NOT LIKE '% ' AND model_difficulty IN ('lako', 'srednje', 'tesko')),
  ADD CONSTRAINT chk_artifact_model_bloom
    CHECK (model_bloom_level IS NULL OR model_bloom_level NOT LIKE '% ' AND model_bloom_level IN
           ('pamcenje', 'razumevanje', 'primena', 'analiza', 'vrednovanje', 'stvaranje')),
  ADD CONSTRAINT chk_artifact_reviewed_difficulty
    CHECK (reviewed_difficulty IS NULL OR reviewed_difficulty NOT LIKE '% ' AND reviewed_difficulty IN ('lako', 'srednje', 'tesko')),
  ADD CONSTRAINT chk_artifact_reviewed_bloom
    CHECK (reviewed_bloom_level IS NULL OR reviewed_bloom_level NOT LIKE '% ' AND reviewed_bloom_level IN
           ('pamcenje', 'razumevanje', 'primena', 'analiza', 'vrednovanje', 'stvaranje'));

ALTER TABLE exam_questions
  ADD COLUMN difficulty  VARCHAR(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NULL DEFAULT NULL,
  ADD COLUMN bloom_level VARCHAR(12) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NULL DEFAULT NULL,
  ADD CONSTRAINT chk_exam_questions_difficulty
    CHECK (difficulty IS NULL OR difficulty NOT LIKE '% ' AND difficulty IN ('lako', 'srednje', 'tesko')),
  ADD CONSTRAINT chk_exam_questions_bloom
    CHECK (bloom_level IS NULL OR bloom_level NOT LIKE '% ' AND bloom_level IN
           ('pamcenje', 'razumevanje', 'primena', 'analiza', 'vrednovanje', 'stvaranje'));

-- Provera posle pokretanja (treba da vrati 6 redova):
--   SELECT TABLE_NAME, COLUMN_NAME FROM information_schema.COLUMNS
--   WHERE TABLE_SCHEMA = DATABASE()
--     AND ((TABLE_NAME = 'ai_generated_artifacts' AND COLUMN_NAME IN
--           ('model_difficulty','model_bloom_level','reviewed_difficulty','reviewed_bloom_level'))
--       OR (TABLE_NAME = 'exam_questions' AND COLUMN_NAME IN ('difficulty','bloom_level')));

-- Rollback (briše kolone i podatke u njima; ograničenja se brišu pre kolona):
-- ALTER TABLE exam_questions
--   DROP CONSTRAINT chk_exam_questions_difficulty,
--   DROP CONSTRAINT chk_exam_questions_bloom,
--   DROP COLUMN difficulty,
--   DROP COLUMN bloom_level;
-- ALTER TABLE ai_generated_artifacts
--   DROP CONSTRAINT chk_artifact_model_difficulty,
--   DROP CONSTRAINT chk_artifact_model_bloom,
--   DROP CONSTRAINT chk_artifact_reviewed_difficulty,
--   DROP CONSTRAINT chk_artifact_reviewed_bloom,
--   DROP COLUMN model_difficulty,
--   DROP COLUMN model_bloom_level,
--   DROP COLUMN reviewed_difficulty,
--   DROP COLUMN reviewed_bloom_level;
