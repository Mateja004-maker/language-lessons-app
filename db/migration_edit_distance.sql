-- Migracija: razdaljina izmene za AI predloge pitanja (tačka B)
-- Ne pokretati automatski - pokreće se ručno (phpMyAdmin ili mysql klijent).
--
-- Za predlog sa odlukom 'prihvaceno_izmena' čuva obim nastavničke intervencije
-- (backend/edit_distance.py):
--   edit_distance       - Levenshtein: pitanje + odgovori (broj znakova)
--   edit_distance_norm  - edit_distance / zbir dužina dužeg teksta po delu (0..1)
-- Ostali predlozi ostaju NULL.
--
-- Pre migracije: pregled radi kao i do sada, vrednosti se samo ne upisuju.
-- Posle migracije: novi pregledi ih upisuju; za već izmenjene predloge pokrenuti
--   python tools/backfill_edit_distance.py           (iz backend/; upisuje samo NULL vrednosti)

ALTER TABLE ai_generated_artifacts
  ADD COLUMN edit_distance INT UNSIGNED NULL DEFAULT NULL,
  ADD COLUMN edit_distance_norm DECIMAL(5,4) NULL DEFAULT NULL,
  ADD CONSTRAINT chk_artifact_edit_distance_norm
    CHECK (edit_distance_norm IS NULL OR (edit_distance_norm >= 0 AND edit_distance_norm <= 1));

-- Rollback (briše kolone i vrednosti u njima):
-- ALTER TABLE ai_generated_artifacts
--   DROP CONSTRAINT chk_artifact_edit_distance_norm,
--   DROP COLUMN edit_distance,
--   DROP COLUMN edit_distance_norm;
