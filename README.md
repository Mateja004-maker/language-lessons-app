# Sistem za onlajn testiranje sa AI generisanjem pitanja, rešenja i objašnjenja

Web aplikacija za onlajn testiranje. Izvorno je napravljena za školu jezika, a sada je
proširena za akademske predmete:

- **Uloge:** ADMIN, TEACHER, STUDENT.
- **Predmeti i oblasti:** banka pitanja po predmetu; testovi se sastavljaju iz banke.
- **Rad testova:** studenti rade testove, a sistem ocenjuje.
- **AI modul:**
  - generisanje sličnih pitanja: iz jednog pitanja ili iz skupa pitanja testa;
  - generisanje rešenja i objašnjenja: Andrejev deo, režimi A i B.
- **Pregled AI sadržaja:** nijedan generisan sadržaj ne ide automatski studentima. Uvek prolazi
  status `predlog` → slepi pregled nastavnika → odluka (prihvaćeno / uz izmenu / odbačeno).
- **Eksperiment:** poređenje modela (groq, gemini, openrouter) na referentnom skupu pitanja.
  Uključuje drugu ocenu, saglasnost ocenjivača (Koenova kapa, Kripendorfova alfa) i CSV izvoz.
  Postupak je opisan u [docs/PONAVLJANJE_EKSPERIMENTA.md](docs/PONAVLJANJE_EKSPERIMENTA.md), a za
  objašnjenja (režimi A i B, mehanička provera tačnosti) u
  [docs/PONAVLJANJE_EKSPERIMENTA_OBJASNJENJA.md](docs/PONAVLJANJE_EKSPERIMENTA_OBJASNJENJA.md).

## Struktura

| Folder | Sadržaj |
|--------|---------|
| `backend/` | Flask API (`app.py`), AI provajderi (`ai_provider.py`), validacija, sličnost, saglasnost |
| `backend/prompts/` | šabloni promptova (verzija je u zaglavlju fajla) |
| `backend/tools/` | pokretač eksperimenta, analiza, probe i popune |
| `backend/tests/` | `test_*.py` (bez baze) i `verify_*.py` (rade nad bazom) |
| `frontend/` | Vue 3 + Vite + Bootstrap |
| `db/` | `schema.sql`, `reference_data.sql`, migracije ([db/MIGRATIONS.md](db/MIGRATIONS.md)), `queries/` |
| `docs/` | uputstva |

## Zahtevi

- Python 3.11+ (razvijano na 3.14)
- Node.js 20+ i npm (razvijano na Node 24)
- MariaDB 10.4+ ili MySQL 8 (razvijano na MariaDB 10.4 iz XAMPP-a; upiti u
  `db/queries/` koriste `MEDIAN() OVER`, što postoji samo u MariaDB-u)

## 1. Baza

```bash
mysql -u root -e "CREATE DATABASE language_learning CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci"
mysql -u root language_learning < db/schema.sql
mysql -u root language_learning < db/reference_data.sql
# opciono, samo lokalno: probni korisnici, jezici i lekcije
mysql -u root language_learning < db/seed.sql
```

- `schema.sql` već sadrži sve migracije. Redosled migracija za staru bazu je u
  [db/MIGRATIONS.md](db/MIGRATIONS.md).
### Prvi administrator

Nova baza nema nijednog korisnika (`seed.sql` dodaje probne naloge, ali samo za lokalni razvoj).

1. Registrujte se u aplikaciji kao student ili nastavnik. Javna registracija ne dozvoljava
   ulogu ADMIN, i pravi **neaktivan** nalog koji čeka odobrenje.
2. Prvi nalog nema ko da odobri, pa ga ručno pretvorite u aktivnog administratora:
   ```sql
   UPDATE users SET role_id = (SELECT id FROM roles WHERE name = 'ADMIN'), is_active = 1
   WHERE email = 'vas@email';
   ```
3. Ostale naloge admin odobrava ili pravi u aplikaciji: **Administracija → Korisnici** (`/admin/users`, samo ADMIN).
   Nove ADMIN naloge posle toga pravi samo postojeći admin.

### Predmeti

Predmete pravi admin na stranici **Administracija → Upravljanje predmetima** (`/admin/predmeti`,
samo ADMIN): dodavanje (naziv i oznaka; `code` ima najviše 10 znakova, `name` najviše 80),
izmena naziva i brisanje. Naziv je jedinstven bez obzira na velika i mala slova. Brisanje je
zaštićeno: predmet koji koriste nastavnici, studenti, oblasti, lekcije, pitanja, testovi ili
referentni skupovi se ne briše, nego aplikacija javlja šta ga koristi i koliko puta
(API: `POST /api/subjects`, `PUT /api/subjects/<id>`, `DELETE /api/subjects/<id>`).

Predmete nastavnicima i studentima dodeljuje admin na stranici **Administracija → Korisnici**
(`/admin/users`): pri pravljenju korisnika ili kasnijom izmenom (`PUT /api/users/<id>/subjects`).
Oblasti unutar predmeta i banku pitanja nastavnik pravi u aplikaciji.

Lekcija pripada predmetu (`lessons.subject_id`) i može da ima oblast tog predmeta
(`lessons.area_id`, neobavezno). Student i nastavnik vide samo lekcije svojih predmeta, a
nastavnik dodaje, menja i briše samo lekcije predmeta koje predaje.

### Uvoz skupa pitanja iz JSON fajla

Programska pitanja (`reference_solution` i test primeri) ne mogu da se unesu kroz aplikaciju,
pa se ceo skup pitanja može uvesti alatom (iz `backend/`):

