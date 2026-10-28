# Provera usklađenosti — Andrejev modul (rešenja i objašnjenja)

**Datum:** 2026-10-21
**Grana koja je proveravana:** `main`, commit `c022dfa7ca3b3dc27680e429167a70070270336b`
**Metod:** samo čitanje koda (grep/read), bez pokretanja aplikacije, testova ili baze. Gde je
za potvrdu potreban stvarni rad sistema (pokretanje, baza, izveštaj), stavka je obeležena
"ne mogu da potvrdim" umesto da se nagađa.

**Napomena o putanjama izvora:** tražena putanja `docs/zadatak/` nije postojala; sva četiri
izvorna dokumenta su pronađena direktno u `docs/`, tri sa sufiksom `(1)` u imenu
(`Zadatak-Andrej-Resenja-i-objasnjenja (1).md`, `Vodic-za-rad-sa-Claude-om (1).md`,
`Plan-integracije-i-objedinjeni-sistem (1).md`), a REZIME kao
`REZIME_ZA_ANDREJA_SPAJANJE_najnovije.md`. Potvrđeno je i da grana `feature/dopune-objasnjenja`
(koju REZIME najavljuje za "Rupe 1-7") **ne postoji** ni lokalno ni na `origin` — rad na tim
rupama očigledno još nije započet.

---

## 1. Zadatak-Andrej-Resenja-i-objasnjenja — odeljak 3 (arhitektura)

| # | Stavka | Status | Dokaz | Šta treba dodati |
|---|---|---|---|---|
| 3.1 | Sloj apstrakcije prema modelima (provider layer), zajednički sa Anđom | **urađeno** | `backend/ai_provider.py`, funkcija `generate(prompt, provider, options)`; identičan potpis pozvan na tri mesta u `app.py` (linije 3063, 4441, 5376) — dva Anđina poziva i Andrejev `generate_explanation` | — |
| 3.2 | Modul za objašnjenja (prima zadatak/rešenje, vraća strukturiran odgovor po režimu) | **delimično** | `app.py:4376-4557` (`generate_explanation`), `app.py:4306-4352` (`resolve_explanation_source`), `app.py:4355-4373` (`validate_explanation_payload`) — radi za: pitanja sa `reference_solution`, MC pitanja u režimu A, programska pitanja u režimu B | Režim B za MC pitanja i dugme/ruta za otvorena pitanja bez `reference_solution` nedostaju (= Rupa 1 i 2, vidi odeljak 4 ovog izveštaja) |
| 3.3 | Radni tok odobravanja (review workflow) — ništa ne ide studentu automatski | **urađeno** | `explanation_review.py` (status `predlog`→`prihvaceno`/`prihvaceno_izmena`/`odbaceno`, `app.py:4636-4677`); `get_question_explanation` (`app.py:4713-4739`) vraća samo artefakte sa statusom `prihvaceno`/`prihvaceno_izmena` | — |
| 3.4 | Dvostrani modul za evaluaciju (student + nastavnik) | **delimično** | Nastavnik: `explanation_review.py` (rubrika TEACHER, obavezna potpunost ocena, linije 152-159). Student: `explanation_rating.py:39-153` (`submit_student_rating`, rubrika STUDENT, jedna ocena po studentu). Obe strane rade i upisuju u zajedničku `ai_evaluations` | Drugi ocenjivač / saglasnost ocenjivača (vidi 6.2) ne postoji za objašnjenja — ruta `GET /api/ai/artifacts/second-rating` filtrira isključivo `artifact_type='question'` (`app.py:5172`) |
| 3.5 | Sloj za analitiku (svaka radnja se trajno beleži, pokazatelji se mogu izračunati) | **delimično** | `db/queries/zbirno_po_modelu_objasnjenja.sql` — broj pokušaja, neuspesi, mehanička provera, odluke nastavnika, prosečne ocene (nastavnik + student) po modelu | Nema vremena odziva/tokena u upitu, nema raspodele ocena, nema oznake rizičnih slučajeva, nema podrške u `tools/analyze_experiment.py` (grep ne nalazi ni jedan pomen `explanation`/`mode_a`/`mode_b` u tom fajlu) |
| 3.6 | Evidencija (model + verzija, prompt, parametri, sirov odgovor, ishod validacije) | **delimično** | `app.py:4483-4515` upisuje: `model_id`, `prompt_id`, `params_used` (uključuje `attempts`, `finish_reason`, `solution_source`), `raw_response`, `parsed_result`, `validation_passed/errors`, `accuracy_check_passed/details`, `response_time_ms`, `tokens_used` | `model_version` je uvek `NULL` (`ensure_ai_model(conn, provider=provider, model_name=model_name)` na liniji 4438 — parametar `model_version` se ne prosleđuje); `retry_count` je literalni `0` u INSERT-u (linija ~4490), stvarna vrednost je samo u `params_used.attempts` — ovo je Rupa 5 iz REZIME-a, još otvorena |

