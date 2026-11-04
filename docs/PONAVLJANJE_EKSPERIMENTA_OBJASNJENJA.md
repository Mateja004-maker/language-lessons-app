# Ponavljanje eksperimenta: generisanje objašnjenja

Ovo uputstvo pokriva samo objašnjenja i rešenja (Andrejev modul): kako se eksperiment
poređenja modela za objašnjenja ponavlja od početka do tabela. Za generisanje sličnih
pitanja važi [PONAVLJANJE_EKSPERIMENTA.md](PONAVLJANJE_EKSPERIMENTA.md).

Priprema baze, referentni skup i evaluaciona serija prave se istim koracima kao za
pitanja (odeljci 0, 1 i 2 tog dokumenta), pa se ovde ne prepisuju. Ovde su opisane samo
razlike. Sve komande se pokreću iz `backend/`. Na Windows konzoli prvo pokrenite
`set PYTHONIOENCODING=utf-8`.

## Šta je fiksirano (protokol)

**Modeli** (`backend/app.py`, `EXPLANATION_DEFAULT_MODELS`):

| Provajder | Model | `--models` |
|-----------|-------|-----------|
| groq | `openai/gpt-oss-20b` | `groq` |
| gemini | `gemini-3.6-flash` | `gemini` |
| openrouter | `nvidia/nemotron-3-super-120b-a12b:free` | `openrouter` |

Mistral (`mistral-small-latest`) postoji u kodu, ali nije u eksperimentu (vidi Poznata ograničenja).

**Verzija modela** (`EXPLANATION_MODEL_VERSIONS`) se upisuje u `ai_models.model_version`,
na primer `openai/gpt-oss-20b - provereno 2026-10-21` (openrouter ima kraći tekst, jer kolona
prima najviše 50 znakova). To je ručno proveren
identifikator modela sa datumom provere, a ne verzija iz API odgovora: `ai_provider.py` ne
vraća naziv ni verziju modela iz sirovog odgovora.

**Parametri:**

- temperatura 0.7;
- timeout, ponovni pokušaji posle mrežne greške, 429 ili 5xx i poštovanje `Retry-After` su
  isti kao za pitanja, jer oba modula zovu `ai_provider.generate`;
- posle odgovora u lošem formatu **nema** ponovnog zahteva (kod pitanja ima, `MAX_FORMAT_RETRIES = 1`).
  Zato je za objašnjenja `format_retries` uvek 0.

**Verzije prompta** (fajlovi u `backend/prompts/`, verzija je u prvom redu `{# version: … #}`):

| Režim | Vrsta pitanja | Prompt | Fajl |
|-------|---------------|--------|------|
| A (poznato rešenje → objašnjenje) | sve | `mode_a-v2` | `explanation_mode_a_v2.txt` |
| B (model sam rešava) | programski zadatak sa test primerima | `mode_b-v1` | `explanation_mode_b_v1.txt` |
| B | višestruki izbor (MC) | `mode_b_mc-v1` | `explanation_mode_b_mc_v1.txt` |
| B | otvoreno pitanje bez test primera | `mode_b_open-v1` | `explanation_mode_b_open_v1.txt` |

- Fajl bira `explanation_prompts._template_path(mode, question_type, has_test_cases)`. Vrsta
  pitanja (MC ili otvoreno) određuje se kao i za pitanja (`prompt_templates.detect_question_type`).
- Šta model dobija određuje `resolve_explanation_source` (`app.py`):
  - **režim A**: dobija poznato rešenje. `exam_questions.reference_solution` ima prioritet,
    a inače se kod MC pitanja sa tačno jednim tačnim odgovorom uzima taj odgovor (ponuđeni
    odgovori se dodaju tekstu zadatka). Pitanje bez poznatog rešenja ne može u režim A.
  - **režim B, MC**: dobija numerisanu listu ponuđenih odgovora, bez oznake tačnog, i bira broj (`selected_option`).
  - **režim B, programski zadatak ili otvoreno pitanje**: model sam piše rešenje (`solution`).
