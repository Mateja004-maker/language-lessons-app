-- Migracija: podrška za pregled/odobravanje AI predloga pitanja
-- (ai_generated_artifacts.status = 'predlog').
-- Ne pokretati automatski - runs se ručno kroz phpMyAdmin.
--
-- Deo 1: created_question_id povezuje odobreni predlog (status
-- 'prihvaceno' / 'prihvaceno_izmena') sa redom koji se kreira u
-- exam_questions ("banka" pitanja, exam_id IS NULL - isti obrazac kao
-- migration_exam_questions_subject.sql). Bez ovoga ne bi postojao trag
-- koje pitanje je nastalo od kog predloga, i ruta za pregled ne bi mogla
-- da spreči duplo objavljivanje istog predloga.
--
-- Deo 2: seed 8 kriterijuma rubrike za ručno ocenjivanje predloga pitanja
-- (Likert 1-5). "Formalna ispravnost" NIJE ovde - ona je već PASS/FAIL
-- preko ai_generation_runs.validation_passed, ne ocenjuje se ručno.
-- "Kvalitet distraktora" ima applies_to='question_mc' jer važi samo za
-- pitanja sa ponuđenim odgovorima (MC); ostalih 7 ima applies_to='question'
-- (važi za mc i open podjednako).

ALTER TABLE ai_generated_artifacts
  ADD COLUMN created_question_id BIGINT UNSIGNED NULL AFTER reviewed_at,
  ADD CONSTRAINT fk_artifact_created_question
    FOREIGN KEY (created_question_id) REFERENCES exam_questions(id)
    ON UPDATE RESTRICT
    ON DELETE SET NULL;

INSERT INTO ai_rubric_definitions
  (applies_to, dimension_key, dimension_label, scale_min, scale_max, evaluator_role)
VALUES
  ('question', 'strucna_tacnost', 'Stručna tačnost', 1, 5, 'TEACHER'),
  ('question', 'odgovorljivost', 'Odgovorljivost', 1, 5, 'TEACHER'),
  ('question', 'relevantnost', 'Relevantnost', 1, 5, 'TEACHER'),
  ('question_mc', 'kvalitet_distraktora', 'Kvalitet distraktora', 1, 5, 'TEACHER'),
  ('question', 'kalibracija_tezine', 'Kalibracija težine', 1, 5, 'TEACHER'),
  ('question', 'kognitivni_nivo', 'Kognitivni nivo', 1, 5, 'TEACHER'),
  ('question', 'originalnost', 'Originalnost', 1, 5, 'TEACHER'),
  ('question', 'jezicka_ispravnost', 'Jezička ispravnost', 1, 5, 'TEACHER');
