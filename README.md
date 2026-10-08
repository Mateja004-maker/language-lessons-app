# Sistem za onlajn testiranje sa AI generisanjem pitanja

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
  Postupak je opisan u [docs/PONAVLJANJE_EKSPERIMENTA.md](docs/PONAVLJANJE_EKSPERIMENTA.md).

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
- Predmete (`subjects`) unesite ručno (phpMyAdmin). Dodelu predmeta korisnicima radi
  admin u aplikaciji.

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

# AI provajderi (potrebni samo za generisanje; testovi ih ne koriste)
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

**Unit testovi** ne traže bazu ni mrežu:

```bash
python tests/test_question_validation.py
python tests/test_edit_distance.py
python tests/test_question_similarity.py
python tests/test_generation_failures.py
python tests/test_agreement.py
python tests/test_analyze_experiment.py
```

**Integracioni testovi** (`verify_*`):

- traže bazu iz `.env`, sa svim migracijama (osim `verify_ai_provider_retry`, koji ne koristi bazu);
- prave privremene podatke, na kraju ih brišu i proveravaju da je broj redova isti kao pre;
- AI provajder je lažan, pa se pravi modeli nikad ne pozivaju.

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
```

Svaki skript na kraju ispisuje zbir (`Ukupno: N, palo: 0` ili `N/N OK`). Ako nešto
padne, izlazni kod je različit od 0.
