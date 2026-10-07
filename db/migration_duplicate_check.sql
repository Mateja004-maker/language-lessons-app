-- Migracija: provera mogućih duplikata AI predloga pitanja (tačka C)
-- Ne pokretati automatski - pokreće se ručno (phpMyAdmin ili mysql klijent).
--
-- Pri generisanju (backend/question_similarity.py) predlog se poredi sa
-- pitanjima iz banke istog predmeta, sa izvornim pitanjem i sa ranijim
-- predlozima istog predmeta; čuva se najsličnije:
--   max_similarity       - difflib ratio 0..1 (normalizovan tekst)
--   similar_source       - 'bank' | 'source' | 'artifact'
--   similar_question_id  - pitanje iz banke / izvorno pitanje (FK exam_questions)
--   similar_artifact_id  - raniji predlog (FK ai_generated_artifacts)
--     (dve kolone jer jedna FK ne može da pokazuje na dve tabele; popunjena je
--      ona koja odgovara similar_source)
--   reviewed_duplicate   - nastavnikova potvrda: 1 = duplikat, 0 = nije, NULL = nije označeno
--
-- Pre migracije: generisanje i pregled rade kao i do sada (sličnost se ne
-- upisuje; nastavnikova oznaka duplikata vraća 409). Posle migracije, za stare
-- predloge pokrenuti: python tools/recompute_similarity.py (iz backend/).

ALTER TABLE ai_generated_artifacts
  ADD COLUMN max_similarity DECIMAL(4,3) NULL DEFAULT NULL,
  ADD COLUMN similar_source VARCHAR(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NULL DEFAULT NULL,
  ADD COLUMN similar_question_id BIGINT UNSIGNED NULL DEFAULT NULL,
  ADD COLUMN similar_artifact_id BIGINT UNSIGNED NULL DEFAULT NULL,
  ADD COLUMN reviewed_duplicate TINYINT(1) NULL DEFAULT NULL,
  ADD KEY fk_artifact_similar_question (similar_question_id),
  ADD KEY fk_artifact_similar_artifact (similar_artifact_id),
  ADD CONSTRAINT fk_artifact_similar_question
    FOREIGN KEY (similar_question_id) REFERENCES exam_questions (id) ON DELETE SET NULL,
  ADD CONSTRAINT fk_artifact_similar_artifact
    FOREIGN KEY (similar_artifact_id) REFERENCES ai_generated_artifacts (id) ON DELETE SET NULL,
  ADD CONSTRAINT chk_artifact_max_similarity
    CHECK (max_similarity IS NULL OR (max_similarity >= 0 AND max_similarity <= 1)),
  ADD CONSTRAINT chk_artifact_similar_source
    CHECK (similar_source IS NULL OR similar_source IN ('bank', 'source', 'artifact')),
  ADD CONSTRAINT chk_artifact_reviewed_duplicate
    CHECK (reviewed_duplicate IS NULL OR reviewed_duplicate IN (0, 1));

-- Rollback (briše kolone i vrednosti u njima; strani ključevi i ograničenja pre kolona):
-- ALTER TABLE ai_generated_artifacts
--   DROP FOREIGN KEY fk_artifact_similar_question,
--   DROP FOREIGN KEY fk_artifact_similar_artifact,
--   DROP CONSTRAINT chk_artifact_max_similarity,
--   DROP CONSTRAINT chk_artifact_similar_source,
--   DROP CONSTRAINT chk_artifact_reviewed_duplicate,
--   DROP KEY fk_artifact_similar_question,
--   DROP KEY fk_artifact_similar_artifact,
--   DROP COLUMN max_similarity,
--   DROP COLUMN similar_source,
--   DROP COLUMN similar_question_id,
--   DROP COLUMN similar_artifact_id,
--   DROP COLUMN reviewed_duplicate;
