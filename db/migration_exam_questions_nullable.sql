-- Migracija: exam_questions.exam_id postaje nullable, FK menja
-- pravilo sa ON DELETE CASCADE na ON DELETE SET NULL.
-- Ne pokretati automatski - runs se ručno kroz phpMyAdmin.
--
-- Razlog: exam_test_questions (banka pitanja, vidi
-- migration_exam_test_questions.sql) sada može da drži isto
-- pitanje u više testova. Stari exam_id na exam_questions je
-- zastareo "legacy" pokazivač koji se i dalje čita u nekim
-- rutama, ali brisanje testa NE SME više da povuče brisanje
-- sadržaja pitanja (i njegovih exam_answers) - pitanje mora da
-- preživi, samo se otkačinje od obrisanog testa.
--
-- Postojeći FK (exam_questions_ibfk_1) ima ON DELETE CASCADE -
-- MySQL ne dozvoljava izmenu FK pravila in-place, pa se mora
-- prvo dropovati, pa ponovo napraviti sa novim pravilom.

-- 1) Dropuj postojeći FK sa CASCADE pravilom
ALTER TABLE exam_questions
  DROP FOREIGN KEY exam_questions_ibfk_1;

-- 2) exam_id postaje nullable
ALTER TABLE exam_questions
  MODIFY exam_id BIGINT UNSIGNED NULL;

-- 3) Ponovo dodaj FK, sada sa ON DELETE SET NULL
ALTER TABLE exam_questions
  ADD CONSTRAINT fk_exam_questions_exam
    FOREIGN KEY (exam_id) REFERENCES exams(id)
    ON UPDATE RESTRICT
    ON DELETE SET NULL;