- Aplikacija pri prvoj upotrebi upisuje prompt u `ai_prompts` (`purpose = 'explanation'`).
  Run u `ai_generation_runs` nosi `purpose = 'explanation'`, `mode = 'mode_a' | 'mode_b'` i
  `prompt_id`, pa se uvek zna kojim režimom i kojom verzijom prompta je nastao.

**Mehanička provera tačnosti (samo režim B)** se radi odmah pri generisanju, po run-u, i
upisuje u `ai_generation_runs.accuracy_check_passed` i `accuracy_check_details`:

- MC: izabrani odgovor se poredi sa `exam_answers.is_correct`. Nevažeći izbor (van 1..broj odgovora) daje 0.
- programski zadatak: rešenje se pokreće nad `exam_question_test_cases` (`code_executor`,
  5 s po test primeru). Vrednost je 1 samo ako prođu svi primeri.
- otvoreno pitanje bez test primera: provera nije moguća, pa ostaje `NULL` („nije izvršena“).

**Pravila serije** (`tools/run_experiment.py` ih proverava pre svakog poziva,
`check_explanation_protocol`, i odbija pokretanje ako bi bila narušena):

- jedna serija = jedan režim objašnjenja (`mode_a` ili `mode_b`), bez run-ova pitanja;
- finalne serije režima A i B moraju da imaju isti referentni skup, inače pokretač prekida rad;
  isti skup ne znači i ista pitanja, jer režim A preskače pitanja bez poznatog rešenja;
- serija ne sme da meša modele (proverava se ime modela po provajderu) ni verzije prompta
  (očekivana verzija zavisi od vrste pitanja);
- redosled poziva, nastavak prekinutog pokretanja i zaustavljanje modela posle
  infrastrukturnih padova isti su kao za pitanja (PONAVLJANJE_EKSPERIMENTA.md, „Pravila serije“).

## Koraci

### 0–2. Priprema, referentni skup i evaluaciona serija

Kao u [PONAVLJANJE_EKSPERIMENTA.md](PONAVLJANJE_EKSPERIMENTA.md), odeljci 0, 1 i 2. Razlike:

- `ai_models` sme da ima više redova za isti model: stari run-ovi ostaju na starim redovima (npr.
  `model_version` NULL), a novi koriste red sa verzijom iz `EXPLANATION_MODEL_VERSIONS`. Bitno je da
  run-ovi jedne serije budu pod jednim redom po modelu (vidi Poznata ograničenja). Proverava se
  posle generisanja, a upit ne sme da vrati nijedan red:
  ```sql
  SELECT m.provider, m.model_name, COUNT(DISTINCT r.model_id)
  FROM ai_generation_runs r JOIN ai_models m ON m.id = r.model_id
  WHERE r.evaluation_batch_id = <id>
  GROUP BY m.provider, m.model_name HAVING COUNT(DISTINCT r.model_id) > 1;
  ```
- Za referentni skup režima A birajte pitanja sa poznatim rešenjem (`reference_solution` ili MC
  sa tačno jednim tačnim odgovorom). Ostala pokretač preskače.
- Za režim B formalnog eksperimenta referentni skup sme da sadrži **samo MC pitanja i programske
  zadatke sa test primerima**, jer samo za njih postoji mehanička provera tačnosti rešenja
  (eliminacioni kriterijum). Otvorena pitanja bez test primera se ne uključuju: provera bi za
  njih ostala „nije izvršena“, a ocena `tacnost_objasnjenja` ocenjuje objašnjenje, ne rešenje.
  Takva pitanja i dalje mogu da se koriste u aplikaciji van eksperimenta.
  Za njih postoji ručna ocena `tacnost_resenja` (tačno/netačno, vidi ispod), a `analyze_experiment.py`
  je izdvaja u `tabela_tacnost_rucna.csv` i `tabela_saglasnost_rucna.csv` (vidi „Izlaz analize“).
  Ručna ocena nije mehanička provera, pa se dve stope ne sabiraju.
- Za svaki režim objašnjenja pravi se posebna serija, odvojena i od serija pitanja.

### 3. Generisanje: `tools/run_experiment.py --task explanation`

Prvo suvi prolaz, koji samo ispisuje plan i ne poziva modele:

```bash
python tools/run_experiment.py --task explanation --explain-mode mode_a --batch 3 --reference-set 1 --models groq,gemini,openrouter --per-question 3 --dry-run
python tools/run_experiment.py --task explanation --explain-mode mode_b --batch 4 --reference-set 1 --models groq,gemini,openrouter --per-question 3 --dry-run
```

Zatim ista komanda bez `--dry-run`. Ovaj korak poziva prave modele i troši kvotu.

- `--explain-mode` je obavezan uz `--task explanation`.
- `--mode set`, `--group-size` i `--k` ne važe uz `--task explanation`; pokretač odbija takvu komandu.
- `--reference-set` je potreban samo pri prvom pokretanju, a `--max-calls K` radi isto kao za pitanja.
- **Režim A**: pitanja bez poznatog rešenja izbacuju se iz plana i na kraju se ispisuju kao
  „preskočeno (nema poznatog rešenja)“. Ako nijedno pitanje skupa ne može u režim A, pokretač ne počinje.
- **Režim B**: izveštaj po modelu dodatno broji mehaničku proveru: prošla / nije prošla / nije izvršena.
- U izveštaju je kolona „ok posle pon.“ za objašnjenja uvek 0, jer nema ponovnog zahteva posle lošeg formata.

Svaki predlog dobija status `predlog`. Studenti ga ne vide dok ga nastavnik ne odobri.

### 4. Ocenjivanje (slepo)

**Nastavnik koji odlučuje** (runda 1), u aplikaciji **AI objašnjenja** (`/ai/objasnjenja`,
`POST /api/ai-artifacts/explanation/<id>/review`):

- model je sakriven dok je predlog u statusu `predlog` (isto pravilo slepog pregleda kao kod pitanja);
- ocenjuje rubriku 1–5: tačnost objašnjenja, vernost (faithfulness), potpunost, pedagoška
  vrednost, jezička ispravnost;
- u režimu B bez mehaničke provere (`accuracy_check_passed` prazno, npr. otvoreno pitanje bez
  test primera) ocenjuje i `tacnost_resenja`: 0 = netačno, 1 = tačno. Ocena „netačno“ dozvoljava
  samo odbacivanje, kao neuspela mehanička provera. Drugi ocenjivač daje istu ocenu, bez odluke;
- donosi odluku: prihvaćeno / prihvaćeno uz izmenu / odbačeno;
- objašnjenja nemaju oznake težine i Blumovog nivoa ni proveru duplikata.

**Studentska ocena**, `POST /api/ai-artifacts/explanation/<id>/rate` (uloga STUDENT):

- samo za odobrena objašnjenja (inače 409), i samo student koji je završio to pitanje (inače 403);
- jedan student ocenjuje jedno objašnjenje najviše jednom (ponovni pokušaj daje 409);
- rubrika 1–5: korisnost, jasnoća, percepcija naučenog.

**Drugi ocenjivač** (runda 2), u aplikaciji **Druga ocena** (`/ai/druga-ocena`): isto kao za
pitanja. Uzorak je stabilan i obuhvata oko 30% predloga (`SECOND_RATING_SAMPLE = 0.30`), a
objašnjenja su u istom uzorku kao pitanja (`SECOND_RATING_ARTIFACT_TYPES`). Drugi ocenjivač
daje rubriku nastavnika, ali ne donosi odluku.

Kada je ocenjivanje gotovo, ADMIN zatvara seriju kao za pitanja
(`POST /api/evaluation-batches/<id>/close`).

### 5. Mehanička validacija serije: `tools/validate_batch.py`

```bash
python tools/validate_batch.py --batch 4
```

Za svaki sačuvan predlog objašnjenja alat ponovo pušta isti validator kao pri generisanju
(`validate_explanation_payload`): `explanation` nije prazan, u režimu B postoji `solution`
(programski zadatak ili otvoreno pitanje) ili `selected_option` (MC), a u režimu A nema
`solution`. Režim je iz run-a, a vrsta pitanja iz verzije šablona (`mode_b_mc-*` je MC).

- Proverava se i doslednost: run sa predlogom mora imati `validation_passed = 1`, a run
  objašnjenja najviše jedan predlog.
