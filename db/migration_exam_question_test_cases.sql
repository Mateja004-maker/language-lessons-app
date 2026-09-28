-- Migracija: test primeri (ulaz/očekivan izlaz) za programske zadatke -
-- potrebno za mehaničku proveru tačnosti generisanog rešenja u režimu B
-- (zadatak, odeljak 8: "za programske zadatke pripremiti automatske testove
-- kojima se generisana rešenja izvršavaju i proveravaju").
--
-- Model interfejsa: svaki zadatak se rešava kao kompletan Python program koji
-- čita ulaz sa standardnog ulaza (input()) i ispisuje rezultat na standardni
-- izlaz (print()) - isto važi i za referentno rešenje (exam_questions.
-- reference_solution) i za generisano rešenje modela u režimu B. Ovo je
-- namerno nezavisno od tačnog imena/potpisa funkcije, da mehanička provera
-- meri ISPRAVNOST LOGIKE, ne poklapanje interfejsa.
--
-- Aditivno - nova tabela, ne dira postojeće. Ne pokretati automatski - runs
-- se ručno kroz phpMyAdmin.

CREATE TABLE IF NOT EXISTS exam_question_test_cases (
  id BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  question_id BIGINT UNSIGNED NOT NULL,
  input_data MEDIUMTEXT NULL,          -- šalje se na stdin; NULL ako program ne čita ulaz
  expected_output MEDIUMTEXT NOT NULL, -- očekivan stdout (poredi se posle .strip() na oba)
  order_no INT NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

  CONSTRAINT fk_test_cases_question
    FOREIGN KEY (question_id) REFERENCES exam_questions(id)
    ON UPDATE RESTRICT ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE INDEX idx_test_cases_question ON exam_question_test_cases(question_id);
