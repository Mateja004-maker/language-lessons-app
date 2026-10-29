# Provera usklađenosti — Andrejev modul (rešenja i objašnjenja), ponovljena

**Datum:** 2026-10-29
**Grana koja je proveravana:** `feature/dopune-objasnjenja`, commit `9149c40`
**Prethodna provera:** [provera_uskladjenosti_2026-10-21.md](provera_uskladjenosti_2026-10-21.md) (`main`, `c022dfa`)
**Metod:** isti kao u prethodnoj proveri: čitanje koda, uz upite nad bazom samo za čitanje. Izvori:
`docs/Zadatak-Andrej-Resenja-i-objasnjenja.md`, `docs/Vodic-za-rad-sa-Claude-om.md`,
`docs/Plan-integracije-i-objedinjeni-sistem.md` i `docs/REZIME_ZA_ANDREJA_SPAJANJE_najnovije.md` (Rupe 1–7).
Brojevi redova su iz `9149c40`.

---

## 1. Stavke iz prethodne provere (c022dfa): stanje sada

| Stavka iz prethodne provere | Status sada | Dokaz |
|---|---|---|
| Rupa 1: Režim B za MC | **pokriveno** | `resolve_explanation_source` (`app.py:4343`) šalje numerisanu listu bez tačnog odgovora; mehanička provera `chosen["is_correct"]` (`app.py:4547`). Testirano u `verify_generate_explanation.py:185`. |
| Rupa 2: dugme na svakom pitanju | **pokriveno, ali otvorilo novu rupu** (nalaz 1) | `281d78c` (opšti šablon `mode_b_open-v1`), `93bcc2a` (frontend) |
| Rupa 3: nastavnička ocena tačnosti rešenja | **delimično** | Ne postoji kao kriterijum rubrike. Zamenjena je tvrdom blokadom kada je `accuracy_check_passed == 0` (`explanation_review.py:116`). Ne pokriva slučaj `NULL` (nalaz 1). |
| Rupa 4: rizični slučajevi | **delimično** | Postoje samo kao zbir po modelu u SQL-u (`per_model_risk`, `broj_rizicnih_slucajeva`, korelacija). Pojedinačni predlog se nigde ne označava: nema ga ni u UI-ju, ni u CSV-u, ni u `analyze_experiment.py`. |
| Rupa 5: beleženje | **pokriveno, uz jednu grešku** | `model_version` se prosleđuje (`app.py:4487`). Kolona `retry_count` dobija `result.get("attempts")` (`app.py:4605`), a to je broj pokušaja, ne ponavljanja: run uspešan iz prve ima `retry_count = 1`. Studentski id je pravi u bazi (potreban za „jedna ocena po studentu“ i proveru da je student završio pitanje), a u izvozu je HMAC pseudonim (`anonymize_user`). |
| Rupa 6: pokazatelji | **pokriveno** | Raspodela korisnosti, stopa iz prve, formalna ispravnost, vreme odziva i grupisanje po režimu u `zbirno_po_modelu_objasnjenja.sql` (`980f691`); CSV kolone (`455d503`). |
| Rupa 7: 20–30 zadataka | **i dalje otvoreno** | U bazi: 1 pitanje sa `reference_solution`, 1 sa test primerima, 51 MC pitanje sa tačno jednim tačnim odgovorom. `reference_sets` je prazna. |
| 3.4 / 6.2: drugi ocenjivač i saglasnost | **pokriveno** | `SECOND_RATING_ARTIFACT_TYPES` (`app.py:5220`), `verify_second_rating_explanations` 22/22; kapa i alfa u `analyze_experiment.py` |
| Model i datum provere (Zadatak 4) | **delimično** | `EXPLANATION_MODEL_VERSIONS` je ime modela sa datumom provere. Limiti besplatnih nivoa nisu zapisani ni za jedan model. |
| Protokolna skripta (7.2) | **pokriveno** | `run_experiment.py --task explanation` (`8a6a489`), `verify_experiment_runner_explanations` 10/10 |
| Granični slučajevi (8.3) | **pokriveno** | Kroz Andrejevu rutu: nevalidan JSON, šema, 401 (`verify_generate_explanation.py:191-198`); 429 kroz pokretač (`verify_experiment_runner_explanations.py:131`); mreža i 5xx u zajedničkom `verify_ai_provider_retry`. |
| CSV kolone i dokument reproducibilnosti (8.4, 8.5) | **pokriveno** | `455d503`, `d01670e`, `9149c40` |
| Validaciona skripta PASS/FAIL (8.1; Vodič 8.2) | **delimično** | Vidi nalaz 4. |
| Filter po predmetu (Plan 6.3) | **pokriveno** | Lista `app.py:4710`, detalj `4747`, odluka `4811` (Propust 1) |
| `jinja2` u `requirements.txt` | **pokriveno** | `a3f9c2e` |
| CLAUDE.md ažuran (Vodič 8.5) | **nije ažurno** | Vidi nalaz 6. |

