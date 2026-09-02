-- Migracija: osnovne AI tabele (ai_models, ai_prompts, ai_generation_runs,
-- ai_generated_artifacts, ai_rubric_definitions, ai_evaluations).
--
-- POTVRĐENO 2026-09-02: ovo je tačan DDL izvučen komandom SHOW CREATE TABLE
-- iz Andrejeve lokalne baze (SVIH 6 tabela je zatečeno prazno, samo struktura,
-- bez ijednog reda podataka) — zamenjuje raniju pretpostavku
-- (migration_ai_generation_base_INFERRED.sql, sad zastarela/za brisanje).
--
-- I dalje NIJE POTVRĐENO da je Anđina baza IDENTIČNA ovome — samo da je
-- struktura kod Andreja prazna kopija nečega. Vredi da Anđa jednom potvrdi
-- (SHOW CREATE TABLE kod nje) da se poklapa, pošto je ona kasnije dodala bar
-- jednu izmenu (created_question_id na ai_generated_artifacts, iz
-- migration_ai_review.sql na njenoj grani) koju ova verzija namerno NE
-- uključuje jer nije bila deo zajedničkog početnog koraka.
--
-- Ne pokretati ovo na bazi gde tabele već postoje (npr. kod Andreja - već su
-- tu). Služi kao dokumentacija/reprodukovanje za svakog ko podiže bazu iz
-- čistog stanja (zadatak, odeljak 8: "ceo eksperiment mora biti ponovljiv").

CREATE TABLE IF NOT EXISTS `ai_models` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `provider` varchar(50) NOT NULL,
  `model_name` varchar(100) NOT NULL,
  `model_version` varchar(50) DEFAULT NULL,
  `default_params` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`default_params`)),
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS `ai_prompts` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `purpose` varchar(30) NOT NULL,
  `version` varchar(20) NOT NULL,
  `template` text NOT NULL,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_prompt_purpose_version` (`purpose`,`version`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS `ai_generation_runs` (
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
  `response_time_ms` int(11) DEFAULT NULL,
  `tokens_used` int(11) DEFAULT NULL,
  `retry_count` int(11) NOT NULL DEFAULT 0,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  KEY `fk_run_model` (`model_id`),
  KEY `fk_run_prompt` (`prompt_id`),
  CONSTRAINT `fk_run_model` FOREIGN KEY (`model_id`) REFERENCES `ai_models` (`id`),
  CONSTRAINT `fk_run_prompt` FOREIGN KEY (`prompt_id`) REFERENCES `ai_prompts` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS `ai_generated_artifacts` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `generation_run_id` bigint(20) unsigned NOT NULL,
  `artifact_type` varchar(30) NOT NULL,
  `status` varchar(20) NOT NULL DEFAULT 'predlog',
  `original_text` mediumtext NOT NULL,
  `edited_text` mediumtext DEFAULT NULL,
  `rejection_reason` text DEFAULT NULL,
  `reviewed_by` bigint(20) unsigned DEFAULT NULL,
  `reviewed_at` timestamp NULL DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  KEY `fk_artifact_run` (`generation_run_id`),
  KEY `fk_artifact_reviewer` (`reviewed_by`),
  CONSTRAINT `fk_artifact_reviewer` FOREIGN KEY (`reviewed_by`) REFERENCES `users` (`id`),
  CONSTRAINT `fk_artifact_run` FOREIGN KEY (`generation_run_id`) REFERENCES `ai_generation_runs` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS `ai_rubric_definitions` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `applies_to` varchar(30) NOT NULL,
  `dimension_key` varchar(50) NOT NULL,
  `dimension_label` varchar(100) NOT NULL,
  `scale_min` tinyint(4) NOT NULL DEFAULT 1,
  `scale_max` tinyint(4) NOT NULL DEFAULT 5,
  `evaluator_role` varchar(20) NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS `ai_evaluations` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `artifact_id` bigint(20) unsigned NOT NULL,
  `rubric_definition_id` int(10) unsigned NOT NULL,
  `evaluator_id` bigint(20) unsigned NOT NULL,
  `evaluator_role` varchar(20) NOT NULL,
  `score` tinyint(4) NOT NULL,
  `comment` text DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  KEY `fk_eval_artifact` (`artifact_id`),
  KEY `fk_eval_rubric` (`rubric_definition_id`),
  KEY `fk_eval_evaluator` (`evaluator_id`),
  CONSTRAINT `fk_eval_artifact` FOREIGN KEY (`artifact_id`) REFERENCES `ai_generated_artifacts` (`id`),
  CONSTRAINT `fk_eval_evaluator` FOREIGN KEY (`evaluator_id`) REFERENCES `users` (`id`),
  CONSTRAINT `fk_eval_rubric` FOREIGN KEY (`rubric_definition_id`) REFERENCES `ai_rubric_definitions` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
