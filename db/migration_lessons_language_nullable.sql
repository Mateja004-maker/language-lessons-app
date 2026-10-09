-- Migracija: lessons.language_id postaje NULL-dozvoljen.
-- Ne pokretati automatski - pokreće se ručno (phpMyAdmin ili mysql klijent).
-- Pre pokretanja napraviti backup van repozitorijuma.
--
-- Lekcija pripada predmetu preko lessons.subject_id (migracija 19). language_id
-- je nasleđe škole jezika: nova lekcija sa samo subject_id ostaje bez jezika (NULL).
-- Strani ključ fk_lessons_language (na languages.id) ostaje nepromenjen.
-- Postojeće vrednosti se ne menjaju.
--
-- Bezbedno za ponovno pokretanje: MODIFY na isti tip ne menja ništa ako je
-- kolona već NULL-dozvoljena.

ALTER TABLE lessons
  MODIFY COLUMN language_id INT UNSIGNED NULL DEFAULT NULL;

-- Rollback - SAMO ako sledeći upit vraća 0 redova:
--   SELECT id, title, subject_id FROM lessons WHERE language_id IS NULL;
-- PAŽNJA: sql_mode nije strict, pa rollback NE pada kad postoje takve lekcije, nego
-- im tiho upiše language_id = 0 (red koji krši strani ključ; provereno na probnoj bazi).
-- Takvim lekcijama prvo ručno upisati postojeći language_id ili ih obrisati.
-- ALTER TABLE lessons MODIFY COLUMN language_id INT UNSIGNED NOT NULL;
