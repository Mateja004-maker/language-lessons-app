-- Migracija: exam_test_questions (posrednička tabela test <-> pitanje)
-- "Expand" korak inkrementalne migracije ka banci pitanja.
-- Ne pokretati automatski - runs se ručno kroz phpMyAdmin.
--
-- Ovaj korak je čisto aditivan: exam_questions.exam_id se NE dira,
-- nijedna postojeća ruta u app.py se ne menja, aplikacija nastavlja
-- da radi identično kao pre migracije. Nova tabela je za sada
-- "mrtva težina" - popunjena kopijom postojećih podataka, ali je
-- još niko ne čita niti upisuje u nju.

-- 1) Nova tabela exam_test_questions (many-to-many test <-> pitanje)
CREATE TABLE IF NOT EXISTS exam_test_questions (
  id BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  exam_id BIGINT UNSIGNED NOT NULL,
  question_id BIGINT UNSIGNED NOT NULL,
  order_no INT NOT NULL DEFAULT 0,

  CONSTRAINT fk_etq_exam
    FOREIGN KEY (exam_id) REFERENCES exams(id)
    ON UPDATE RESTRICT
    ON DELETE CASCADE,

  CONSTRAINT fk_etq_question
    FOREIGN KEY (question_id) REFERENCES exam_questions(id)
    ON UPDATE RESTRICT
    ON DELETE RESTRICT,

  CONSTRAINT uq_etq_exam_question UNIQUE (exam_id, question_id)
) ENGINE=InnoDB;

-- 2) Backfill - prekopiraj postojeće (exam_id, question_id, order_no)
-- parove iz exam_questions (na dan migracije: 55 redova, svi sa
-- popunjenim exam_id).
INSERT INTO exam_test_questions (exam_id, question_id, order_no)
SELECT exam_id, id, order_no
FROM exam_questions;
