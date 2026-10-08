-- Referentni podaci bez kojih aplikacija ne radi (posle db/schema.sql).
-- Bez korisnika i bez lozinki. Id-jevi su isti kao u stvarnoj bazi
-- (role_id 1/2/3 i rubric_definition_id se koriste u kodu i izvozu).
--   roles                 - ADMIN, TEACHER, STUDENT
--   ai_rubric_definitions - kriterijumi ocenjivanja (pitanja: TEACHER;
--                           objašnjenja: TEACHER i STUDENT), skala 1-5
-- ai_models i ai_prompts se NE unose ovde: aplikacija ih sama upisuje pri prvoj
-- upotrebi (modeli iz ai_provider.py, promptovi iz backend/prompts/*.txt).

SET NAMES utf8mb4;

INSERT INTO roles (id, name) VALUES
  (1,'ADMIN'),
  (3,'STUDENT'),
  (2,'TEACHER');

INSERT INTO ai_rubric_definitions (id, applies_to, dimension_key, dimension_label, scale_min, scale_max, evaluator_role) VALUES
  (1,'question','strucna_tacnost','Stručna tačnost',1,5,'TEACHER'),
  (2,'question','odgovorljivost','Odgovorljivost',1,5,'TEACHER'),
  (3,'question','relevantnost','Relevantnost',1,5,'TEACHER'),
  (4,'question_mc','kvalitet_distraktora','Kvalitet distraktora',1,5,'TEACHER'),
  (5,'question','kalibracija_tezine','Kalibracija težine',1,5,'TEACHER'),
  (6,'question','kognitivni_nivo','Kognitivni nivo',1,5,'TEACHER'),
  (7,'question','originalnost','Originalnost',1,5,'TEACHER'),
  (8,'question','jezicka_ispravnost','Jezička ispravnost',1,5,'TEACHER'),
  (9,'explanation','korisnost','Korisnost',1,5,'STUDENT'),
  (10,'explanation','jasnoca','Jasnoća',1,5,'STUDENT'),
  (11,'explanation','percepcija_naucenog','Percepcija naučenog',1,5,'STUDENT'),
  (12,'explanation','tacnost_objasnjenja','Tačnost objašnjenja',1,5,'TEACHER'),
  (13,'explanation','vernost','Vernost (faithfulness)',1,5,'TEACHER'),
  (14,'explanation','potpunost','Potpunost',1,5,'TEACHER'),
  (15,'explanation','pedagoska_vrednost','Pedagoška vrednost',1,5,'TEACHER'),
  (16,'explanation','jezicka_ispravnost','Jezička ispravnost',1,5,'TEACHER');
