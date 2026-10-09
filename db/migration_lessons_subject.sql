-- Migracija: lessons dobija subject_id (lekcija pripada predmetu).
-- Ne pokretati automatski - pokreće se ručno (phpMyAdmin ili mysql klijent).
-- Pre pokretanja napraviti backup van repozitorijuma.
--
-- Do sada je lekcija bila vezana za predmet samo preko lessons.language_id,
-- što radi zato što se id-jevi jezika i predmeta slučajno poklapaju (1, 2, 5, 6;
-- id 7 se ne poklapa: jezik 'french', predmet 'Osnove programiranja').
--
-- - subject_id je INT UNSIGNED (isti tip kao subjects.id), NULL dozvoljen,
--   FK ON DELETE RESTRICT kao kod exam_questions.subject_id.
-- - Jednokratna popuna: subject_id = language_id, ali samo za lekcije čiji
--   language_id postoji u subjects. Ostale lekcije ostaju NULL.
-- - Stara kolona language_id se ne briše i ne menja.
-- - Bezbedno za ponovno pokretanje (MariaDB 10.4: IF NOT EXISTS; popuna dira
--   samo redove gde je subject_id još NULL).
--
-- Provera pre pokretanja - lekcije čiji language_id NE postoji u subjects
-- (one neće dobiti subject_id). Stanje 2026-10-09: 0 redova od 15 lekcija.
--   SELECT l.id, l.language_id, l.title FROM lessons l
--   LEFT JOIN subjects s ON s.id = l.language_id WHERE s.id IS NULL;

ALTER TABLE lessons
  ADD COLUMN IF NOT EXISTS subject_id INT UNSIGNED NULL DEFAULT NULL AFTER language_id;

ALTER TABLE lessons
  ADD CONSTRAINT fk_lessons_subject
    FOREIGN KEY IF NOT EXISTS (subject_id) REFERENCES subjects (id)
    ON UPDATE RESTRICT
    ON DELETE RESTRICT;

UPDATE lessons l
JOIN subjects s ON s.id = l.language_id
SET l.subject_id = s.id
WHERE l.subject_id IS NULL;

-- Rollback (briše samo novu kolonu; language_id ostaje netaknut):
-- ALTER TABLE lessons DROP FOREIGN KEY fk_lessons_subject;
-- ALTER TABLE lessons DROP KEY fk_lessons_subject;
-- ALTER TABLE lessons DROP COLUMN subject_id;