## 2. Zadatak — odeljak 4 (najmanje 3 modela)

| Stavka | Status | Dokaz | Napomena |
|---|---|---|---|
| Najmanje 3 besplatna modela ožičena kroz provider layer | **urađeno** | `EXPLANATION_DEFAULT_MODELS` (`app.py:4298-4303`): groq (`openai/gpt-oss-20b`), gemini (`gemini-3.6-flash`), mistral (`mistral-small-latest`), openrouter (`nvidia/nemotron-3-super-120b-a12b:free`) — 4 provajdera | Prema REZIME-u (odeljak "Zapažanja", tačka 7) Mistral vraća 429 (limit 0 zahteva/min) na dva ključa — **ne mogu da potvrdim** da li je to i danas tako, jer bi provera zahtevala stvaran pozив API-ja, što nije u obimu ovog (read-only) zadatka. Realno upotrebljiva 3 modela su groq/gemini/openrouter. |
| Dokumentovana tačna verzija i datum pristupa za svaki model | **nedostaje** | Pretraga `pristup`/`datum pristupa` po `*.md` ne pogađa nijedan fajl koji bi dokumentovao datum provere dostupnosti/verzije modela za Andrejev modul (jedini pogoci su u samim zahtevima, ne u evidenciji) | Treba kratka tabela (model, verzija, datum provere) po uzoru na `docs/PONAVLJANJE_EKSPERIMENTA.md`, koja za sada postoji samo za Anđin modul |

## 3. Zadatak — odeljak 5.1 i 5.2 (dimenzije ocenjivanja)

| # | Stavka | Status | Dokaz | Šta treba dodati |
|---|---|---|---|---|
| 5.1.1-3 | Studentske dimenzije: korisnost, jasnoća, percepcija naučenog | **urađeno** | `db/migration_ai_explanation_module.sql:24-29` (rubrika STUDENT, skala 1-5); upis/validacija u `explanation_rating.py:98-134` | — |
| 5.2.1 | Tačnost rešenja (režim B, eliminaciono, mehanička provera gde je moguće) | **urađeno** (ali samo za programske zadatke) | `app.py:4462-4481` poziva `code_executor.run_against_test_cases`; `explanation_review.py:102-109` tvrdo blokira `approve`/`edit` kad `accuracy_check_passed == 0` | Pošto MC u režimu B nije podržan (Rupa 1), mehanička provera trenutno postoji samo za programske zadatke — kad se MC za režim B uvede, treba i mehanička provera "izabrani odgovor je is_correct" (REZIME, Rupa 1) |
| 5.2.2-6 | Tačnost objašnjenja, vernost, potpunost, pedagoška vrednost, jezička ispravnost | **urađeno** | `db/migration_ai_explanation_module.sql:36-43` (5 TEACHER dimenzija, skala 1-5); `explanation_review.py:121-159` zahteva tačno svih 5 za `approve`/`edit` | — |
| 5.2 | Oznaka rizičnog slučaja (visoka studentska korisnost + niska nastavnička tačnost) | **nedostaje** | Pretraga `rizi\|risk\|mismatch` po `backend/` i `db/` ne pogađa nijedan fajl vezan za ovu logiku (jedini pogoci su nepovezani: `code_executor.py`, `verify_generation_failures.py`) | Treba definisati prag (npr. studentski `korisnost` ≥4 i nastavnički `tacnost_objasnjenja` ≤2), izračunati ga (upit ili ruta) i prikazati ga nastavniku — ovo je Rupa 4 iz REZIME-a |

## 4. Zadatak — odeljak 6.1 i 6.2 (podaci i pokazatelji)

