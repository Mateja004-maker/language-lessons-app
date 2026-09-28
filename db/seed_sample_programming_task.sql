-- PRIVREMEN probni zadatak, samo za testiranje mehanizma generisanja i
-- mehaničke provere (stdin/stdout, subprocess, poređenje sa test primerima).
-- NIJE deo pravog referentnog skupa od 20-30 zadataka - taj skup se pravi
-- posebno, sa stvarno biranim programskim zadacima odgovarajuće težine.
-- Slobodno obrisati ovaj red i njegove test primere kad pravi skup bude gotov.

INSERT INTO exam_questions (exam_id, subject_id, area_id, question_text, reference_solution, points, order_no)
VALUES (
  NULL,
  NULL,
  NULL,
  'Napiši Python program koji sa standardnog ulaza učitava dva cela broja (svaki u posebnom redu) i ispisuje njihov zbir.',
  'a = int(input())\nb = int(input())\nprint(a + b)',
  1,
  0
);

-- Zapamti ID iz prethodnog INSERT-a (LAST_INSERT_ID()) za test primere ispod.
SET @new_question_id = LAST_INSERT_ID();

INSERT INTO exam_question_test_cases (question_id, input_data, expected_output, order_no)
VALUES
  (@new_question_id, '2\n3\n', '5', 0),
  (@new_question_id, '10\n-4\n', '6', 1),
  (@new_question_id, '0\n0\n', '0', 2);

SELECT @new_question_id AS test_task_question_id;