```bash
python tools/import_question_set.py tools/question_set_example.json          # probni rad, ništa ne upisuje
python tools/import_question_set.py tools/question_set_example.json --apply  # upis (prvo backup baze)
```

Fajl sadrži predmet (`name`, `code`), oblasti, pitanja i, opciono, referentni skup (ime i
`key` vrednosti pitanja). Pitanje ima oblast, tekst, `difficulty` (`lako`/`srednje`/`tesko`),
opciono `bloom_level` i `points`. Uz to ima ili `answers` sa `is_correct` (MC), ili
`reference_solution` sa `test_cases` (programsko), ili samo tekst (otvoreno). Primer je
`backend/tools/question_set_example.json`.

- Predmet (po kodu) i oblasti (po imenu) se prave ako ne postoje. Pitanja idu u banku
  (`exam_id` NULL).
- Pitanje sa istim tekstom u istom predmetu se preskače, pa je ponovno pokretanje bezbedno.
  Isto važi za referentni skup sa istim imenom.
- `reference_solution` se pre upisa pokreće nad svim test primerima (`code_executor`, isto kao
  mehanička provera objašnjenja). Ako neki primer padne, uvoz se prekida.
- Upis je u jednoj transakciji. Nastavnike predmetu dodeljuje admin u aplikaciji.

## 2. Backend

```bash
cd backend
python -m venv venv
venv\Scripts\activate            # Windows (Linux/macOS: source venv/bin/activate)
pip install -r requirements.txt
```

Napravite `backend/.env`. Fajl je u `.gitignore` i ne sme u repozitorijum:

```ini
JWT_SECRET_KEY=<dugačak nasumičan string>
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=
MYSQL_DATABASE=language_learning

# AI provajderi (potrebni za generisanje; testovi ne pozivaju prave modele, ali
# verify_experiment_runner i verify_set_generation traže da su ključevi za groq, gemini i openrouter upisani)
GROQ_API_KEY=<ključ>
GEMINI_API_KEY=<ključ>
OPENROUTER_API_KEY=<ključ>
MISTRAL_API_KEY=<ključ>
```

`JWT_SECRET_KEY` služi i za pseudonime ocenjivača u CSV izvozu. Ako se promeni,
promene se i heševi.

```bash
python app.py                    # http://127.0.0.1:5000
```

## 3. Frontend

```bash
cd frontend
npm install
npm run dev                      # http://localhost:5173 (/api se prosleđuje na 127.0.0.1:5000)
npm run build                    # produkcijski build u frontend/dist
```

## 4. Testovi

Komande se pokreću iz `backend/`. Na Windows konzoli prvo postavite `set PYTHONIOENCODING=utf-8`.
AI provajder je u testovima lažan, pa se pravi modeli nikad ne pozivaju.

### Na čistoj bazi (preporučeno; ne dira pravu bazu)

```bash
python tools/test_clean_db.py
```

Alat radi sledeće:

1. pravi praznu probnu bazu `language_learning_test` (ime mora da se završava na `_test`
   i ne sme već da postoji);
2. učitava `db/schema.sql` i `db/reference_data.sql`;
3. upisuje izmišljene podatke (`tools/seed_test_data.py`): ADMIN, nastavnika i studenta bez
   lozinke, dva predmeta, nekoliko pitanja, modele, promptove i par AI predloga;
4. pokreće sve `test_*` i `verify_*` testove nad probnom bazom;
5. na kraju briše probnu bazu.

`--keep` ostavlja probnu bazu radi pregleda. `--only verify_set_generation` pokreće samo
navedene testove, a `--verbose` ispisuje ceo izlaz testova koji su pali. Alat odbija
da radi nad bazom iz `.env`.

### Pojedinačno, nad bazom iz `.env`

**Unit testovi** ne traže bazu ni mrežu:

```bash
python tests/test_question_validation.py
python tests/test_edit_distance.py
python tests/test_question_similarity.py
python tests/test_generation_failures.py
python tests/test_agreement.py
python tests/test_analyze_experiment.py
```

**Integracioni testovi** (`verify_*`) rade nad bazom iz `.env` (osim `verify_ai_provider_retry`,
koji ne koristi bazu). Prave privremene podatke, na kraju ih brišu i proveravaju da je
broj redova isti kao pre.

Baza mora da ima sve migracije **i** osnovne podatke: bar jednog ADMIN-a, predmet
„Osnove programiranja“ sa nekoliko MC pitanja i jednim otvorenim pitanjem, pitanje iz
drugog predmeta, modele i promptove (uključujući arhivirane `mc-v2` / `open-v2` i bar jedan
prompt objašnjenja). Na
praznoj bazi zato koristite `tools/test_clean_db.py`.

```bash
python tests/verify_exam_security.py
python tests/verify_ai_blind_review.py
python tests/verify_ai_provider_retry.py
python tests/verify_question_labels.py
python tests/verify_experiment_runner.py
python tests/verify_edit_distance_duplicates.py
python tests/verify_generation_failures.py
python tests/verify_set_generation.py
python tests/verify_experiment_export.py
python tests/verify_validate_batch.py
python tests/verify_registration.py
python tests/verify_lessons_subject.py
python tests/verify_subjects_crud.py
python tests/verify_generate_explanation.py
python tests/verify_explanation_review.py
python tests/verify_second_rating_explanations.py
python tests/verify_experiment_runner_explanations.py
```

Svaki skript na kraju ispisuje zbir (`Ukupno: N, palo: 0` ili `N/N OK`). Ako nešto
padne, izlazni kod je različit od 0.

`verify_import_question_set.py` upisuje kroz `--apply`, pa radi samo nad probnom bazom
(`python tools/test_clean_db.py --only verify_import_question_set`). Nad bazom iz `.env` se preskače.
