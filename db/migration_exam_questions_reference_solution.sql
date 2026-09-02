-- Migracija: referentno (poznato tačno) rešenje za otvorene/praktične
-- zadatke - potrebno za režim A (objašnjenje uz poznato rešenje).
-- Aditivno, nullable - ne menja ponašanje postojećih ruta/MC pitanja.
-- Ne pokretati automatski - runs se ručno kroz phpMyAdmin.
-- NAPOMENA: dira exam_questions, deljenu tabelu - najaviti Anđi pre merge-a.

ALTER TABLE exam_questions
  ADD COLUMN reference_solution MEDIUMTEXT NULL AFTER question_text;
