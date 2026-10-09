# CLAUDE.md — Sistem za onlajn testiranje (proširenje za Akademiju)

## Šta je ovo
Web aplikacija za onlajn testiranje, izvorno napravljena za školu jezika,
proširena za akademske predmete i AI funkcionalnosti: generisanje sličnih
pitanja (Anđa) i generisanje rešenja/objašnjenja (Andrej). Pregled za ljude je
u `README.md`, ponavljanje eksperimenta u `docs/PONAVLJANJE_EKSPERIMENTA.md`.

## Tehnologije
- Frontend: Vue 3 + Vite + Bootstrap (folder `frontend/`); `/api` se kroz Vite proxy prosleđuje na 127.0.0.1:5000
- Backend: Flask, glavni fajl `backend/app.py` (~5400 linija, bez blueprint podele).
  Pomoćni moduli: `ai_provider.py`, `prompt_templates.py`, `question_validation.py`,
  `generation_failures.py`, `question_similarity.py`, `edit_distance.py`, `agreement.py`,
  `explanation_*.py` i `code_executor.py` (Andrejev modul)
- Baza: MariaDB 10.4 (XAMPP), baza `language_learning`, pristup preko phpMyAdmin-a
  ili `C:/xampp/mysql/bin/mysql.exe`. `sql_mode` nije strict.
- Auth: JWT (flask-jwt-extended); uloge ADMIN (1), TEACHER (2), STUDENT (3), dekorator `role_required`
- Konfiguracija: `backend/.env` (MYSQL_*, JWT_SECRET_KEY, *_API_KEY). Vrednosti se nikad ne ispisuju.
  `app` se importuje pre `ai_provider`, jer `app.py` učitava `.env`.

## Baza
- `db/schema.sql` je POTPUNA trenutna šema (28 tabela, sve migracije uračunate). Izvučena je
  iz stvarne baze 2026-10-08 i proverena na praznoj probnoj bazi (struktura identična).
  Ne sadrži podatke. `db/reference_data.sql` sadrži uloge i kriterijume ocenjivanja.
- `db/MIGRATIONS.md`: redosled migracija za staru bazu i postupak osvežavanja `schema.sql`.
- Pre svake izmene šeme proveriti stvarnu bazu (`SHOW CREATE TABLE` / `information_schema`)
  i napraviti backup VAN repozitorijuma (`../backup_*.sql`).
- Migracije se samo pišu, sa rollback-om u komentaru. Pokreću se tek uz potvrdu korisnika,
  tačno jednom: pre pokretanja proveriti da kolone ili tabele već ne postoje.
  Posle svake nove migracije osvežiti `schema.sql` (vidi `MIGRATIONS.md`).
- Upiti samo za čitanje su u `db/queries/`.

## Jezik → predmet (stanje)
- Predmeti: `subjects` + many-to-many `teacher_subjects` / `student_subjects`;
  `get_user_subject_ids` / `user_has_subject` u app.py.
- Testovi i pitanja pripadaju predmetu: `exams.subject_id`, `exam_questions.subject_id`
  (banka pitanja, `exam_id IS NULL`), oblasti u `areas`, a veza test ↔ pitanje ide preko `exam_test_questions`.
- Nasleđe škole jezika:
  - `languages`, `lessons.language_id`, `users.learning_language_id`
    (registracija, izmena i prikaz profila) i `exams.language_id` (više se ne upisuje).
  - Kreiranje testa još prima `language_id` kao rezervu za `subject_id`.
  - Lekcije pripadaju predmetu preko `lessons.subject_id` (migracije 19 i 20); filtriranje, detalj,
    izmena i brisanje proveravaju predmet korisnika. `lessons.language_id` je neobavezan (NULL);
    rute lekcija ga još primaju kao rezervu za `subject_id` dok frontend ne pređe na `subject_id`.

## AI modul
- Provajderi: groq `openai/gpt-oss-20b`, gemini `gemini-3.6-flash`,
  openrouter `nvidia/nemotron-3-super-120b-a12b:free` (`ai_provider.DEFAULT_MODELS`).
  Mistral postoji u kodu, ali se ne dira i nije u eksperimentu.
- Promptovi su fajlovi u `backend/prompts/`, a verzija je u prvom redu `{# version: … #}`.
  - Aktivni: `mc-v3`, `open-v3` (jedno pitanje) i `set-v1` (skup pitanja).
  - Arhiva: `*_v2.txt`.
  - Andrej: `explanation_mode_a_v1`, `explanation_mode_b_v1`.
- Nijedan generisan sadržaj ne ide automatski studentima: status `predlog` → slepi
  pregled nastavnika → `prihvaceno` / `prihvaceno_izmena` / `odbaceno`. Odobreno pitanje
  ide u banku, ne direktno u test.
- Slepi pregled: model se ne sme otkriti dok je predlog u statusu `predlog` / serija otvorena.
  Nastavnik bira težinu i Blumov nivo PRE nego što vidi oznake modela.
- Eksperiment:
  - referentni skup → evaluaciona serija → `backend/tools/run_experiment.py`
    (režimi `single` / `set`, `--dry-run`);
  - prvi i drugi ocenjivač (`evaluation_round` 1/2, `ai_label_evaluations`);
  - zatvaranje serije;
  - CSV izvoz `GET /api/evaluation-batches/<id>/export.csv` (ADMIN; korisnici samo kao HMAC heš);
  - analiza `backend/tools/analyze_experiment.py` (kapa, alfa, SVG grafikoni, samo stdlib).
- Tačku F (`retry_count` / `response_model` / `model_version`) radi Andrejeva grana. Ne dirati je ovde.
- Probni redovi (probe v3, gemini i set) su zabeleženi u `backend/probe_v3_ids.json`
  (gitignore). Ne brisati ih bez dogovora.

## Testovi (iz `backend/`, uz `PYTHONIOENCODING=utf-8`)
- `tests/test_*.py`: unit testovi, bez baze i mreže.
- `tests/verify_*.py`: integracioni testovi nad bazom iz `.env`, sa lažnim AI provajderom.
  Brišu privremene podatke i porede broj redova pre i posle.
- `tools/test_clean_db.py`: svi testovi na praznoj probnoj bazi (`*_test`, iz `schema.sql` + seed), koja se na kraju briše.
  Testovi ne smeju da pokreću nov Python proces koji importuje `app` (ponovo bi učitao `.env`, tj. pravu bazu).
- Pravi modeli se nikad ne pozivaju iz testova. Pravi pozivi idu samo uz izričitu potvrdu korisnika
  (npr. `tools/probe_v3.py --confirm`, `run_experiment.py` bez `--dry-run`).

## Pravila rada u ovom projektu
- Male izmene, čest commit, jasne poruke na srpskom bez dijakritika
- Pre veće izmene: prvo plan, pa tek kod
- Ne menjati postojeće rute/ponašanje bez izričitog dogovora
- Svaka izmena koja ne sme da promeni ponašanje mora se proveriti pre/posle na istom ulazu
- Prompt šabloni se čuvaju kao fajlovi u repozitorijumu, ne kao stringovi razbacani u kodu
- `main` se ne push-uje bez potvrde; feature grana tek kad se traži

## Komande
- Baza od nule: vidi `README.md` (`schema.sql` + `reference_data.sql`)
- Backend: `cd backend && venv\Scripts\activate && python app.py`
- Frontend: `cd frontend && npm run dev` (build: `npm run build`)
- Testovi: vidi `README.md`, odeljak 4
