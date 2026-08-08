-- Migracija: exam_questions dobija subject_id kolonu.
-- Ne pokretati automatski - runs se ručno kroz phpMyAdmin.
--
-- Razlog: pitanje u banci (exam_id IS NULL) može, ali ne mora,
-- imati area_id (oblast je opciona). Bez direktne subject_id
-- kolone, pitanje bez oblasti ne bi imalo nikakav sačuvan trag
-- kog predmeta pripada, pa ga ni GET /api/subjects/<id>/questions
-- ni provera "isti predmet" u POST /api/exams/<id>/questions/<qid>
-- ne bi mogle pouzdano da nađu/provere.
--
-- subject_id je nullable (radi konzistentnosti sa area_id i radi
-- kompatibilnosti sa postojećim redovima koji ga još nemaju), i
-- FK je ON DELETE RESTRICT - sprečava brisanje predmeta dok god
-- postoji bar jedno pitanje (u banci ili u testu) tog predmeta,
-- isto obrazloženje kao kod areas.subject_id.

ALTER TABLE exam_questions
  ADD COLUMN subject_id INT UNSIGNED NULL AFTER exam_id,
  ADD CONSTRAINT fk_exam_questions_subject
    FOREIGN KEY (subject_id) REFERENCES subjects(id)
    ON UPDATE RESTRICT
    ON DELETE RESTRICT;