## 2. Da li su izmene posle prethodne provere zatvorile ono što su trebale

- **Drugi ocenjivač:** zatvoreno. Prikazuje mehaničku proveru (`AiSecondRatingView.vue:173`). Isti korisnik ne može i da oceni i da odluči (`explanation_review.py:104`).
- **`run_experiment.py`:** zatvoreno. Jedina nova slabost: proverava se ime modela, a ne `model_version`. Dokumentovano je, a u probnoj seriji 1 već postoje dva reda za groq.
- **`analyze_experiment.py` / `tabela_tacnost.csv`:** zatvoreno za mehaničku tačnost. Predlozi sa `NULL` su van imenioca, pa model nema nikakvu meru tačnosti za otvorena pitanja bez test primera (nalaz 1).
- **PageHeader / dugmići:** samo izgled, bez funkcionalnog uticaja.
- **CSV kolone:** zatvoreno.
- **Rupa 2 (`281d78c`)** je otvorila nalaz 1, a **Rupa 5 (`d29dc4d`)** nalaz 5.

## 3. Lanac Režima B: „tačnost je prvi i eliminacioni kriterijum“

| Karika | MC | Programski sa testovima | Otvoreno bez testova |
|---|---|---|---|
| Generisanje i mehanička provera | ✔ `app.py:4528` | ✔ `app.py:4569` | ✘ ostaje `NULL` (`app.py:4566`) |
| Čuvanje | ✔ `accuracy_check_*` | ✔ | ✔ (`NULL`) |
| Prikaz nastavniku | ✔ | ✔ tabela test primera | ✔ žuta oznaka „nije izvršena“ (`AiExplanationDetailView.vue:248`) |
| Blokada odobravanja | ✔ kad je 0 | ✔ kad je 0 | ✘ nema blokade i nema ocene tačnosti rešenja |
| Druga ocena | ✔ | ✔ | ✔ prikaz |
| Izvoz i analiza | ✔ | ✔ | izostavljeno iz stope, bez zamenske mere |

Sporedna rupa iste vrste: kod izmene u Režimu B nastavnik može da promeni `solution`
(`AiExplanationDetailView.vue:114`), a izmenjeno rešenje se ne proverava ponovo nad test
primerima (`code_executor` se poziva samo u `app.py:4569`). Student tada vidi rešenje koje
niko nije proverio.

## 4. Nešto što nije pominjano ni u prethodnoj proveri ni posle nje

- **Few-shot primeri (Vodič 6.3):** nijedan od 4 šablona objašnjenja nema primer ulaza i izlaza, samo JSON šemu. Ovo je preporuka, ne obaveza. Ako se dodaju, to mora biti pre Faze 3, jer je svaka izmena prompta nova verzija.
- **Lokalni modeli, Ollama ili LM Studio (Zadatak 4):** nisu uključeni. Zadatak kaže „po mogućstvu iz obe kategorije“, pa ovo nije obavezno, ali u radu treba obrazložiti zašto ih nema.
- **Limiti besplatnih nivoa sa datumom provere (Zadatak 4; Vodič 8.4):** nisu zapisani nigde.
- **Ocene rubrike kod odbijanja:** nisu obavezne (`explanation_review.py:165` traži sve kriterijume samo za approve i edit), a analiza ne razdvaja ocene kvaliteta po ishodu provere tačnosti. To je metodološko pitanje za rad.
- **Akademski integritet (Vodič 7) i mere zaštite u produkciji (Zadatak 9.5):** tiču se teksta rada, ne koda.

## Namerno izostavljeno, sa razlogom

