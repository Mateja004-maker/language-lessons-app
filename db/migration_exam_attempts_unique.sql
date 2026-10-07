-- Migracija: jedan pokusaj po studentu po testu (UNIQUE exam_id, student_id)
-- Ne pokretati automatski - pokrece se rucno kroz phpMyAdmin.
--
-- Zasto: submit_exam proverava "vec postoji COMPLETED pokusaj" pa tek onda
-- upisuje (check-pa-insert). Dve istovremene predaje istog studenta obe
-- prodju proveru i upisu dva COMPLETED pokusaja. UNIQUE indeks to presece u
-- bazi; submit_exam hvata gresku 1062 i vraca 409.
--
-- Provera pre pokretanja (stanje 2026-10-07: 0 redova, 0 pokusaja sa
-- status <> 'COMPLETED' od ukupno 23):
--   SELECT exam_id, student_id, COUNT(*) FROM exam_attempts
--   GROUP BY exam_id, student_id HAVING COUNT(*) > 1;
-- Ako upit vrati bilo sta, ALTER ispod ce pasti - prvo resiti duplikate.
--
-- Napomena: ovim se zabranjuje i svako buduce ponovno polaganje istog testa
-- (vise pokusaja po studentu). Ako to zatreba, indeks se mora ukloniti/promeniti.
--
-- Pokrenuto 2026-10-07. Baza je pri tome SAMA uklonila stari KEY exam_id
-- (exam_id): novi indeks pocinje istom kolonom pa sada on pokriva FK
-- exam_attempts_ibfk_1.

ALTER TABLE exam_attempts
  ADD CONSTRAINT uq_exam_attempts_exam_student UNIQUE (exam_id, student_id);

-- Rollback (FK na exam_id mora imati indeks, pa se stari KEY vraca u istoj naredbi):
-- ALTER TABLE exam_attempts
--   ADD KEY exam_id (exam_id),
--   DROP INDEX uq_exam_attempts_exam_student;
