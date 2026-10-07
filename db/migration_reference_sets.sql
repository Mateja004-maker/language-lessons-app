-- Migracija: referentni skup pitanja za eksperiment generisanja
-- Ne pokretati automatski - pokreće se ručno (phpMyAdmin ili mysql klijent).
--
-- Referentni skup je zamrznut spisak izvornih pitanja (jednog predmeta) koji
-- ulazi u SVAKI model pod istim redosledom. Evaluaciona serija se vezuje za
-- skup (evaluation_batches.reference_set_id), a backend/tools/run_experiment.py
-- iz skupa pravi plan: pitanje x model x N pokušaja.
--
-- - reference_set_questions.question_id: ON DELETE RESTRICT - pitanje koje je
--   u skupu ne može da se obriše iz banke dok je skup tu (eksperiment ostaje
--   ponovljiv).
-- - evaluation_batches.reference_set_id: NULL dozvoljen (stare serije i
--   razvojne probe nemaju skup); ON DELETE RESTRICT - skup vezan za seriju
--   ne može da se obriše.
--
-- Pre migracije: GET/POST /api/reference-sets vraćaju 409 sa porukom da se
-- pokrene ova migracija; ostatak aplikacije radi kao do sada.

CREATE TABLE reference_sets (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  name VARCHAR(150) NOT NULL,
  subject_id INT UNSIGNED NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_reference_sets_name (name),
  KEY fk_reference_sets_subject (subject_id),
  CONSTRAINT fk_reference_sets_subject
    FOREIGN KEY (subject_id) REFERENCES subjects (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE reference_set_questions (
  reference_set_id INT UNSIGNED NOT NULL,
  question_id BIGINT UNSIGNED NOT NULL,
  order_no INT NOT NULL DEFAULT 0,
  PRIMARY KEY (reference_set_id, question_id),
  KEY fk_rsq_question (question_id),
  CONSTRAINT fk_rsq_set
    FOREIGN KEY (reference_set_id) REFERENCES reference_sets (id) ON DELETE CASCADE,
  CONSTRAINT fk_rsq_question
    FOREIGN KEY (question_id) REFERENCES exam_questions (id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

ALTER TABLE evaluation_batches
  ADD COLUMN reference_set_id INT UNSIGNED NULL DEFAULT NULL,
  ADD KEY fk_evaluation_batches_reference_set (reference_set_id),
  ADD CONSTRAINT fk_evaluation_batches_reference_set
    FOREIGN KEY (reference_set_id) REFERENCES reference_sets (id) ON DELETE RESTRICT;

-- Provera posle pokretanja (3 reda: reference_sets, reference_set_questions,
-- evaluation_batches.reference_set_id):
--   SELECT TABLE_NAME, COLUMN_NAME FROM information_schema.COLUMNS
--   WHERE TABLE_SCHEMA = DATABASE()
--     AND ((TABLE_NAME IN ('reference_sets', 'reference_set_questions') AND COLUMN_NAME = 'id')
--       OR (TABLE_NAME = 'reference_set_questions' AND COLUMN_NAME = 'question_id')
--       OR (TABLE_NAME = 'evaluation_batches' AND COLUMN_NAME = 'reference_set_id'));
-- (reference_set_questions nema kolonu id, pa upit vraća 3 reda.)

-- Rollback (briše skupove i vezu serija sa skupovima; serije ostaju):
-- ALTER TABLE evaluation_batches
--   DROP FOREIGN KEY fk_evaluation_batches_reference_set,
--   DROP KEY fk_evaluation_batches_reference_set,
--   DROP COLUMN reference_set_id;
-- DROP TABLE reference_set_questions;
-- DROP TABLE reference_sets;