- **Mistral:** limit 0 zahteva u minutu; dokumentovano.
- **`format_retries = 0`:** objašnjenja nemaju ponovni zahtev posle lošeg formata; dokumentovano.
- **Studentski id u bazi:** pravi je, jer je potreban za pravila ocenjivanja; u izvozu je HMAC pseudonim.
- **Ruta za generisanje ne proverava predmet ni zatvorenu seriju:** isto ponašanje ima i Anđina ruta `generate-similar` (`app.py:3190`), pa je dosledno.
- **Testovi 21/23:** dva pada zbog nedostajućeg `OPENROUTER_API_KEY` u lokalnom `.env`. README traži taj ključ, pa je to okruženje, a ne kod.

## Stvarni nedostaci, po ozbiljnosti

1. **Visoka. Režim B, otvoreno pitanje bez test primera.** Rešenje se može odobriti i prikazati studentu bez ikakve provere tačnosti, što krši eliminacioni kriterijum. U istoj porodici je izmenjeno rešenje koje se ne proverava ponovo. Moguća rešenja:
   - (a) blokirati odobravanje kad je `accuracy_check_passed IS NULL` u Režimu B, osim uz izričitu nastavničku ocenu „tačnost rešenja“ (originalna Rupa 3, nova migracija);
   - (b) isključiti takva pitanja iz Režima B u eksperimentu i blokirati ih u UI-ju.

   **Zatvoreno odlukom, ne kodom (2026-10-29): opcija (b) za formalni eksperiment.** Zadatak
   (odeljak 5.2, stavka 1) traži da se tačnost rešenja „proverava mehanički gde god je moguće“,
   a za otvoreno pitanje bez test primera mehanička provera nije moguća. Kriterijum
   `tacnost_objasnjenja` nije zamena: ocenjuje objašnjenje, ne rešenje, i ne blokira odobravanje.
   Zato referentni skup za Režim B formalnog eksperimenta (Faza 3) sme da sadrži **samo MC pitanja
   i programske zadatke sa test primerima**, odnosno samo zadatke za koje je mehanička provera
   moguća. Otvorena pitanja bez test primera ostaju dostupna u aplikaciji za običnu upotrebu
   (Režim B uz nastavničku procenu pri pregledu), ali se ne koriste u formalnom poređenju modela.
   Pravilo je zapisano u `docs/PONAVLJANJE_EKSPERIMENTA_OBJASNJENJA.md` (odeljak 0–2).
   Sporedni deo nalaza (izmenjeno rešenje se ne proverava ponovo) ispravljen je kodom u `ddc20b3`.
2. **Srednja. Referentni skup ne postoji.** Ima 1 programsko pitanje, `reference_sets` je prazna. To je preduslov za Fazu 3; MC pitanja (51) mogu da nose Režim B.
3. **Srednja. Studentski pokazatelji i rizični slučajevi nisu u CSV procesu.** Dobijaju se samo iz SQL-a nad živom bazom, a nijedan pojedinačni predlog nije označen. Vodič 5.5 i Zadatak 6.2 traže da tabele potiču iz izvornih fajlova. Predlog: tabela studentskih ocena i rizika u `analyze_experiment.py` iz CSV-a `evaluations`.
4. **Srednja ili niska. Nema PASS/FAIL skripte nad konačnim skupom objašnjenja.** Zadatak 8.1 i Vodič 8.2 je traže; provera postoji samo pri generisanju. Popravka je jeftina: grana za `purpose = 'explanation'` u `validate_batch.py` koja zove `validate_explanation_payload`.
5. **Niska. `retry_count = attempts`** je za 1 veće od stvarnog broja ponavljanja. Izvoz koristi `params_used.attempts`, pa analiza nije pogođena, ali kolona u bazi je pogrešna.
6. **Niska. CLAUDE.md i README nisu ažurni:**
   - lista promptova nema `mode_b_mc_v1` i `mode_b_open_v1`;
   - „Tačku F radi Andrejeva grana“ je zastarelo;
   - nema `--task explanation`, novog dokumenta reproducibilnosti ni `tabela_tacnost.csv`.
7. **Niska.** Pokretač ne proverava `model_version`. Dokumentovano je, ali bi se moglo dodati u `check_explanation_protocol`.
8. **Niska.** Nisu zapisani limiti besplatnih nivoa sa datumom provere, nema few-shot primera u promptovima (odluka pre Faze 3) i nema obrazloženja za izostanak lokalnih modela.

Pre spajanja sa `main` predlaže se da se reše tačke 1, 5 i 6, jer su to izmene koda ili
dokumentacije. Tačke 2 i 3 su priprema za Fazu 3.
