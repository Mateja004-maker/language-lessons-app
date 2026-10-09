-- =====================================================================
-- Šema baze: sistem za onlajn testiranje + AI modul (stanje 2026-10-09)
-- =====================================================================
-- Kreira SVE tabele iz nule, bez podataka. Izvučeno komandom
--   mysqldump --no-data --skip-comments language_learning
-- iz stvarne baze (MariaDB 10.4) posle svih migracija iz db/MIGRATIONS.md,
-- pa su migracije već uračunate - na novu bazu se NE pokreću.
--
-- Upotreba (nova, PRAZNA baza):
--   CREATE DATABASE language_learning CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
--   mysql -u root language_learning < db/schema.sql
--   mysql -u root language_learning < db/reference_data.sql   (uloge + rubrike)
-- Fajl namerno nema CREATE DATABASE / USE (učitava se u bazu zadatu u komandi)
-- ni IF NOT EXISTS (na bazi koja već ima tabele pada odmah, umesto da je delimično izmeni).
--
-- Napomena: tabela languages i kolone *.language_id / users.learning_language_id
-- su nasleđe škole jezika; predmeti su u subjects + teacher_subjects/student_subjects.
-- =====================================================================

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `ai_evaluations` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `artifact_id` bigint(20) unsigned NOT NULL,
  `rubric_definition_id` int(10) unsigned NOT NULL,
  `evaluator_id` bigint(20) unsigned NOT NULL,
  `evaluator_role` varchar(20) NOT NULL,
  `score` tinyint(4) NOT NULL,
  `comment` text DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  `evaluation_round` tinyint(3) unsigned NOT NULL DEFAULT 1,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_eval_artifact_rubric_evaluator` (`artifact_id`,`rubric_definition_id`,`evaluator_id`),
  KEY `fk_eval_rubric` (`rubric_definition_id`),
  KEY `fk_eval_evaluator` (`evaluator_id`),
  CONSTRAINT `fk_eval_artifact` FOREIGN KEY (`artifact_id`) REFERENCES `ai_generated_artifacts` (`id`),
  CONSTRAINT `fk_eval_evaluator` FOREIGN KEY (`evaluator_id`) REFERENCES `users` (`id`),
  CONSTRAINT `fk_eval_rubric` FOREIGN KEY (`rubric_definition_id`) REFERENCES `ai_rubric_definitions` (`id`),
  CONSTRAINT `chk_eval_round` CHECK (`evaluation_round` in (1,2))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `ai_generated_artifacts` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `generation_run_id` bigint(20) unsigned NOT NULL,
  `artifact_type` varchar(30) NOT NULL,
  `status` varchar(20) NOT NULL DEFAULT 'predlog',
  `original_text` mediumtext NOT NULL,
  `edited_text` mediumtext DEFAULT NULL,
  `rejection_reason` text DEFAULT NULL,
  `reviewed_by` bigint(20) unsigned DEFAULT NULL,
  `reviewed_at` timestamp NULL DEFAULT NULL,
  `created_question_id` bigint(20) unsigned DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  `model_difficulty` varchar(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `model_bloom_level` varchar(12) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `reviewed_difficulty` varchar(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `reviewed_bloom_level` varchar(12) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `edit_distance` int(10) unsigned DEFAULT NULL,
  `edit_distance_norm` decimal(5,4) DEFAULT NULL,
  `max_similarity` decimal(4,3) DEFAULT NULL,
  `similar_source` varchar(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `similar_question_id` bigint(20) unsigned DEFAULT NULL,
  `similar_artifact_id` bigint(20) unsigned DEFAULT NULL,
  `reviewed_duplicate` tinyint(1) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `fk_artifact_run` (`generation_run_id`),
  KEY `fk_artifact_reviewer` (`reviewed_by`),
  KEY `fk_artifact_created_question` (`created_question_id`),
  KEY `fk_artifact_similar_question` (`similar_question_id`),
  KEY `fk_artifact_similar_artifact` (`similar_artifact_id`),
  CONSTRAINT `fk_artifact_created_question` FOREIGN KEY (`created_question_id`) REFERENCES `exam_questions` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_artifact_reviewer` FOREIGN KEY (`reviewed_by`) REFERENCES `users` (`id`),
  CONSTRAINT `fk_artifact_run` FOREIGN KEY (`generation_run_id`) REFERENCES `ai_generation_runs` (`id`),
  CONSTRAINT `fk_artifact_similar_artifact` FOREIGN KEY (`similar_artifact_id`) REFERENCES `ai_generated_artifacts` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_artifact_similar_question` FOREIGN KEY (`similar_question_id`) REFERENCES `exam_questions` (`id`) ON DELETE SET NULL,
  CONSTRAINT `chk_artifact_model_difficulty` CHECK (`model_difficulty` is null or `model_difficulty`  not like '% ' and `model_difficulty` in ('lako','srednje','tesko')),
  CONSTRAINT `chk_artifact_model_bloom` CHECK (`model_bloom_level` is null or `model_bloom_level`  not like '% ' and `model_bloom_level` in ('pamcenje','razumevanje','primena','analiza','vrednovanje','stvaranje')),
  CONSTRAINT `chk_artifact_reviewed_difficulty` CHECK (`reviewed_difficulty` is null or `reviewed_difficulty`  not like '% ' and `reviewed_difficulty` in ('lako','srednje','tesko')),
  CONSTRAINT `chk_artifact_reviewed_bloom` CHECK (`reviewed_bloom_level` is null or `reviewed_bloom_level`  not like '% ' and `reviewed_bloom_level` in ('pamcenje','razumevanje','primena','analiza','vrednovanje','stvaranje')),
  CONSTRAINT `chk_artifact_edit_distance_norm` CHECK (`edit_distance_norm` is null or `edit_distance_norm` >= 0 and `edit_distance_norm` <= 1),
  CONSTRAINT `chk_artifact_max_similarity` CHECK (`max_similarity` is null or `max_similarity` >= 0 and `max_similarity` <= 1),
  CONSTRAINT `chk_artifact_similar_source` CHECK (`similar_source` is null or `similar_source` in ('bank','source','artifact')),
  CONSTRAINT `chk_artifact_reviewed_duplicate` CHECK (`reviewed_duplicate` is null or `reviewed_duplicate` in (0,1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `ai_generation_runs` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `model_id` int(10) unsigned NOT NULL,
  `prompt_id` int(10) unsigned NOT NULL,
  `purpose` varchar(30) NOT NULL,
  `mode` varchar(10) DEFAULT NULL,
  `source_question_id` bigint(20) unsigned DEFAULT NULL,
  `params_used` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`params_used`)),
  `raw_response` mediumtext DEFAULT NULL,
  `parsed_result` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`parsed_result`)),
  `validation_passed` tinyint(1) DEFAULT NULL,
  `validation_errors` text DEFAULT NULL,
  `accuracy_check_passed` tinyint(1) DEFAULT NULL COMMENT 'relevantno samo za mode=mode_b; NULL = nije primenjivo/nije provereno',
  `accuracy_check_details` text DEFAULT NULL COMMENT 'npr. koji automatski test/poredjenje je koriscen i rezultat',
  `response_time_ms` int(11) DEFAULT NULL,
  `tokens_used` int(11) DEFAULT NULL,
  `retry_count` int(11) NOT NULL DEFAULT 0,
  `evaluation_batch_id` int(10) unsigned DEFAULT NULL COMMENT 'NULL = razvojna proba, van formalne evaluacije',
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  `failure_type` varchar(12) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `first_attempt_passed` tinyint(1) DEFAULT NULL,
  `format_retries` tinyint(3) unsigned DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `fk_run_model` (`model_id`),
  KEY `fk_run_prompt` (`prompt_id`),
  KEY `fk_run_evaluation_batch` (`evaluation_batch_id`),
  CONSTRAINT `fk_run_evaluation_batch` FOREIGN KEY (`evaluation_batch_id`) REFERENCES `evaluation_batches` (`id`),
  CONSTRAINT `fk_run_model` FOREIGN KEY (`model_id`) REFERENCES `ai_models` (`id`),
  CONSTRAINT `fk_run_prompt` FOREIGN KEY (`prompt_id`) REFERENCES `ai_prompts` (`id`),
  CONSTRAINT `chk_runs_failure_type` CHECK (`failure_type` is null or `failure_type`  not like '% ' and `failure_type` in ('network','http_4xx','rate_limit','http_5xx','empty','invalid_json','schema')),
  CONSTRAINT `chk_runs_first_attempt_passed` CHECK (`first_attempt_passed` is null or `first_attempt_passed` in (0,1)),
  CONSTRAINT `chk_runs_format_retries` CHECK (`format_retries` is null or `format_retries` <= 5)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `ai_label_evaluations` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `artifact_id` bigint(20) unsigned NOT NULL,
  `evaluator_id` bigint(20) unsigned NOT NULL,
  `evaluator_role` varchar(20) NOT NULL,
  `difficulty` varchar(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `bloom_level` varchar(12) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_label_eval_artifact_evaluator` (`artifact_id`,`evaluator_id`),
  KEY `fk_label_eval_evaluator` (`evaluator_id`),
  CONSTRAINT `fk_label_eval_artifact` FOREIGN KEY (`artifact_id`) REFERENCES `ai_generated_artifacts` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_label_eval_evaluator` FOREIGN KEY (`evaluator_id`) REFERENCES `users` (`id`),
  CONSTRAINT `chk_label_eval_difficulty` CHECK (`difficulty` is null or `difficulty`  not like '% ' and `difficulty` in ('lako','srednje','tesko')),
  CONSTRAINT `chk_label_eval_bloom` CHECK (`bloom_level` is null or `bloom_level`  not like '% ' and `bloom_level` in ('pamcenje','razumevanje','primena','analiza','vrednovanje','stvaranje'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `ai_models` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `provider` varchar(50) NOT NULL,
  `model_name` varchar(100) NOT NULL,
  `model_version` varchar(50) DEFAULT NULL,
  `default_params` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`default_params`)),
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `ai_prompts` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `purpose` varchar(30) NOT NULL,
  `version` varchar(20) NOT NULL,
  `template` text NOT NULL,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_prompt_purpose_version` (`purpose`,`version`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `ai_rubric_definitions` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `applies_to` varchar(30) NOT NULL,
  `dimension_key` varchar(50) NOT NULL,
  `dimension_label` varchar(100) NOT NULL,
  `scale_min` tinyint(4) NOT NULL DEFAULT 1,
  `scale_max` tinyint(4) NOT NULL DEFAULT 5,
  `evaluator_role` varchar(20) NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `areas` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `subject_id` int(10) unsigned NOT NULL,
  `name` varchar(150) NOT NULL,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_areas_subject_name` (`subject_id`,`name`),
  CONSTRAINT `fk_areas_subject` FOREIGN KEY (`subject_id`) REFERENCES `subjects` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `evaluation_batches` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `name` varchar(150) NOT NULL,
  `description` text DEFAULT NULL,
  `is_final` tinyint(1) NOT NULL DEFAULT 0,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  `reference_set_id` int(10) unsigned DEFAULT NULL,
  `closed_at` timestamp NULL DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_evaluation_batches_name` (`name`),
  KEY `fk_evaluation_batches_reference_set` (`reference_set_id`),
  CONSTRAINT `fk_evaluation_batches_reference_set` FOREIGN KEY (`reference_set_id`) REFERENCES `reference_sets` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `exam_answers` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `question_id` bigint(20) unsigned NOT NULL,
  `answer_text` text NOT NULL,
  `is_correct` tinyint(1) NOT NULL DEFAULT 0,
  PRIMARY KEY (`id`),
  KEY `question_id` (`question_id`),
  CONSTRAINT `exam_answers_ibfk_1` FOREIGN KEY (`question_id`) REFERENCES `exam_questions` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `exam_attempt_answers` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `attempt_id` bigint(20) unsigned NOT NULL,
  `question_id` bigint(20) unsigned NOT NULL,
  `answer_id` bigint(20) unsigned NOT NULL,
  `is_correct` tinyint(1) NOT NULL DEFAULT 0,
  `points_awarded` int(11) NOT NULL DEFAULT 0,
  PRIMARY KEY (`id`),
  KEY `attempt_id` (`attempt_id`),
  KEY `question_id` (`question_id`),
  KEY `answer_id` (`answer_id`),
  CONSTRAINT `exam_attempt_answers_ibfk_1` FOREIGN KEY (`attempt_id`) REFERENCES `exam_attempts` (`id`) ON DELETE CASCADE,
  CONSTRAINT `exam_attempt_answers_ibfk_2` FOREIGN KEY (`question_id`) REFERENCES `exam_questions` (`id`) ON DELETE CASCADE,
  CONSTRAINT `exam_attempt_answers_ibfk_3` FOREIGN KEY (`answer_id`) REFERENCES `exam_answers` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `exam_attempts` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `exam_id` bigint(20) unsigned NOT NULL,
  `student_id` bigint(20) unsigned NOT NULL,
  `started_at` timestamp NOT NULL DEFAULT current_timestamp(),
  `submitted_at` timestamp NULL DEFAULT NULL,
  `score` int(11) NOT NULL DEFAULT 0,
  `total_points` int(11) NOT NULL DEFAULT 0,
  `status` varchar(20) NOT NULL DEFAULT 'IN_PROGRESS',
  `tab_warnings` int(11) NOT NULL DEFAULT 0,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_exam_attempts_exam_student` (`exam_id`,`student_id`),
  KEY `student_id` (`student_id`),
  CONSTRAINT `exam_attempts_ibfk_1` FOREIGN KEY (`exam_id`) REFERENCES `exams` (`id`) ON DELETE CASCADE,
  CONSTRAINT `exam_attempts_ibfk_2` FOREIGN KEY (`student_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `exam_question_test_cases` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `question_id` bigint(20) unsigned NOT NULL,
  `input_data` mediumtext DEFAULT NULL,
  `expected_output` mediumtext NOT NULL,
  `order_no` int(11) NOT NULL DEFAULT 0,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  KEY `idx_test_cases_question` (`question_id`),
  CONSTRAINT `fk_test_cases_question` FOREIGN KEY (`question_id`) REFERENCES `exam_questions` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `exam_questions` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `exam_id` bigint(20) unsigned DEFAULT NULL,
  `subject_id` int(10) unsigned DEFAULT NULL,
  `area_id` int(10) unsigned DEFAULT NULL,
  `question_text` text NOT NULL,
  `reference_solution` mediumtext DEFAULT NULL,
  `points` int(11) NOT NULL DEFAULT 1,
  `order_no` int(11) NOT NULL DEFAULT 0,
  `difficulty` varchar(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  `bloom_level` varchar(12) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_exam_questions_area` (`area_id`),
  KEY `fk_exam_questions_exam` (`exam_id`),
  KEY `fk_exam_questions_subject` (`subject_id`),
  CONSTRAINT `fk_exam_questions_area` FOREIGN KEY (`area_id`) REFERENCES `areas` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_exam_questions_exam` FOREIGN KEY (`exam_id`) REFERENCES `exams` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_exam_questions_subject` FOREIGN KEY (`subject_id`) REFERENCES `subjects` (`id`),
  CONSTRAINT `chk_exam_questions_difficulty` CHECK (`difficulty` is null or `difficulty`  not like '% ' and `difficulty` in ('lako','srednje','tesko')),
  CONSTRAINT `chk_exam_questions_bloom` CHECK (`bloom_level` is null or `bloom_level`  not like '% ' and `bloom_level` in ('pamcenje','razumevanje','primena','analiza','vrednovanje','stvaranje'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `exam_results` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `exam_id` int(11) NOT NULL,
  `student_id` int(11) NOT NULL,
  `score` int(11) NOT NULL,
  `total` int(11) NOT NULL,
  `submitted_at` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `exam_test_questions` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `exam_id` bigint(20) unsigned NOT NULL,
  `question_id` bigint(20) unsigned NOT NULL,
  `order_no` int(11) NOT NULL DEFAULT 0,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_etq_exam_question` (`exam_id`,`question_id`),
  KEY `fk_etq_question` (`question_id`),
  CONSTRAINT `fk_etq_exam` FOREIGN KEY (`exam_id`) REFERENCES `exams` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_etq_question` FOREIGN KEY (`question_id`) REFERENCES `exam_questions` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `exams` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `title` varchar(200) NOT NULL,
  `description` text DEFAULT NULL,
  `language_id` int(10) unsigned DEFAULT NULL,
  `subject_id` int(10) unsigned DEFAULT NULL,
  `level` varchar(10) NOT NULL,
  `duration_minutes` int(11) NOT NULL DEFAULT 30,
  `open_at` datetime DEFAULT NULL,
  `close_at` datetime DEFAULT NULL,
  `exam_mode` tinyint(1) NOT NULL DEFAULT 0,
  `is_published` tinyint(1) NOT NULL DEFAULT 0,
  `created_by` bigint(20) unsigned DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  `updated_at` timestamp NULL DEFAULT NULL ON UPDATE current_timestamp(),
  PRIMARY KEY (`id`),
  KEY `language_id` (`language_id`),
  KEY `created_by` (`created_by`),
  KEY `fk_exams_subject` (`subject_id`),
  CONSTRAINT `exams_ibfk_1` FOREIGN KEY (`language_id`) REFERENCES `languages` (`id`),
  CONSTRAINT `exams_ibfk_2` FOREIGN KEY (`created_by`) REFERENCES `users` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_exams_subject` FOREIGN KEY (`subject_id`) REFERENCES `subjects` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `favorite_lessons` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `user_id` int(11) NOT NULL,
  `lesson_id` int(11) NOT NULL,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `unique_user_lesson` (`user_id`,`lesson_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `languages` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `code` varchar(10) NOT NULL,
  `name` varchar(80) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `code` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `lesson_progress` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `user_id` int(11) NOT NULL,
  `lesson_id` int(11) NOT NULL,
  `viewed_at` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `unique_user_lesson_progress` (`user_id`,`lesson_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `lessons` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `language_id` int(10) unsigned DEFAULT NULL,
  `subject_id` int(10) unsigned DEFAULT NULL,
  `area_id` int(10) unsigned DEFAULT NULL,
  `level` varchar(10) NOT NULL,
  `title` varchar(200) NOT NULL,
  `content_html` mediumtext DEFAULT NULL,
  `order_no` int(11) NOT NULL DEFAULT 0,
  `created_by` bigint(20) unsigned DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  `updated_at` timestamp NULL DEFAULT NULL ON UPDATE current_timestamp(),
  `tips` text DEFAULT NULL,
  `important_info` text DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `fk_lessons_created_by` (`created_by`),
  KEY `idx_lessons_language_level` (`language_id`,`level`),
  KEY `idx_lessons_order` (`language_id`,`order_no`),
  KEY `fk_lessons_subject` (`subject_id`),
  KEY `fk_lessons_area` (`area_id`),
  CONSTRAINT `fk_lessons_area` FOREIGN KEY (`area_id`) REFERENCES `areas` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_lessons_created_by` FOREIGN KEY (`created_by`) REFERENCES `users` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_lessons_language` FOREIGN KEY (`language_id`) REFERENCES `languages` (`id`),
  CONSTRAINT `fk_lessons_subject` FOREIGN KEY (`subject_id`) REFERENCES `subjects` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `reference_set_questions` (
  `reference_set_id` int(10) unsigned NOT NULL,
  `question_id` bigint(20) unsigned NOT NULL,
  `order_no` int(11) NOT NULL DEFAULT 0,
  PRIMARY KEY (`reference_set_id`,`question_id`),
  KEY `fk_rsq_question` (`question_id`),
  CONSTRAINT `fk_rsq_question` FOREIGN KEY (`question_id`) REFERENCES `exam_questions` (`id`),
  CONSTRAINT `fk_rsq_set` FOREIGN KEY (`reference_set_id`) REFERENCES `reference_sets` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `reference_sets` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `name` varchar(150) NOT NULL,
  `subject_id` int(10) unsigned NOT NULL,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_reference_sets_name` (`name`),
  KEY `fk_reference_sets_subject` (`subject_id`),
  CONSTRAINT `fk_reference_sets_subject` FOREIGN KEY (`subject_id`) REFERENCES `subjects` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `roles` (
  `id` tinyint(3) unsigned NOT NULL AUTO_INCREMENT,
  `name` varchar(32) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `student_subjects` (
  `student_id` bigint(20) unsigned NOT NULL,
  `subject_id` int(10) unsigned NOT NULL,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`student_id`,`subject_id`),
  KEY `fk_ss_subject` (`subject_id`),
  CONSTRAINT `fk_ss_student` FOREIGN KEY (`student_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_ss_subject` FOREIGN KEY (`subject_id`) REFERENCES `subjects` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `subjects` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `code` varchar(10) NOT NULL,
  `name` varchar(80) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `code` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `teacher_subjects` (
  `teacher_id` bigint(20) unsigned NOT NULL,
  `subject_id` int(10) unsigned NOT NULL,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`teacher_id`,`subject_id`),
  KEY `fk_ts_subject` (`subject_id`),
  CONSTRAINT `fk_ts_subject` FOREIGN KEY (`subject_id`) REFERENCES `subjects` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_ts_teacher` FOREIGN KEY (`teacher_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `users` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `email` varchar(190) NOT NULL,
  `password_hash` varchar(255) NOT NULL,
  `role_id` tinyint(3) unsigned NOT NULL,
  `display_name` varchar(80) DEFAULT NULL,
  `profile_image` varchar(255) DEFAULT NULL,
  `is_active` tinyint(1) NOT NULL DEFAULT 1,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  `updated_at` timestamp NULL DEFAULT NULL ON UPDATE current_timestamp(),
  `learning_language_id` int(10) unsigned DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `email` (`email`),
  KEY `idx_users_role` (`role_id`),
  KEY `fk_users_learning_language` (`learning_language_id`),
  CONSTRAINT `fk_users_learning_language` FOREIGN KEY (`learning_language_id`) REFERENCES `languages` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_users_role` FOREIGN KEY (`role_id`) REFERENCES `roles` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

