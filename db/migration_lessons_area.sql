-- Migracija: lessons dobija area_id (oblast predmeta, ista tabela areas kao za pitanja).
-- Ne pokretati automatski - pokreće se ručno (phpMyAdmin ili mysql klijent).
-- Pre pokretanja napraviti backup van repozitorijuma.
--
-- - area_id je INT UNSIGNED (isti tip kao areas.id), NULL dozvoljen; postojeće
--   lekcije ostaju bez oblasti.
-- - FK isto kao exam_questions.area_id: ON DELETE SET NULL (brisanjem oblasti
--   lekcija ostaje, samo bez oblasti).
-- - Da oblast pripada predmetu lekcije (areas.subject_id = lessons.subject_id)
--   proverava backend, kao i za pitanja.
-- - Bezbedno za ponovno pokretanje (MariaDB 10.4: IF NOT EXISTS).

ALTER TABLE lessons
  ADD COLUMN IF NOT EXISTS area_id INT UNSIGNED NULL DEFAULT NULL AFTER subject_id;

ALTER TABLE lessons
  ADD CONSTRAINT fk_lessons_area
    FOREIGN KEY IF NOT EXISTS (area_id) REFERENCES areas (id)
    ON UPDATE RESTRICT
    ON DELETE SET NULL;

-- Rollback (briše samo oblast lekcija; predmet i jezik ostaju):
-- ALTER TABLE lessons DROP FOREIGN KEY fk_lessons_area;
-- ALTER TABLE lessons DROP KEY fk_lessons_area;
-- ALTER TABLE lessons DROP COLUMN area_id;
