-- Migracija: exams dobija subject_id kolonu (test pripada PREDMETU, ne jeziku).
-- Ne pokretati automatski - runs se ručno kroz phpMyAdmin (posle backup-a).
-- NIJE idempotentna - ne pokretati dva puta (ADD COLUMN / ADD CONSTRAINT bi pukli).
--
-- Razlog: exams.language_id ima FK na languages(id), ali sva logika pristupa u
-- app.py (user_has_subject, get_user_subject_ids, areas.subject_id,
-- exam_questions.subject_id) ga već tretira kao id PREDMETA. Radi samo zato što
-- se id-jevi 1-6 u languages i subjects slučajno poklapaju; predmet 7 ("Osnove
-- programiranja") bi se prikazivao kao jezik 7 ("french"), a predmet sa id >= 8
-- bi pao na FK pri kreiranju testa.
--
-- "Expand" korak (isti obrazac kao migration_exam_test_questions.sql):
-- nova kolona se dodaje i popunjava, stara language_id se NE briše - samo
-- postaje nullable, da novi testovi ne bi morali da imaju jezik. Postojeći kod
-- nastavlja da radi identično posle ove migracije (i dalje čita language_id,
-- koji je za sve postojeće testove i dalje popunjen). Prelazak koda na
-- subject_id je sledeći, zaseban korak; brisanje language_id je kasnija
-- "contract" migracija.
--
-- Stanje baze provereno pre pisanja (samo čitanje, 2026-09-29): 25 testova,
-- language_id iz {1, 2, 5, 6}, svi imaju par sa istim id-jem i istim nazivom u
-- subjects; nijedan test sa language_id = 7; nijedno pitanje u testu nema
-- subject_id različit od testa.

-- 1) Nova kolona subject_id (nullable, isto kao exam_questions.subject_id i
--    areas.subject_id; FK ON DELETE RESTRICT - predmet se ne sme obrisati dok
--    ima testova)
ALTER TABLE exams
  ADD COLUMN subject_id INT UNSIGNED NULL AFTER language_id,
  ADD CONSTRAINT fk_exams_subject
    FOREIGN KEY (subject_id) REFERENCES subjects(id)
    ON UPDATE RESTRICT
    ON DELETE RESTRICT;

-- 2) Popunjavanje iz language_id - samo gde postoji predmet sa istim id-jem
--    (na dan migracije: svih 25 testova)
UPDATE exams e
  JOIN subjects s ON s.id = e.language_id
SET e.subject_id = e.language_id;

-- 3) language_id postaje nullable (FK na languages ostaje - NULL je dozvoljen),
--    da novi testovi za predmete bez para u languages ne padaju na FK
ALTER TABLE exams
  MODIFY language_id INT UNSIGNED NULL;

-- =====================================================================
-- Provera posle migracije (samo čitanje) - očekivano je naznačeno
-- =====================================================================

-- a) Testovi bez predmeta - očekivano 0
-- SELECT COUNT(*) AS bez_predmeta FROM exams WHERE subject_id IS NULL;

-- b) Testovi gde se subject_id razlikuje od language_id - očekivano 0
-- SELECT COUNT(*) AS razlicito FROM exams WHERE subject_id <> language_id;

-- c) Raspodela - očekivano 1 -> 21, 2 -> 2, 5 -> 1, 6 -> 1
-- SELECT subject_id, COUNT(*) AS n FROM exams GROUP BY subject_id ORDER BY subject_id;

-- d) Struktura - subject_id INT UNSIGNED NULL sa fk_exams_subject,
--    language_id INT UNSIGNED NULL (DEFAULT NULL), exams_ibfk_1 i dalje na languages
-- SHOW CREATE TABLE exams;
