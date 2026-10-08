# Ponavljanje eksperimenta: generisanje sličnih pitanja

Ovo uputstvo opisuje kako se eksperiment poređenja modela ponavlja od početka do
tabela i grafikona. Sve komande se pokreću iz `backend/`, osim tamo gde piše drugačije.
Na Windows konzoli prvo pokrenite `set PYTHONIOENCODING=utf-8`.

## Šta je fiksirano (protokol)

**Modeli** (`backend/ai_provider.py`, `DEFAULT_MODELS`):

| Provajder | Model | `--models` |
|-----------|-------|-----------|
| groq | `openai/gpt-oss-20b` | `groq` |
| gemini | `gemini-3.6-flash` | `gemini` |
| openrouter | `nvidia/nemotron-3-super-120b-a12b:free` | `openrouter` |

Mistral (`mistral-small-latest`) postoji u kodu, ali nije u eksperimentu.

**Parametri:**

- temperatura 0.7;
- HTTP timeout 30 s;
- ponovni pokušaji provajdera posle mrežne greške, 429 ili 5xx: pauze 5 s i 15 s
  (`Retry-After` se poštuje, najviše 30 s);
- posle odgovora u lošem formatu (prazan, neispravan JSON, šema) model se pita
  još tačno jednom (`MAX_FORMAT_RETRIES = 1`).

**Verzije prompta** (fajlovi u `backend/prompts/`, verzija je u prvom redu `{# version: … #}`):

| Režim | `purpose` | Prompt | Fajl |
|-------|-----------|--------|------|
| jedno pitanje, višestruki izbor | `similar_question` | `mc-v3` | `similar_question_mc.txt` |
| jedno pitanje, otvoreno | `similar_question` | `open-v3` | `similar_question_open.txt` |
| skup pitanja (K novih iz grupe) | `similar_question_set` | `set-v1` | `similar_question_set.txt` |

- Aplikacija pri prvoj upotrebi upisuje prompt u `ai_prompts`. Run se vezuje za
  `prompt_id`, pa se uvek zna kojom verzijom je nastao.
- Prompti v3 i set-v1 traže od modela oznake `difficulty` (lako / srednje / tesko) i
  `bloom_level` (pamcenje … stvaranje). Validacija je stroga: nepoznata polja i
  nedostajuće oznake ne prolaze.
- Stare verzije `*_v2.txt` su arhiva i ne koriste se.

**Pravila serije** (`tools/run_experiment.py` ih proverava pre svakog poziva i odbija
pokretanje ako bi bila narušena):

- jedna serija = jedan referentni skup, jedan režim (single ili set), u režimu set
  jedna veličina grupe i jedno K;
- serija ne sme da meša modele ni verzije prompta: ako se model ili prompt promeni,
  pravi se nova serija;
- redosled poziva je uvek isti i naizmeničan po modelima
  (pokušaj 1: pitanje 1 → A, B, C; pitanje 2 → A, B, C; …);
- prekinuto pokretanje se nastavlja istom komandom, bez dupliranja.
  - Mesto je urađeno kada je model odgovorio, čak i u lošem formatu (to je rezultat).
  - Infrastrukturni padovi (mreža, 4xx, 429, 5xx) se beleže i ponavljaju pri sledećem pokretanju.
  - Posle 3 uzastopna infrastrukturna pada istog modela pokretač prestaje da poziva taj model.

## Koraci

### 0. Priprema

1. Baza po [README.md](../README.md) (`db/schema.sql`, `db/reference_data.sql`), sa API ključevima u `backend/.env`.
2. Pre eksperimenta napravite backup baze van repozitorijuma:
   `mysqldump -u root language_learning > ../backup_pre_eksperimenta.sql`
3. Proverite da svi testovi prolaze (README, odeljak 4). Testovi ne pozivaju prave modele.

### 1. Referentni skup pitanja

