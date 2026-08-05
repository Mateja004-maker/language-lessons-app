# CLAUDE.md — Sistem za onlajn testiranje (proširenje za Akademiju)

## Šta je ovo
Web aplikacija za onlajn testiranje, izvorno napravljena za školu jezika,
sada se proširuje za akademske predmete i AI funkcionalnosti (generisanje
pitanja i generisanje rešenja/objašnjenja).

## Tehnologije
- Frontend: Vue 3 + Vite + Bootstrap (folder `frontend/`)
- Backend: Flask, JEDAN fajl `backend/app.py` (~2100 linija, bez blueprint podele)
- Baza: MySQL, pristupa se preko phpMyAdmin-a
- Auth: JWT (flask-jwt-extended)
- Uloge: ADMIN, TEACHER, STUDENT (provera preko role_id / role_required dekoratora)

## VAŽNO — stanje baze
`db/schema.sql` u repozitorijumu je NEPOTPUN (samo placeholder) i NE odražava
stvarnu bazu. Stvarna baza ima dodatno bar ove tabele koje se koriste u app.py:
exams, exam_questions, exam_answers, exam_attempts, exam_attempt_answers,
favorite_lessons, lesson_progress.
Pre bilo kakve izmene šeme, uvek prvo proveriti stvarnu bazu (export iz phpMyAdmin-a),
ne verovati slepo schema.sql fajlu.

## Migracija u toku: jezik → predmet
Aplikacija je izvorno vezana za JEDAN jezik po korisniku (kolona
`users.learning_language_id`, i `exams.language_id`, `lessons.language_id`).
Cilj je da student/nastavnik mogu da budu vezani za VIŠE predmeta (many-to-many).
Vidi `db/migration_subjects.sql` za predloženu novu strukturu.
NE brisati staru `learning_language_id` logiku dok se sva mesta u app.py koja
je koriste ne prebace na novi model (vidi listu mesta niže).

Mesta u app.py koja trenutno koriste learning_language_id / language_id
(potrebno ih je prilagoditi many-to-many modelu):
- registracija i izmena profila korisnika
- prikaz profila (SELECT sa JOIN languages)
- filtriranje dostupnih lekcija po jeziku korisnika
- provera da nastavnik predaje odgovarajući jezik pri kreiranju testa
- provera da student pripada jeziku testa pri pristupu/radu testa
- listing testova dostupnih studentu/nastavniku

## AI proširenje (u razvoju)
Dva paralelna modula, zajednička infrastruktura:
- Anđa: generisanje novih pitanja na osnovu postojećih
- Andrej: generisanje rešenja i objašnjenja (režim A: uz gotovo rešenje, režim B: bez njega)
- Zajedničko: provider layer (jedinstven `generate(prompt, options)` interfejs
  ka različitim AI modelima), zajednički model podataka za evaluaciju
  (modeli, promptovi, generation runs, generisani artefakti, ocene, rubrike)
- Nijedan generisan sadržaj ne sme automatski da se plasira studentima —
  uvek prolazi kroz status "predlog" → pregled nastavnika → odobrenje

## Pravila rada u ovom projektu
- Male izmene, čest commit, jasne poruke
- Pre veće izmene: prvo plan, pa tek kod
- Ne menjati postojeće rute/ponašanje bez izričitog dogovora
- Svaka izmena koja ne sme da promeni ponašanje mora se proveriti pre/posle na istom ulazu
- Prompt šabloni se čuvaju kao fajlovi u repozitorijumu, ne kao stringovi razbacani u kodu

## Komande
- Backend: `cd backend && python app.py` (proveriti tačan način pokretanja/venv)
- Frontend: `cd frontend && npm run dev`
