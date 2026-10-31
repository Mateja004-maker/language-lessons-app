-- Migracija: ručna ocena tačnosti rešenja za predloge objašnjenja u režimu B
-- bez mehaničke provere (accuracy_check_passed IS NULL, npr. otvoreno pitanje
-- bez test primera).
-- Ne pokretati automatski - pokreće se ručno (phpMyAdmin ili mysql klijent).
-- Pre pokretanja napraviti backup van repozitorijuma.
--
-- - Menja samo podatke (jedan red u ai_rubric_definitions); šema ostaje ista,
--   pa se schema.sql ne osvežava. Isti red je u db/reference_data.sql (id 17).
-- - Binarna skala: 0 = netačno, 1 = tačno (score je tinyint, bez CHECK-a).
-- - applies_to = 'explanation_open_b': opšti upiti za objašnjenja
--   (applies_to = 'explanation') ga ne biraju; dodaje ga samo
--   explanation_review.teacher_rubric_applies_to za mode_b bez mehaničke provere.
-- - Bezbedno za ponovno pokretanje (ne upisuje drugi put isti kriterijum).

-- id 17 izričito, isti kao u reference_data.sql (auto_increment je mogao da
-- odmakne, npr. od privremenih upisa testova); zauzet id 17 -> greška, ništa se ne upisuje.
INSERT INTO ai_rubric_definitions
  (id, applies_to, dimension_key, dimension_label, scale_min, scale_max, evaluator_role)
SELECT 17, 'explanation_open_b', 'tacnost_resenja', 'Tačnost rešenja (tačno/netačno)', 0, 1, 'TEACHER'
FROM DUAL
WHERE NOT EXISTS (
  SELECT 1 FROM ai_rubric_definitions
  WHERE applies_to = 'explanation_open_b' AND dimension_key = 'tacnost_resenja'
);

-- Rollback (prvo ocene tog kriterijuma, pa kriterijum):
-- DELETE e FROM ai_evaluations e JOIN ai_rubric_definitions d ON d.id = e.rubric_definition_id
--   WHERE d.applies_to = 'explanation_open_b' AND d.dimension_key = 'tacnost_resenja';
-- DELETE FROM ai_rubric_definitions
--   WHERE applies_to = 'explanation_open_b' AND dimension_key = 'tacnost_resenja';