- Run-ovi bez predloga (padovi) se samo navode u rezimeu i ne validiraju se.
- Ispisuje PASS/FAIL po predlogu, a u rezimeu poseban red „predlozi objašnjenja“. Izlazni
  kodovi su isti kao za pitanja (0 = sve PASS, 1 = bar jedan FAIL).
- `accuracy_check_passed` se ovde **ne** računa ponovo: to je drugi nivo provere (sadržaj,
  ne format), upisuje se po run-u pri generisanju i ulazi u analizu (odeljak 6).

### 6. Izvoz CSV i analiza

Izvoz (tri CSV fajla) i pokretanje `tools/analyze_experiment.py` isti su kao u
[PONAVLJANJE_EKSPERIMENTA.md](PONAVLJANJE_EKSPERIMENTA.md), odeljci 6 i 7. Specifično za objašnjenja:

**CSV `artifacts`:**

- `mode` je `mode_a` ili `mode_b`, pa su modeli u analizi označeni sa `[mode_a]` ili `[mode_b]`;
- `accuracy_check_passed`: 1 / 0 / prazno (nije izvršena), samo u režimu B;
- `solution_source`: odakle je poznato rešenje u režimu A (`reference_solution` ili `mc_correct_answer`);
- `r1_*` i `r2_*` su kriterijumi nastavnika za objašnjenja (`tacnost_objasnjenja`, `vernost`,
  `potpunost`, `pedagoska_vrednost`, `jezicka_ispravnost`), a za režim B bez mehaničke provere
  i `tacnost_resenja` (0/1; za ostale predloge prazno);
- kolone težine i Blumovog nivoa (`model_*`, `reviewed_*`, `second_*`), `edit_distance*` i
  kolone duplikata su prazne.

**Izlaz analize:**

- `tabela_pozivi.csv`, `tabela_predlozi.csv`, `tabela_ocene.csv`, `tabela_raspodela_ocena.csv`
  i kapa i alfa za rubriku rade kao za pitanja. U `tabela_predlozi.csv` su kolone težine i
  Bluma nule, a u `tabela_saglasnost.csv` redovi za `difficulty` i `bloom_level` imaju
  `parova = 0`. To nije greška: objašnjenja nemaju te oznake.
- `tabela_tacnost.csv` (samo ako serija ima predloge režima B): po modelu `predloga`,
  `prosla`, `nije_prosla`, `nije_izvrsena` i
  `stopa_tacnosti = prosla / (prosla + nije_prosla)`. Neizvršene provere nisu u imeniocu.
  Ako nijedna provera nije izvršena, stopa je prazna. Ista tabela je i u `izvestaj.md`.
  Uz `--runs` ima još tri kolone: `bez_predloga` (model je odgovorio u lošem formatu, pa predlog
  nije nastao: `empty`, `invalid_json`, `schema`), `svih_pokusaja` (`predloga + bez_predloga`) i
  `stopa_od_svih = prosla / svih_pokusaja`. Padovi servisa (mreža, 4xx, 429, 5xx) nisu pokušaji,
  jer nisu greška modela i ponavljaju se. Bez `--runs` su ove kolone prazne.
- `tabela_tacnost_rucna.csv` (samo ako serija ima predloge režima B bez mehaničke provere,
  tj. sa praznim `accuracy_check_passed`): ručna ocena `tacnost_resenja` nastavnika koji
  odlučuje, po modelu `predloga`, `ocenjeno`, `tacno`, `netacno` i
  `stopa_tacnosti = tacno / ocenjeno`. Neocenjeni predlozi nisu u imeniocu. Ovi predlozi
  nisu ni u imeniocu `tabela_tacnost.csv`, pa se dve stope ne sabiraju.
- `tacnost_resenja` (0/1) nije u `tabela_ocene.csv`, `tabela_raspodela_ocena.csv` ni u
  `tabela_saglasnost.csv` (te tabele su za skalu 1–5). Njena saglasnost je u
  `tabela_saglasnost_rucna.csv` (kad postoji druga ocena): procenat slaganja i nominalna
  kapa za par nastavnik / prvi drugi ocenjivač, i nominalna alfa (uz `--evaluations` sa
  svim ocenjivačima).
- Ne mešati `stopa_tacnosti` sa „iz prve“ u `tabela_pozivi.csv`: „iz prve“ meri **format**
  odgovora, a `stopa_tacnosti` **sadržajnu** tačnost.