| # | Stavka | Status | Dokaz | Šta treba dodati |
|---|---|---|---|---|
| 6.1 provenance | model id/verzija, verzija prompta, režim, parametri, vreme | **delimično** | `model_id`, `prompt_id`, `mode`, `params_used`, `created_at` se upisuju (`app.py:4483-4515`) | `model_version` je uvek `NULL` (vidi 3.6) |
| 6.1 ulaz/izlaz | referenca na zadatak, sirov odgovor, isparsiran rezultat, ishod validacije, mehanička provera (rež. B) | **urađeno** | iste linije — `source_question_id`, `raw_response`, `parsed_result`, `validation_passed/errors`, `accuracy_check_passed/details` | — |
| 6.1 tehnički | vreme odziva, tokeni, broj ponavljanja | **delimično** | `response_time_ms`, `tokens_used` se upisuju; broj ponavljanja postoji samo kao `params_used.attempts` (JSON), ne kao vlastita kolona (`retry_count` je hardkodiran 0) | Upisati stvarni `retry_count` u kolonu umesto literalnog 0 |
| 6.1 studentska evaluacija | anonimizovan id, ocene, komentar | **delimično** | Ocene i komentar: `explanation_rating.py:136-148`. Id: `evaluator_id` je **stvarni** `student_id`, nije anonimizovan pri upisu (anonimizacija se radi samo pri CSV izvozu, funkcijom `anonymize_user`, koja se uopšte i ne koristi u izvozu ocena objašnjenja — vidi 6.2) | Ovo je Rupa 5 (treći deo) iz REZIME-a — i dalje otvorena |
| 6.1 nastavnička evaluacija | id ocenjivača, ocene po 5.2, odluka, izmenjeni tekst | **urađeno** | `explanation_review.py:163-191` (`reviewed_by`, ocene po dimenziji, `new_status`, `edited_text`) | — |
| 6.2 | Tačnost rešenja u režimu B (udeo tačnih) po modelu | **urađeno** | `db/queries/zbirno_po_modelu_objasnjenja.sql:31` (`pala_mehanicka_provera`) | — |
| 6.2 | Prosečne nastavničke ocene po dimenziji/modelu/režimu | **delimično** | Ista datoteka, linije 46-50 — prosek po dimenziji i modelu, **ali ne i po režimu** (mode_a/mode_b nije u `GROUP BY`, upit grupiše samo po `model_id`) | Dodati `mode` u grupisanje da bi poređenje bilo odvojeno po režimu kako zadatak traži |
| 6.2 | Prosečne studentske ocene i njihova raspodela | **delimično** | Prosek postoji (linije 52-54); **raspodela ne postoji** nigde (nema upita ni koda koji računa histogram ocena) | Rupa 6 iz REZIME-a — dodati upit/izveštaj za raspodelu |
| 6.2 | Neslaganje perspektiva (rizični slučajevi) i korelacija | **nedostaje** | Vidi 5.2 — oznaka ne postoji, pa ni korelacija ne može postojati | Zavisi od prethodne stavke (oznaka rizika) |
| 6.2 | Stopa formalne ispravnosti iz prve i stopa odobravanja | **delimično** | Stopa odobravanja: urađeno (`prihvaceno`/`prihvaceno_izmena`/`odbaceno`/`na_cekanju` u istom upitu). Formalna ispravnost **iz prve** (bez ponavljanja): ne postoji — `neuspeli_pokusaji` broji sve neuspehe, ne razlikuje prvi pokušaj od pokušaja posle ponavljanja (nema `first_attempt_passed`/`format_retries` kolona kod objašnjenja, za razliku od pitanja koja ih imaju od migracije 17) | Rupa 6 iz REZIME-a |
| 6.2 | Tehnički pokazatelji (vreme odziva, stabilnost, limiti) | **nedostaje** | `response_time_ms`/`tokens_used` postoje u bazi (vidi 6.1) ali se ne agregiraju nigde za objašnjenja — nema ih u `zbirno_po_modelu_objasnjenja.sql` ni u `analyze_experiment.py` | Rupa 6 iz REZIME-a |
| 6.2 | Saglasnost ocenjivača (Cohen kappa/Krippendorff alfa) | **nedostaje** | `agreement.py` postoji i radi (ima testove u `backend/tests/test_agreement.py`), ali podaci za drugog ocenjivača postoje samo za pitanja — `GET /api/ai/artifacts/second-rating` filtrira `WHERE a.artifact_type = %s` sa `ARTIFACT_TYPE_QUESTION` (`app.py:5172`) | Dodatna rupa, nije u originalnoj listi od 7: treba proširiti drugi-ocenjivač mehanizam i na `artifact_type='explanation'` da bi `agreement.py` imao šta da računa za ovaj modul |