Referentni skup je zamrznut spisak izvornih pitanja jednog predmeta. Redosled je bitan.
Pravi ga ADMIN preko API-ja; za ovo nema ekrana u aplikaciji. Token se dobija iz
`POST /api/auth/login` (polje `access_token`).

```bash
curl -X POST http://127.0.0.1:5000/api/reference-sets \
  -H "Authorization: Bearer <ADMIN token>" -H "Content-Type: application/json" \
  -d '{"name": "Referentni skup v1", "subject_id": 1, "question_ids": [101, 102, 103]}'
```

- Pitanja moraju biti iz banke tog predmeta.
- Pregled: `GET /api/reference-sets` i `GET /api/reference-sets/<id>`.

### 2. Evaluaciona serija

```bash
curl -X POST http://127.0.0.1:5000/api/evaluation-batches \
  -H "Authorization: Bearer <ADMIN token>" -H "Content-Type: application/json" \
  -d '{"name": "Eksperiment pitanja v1", "description": "single, 3 modela, N=3", "is_final": true}'
```

Za svaki režim se pravi posebna serija.

### 3. Generisanje: `tools/run_experiment.py`

Prvo suvi prolaz, koji samo ispisuje plan i ne poziva modele:

```bash
# jedno pitanje po pozivu
python tools/run_experiment.py --batch 1 --reference-set 1 --models groq,gemini,openrouter --per-question 3 --dry-run

# skup: grupe od G pitanja skupa, K novih pitanja po pozivu
python tools/run_experiment.py --batch 2 --reference-set 1 --models groq,gemini,openrouter --per-question 1 --mode set --group-size 3 --k 3 --dry-run
```

Zatim ista komanda bez `--dry-run`. Ovaj korak poziva prave modele i troši kvotu.

- `--reference-set` je potreban samo pri prvom pokretanju: veže skup za seriju.
- `--max-calls K` ograničava broj poziva u jednom pokretanju (besplatne kvote). Ostatak se
  pokreće istom komandom kasnije.
- Na kraju se ispisuje izveštaj po modelu: ok iz prve, ok posle ponavljanja, loš format,
  prazan odgovor i bez odgovora po vrsti pada.

Svaki predlog dobija status `predlog`. Studenti ga ne vide dok ga nastavnik ne odobri.
Odobreno pitanje ide u banku, ne direktno u test.

### 4. Ocenjivanje (slepo)

**Nastavnik koji odlučuje** (runda 1), u aplikaciji **AI predlozi** (`/ai/predlozi`):

- model i provajder su sakriveni dok je predlog u statusu `predlog` i dok serija nije zatvorena;
- nastavnik **prvo** bira težinu i Blumov nivo, pa tek onda vidi oznake modela;
- zatim ocenjuje rubriku 1–5: stručna tačnost, odgovorljivost, relevantnost, kvalitet
  distraktora (MC), kalibracija težine, kognitivni nivo, originalnost, jezička ispravnost;
- na kraju donosi odluku: prihvaćeno / prihvaćeno uz izmenu / odbačeno.
  - Kod izmene se automatski računa razdaljina izmene.
  - Kod mogućeg duplikata (sličnost ≥ 0.90) nastavnik potvrđuje da li je duplikat.

**Drugi ocenjivač** (runda 2), u aplikaciji **Druga ocena** (`/ai/druga-ocena`):

- drugi nastavnik dobija stabilan uzorak od oko 30% predloga iz otvorenih serija svojih predmeta;
- vidi samo predlog, bez modela i bez odluke prvog nastavnika;
- daje oznake i rubriku, ali ne donosi odluku;
- na listi su samo predlozi koje taj nastavnik još nije ocenio, pa nastavnik koji je već odlučivao o predlogu ne dobija isti predlog za drugu ocenu.

Kada je ocenjivanje gotovo, ADMIN zatvara seriju. Tek tada model i odluke postaju vidljivi.

```bash
curl -X POST http://127.0.0.1:5000/api/evaluation-batches/1/close -H "Authorization: Bearer <ADMIN token>"
```

