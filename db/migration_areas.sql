-- Migracija: oblasti (areas) unutar predmeta
-- Ne pokretati automatski - runs se ručno kroz phpMyAdmin.
-- Pretpostavka: tabela `subjects` i `exam_questions` već postoje u bazi
-- (vidi CLAUDE.md - stvarna baza je ispred schema.sql placeholdera).

-- 1) Nova tabela areas (many-to-one prema subjects)
CREATE TABLE IF NOT EXISTS areas (
  id INT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  subject_id INT UNSIGNED NOT NULL,
  name VARCHAR(150) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

  CONSTRAINT fk_areas_subject
    FOREIGN KEY (subject_id) REFERENCES subjects(id)
    ON UPDATE RESTRICT
    ON DELETE RESTRICT,

  CONSTRAINT uq_areas_subject_name UNIQUE (subject_id, name)
) ENGINE=InnoDB;

-- 2) Nova kolona area_id u exam_questions (nullable - postojeća pitanja ostaju validna)
ALTER TABLE exam_questions
  ADD COLUMN area_id INT UNSIGNED NULL AFTER exam_id,
  ADD CONSTRAINT fk_exam_questions_area
    FOREIGN KEY (area_id) REFERENCES areas(id)
    ON UPDATE RESTRICT
    ON DELETE SET NULL;

-- 3) Indeks za filtriranje pitanja po oblasti
CREATE INDEX idx_exam_questions_area ON exam_questions(area_id);