**Studentske ocene** (korisnost, jasnoća, percepcija naučenog) jesu u CSV-u `evaluations`
(`evaluator_role = STUDENT`), ali ih `analyze_experiment.py` **ne obrađuje**: tabele i kapa
koriste samo kriterijume nastavnika iz `r1_*` i `r2_*` kolona. Za studentske pokazatelje
koristite upit `db/queries/zbirno_po_modelu_objasnjenja.sql` direktno nad bazom (phpMyAdmin).
Za jednu seriju red sa `-- FILTER_EKSPERIMENT` zamenite sa `AND r.evaluation_batch_id = <id>`.
Upit daje:

- prosečne ocene nastavnika i studenata po kriterijumu i raspodelu studentske korisnosti (1–5);
- broj rizičnih slučajeva (korisnost ≥ 4, a tačnost objašnjenja ≤ 2: uverljivo, ali netačno);
- Pirsonovu korelaciju korisnosti i tačnosti;
- kontrolne kolone `pala_mehanicka_provera`, `prosla_mehanicka_provera` i `nije_izvrsena`,
  koje moraju da se slože sa `tabela_tacnost.csv`.

Upit grupiše po `ai_models.id`, a analiza po imenu modela. Ako postoji više redova u
`ai_models` za isti model, upit ih prikazuje odvojeno, a analiza zajedno.

## Poznata ograničenja

- **Mistral nije u eksperimentu.** Limit je 0 zahteva u minutu, potvrđeno na dva ključa i dva
  imena modela (i kod Anđe), i prijavljeno Mistral podršci. Treći model za poređenje je OpenRouter.
- **`format_retries` je za objašnjenja uvek 0.** Posle lošeg formata nema ponovnog zahteva,
  za razliku od pitanja (`MAX_FORMAT_RETRIES = 1`). Pokazatelji „iz prve“ i „posle ponavljanja“
  zato nisu direktno uporedivi između pitanja i objašnjenja. Za stare run-ove objašnjenja,
  nastale pre upisa vrste pada, ta polja jednom dopunjava
  `python tools/backfill_failure_type_explanations.py [--dry-run]`. Skripta upisuje samo
  `failure_type`, `first_attempt_passed` i `format_retries = 0` i ne dira run-ove pitanja.
- **Pokretač proverava samo ime modela, ne i `ai_models.model_version`.** Ako baza ima više
  redova za isti model sa različitom verzijom (na primer stari red sa `model_version = NULL`
  i nov sa `… - provereno 2026-10-21`), `run_experiment.py` to neće uhvatiti kao mešanje
  protokola. Takav je slučaj u probnoj seriji 1 (groq). Za pravi eksperiment (Faza 3)
  krenite od nove, čiste serije, ne menjajte tekst verzije tokom serije i proverite je upitom
  iz odeljka 0–2.

## Kontrolna lista

- [ ] Backup baze napravljen van repozitorijuma; testovi prolaze.
- [ ] Run-ovi serije su pod jednim redom `ai_models` po modelu (upit u odeljku 0–2).
- [ ] Referentni skup napravljen, a njegov id zapisan; za režim A pitanja imaju poznato rešenje.
- [ ] Za svaki režim (`mode_a`, `mode_b`) posebna serija; suvi prolaz pregledan (i spisak preskočenih pitanja).
- [ ] Generisanje završeno: izveštaj pokretača nema preostalih mesta.
- [ ] Sve odluke nastavnika donete; druga ocena na uzorku urađena.
- [ ] Studentske ocene prikupljene (posle odobravanja objašnjenja).
- [ ] Serija zatvorena; `validate_batch.py` za svaku seriju završava sa `UKUPNO: PASS`.
- [ ] Sva tri CSV izvoza sačuvana uz rad, zajedno sa verzijom koda (git commit hash); `analyze_experiment.py` pokrenut, a `tabela_tacnost.csv` postoji za režim B.
- [ ] `zbirno_po_modelu_objasnjenja.sql` pokrenut za seriju i rezultat sačuvan (studentski pokazatelji); kontrolne kolone se slažu sa `tabela_tacnost.csv`.
