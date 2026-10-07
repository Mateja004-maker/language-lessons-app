-- Migracija: drugi ocenjivač AI predloga pitanja (tačka E)
-- Ne pokretati automatski - pokreće se ručno (phpMyAdmin ili mysql klijent).
--
-- - ai_evaluations.evaluation_round: 1 = ocenjivač koji donosi odluku (i
--   studentske ocene objašnjenja), 2 = drugi ocenjivač (samo ocena, bez odluke).
-- - UNIQUE(artifact_id, rubric_definition_id, evaluator_id): ista osoba ne
--   može dvaput da oceni isti kriterijum istog predloga. Provera pre
--   pokretanja (stanje 2026-10-07: 0 redova od 36 ocena):
--     SELECT artifact_id, rubric_definition_id, evaluator_id, COUNT(*) FROM ai_evaluations
--     GROUP BY 1, 2, 3 HAVING COUNT(*) > 1;
-- - ai_label_evaluations: težina i Blumov nivo drugog ocenjivača (oznake
--   ocenjivača koji odlučuje su u ai_generated_artifacts.reviewed_*), radi
--   saglasnosti i na kategorijama.
-- - evaluation_batches.closed_at: dok serija nije zatvorena, model i odluka
--   su skriveni od svakoga ko predlog iz serije još nije ocenio.
--
-- Pre migracije: rute druge ocene vraćaju 409 sa porukom; pregled i slepo
-- ocenjivanje rade (serije se smatraju otvorenim).

ALTER TABLE ai_evaluations
  ADD COLUMN evaluation_round TINYINT UNSIGNED NOT NULL DEFAULT 1,
  ADD CONSTRAINT chk_eval_round CHECK (evaluation_round IN (1, 2)),
  ADD UNIQUE KEY uq_eval_artifact_rubric_evaluator (artifact_id, rubric_definition_id, evaluator_id);

CREATE TABLE ai_label_evaluations (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  artifact_id BIGINT UNSIGNED NOT NULL,
  evaluator_id BIGINT UNSIGNED NOT NULL,
  evaluator_role VARCHAR(20) NOT NULL,
  difficulty VARCHAR(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NULL DEFAULT NULL,
  bloom_level VARCHAR(12) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NULL DEFAULT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_label_eval_artifact_evaluator (artifact_id, evaluator_id),
  KEY fk_label_eval_evaluator (evaluator_id),
  CONSTRAINT fk_label_eval_artifact
    FOREIGN KEY (artifact_id) REFERENCES ai_generated_artifacts (id) ON DELETE CASCADE,
  CONSTRAINT fk_label_eval_evaluator
    FOREIGN KEY (evaluator_id) REFERENCES users (id),
  CONSTRAINT chk_label_eval_difficulty
    CHECK (difficulty IS NULL OR difficulty NOT LIKE '% ' AND difficulty IN ('lako', 'srednje', 'tesko')),
  CONSTRAINT chk_label_eval_bloom
    CHECK (bloom_level IS NULL OR bloom_level NOT LIKE '% ' AND bloom_level IN
           ('pamcenje', 'razumevanje', 'primena', 'analiza', 'vrednovanje', 'stvaranje'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

ALTER TABLE evaluation_batches
  ADD COLUMN closed_at TIMESTAMP NULL DEFAULT NULL;

-- Napomena za rollback: briše drugu ocenu kategorija, zatvaranje serija i oznaku runde; same ocene u ai_evaluations ostaju.
-- Rollback:
-- ALTER TABLE evaluation_batches DROP COLUMN closed_at;
-- DROP TABLE ai_label_evaluations;
-- ALTER TABLE ai_evaluations
--   DROP KEY uq_eval_artifact_rubric_evaluator,
--   DROP CONSTRAINT chk_eval_round,
--   DROP COLUMN evaluation_round;
