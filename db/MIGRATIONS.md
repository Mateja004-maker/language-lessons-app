# Baza: šema i migracije

## Nova baza (preporučeno)

`db/schema.sql` je potpuna trenutna šema: 28 tabela, sve migracije su već
uračunate. Na novu bazu se migracije **ne** pokreću.

```bash
mysql -u root -e "CREATE DATABASE language_learning CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci"
mysql -u root language_learning < db/schema.sql
mysql -u root language_learning < db/reference_data.sql   # uloge + kriterijumi ocenjivanja
```

Opciono, samo za lokalni razvoj:

- `db/seed.sql`: jezici, lekcije i probni korisnici (ADMIN / TEACHER / STUDENT).
  Sadrži heševe lozinki probnih naloga, pa ga ne koristiti na javnom serveru.
- `db/seed_sample_programming_task.sql`: jedan privremeni programski zadatak sa test primerima.

Predmete (`subjects`) i veze nastavnik/student–predmet (`teacher_subjects`,
`student_subjects`) aplikacija ne pravi preko API-ja. Unose se ručno
(phpMyAdmin), a dodela predmeta korisnicima ide kroz admin stranicu
(`PUT /api/users/<id>/subjects`).

Provera (2026-10-08): `schema.sql` i `reference_data.sql` učitani su u praznu bazu
`language_learning_test`. Struktura je upoređena sa stvarnom bazom preko
`information_schema` (tabele, kolone, indeksi, ograničenja, strani ključevi, CHECK)
i identična je: 28 tabela, 197 kolona, 76 indeksa, 41 strani ključ, 19 CHECK
ograničenja. Probna baza je potom obrisana.

Dopuna (2026-10-09): posle migracije 19 (`lessons.subject_id`) `schema.sql` je ponovo
izvučen iz baze; razlika u odnosu na prethodnu verziju je samo u tabeli `lessons`
(nova kolona, indeks i strani ključ).

Kada se šema promeni, `schema.sql` se ponovo izvlači iz baze:
`mysqldump --no-data --skip-comments --skip-dump-date --skip-add-drop-table`.
Iz izlaza se uklanjaju vrednosti `AUTO_INCREMENT=N`, a zaglavlje fajla se zadržava.

## Nadogradnja postojeće (stare) baze: redosled migracija

Ovaj redosled važi samo za bazu napravljenu pre ovih izmena. Osnovne tabele
škole jezika nikada nisu imale potpun skript. To su `roles`, `users`, `languages`,
`lessons`, `favorite_lessons`, `lesson_progress`, `subjects`, `teacher_subjects`,
`student_subjects`, `exams`, `exam_questions`, `exam_answers`, `exam_attempts`,
`exam_attempt_answers` i `exam_results`. Migracije pretpostavljaju da one već postoje.

Pravila:

- pre svake migracije napraviti backup van repozitorijuma;
- svaku migraciju pokrenuti tačno jednom;
- pre pokretanja proveriti da kolone ili tabele koje migracija dodaje već ne postoje;
- rollback je u komentaru na kraju fajla, gde postoji.

| # | Fajl | Šta radi | Zavisi od |
|---|------|----------|-----------|
| 1 | `migration_areas.sql` | tabela `areas` (oblasti predmeta), `exam_questions.area_id` | `subjects`, `exam_questions` |
| 2 | `migration_exam_test_questions.sql` | tabela `exam_test_questions` (test ↔ pitanje), popunjava je iz `exam_questions.exam_id` | — |
| 3 | `migration_exam_questions_nullable.sql` | `exam_questions.exam_id` postaje NULL, FK `ON DELETE SET NULL` (banka pitanja) | 2 |
| 4 | `migration_exam_questions_subject.sql` | `exam_questions.subject_id` | 1 |
| 5 | `migration_ai_generation_base_VERIFIED.sql` | AI tabele: `ai_models`, `ai_prompts`, `ai_generation_runs`, `ai_generated_artifacts`, `ai_rubric_definitions`, `ai_evaluations` | — |
| 6 | `migration_ai_review.sql` | `ai_generated_artifacts.created_question_id`, kriterijumi ocenjivanja pitanja | 5 |
| 7 | `migration_ai_explanation_module.sql` | `evaluation_batches`, `ai_generation_runs.accuracy_check_*` i `evaluation_batch_id`, kriterijumi za objašnjenja | 5 |
| 8 | `migration_exam_questions_reference_solution.sql` | `exam_questions.reference_solution` | — |
| 9 | `migration_exam_question_test_cases.sql` | tabela `exam_question_test_cases` | 8 |
| 10 | `migration_exams_subject.sql` | `exams.subject_id` + FK na `subjects`; **nije idempotentna** | — |
| 11 | `migration_exam_questions_subject_backfill.sql` | menja samo podatke: dopunjuje `exam_questions.subject_id` iz predmeta testa | 2, 4, 10 |
| 12 | `migration_exam_attempts_unique.sql` | UNIQUE (`exam_id`, `student_id`) na `exam_attempts` | — |
| 13 | `migration_question_labels.sql` | težina i Blumov nivo: `ai_generated_artifacts.model_*` / `reviewed_*`, `exam_questions.difficulty` / `bloom_level` | 5 |
| 14 | `migration_reference_sets.sql` | `reference_sets`, `reference_set_questions`, `evaluation_batches.reference_set_id` | 7 |
| 15 | `migration_edit_distance.sql` | `ai_generated_artifacts.edit_distance`, `edit_distance_norm` | 5 |
| 16 | `migration_duplicate_check.sql` | `max_similarity`, `similar_source`, `similar_question_id`, `similar_artifact_id`, `reviewed_duplicate` | 5 |
| 17 | `migration_failure_type_retry.sql` | `ai_generation_runs.failure_type`, `first_attempt_passed`, `format_retries` | 5 |
| 18 | `migration_second_rater.sql` | `ai_evaluations.evaluation_round` + UNIQUE, `ai_label_evaluations`, `evaluation_batches.closed_at` | 7, 13 |
| 19 | `migration_lessons_subject.sql` | `lessons.subject_id` + FK na `subjects`, jednokratno popunjava iz `language_id` (samo gde predmet postoji); `language_id` ostaje; može da se pokrene ponovo | — |

Redosled prati datume kada su fajlovi dodati u git, uz jedan izuzetak: broj 5
(`ai_generation_base_VERIFIED`) je u git dodat tek 2026-09-02. Tada je zapisana
struktura AI tabela koje su već postojale, pa ta migracija mora da ide pre
broja 6, koji menja `ai_generated_artifacts`.

Popune posle migracija menjaju samo podatke. Pokreću se iz `backend/`, i svaka
ima suvi prolaz (prvo sa `--dry-run`, pa bez njega):

- posle 15: `python tools/backfill_edit_distance.py`
- posle 16: `python tools/recompute_similarity.py`
- posle 17: `python tools/backfill_failure_type.py`

Upiti samo za čitanje (ne menjaju šemu) su u `db/queries/`.