## 5. Zadatak — odeljak 7 (metodologija evaluacije)

| Stavka | Status | Dokaz | Šta treba dodati |
|---|---|---|---|
| Referentni skup 20-30 zadataka, isti za sve modele i oba režima | **nedostaje** | U bazi/seedu postoji samo jedno programsko pitanje sa `reference_solution`+test primerima (`db/seed_sample_programming_task.sql`, pitanje #103) — ovo je Rupa 7 iz REZIME-a, i dalje tačna | Potrebno je 20-30 zadataka sa referentnim rešenjima/test primerima |
| Identičan protokol (isti promptovi/podešavanja, isti broj pokušaja po modelu) | **delimično** | Promptovi su zamrznuti i verzionisani (`backend/prompts/explanation_mode_a_v1.txt`, `explanation_mode_b_v1.txt`); retry-politika je zajednička i deterministička (`ai_provider.py`, `RETRY_PAUSES_S`) | Ne postoji skripta analogna `tools/run_experiment.py` koja bi sistematski prošla ceo referentni skup × sve modele × oba režima za objašnjenja — generisanje je trenutno samo "jedan poziv iz UI-ja po pitanju". Grep za `explanation`/`mode_a`/`mode_b` u `backend/tools/run_experiment.py` ne daje pogodak. |
| Slepo ocenjivanje (ocenjivač ne zna model) | **urađeno** | `app.py:4588-4590` (`hide_while_pending`, `blind_review_order`) u `list_explanation_artifacts`; testirano u `backend/tests/verify_ai_blind_review.py:199-232` (uključuje rutu `/api/ai-artifacts/explanation`) | — |
| Tehničke karakteristike (vreme odziva, % neispravnog formata, limiti, praktičnost) | **delimično** | Podaci se upisuju po pozivu (vidi 6.1); agregacija za objašnjenja ne postoji (vidi 6.2) | Isto kao 6.2 tehnički pokazatelji |

## 6. Zadatak — odeljak 8 (obezbeđivanje ispravnosti rešenja)

| Stavka | Status | Dokaz | Šta treba dodati |
|---|---|---|---|
| Automatska validaciona skripta sa PASS/FAIL za strukturu odgovora | **delimično** | Validacija postoji i radi inline, pri svakom pozivu (`validate_explanation_payload`, `app.py:4355-4373`, upisuje `validation_passed` 1/0) | Nema **samostalne, ponovo-pokretljive** skripte kao `tools/validate_batch.py` koja bi retroaktivno PASS/FAIL validirala celu seriju objašnjenja — taj postojeći alat **eksplicitno preskače** `artifact_type != 'question'` (`validate_batch.py:17,59-60`, komentar: "Predlozi koji nisu pitanja (npr. objašnjenja) se preskaču") |
| Automatski testovi koji izvršavaju generisana rešenja (programski zadaci) | **urađeno** | `code_executor.run_against_test_cases` (pozvano iz `app.py:4477-4481`); izolacija procesa i ograničenja dokumentovana u REZIME-u, smoke test u `backend/smoke_test_code_executor.py` | Pošto postoji samo 1 programsko pitanje sa test primerima, ovo je u praksi provereno na jednom slučaju — vidi odeljak 5 ("20-30 zadataka") |
| Testiranje graničnih slučajeva (nevalidan odgovor, nedostupan servis, limit) | **delimično** | Mrežne greške/429/5xx: `ai_provider.py` (`_post_with_retry`, retry+backoff), testirano u `backend/tests/verify_ai_provider_retry.py` — ali taj test **ne pominje** `generate_explanation`/`EXPLANATION_DEFAULT_MODELS` nigde (provereno grep-om), pa pokriva samo zajednički `ai_provider.py`, ne i ponašanje Andrejeve rute kad dođe do greške | Dodati test koji direktno pogađa `generate-explanation` rutu sa simuliranim neuspehom i proveri 422 + upisan run (po uzoru na ono što je REZIME ručno proverio, ali kao automatski test) |
| CSV izvoz iz kog se generišu tabele/grafikoni | **delimično** | Mehanizam postoji i zajednički je: `GET /api/evaluation-batches/<id>/export.csv?kind=artifacts|runs|evaluations` (`app.py:5709-5741`), `_export_evaluations` (linija 5666) uključuje i STUDENT ocene objašnjenja | `_export_artifacts` (linija 5554) **ne selektuje** `r.mode` niti `accuracy_check_passed`/`solution_source` — kolone specifične za Andrejev modul nisu dodate u izvoz, tačno kako REZIME (9. oktobar) kaže: "Dodaj svoje kolone u taj izvoz" — ovo je (deo) Rupe 6 |
| Ponovljivost eksperimenta na osnovu dokumentacije | **nedostaje** | `docs/PONAVLJANJE_EKSPERIMENTA.md` postoji, ali pokriva **isključivo** Anđin modul (generisanje pitanja) — nijedan pomen `explanation`/`mode_a`/`mode_b` u tom fajlu | Potreban je analogni odeljak/dokument za ponavljanje Andrejevog eksperimenta (referentni skup, serija, redosled poziva modelima, komande) |

---

## 7. Vodič za rad sa Claude-om — odeljak 8 (kontrolna lista pre predaje)

| # | Stavka | Status | Dokaz / razlog |
|---|---|---|---|
| 1 | Sistem se podiže i svi testovi prolaze na čistom okruženju | **ne mogu da potvrdim** | Zahteva stvarno pokretanje (`tools/test_clean_db.py` pravi i briše probnu bazu) — van obima ovog read-only pregleda. Mehanizam postoji (`test_clean_db.py` automatski pokuplja sve `tests/test_*.py` i `tests/verify_*.py` glob-om, linija 151) i uključuje testove za oba modula, ali ga nisam pokretao. |
| 2 | Validaciona skripta prolazi (PASS) nad konačnim skupom generisanih rezultata | **nedostaje** | Nema ni konačnog skupa (vidi odeljak 5 — nema 20-30 zadataka, nema formalne evaluacione serije za objašnjenja), ni skripte koja bi ga validirala (`validate_batch.py` eksplicitno preskače objašnjenja) |
| 3 | Svi brojevi u tekstu/tabelama/figurama iz iste izvorne datoteke | **ne mogu da potvrdim** | Nije pronađen nijedan rad/izveštaj (tekst rada, tabele, grafici) za Andrejev modul u repozitorijumu — nema šta da se uporedi |
| 4 | Sve reference i tvrdnje o modelima provereне sa datumom pristupa | **nedostaje** | Vidi odeljak 2 ovog izveštaja — nijedan fajl ne dokumentuje datum provere modela za ovaj modul |
| 5 | `CLAUDE.md` odražava stvarno stanje projekta | **delimično** | `CLAUDE.md` postoji, aktuelan je i tačan za ono što opisuje (npr. odeljak "AI modul" tačno navodi da "Tačku F (retry_count/response_model/model_version) radi Andrejeva grana. Ne dirati je ovde." — što se slaže sa nalazom da je to i dalje `NULL`/0 na `main`-u). Ne nabraja, međutim, eksplicitno preostalih 7 rupa iz REZIME-a kao otvorenu listu (samo jednu od njih, posredno) | Dopuniti `CLAUDE.md` kratkim odeljkom "Otvoreno — Andrejev modul" koji nabraja tačno ono što ovaj izveštaj potvrđuje kao nedostajuće, da bi i bez čitanja REZIME-a bilo jasno šta nije gotovo |

## 8. Plan integracije i objedinjeni sistem — odeljak 6 (kontrolna lista za objedinjavanje)

| # | Stavka | Status | Dokaz |
|---|---|---|---|
| 1 | Sloj apstrakcije prema modelima jedinstven, oba modula ga koriste isto | **urađeno** | Vidi odeljak 1, stavka 3.1 — `ai_provider.generate(prompt, provider, options)` pozvan identično sa oba modula |
| 2 | Model podataka zajednički, bez dupliranih/nesaglasnih šema | **urađeno** | Zajedničke tabele `ai_models`, `ai_prompts`, `ai_generation_runs`, `ai_generated_artifacts`, `ai_rubric_definitions`, `ai_evaluations` (`db/migration_ai_generation_base_VERIFIED.sql`); Andrejeve kolone (`mode`, `accuracy_check_*`, `evaluation_batch_id`) su aditivne, NULL za Anđine redove (`migration_ai_explanation_module.sql`, komentar linije 8-12) |
| 3 | Radni tok odobravanja usaglašen za obe vrste sadržaja | **delimično** | Status-vokabular (`predlog`/`prihvaceno`/`prihvaceno_izmena`/`odbaceno`) je identičan i usaglašen (commit `047374a`). Razlika: Anđin pregled pitanja ograničava listu po predmetima koje nastavnik predaje (`get_user_subject_ids`), a Andrejev `list_explanation_artifacts` (`app.py:4566-4591`) **ne filtrira po predmetu uopšte** — nastavnik vidi predloge objašnjenja iz svih predmeta, ne samo svojih. Ovo je otvoreno pitanje iz REZIME-a ("Dopuna 10. oktobar") koje Andrej treba da zatvori. |
| 4 | Objedinjena aplikacija se podiže iz čistog okruženja, svi testovi (pojedinačni i objedinjeni) prolaze | **ne mogu da potvrdim** | Isto kao odeljak 7, stavka 1 — mehanizam (`test_clean_db.py`) postoji i objedinjen je, ali nije pokretan u ovoj proveri |
| 5 | Obe funkcionalnosti rade istovremeno bez međusobnog ometanja | **delimično** | REZIME dokumentuje ručnu, jednokratnu proveru oba toka (A i B) kroz pravi browser posle spajanja (odeljak "Šta je posle spajanja provereno"), i rute se ne preklapaju (`/api/ai/artifacts...` vs `/api/ai-artifacts/explanation...`, potvrđeno grep-om — nema dupliranog imena rute/putanje). To je jednokratna ručna provera, a ne automatski regresioni test koji bi ovo garantovao trajno. |
| 6 | Izveštaji se mogu generisati nad objedinjenim podacima iz celog sistema | **delimično** | `db/queries/zbirno_po_modelu_objasnjenja.sql` i `zbirno_po_modelu_pitanja.sql` postoje kao paralelni, ali odvojeni upiti (ne postoji jedan izveštaj koji bi, npr., poredio modele kroz oba modula zajedno); `analyze_experiment.py` (skripta za grafikone) pokriva samo pitanja |
| 7 | Dokumentacija (`CLAUDE.md`) opisuje objedinjeni sistem i pokretanje | **urađeno** | `CLAUDE.md` opisuje oba modula (Anđa i Andrej), zajedničku infrastrukturu (provider layer, AI tabele), komande za pokretanje backend/frontend i testova | — |

---

## 9. REZIME_ZA_ANDREJA_SPAJANJE — status "Rupa 1-7" (od 7. oktobra), potvrđeno na `main` (c022dfa)

| # | Rupa | Status danas | Dokaz |
|---|---|---|---|
| 1 | Režim B za MC pitanja (backend vraća 400) | **nedostaje — i dalje tačno** | `resolve_explanation_source` (`app.py:4326-4329`) i dalje vraća `{"error": "Rezim B nije podrzan za MC pitanja"}` za `mode_b` + MC; frontend (`SubjectAreasView.vue:717,721-722`) onemogućava radio-dugme za režim B kad je pitanje MC |
| 2 | Dugme "Generiši objašnjenje" na svakom pitanju (nedostaje za otvorena pitanja bez `reference_solution`) | **nedostaje — i dalje tačno** | `canExplain(question)` (`SubjectAreasView.vue:344-346`): `return question.answer_count > 0 || question.has_reference_solution` — otvoreno pitanje bez referentnog rešenja i bez ponuđenih odgovora nema dugme |
| 3 | Nastavnička ocena "tačnost rešenja" u režimu B (rubrika 12-16 ne postoji, treba da blokira odobravanje pri ≤2) | **rešeno drugačijim putem (namerna odluka), ne onako kako je rupa opisana** | Rubrika kao Likert-stavka za nastavnika **ne postoji** (`migration_ai_explanation_module.sql:31-34`, eksplicitan komentar: "'Tačnost rešenja' NIJE ovde — eliminaciona je i proverava se MEHANIČKI"). Umesto toga, `explanation_review.py:102-109` tvrdo blokira `approve`/`edit` kad mehanička provera (`accuracy_check_passed`) nije prošla. Ovo zadovoljava slovo zadatka (5.2.1: "proverava se mehanički gde god je moguće"), ali razlikuje se od onoga što je rupa tražila (manuelna ocena + prag ≤2) — vredno je da Andrej eksplicitno potvrdi da je ovo prihvatljivo tumačenje za njegov rad, pošto mehanička provera ne postoji za MC (dok Rupa 1 nije rešena) |
| 4 | Oznaka rizičnih slučajeva (visoka korisnost / niska tačnost) | **nedostaje — i dalje tačno** | Nema pogotka za `rizi`/`risk`/`mismatch` nigde u `backend/` ili `db/` vezano za ovu logiku |
| 5 | Beleženje: `model_version` uvek NULL, `retry_count` uvek 0, student se beleži stvarnim `user_id` | **nedostaje — i dalje tačno, sve tri tačke** | `model_version`: `ensure_ai_model(conn, provider=provider, model_name=model_name)` (`app.py:4438`) bez trećeg argumenta. `retry_count`: literalni `0` u `INSERT INTO ai_generation_runs` (`app.py`, VALUES red oko linije 4490). Student: `explanation_rating.py:146` upisuje `student_id` direktno kao `evaluator_id` |
| 6 | Pokazatelji: nema CSV izvoza, raspodele studentskih ocena, stope formalne ispravnosti iz prve, vremena odziva u upitima | **delimično — CSV mehanizam se u međuvremenu pojavio (zajednički, Anđin), ali bez Andrejevih kolona; ostalo i dalje nedostaje** | CSV: `app.py:5709-5741` sada postoji (dodato nakon 7. oktobra), ali `_export_artifacts` ne izvozi `mode`/`accuracy_check_passed`. Raspodela, stopa "iz prve" i vreme odziva: i dalje nigde agregirani za objašnjenja (vidi odeljak 4 ovog izveštaja, stavke 6.2) |
| 7 | Programskih pitanja u bazi ima samo jedno (#103); treba 20-30 sa `reference_solution` i test primerima | **nedostaje — i dalje tačno** | Jedini fajl sa seed podacima je `db/seed_sample_programming_task.sql` — sadrži tačno 1 `INSERT INTO exam_questions` i 1 `INSERT INTO exam_question_test_cases` (potvrđeno brojanjem) |

**Dodatna napomena van liste od 7:** grana `feature/dopune-objasnjenja`, koju REZIME (10. oktobar) najavljuje kao mesto gde Andrej treba da radi na ovim rupama, **ne postoji** — ni lokalno, ni na `origin` (`git branch -a` prikazuje samo `main`, `feature/resenja-objasnjenja` i Anđine/zajedničke grane). Ovo znači da nijedna od 7 rupa nije ni započeta u posebnoj grani; sve navedeno gore je trenutno stanje na `main`-u.

---

## Rezime za Andreja — šta prvo

Redosled koji minimizuje rizik i poštuje zavisnosti između stavki:

1. **Rupa 5 (beleženje)** — najjeftinije za popraviti, nema zavisnosti od ostalog: prosledi `model_version` u `ensure_ai_model`, upiši stvarni `retry_count` umesto `0`.
2. **Rupa 1 (MC u režimu B)** + mehanička provera za MC (izabrani odgovor `is_correct`) — otvara i Rupu 2 delom (dugme se može proširiti istom izmenom logike `canExplain`).
3. **Rupa 7 (20-30 programskih pitanja)** — preduslov za bilo kakvu stvarnu evaluaciju režima B; bez ovoga odeljak 7 i 8 zadatka ne mogu ni teorijski biti zadovoljeni.
4. **Oznaka rizika (5.2/6.2)** i **raspodela/stopa iz prve/vreme odziva (6.2)** — zavise jedni od drugih i od toga da prvo postoji dovoljno podataka (tačka 3).
5. **CSV kolone, `run_experiment.py` podrška za objašnjenja, `PONAVLJANJE_EKSPERIMENTA`-ekvivalent** — poslednje, kad je protokol već stabilan, jer se inače piše dokumentacija za nešto što će se još menjati.
6. Sitnije stvari usput: filter po predmetu na nastavničkom pregledu (Plan 6.3), `jinja2` u `requirements.txt`.
