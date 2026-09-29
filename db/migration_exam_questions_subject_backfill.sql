-- Migracija: dopuna exam_questions.subject_id za stara pitanja bez predmeta,
-- iz predmeta testa u kome se pitanje nalazi (preko exam_test_questions).
-- Ne pokretati automatski - runs se ručno kroz phpMyAdmin (posle backup-a).
--
-- Razlog: pitanja napravljena pre migration_exam_questions_subject.sql imaju
-- subject_id = NULL. Banka pitanja (GET /api/subjects/<id>/questions) filtrira
-- po subject_id, pa se ta pitanja ne vide ni u jednoj banci. Pošto se od
-- izmene ExamDetailsView pitanja i odgovori menjaju ISKLJUČIVO preko banke
-- (/predmeti), ova pitanja trenutno ne mogu nigde da se izmene.
--
-- Isti "expand" obrazac kao ranije migracije: menja se SAMO subject_id koji je
-- NULL, samo za pitanja koja su u bar jednom testu, i samo kada svi testovi u
-- kojima je pitanje imaju ISTI predmet (dvosmislena pitanja se preskaču).
-- Nijedna postojeća vrednost subject_id se ne prepisuje; ništa se ne briše.
-- exam_questions nema ON UPDATE kolonu, pa UPDATE ne menja nijedno drugo polje
-- (za razliku od exams.updated_at u migration_exams_subject.sql).
--
-- Stanje provereno ranije (samo čitanje, 2026-09-29): 55 veza test<->pitanje
-- ima pitanje sa subject_id = NULL; po predmetu testa: 1 -> 46, 2 -> 5,
-- 5 -> 2, 6 -> 2. Nijedno pitanje u testu nema subject_id različit od testa,
-- niti oblast iz drugog predmeta. Tačan broj RAZLIČITIH pitanja (pitanje može
-- biti u više testova) proveriti upitom 0a pre pokretanja.
--
-- Posledica: ova pitanja se pojavljuju u banci svog predmeta na /predmeti
-- (mogu da se menjaju, a nude se i "Generiši slično" / "Generiši
-- objašnjenje"), a MC pitanja među njima i u listi za dodavanje u testove
-- tog predmeta. Nijedan test, pokušaj ni odgovor se ne menja.
--
-- NIJE idempotentna u smislu vraćanja: posle pokretanja više se ne vidi koja
-- su pitanja bila NULL. Zato SAČUVATI izlaz upita 0a pre pokretanja - to je
-- spisak id-jeva za eventualno vraćanje (vidi dno fajla).

-- =====================================================================
-- 0) Provera PRE pokretanja (samo čitanje)
-- =====================================================================

-- 0a) Pitanja koja će dobiti predmet - SAČUVATI ovaj spisak (id-jevi za vraćanje)
-- SELECT eq.id, MIN(e.subject_id) AS novi_subject_id,
--        GROUP_CONCAT(e.id ORDER BY e.id) AS testovi
-- FROM exam_questions eq
-- JOIN exam_test_questions etq ON etq.question_id = eq.id
-- JOIN exams e ON e.id = etq.exam_id
-- WHERE eq.subject_id IS NULL AND e.subject_id IS NOT NULL
-- GROUP BY eq.id
-- HAVING COUNT(DISTINCT e.subject_id) = 1
-- ORDER BY eq.id;

-- 0b) Dvosmislena pitanja (u testovima različitih predmeta) - očekivano 0 redova;
--     ako ih ima, migracija ih PRESKAČE i ostaju NULL
-- SELECT eq.id, GROUP_CONCAT(DISTINCT e.subject_id) AS predmeti
-- FROM exam_questions eq
-- JOIN exam_test_questions etq ON etq.question_id = eq.id
-- JOIN exams e ON e.id = etq.exam_id
-- WHERE eq.subject_id IS NULL
-- GROUP BY eq.id
-- HAVING COUNT(DISTINCT e.subject_id) > 1;

-- 0c) Pitanja sa oblašću iz drugog predmeta od testa - očekivano 0 redova
-- SELECT eq.id, eq.area_id, ar.subject_id AS predmet_oblasti, e.subject_id AS predmet_testa
-- FROM exam_questions eq
-- JOIN areas ar ON ar.id = eq.area_id
-- JOIN exam_test_questions etq ON etq.question_id = eq.id
-- JOIN exams e ON e.id = etq.exam_id
-- WHERE eq.subject_id IS NULL AND ar.subject_id <> e.subject_id;

-- =====================================================================
-- 1) Dopuna subject_id (jedina naredba koja menja podatke)
-- =====================================================================
UPDATE exam_questions eq
  JOIN (
    SELECT etq.question_id, MIN(e.subject_id) AS subject_id
    FROM exam_test_questions etq
    JOIN exams e ON e.id = etq.exam_id
    WHERE e.subject_id IS NOT NULL
    GROUP BY etq.question_id
    HAVING COUNT(DISTINCT e.subject_id) = 1
  ) t ON t.question_id = eq.id
SET eq.subject_id = t.subject_id
WHERE eq.subject_id IS NULL;

-- =====================================================================
-- Provera POSLE pokretanja (samo čitanje) - očekivano je naznačeno
-- =====================================================================

-- a) Pitanja u testovima i dalje bez predmeta - očekivano 0 (ili tačno
--    dvosmislena iz 0b)
-- SELECT COUNT(DISTINCT eq.id) AS bez_predmeta
-- FROM exam_questions eq
-- JOIN exam_test_questions etq ON etq.question_id = eq.id
-- WHERE eq.subject_id IS NULL;

-- b) Pitanja čiji se predmet ne slaže sa testom - očekivano 0
-- SELECT COUNT(*) AS neslaganje
-- FROM exam_questions eq
-- JOIN exam_test_questions etq ON etq.question_id = eq.id
-- JOIN exams e ON e.id = etq.exam_id
-- WHERE eq.subject_id <> e.subject_id;

-- c) Pitanja bez predmeta koja NISU ni u jednom testu - migracija ih ne dira,
--    broj mora biti isti kao pre pokretanja
-- SELECT COUNT(*) AS van_testova
-- FROM exam_questions eq
-- WHERE eq.subject_id IS NULL
--   AND NOT EXISTS (SELECT 1 FROM exam_test_questions etq WHERE etq.question_id = eq.id);

-- =====================================================================
-- Vraćanje (samo ako zatreba) - id-jeve uzeti iz sačuvanog izlaza upita 0a
-- =====================================================================
-- UPDATE exam_questions SET subject_id = NULL WHERE id IN (...);