### 5. Izvoz CSV (samo ADMIN)

```bash
curl -o serija_1_artifacts.csv   -H "Authorization: Bearer <ADMIN token>" "http://127.0.0.1:5000/api/evaluation-batches/1/export.csv?kind=artifacts"
curl -o serija_1_runs.csv        -H "Authorization: Bearer <ADMIN token>" "http://127.0.0.1:5000/api/evaluation-batches/1/export.csv?kind=runs"
curl -o serija_1_evaluations.csv -H "Authorization: Bearer <ADMIN token>" "http://127.0.0.1:5000/api/evaluation-batches/1/export.csv?kind=evaluations"
```

Šta sadrži svaki izvoz:

- **`artifacts`**: jedan red po predlogu:
  - model, verzija prompta, režim i ulazna pitanja;
  - oznake modela, nastavnika i drugog ocenjivača;
  - rubrika runde 1 (`r1_*`) i runde 2 (`r2_*`);
  - odluka, razdaljina izmene i oznaka duplikata.
- **`runs`**: jedan red po pozivu modela: uspeh, vrsta pada, prolaz iz prve, ponovni zahtev, vreme, tokeni.
- **`evaluations`**: jedan red po pojedinačnoj oceni, za Kripendorfovu alfu sa svim ocenjivačima.

Korisnici su u izvozu samo pseudonimi (`u_` + HMAC heš), bez imena i emailova. Probni
run-ovi bez serije se ne izvoze.

Isti pokazatelji se mogu dobiti i direktno u phpMyAdmin-u, upitima iz
`db/queries/eksperiment_po_modelu.sql`. Red sa `-- FILTER_SERIJA` zamenite sa
`AND r.evaluation_batch_id = <id>`.

### 6. Analiza: `tools/analyze_experiment.py`

```bash
python tools/analyze_experiment.py --artifacts serija_1_artifacts.csv --runs serija_1_runs.csv --evaluations serija_1_evaluations.csv --out analiza_serija_1
```

U folderu `analiza_serija_1/` nastaju:

- `izvestaj.md`: sve tabele na jednom mestu;
- `tabela_pozivi.csv`: uspeh, vrste pada, prosečno i medijansko vreme po modelu i režimu;
- `tabela_predlozi.csv`: odluke u %, razdaljina izmene, duplikati, raspodela težine i
  Blumovih nivoa (model i nastavnik);
- `tabela_ocene.csv`: prosečna ocena po kriterijumu i modelu;
- `tabela_saglasnost.csv`, sa tri vrste mera:
  - kvadratno težinska Koenova kapa (nastavnik vs. drugi ocenjivač, po kriterijumu);
  - nominalna kapa za težinu i Blumov nivo;
  - Kripendorfova alfa (ordinalna za ocene, nominalna za kategorije), uz saglasnost modela sa nastavnikom;
- `grafikon_padovi.svg`, `grafikon_odluke.svg`, `grafikon_ocene.svg`.

Ako druge ocene nema, skripta to jasno ispiše, a ostatak analize uradi. Skripta ne
čita bazu, pa se brojevi u radu uvek reprodukuju iz istih CSV fajlova. Ne traži
dodatne biblioteke (samo standardni Python).

## Kontrolna lista

- [ ] Backup baze napravljen van repozitorijuma.
- [ ] Testovi prolaze.
- [ ] Referentni skup napravljen, a njegov id zapisan.
- [ ] Za svaki režim posebna serija; suvi prolaz pregledan.
- [ ] Generisanje završeno: izveštaj pokretača nema preostalih mesta.
- [ ] Sve odluke donete; druga ocena na uzorku urađena.
- [ ] Serija zatvorena.
- [ ] Sva tri CSV izvoza sačuvana uz rad, zajedno sa verzijom koda (git commit hash).
- [ ] `analyze_experiment.py` pokrenut; tabele i grafikoni preuzeti iz `--out` foldera.
