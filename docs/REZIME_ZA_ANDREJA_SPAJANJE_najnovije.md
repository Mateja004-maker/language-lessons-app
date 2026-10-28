# Rezime za Andreja — šta je menjano tokom spajanja

Anđa je spojila tvoju granu (`feature/resenja-objasnjenja`) sa svojom na probnoj grani
`integration/spajanje` (28. 9. 2026). Ovaj fajl je trag šta je dirnuto u tvom delu i
zašto, jer nisi tu da učestvuješ uživo.

**Kratko:** tvoja poslovna logika (režimi A/B, prompt šabloni, rubrike, ocenjivanje,
`evaluation_batches`) nije menjana. Menjano je samo ono što je bilo nužno da dva modula
rade u istom kodu i istoj bazi. Tvoj režim A je posle spajanja probran od početka do
kraja i radi.

---

## Dogovoreno pre spajanja

1. **Status vokabular**: ceo projekat koristi `predlog` / `prihvaceno` /
   `prihvaceno_izmena` / `odbaceno`. Ti si svoj kod prebacio na ovo (commit `047374a`).
   Potvrđeno u probi: posle odobravanja tvog artefakta status je `prihvaceno`.
2. **Gemini model**: `gemini-3.6-flash` je stvaran model. Njena prva sumnja bila je
   pogrešna (zastarelo znanje), tvoja provera preko pretrage je bila ispravna.
3. **`ai_provider.py`**: tvoja izmena (`model = options.get("model")` u `generate()`)
   je čisto aditivna. Git ju je spojio sam, bez konflikta. Njen `DEFAULT_MODELS` rečnik
   postoji samo na njenoj grani i sad je i u spojenom fajlu; tvoj kod ga ne koristi
   jer prosleđuješ model kroz `options["model"]`.
4. **Kolona `mode`** u `ai_generation_runs`: ostaje samo tvoja (`mode_a`/`mode_b`).
   Kod njenih redova je `NULL` i to ništa ne kvari.

## Izmene u tvom kodu

| Fajl | Šta je promenjeno | Zašto |
|---|---|---|
| `backend/app.py` | Blok importa posle `load_dotenv()`: zadržane obe strane, uklonjen tvoj `import json` (već postoji na liniji 3) i drugi `import ai_provider` | Jedini konflikt pri spajanju. Duplikati su bezopasni ali su očišćeni |
| `backend/app.py` | Obrisana tvoja kopija funkcije `ensure_ai_model`; komentar iznad nje ažuriran | Postojale su dve identične definicije (njena i tvoja). Tela su bila ista, samo docstring različit, pa se ponašanje ne menja. Tvoj `generate_explanation` sad koristi zajedničku verziju iz sekcije Helpers |
| `backend/code_executor.py` | Minimalna zaštita pri izvršavanju koda modela (detalji ispod) | Izvršavao je kod modela direktno na računaru, sa svim ključevima iz `.env` u okruženju |
| `backend/ai_provider.py` | Podrazumevani modeli u njenom `DEFAULT_MODELS`: Groq `llama-3.1-8b-instant` → `openai/gpt-oss-20b`, Gemini `gemini-2.0-flash` → `gemini-3.6-flash` | Stari modeli su ugašeni (404). Tebe to ne pogađa, ti šalješ svoj model kroz `options["model"]`; sad su isti kao tvoji |
| `backend/ai_provider.py` | Otpornost `_call_groq`, `_call_gemini` i `_call_mistral` na neočekivan odgovor i mrežne greške (detalji ispod) | Prazan ili blokiran odgovor davao je izuzetak i 500 bez traga u bazi |
| `backend/ai_provider.py` | Dodat OpenRouter kao četvrti provajder (`_call_openrouter`, `DEFAULT_MODELS["openrouter"]`) | Aditivno, Mistral netaknut; koristi tvoj obrazac ako želiš da ga dodaš i u `EXPLANATION_DEFAULT_MODELS` |
| `backend/app.py` | **MC podrška u `generate_explanation`** - režim A sada automatski uzima tačan odgovor iz `exam_answers` kad `reference_solution` ne postoji; režim B odbija MC pitanja (400, pre AI poziva). Detalji ispod | Bez ovoga: MC pitanje bez `reference_solution` je uvek vraćalo 400 u režimu A, a u režimu B bi tiho pokušalo da generiše Python kod za MC pitanje i moglo da bude odobreno bez mehaničke provere (jer bi `accuracy_check_passed` ostalo `NULL`, van uslova za blokadu) |
| `backend/app.py` | **Bezbednosna zakrpa** - `GET /api/questions/<id>/explanation` i `POST .../rate` sada dozvoljavaju studentu pristup samo ako ima završen pokušaj testa koji sadrži to pitanje. Detalji ispod | Bez ovoga, čim MC podrška proradi, bilo koji student je mogao direktno da pozove rutu i vidi tačan MC odgovor PRE nego što uradi test |
| `backend/app.py` | `EXPLANATION_DEFAULT_MODELS` dobija red `"openrouter": "nvidia/nemotron-3-super-120b-a12b:free"` | Tvoja `generate_explanation` sada prihvata i `provider=openrouter`, bez toga bi vraćala 400 |

### `code_executor.py` — šta je tačno dodato

Potpis `run_against_test_cases` i oblik rezultata su isti, `app.py` nije dirano, a
smoke test daje bajt po bajt isti izlaz kao pre izmene.

- Svako pokretanje u zasebnom, praznom privremenom direktorijumu koji se posle briše
- `python -I -X utf8`: radni direktorijum nije na `sys.path` (`import app` ne prolazi),
  ignorišu se `PYTHON*` promenljive, stdin/stdout u UTF-8
- Okruženje podprocesa sadrži samo `PATH` (i `SYSTEMROOT` na Windows-u); nijedna
  promenljiva iz `.env` ne prelazi u podproces
- Izlaz ograničen na 100 KB po toku; preko toga se proces ubija, a rezultat dobija
  novu poruku "Prekoračena dozvoljena veličina izlaza"
- Timeout i prekoračenje izlaza ubijaju celo stablo procesa (`taskkill /F /T` na
  Windows-u; `killpg` na Linux-u, napisano ali netestirano)
- `actual_output` u rezultatu se seče na 1000 znakova, da `accuracy_check_details`
  (TEXT, najviše 64 KB) ne prepuni pri upisu

Razlike u ponašanju koje treba da znaš:
- Izlaz koji nije ispravan UTF-8 se sada dekodira sa zamenom znakova umesto da obori
  proveru. Izlaz sa "č" i ostalim slovima ispravno radi (ranije bi pao na Windows-u).
- Ograničenje ne pokriva: čitanje/pisanje fajlova apsolutnom putanjom, mrežu,
  memoriju i CPU, procese koji se odvoje od stabla. To nije sandbox protiv
  zlonamernog koda. U radu se može navesti kao poznato ograničenje, uz Docker bez mreže
  kao pravo rešenje.

### `ai_provider.py` — otpornost (ZAJEDNIČKI fajl, tiče se i tvog toka)

Pre izmene, svaki odgovor sa statusom 200 koji nije imao očekivanu strukturu (prazan tekst,
blokiran odgovor, nema `choices` ili `candidates`, telo koje nije JSON) davao je izuzetak
(`KeyError`) ili lažni "uspeh" sa praznim tekstom, a mrežne greške (timeout) su bile
izuzetak. Izuzetak je davao 500 PRE upisa u `ai_generation_runs`, pa pokušaj (za koji su
tokeni već plaćeni) nije ostavljao nikakav trag.

Sada svaka od tri funkcije vraća `{"success": False, "error": ..., "response_time_ms": ...}`
sa razlogom (npr. `finish_reason`, `blockReason`, ime tipa mrežnog izuzetka).

**Šta to menja u tvom toku:** tvoja `generate_explanation` već ume da obradi
`success: False` (upisuje run i vraća 422), pa njoj ne treba izmena. Isti neuspesi sada
daju 422 sa upisanim run-om umesto 500, što znači da neuspeli pokušaji ulaze u evidenciju
i u tvoje statistike (pokušaji su sada vidljivi, `tokens_used` im je `NULL`).

Odluke koje važe za sva tri modela: tekst od samih razmaka je prazan; Gemini uzima prvi
deo koji ima tekst (ne spaja delove); `finish_reason` se ne čuva u rezultatu. U poruku
mrežne greške ide samo ime tipa izuzetka, ne tekst, jer tekst sadrži URL, a Gemini ključ
je u URL-u.

Provereno bez mreže (lažan `requests.post`): rezultat za uspešne pozive je identičan pre i
posle izmene (4/4), a 23/23 neočekivana slučaja vraćaju `success: False` bez izuzetka.

### MC podrška u `generate_explanation` - detalji

Nova pomoćna funkcija `resolve_explanation_source(cursor, question, mode)`, čisto
čitanje iz baze, ista logika detekcije MC/otvoreno kao Anđina `generate_similar_question`
(`prompt_templates.detect_question_type`). Pravila, redom:

- režim B + MC pitanje -> 400 "Rezim B nije podrzan za MC pitanja" (pre AI poziva, bez run-a)
- režim A + `reference_solution` popunjen -> nepromenjeno, isti prompt bajt po bajt
- režim A + nema `reference_solution` + MC sa tačno jednim `is_correct=1` -> koristi se
  taj odgovor; u tekst zadatka se dodaje lista ponuđenih odgovora, a "poznato rešenje"
  postaje "Tačan odgovor: X" (model tako može da objasni i zašto su ostali netačni)
- režim A + MC bez tačnog odgovora ili sa više tačnih -> 400, jasna poruka (u bazi nema
  takvih pitanja, ali provera postoji za svaki slučaj)
- `params_used` u `ai_generation_runs` sada sadrži `"solution_source":
  "reference_solution" | "mc_correct_answer" | null` - trag odakle je poznato rešenje
  došlo, korisno za tvoju analizu jer su to dva različita izvora pouzdanosti

Testirano na pravom MC pitanju iz banke (101, "šta funkcija vraća bez `return`") -
model je iskoristio ponuđene odgovore, objasnio zašto su ostali netačni, sadržajno
tačno. Artefakt je kasnije i ODOBREN kroz browser (nije više probni podatak).

### Bezbednosna zakrpa - detalji

Nova pomoćna funkcija `student_completed_question(student_id, question_id)` - proverava
preko `exam_attempts` JOIN `exam_test_questions` da li student ima pokušaj statusa
`COMPLETED` za test koji sadrži dato pitanje. Samo čitanje.

- `get_question_explanation`: posle provere `mode`, za ulogu STUDENT bez završenog
  pokušaja -> 403. TEACHER/ADMIN bez ograničenja.
- `rate_explanation_artifact_route`: pre `submit_student_rating` učitava
  `source_question_id` artefakta i primenjuje istu proveru.

Testirano: 15 slučajeva (student sa/bez pokušaja, TEACHER/ADMIN bez ograničenja,
pogrešan `mode` ide pre provere pristupa, pitanje van ijednog testa ispravno 403 i za
ADMIN-a/TEACHER-a ostaje 200). Promena ponašanja koju vredi znati: seed pitanje 103
(nije ni u jednom testu) sada vraća 403 za studente - ranija proba (student ocenio
artefakt 23) više se ne bi mogla ponoviti, ali upisane ocene 51-53 od tada ostaju.

Pokrenute su tvoje tri migracije, tačno jednom i ovim redosledom:
`migration_exam_questions_reference_solution.sql`, `migration_exam_question_test_cases.sql`,
`migration_ai_explanation_module.sql`. Fajl `migration_ai_generation_base_VERIFIED.sql`
nije pokretan (dokumentacija; tabele već postoje). Pokrenut je i tvoj opcioni seed
(`seed_sample_programming_task.sql`, pitanje id 103 sa 3 test primera).

Posle migracija `ai_rubric_definitions` ima 16 redova (njenih 8 + tvojih 8).

Odgovori na tvoja otvorena pitanja iz migracije:
- a) `mode` kolona: da, ostaje tvoja; kod njenih redova je `NULL`.
- b) `accuracy_check_passed/details` na `ai_generation_runs`: pokrenuto kako si napisao.
- c) `evaluation_batches` kao zajednička tabela: pokrenuto kako si napisao. I ona
  može da je koristi da odvoji svoje razvojne probe od formalnog kruga.
- d) Osnovna šema (6 `ai_` tabela): identična, osim njene kolone `created_question_id`
  na `ai_generated_artifacts`, koja ostaje samo njena.

## Merge konflikt u `app.py`

Samo jedna konfliktna regija (blok importa, linije 40–54). Rešeno zadržavanjem obe strane.
`ai_provider.py` se spojio automatski. Nijedna od 66 ruta nema dupliran naziv funkcije
ni dupliran par (metod, putanja). Njene rute su `/api/ai/artifacts...`, a tvoje
`/api/ai-artifacts/explanation...`, pa se putanje ne sudaraju.

## Frontend

Tvoja grana ne sadrži nijedan `.vue` fajl. Cela funkcionalnost postoji samo kao API.
Ekrane za tvoj modul (dugme "Generiši objašnjenje", nastavnički pregled, prikaz
objašnjenja studentu sa ocenom) Anđa pravi kao posebnu stavku, i to je njen rad, ne
tvoj — pogledaj to kad budeš pregledao kod.

## Šta je posle spajanja provereno na tvom delu

Režim A, jedan Groq poziv, pitanje 103, bez `evaluation_batch_id` (ostaje razvojna
proba):
- generisanje: 201, provera odgovora prošla, model je napisao tačno objašnjenje
- nastavnički pregled: 5 ocena upisano kao `TEACHER`, status `prihvaceno`
- student: vidi objašnjenje, ocenjuje sa 3 ocene; ponovno ocenjivanje istog studenta
  vraća 409
- njena lista `/api/ai/artifacts` tvoj artefakt ne vidi (dodat filter po tipu)

Režim B, jedan Groq poziv, isto pitanje 103, bez `evaluation_batch_id`, posle ugrađene
zaštite u `code_executor.py`:
- generisanje: 201, provera strukture odgovora prošla
- mehanička provera tačnosti pala (`accuracy_check_passed = 0`) na sva tri test primera,
  sa istom greškom: `SyntaxError`. Model je logiku napisao ispravno (ista kao referentno
  rešenje), ali je prelome redova u kodu poslao kao dva znaka `\` i `n` umesto pravog
  novog reda, pa je ceo program ispao jedna linija. Sirov odgovor je proveren: greška je
  u onome što je model napisao, ne u čitanju odgovora. Program se zbog toga nikad nije
  ni pokrenuo, pa ovo nije test zaštite izvršavanja.
- odobravanje ispravno blokirano: 400, jedina dozvoljena akcija je `reject`; artefakt je
  ostao `predlog`, bez upisanih ocena
- u `%TEMP%` nema ostataka `code_exec_*`

**Odluka je tvoja** (menja kako se meri tačnost u tvom istraživanju): da li grešku
formata računati kao grešku modela (instrukcija u promptu je jasna), da li normalizovati
prelome redova pre izvršavanja uz beleženje da je normalizacija bila potrebna, ili brojati
"grešku formata" i "grešku logike" odvojeno. Zadatak traži identičan protokol za sve
modele, pa pravilo mora biti isto za sva tri. Jedan poziv ne pokazuje koliko često model
tako greši. Provera tačnosti tako meri i format, ne samo logiku, što je vredan nalaz za rad.

Režim B do kraja (provera tačnosti prolazi, pa odobravanje) još nije viđen.

**Ceo tok, do kraja, kroz pravi browser (posle MC podrške i bezbednosne zakrpe):**
generisanje MC objašnjenja (režim A, pitanje "Koja ključna reč se koristi za
definisanje funkcije?") -> tvoj ekran za pregled (rubrika, 5 kriterijuma) -> "Prihvati
bez izmene" -> student uradi test sa tim pitanjem, otvori "Detalji" u svojim
rezultatima -> vidi objašnjenje -> oceni ga (3 kriterijuma) -> ponovna ocena vraća "već
ste ocenili". Artefakti 30 i 32 su na ovaj način ODOBRENI tokom testiranja - nisu više
probni podaci, deo su realnog (ali ne formalnog, bez evaluation_batch_id) toka.

**Studentska strana - nova, Anđina ruta (ne tvoj kod):** nova ruta
`GET /api/my-results/<attempt_id>` vraća pitanja pokušaja sa studentovim odgovorom
(BEZ otkrivanja tačnog odgovora - to student vidi jedino kroz odobreno objašnjenje) i
podacima o poslednjem odobrenom objašnjenju (`explanation_artifact_id`,
`explanation_mode`, `already_rated`). Novi ekran `/my-results/:attemptId` to prikazuje,
sa sklopivim delom "Objašnjenje" i formom za ocenu. Ovo ne menja tvoj kod, samo ga
poziva - spominjem da znaš da sad postoji vidljiv put od tvog objašnjenja do studenta.

Probni podaci koje si dobio u bazi: run 33 i 34, artefakti 23 (režim A) i 24 (režim B,
status `predlog`, bez ocena), ocene 46–53 (nastavničke 46–50, studentske 51–53), prompt 5
(`explanation / mode_a-v1`) i 6 (`explanation / mode_b-v1`), oba trajna, i seed pitanje
103. Nemaju `evaluation_batch_id`, pa ne ulaze u tvoju finalnu evaluaciju. Ocene su
sve 4 i služe samo za probu toka.

## Zapažanja za tebe (nije menjano, tvoja odluka)

1. **Komentar o modelima**: iznad `EXPLANATION_DEFAULT_MODELS` piše da ima "isti sadržaj" kao
   `ai_provider.DEFAULT_MODELS`. Pri spajanju to nije bilo tačno (kod nje su bili ugašeni
   `llama-3.1-8b-instant` i `gemini-2.0-flash`). Posle promene Groq i Gemini modela sada
   je tačno da su vrednosti iste (za Mistral su oba već imala `mistral-small-latest`), ali
   ostaju dva odvojena spiska koje treba držati usklađenim. Dogovorite se koji je izvor
   istine.
2. **`jinja2` nedostaje u `requirements.txt`**: `explanation_prompts.py` ga uvozi
   direktno. Radi samo zato što ga Flask povlači kao zavisnost. Predlog: dodaj ga eksplicitno.
3. **Predmet se ne proverava**: nijedna tvoja ruta ne proverava predmet. Nastavnik može
   da generiše i pregleda objašnjenje za pitanje iz bilo kog predmeta, a student da
   čita i ocenjuje odobreno objašnjenje za bilo koje pitanje. Njene rute to proveravaju.
   Ne kvari probu, ali je razlika između modula.
4. **`tokens_used`**: `gpt-oss-20b` je model koji "razmišlja" i Groq u broj tokena računa
   i tokene razmišljanja (157 tokena za odgovor od pet reči); isto važi i za
   `gemini-3.6-flash` (343). Pri poređenju modela u radu `tokens_used` nije uporediv sa
   modelima koji ne razmišljaju.
5. **Mistral**: kod nje takođe daje 429 pri probi (kod tebe je limit 0 potvrđen na dva
   naloga). Nije potvrđeno da je uzrok isti. `mistral-small-latest` je alias, a ne fiksna
   verzija; za ponovljiv eksperiment treba fiksirati tačan naziv modela.
6. **Servisi koje koristite nisu stabilni**: u istom danu Groq je ugasio model (404),
   Gemini je ugasio stari model i jednom vratio 503 (preopterećenje), a Mistral 429.
   Pre prikupljanja podataka odredite isto pravilo za ponovne pokušaje za sva tri modela.
   Ovo spada u "praktičnost integracije" iz zadatka.
7. **Mistral ostaje blokiran i posle novog ključa** - limit 0 zahteva/min, potvrđeno na
   dva ključa (stari i nov), dva imena modela, i kod tebe i kod Anđe. Prijavljeno
   Mistral podršci. Za treći model za poređenje, Anđa je dodala OpenRouter
   (`nvidia/nemotron-3-super-120b-a12b:free`) u zajednički `ai_provider.py` i u tvoj
   `EXPLANATION_DEFAULT_MODELS` (jedan red, ne menja ništa tvoje) - razmisli da li ga
   koristiš kao treći model umesto Mistrala, ili čekaš odgovor podrške. Napomena iz
   tvog zadatka: obrati pažnju na modele jače u rezonovanju za režim B (npr. DeepSeek);
   Nemotron nije proveravan na rezonovanju za kod, samo na strukturi JSON odgovora.
8. **`exams.language_id` -> `exams.subject_id`**: testovi sada pripadaju predmetu, ne
   jeziku (bila je greška u starijem delu aplikacije, ne u tvom modulu). Ne bi trebalo
   da utiče na tebe - tvoje rute rade preko `question_id`, ne preko `exam_id`/`language_id`
   - ali ako ikad budeš čitao `exams` tabelu direktno, koristi `subject_id`.

## Šta NIJE dirano

- Tvoja poslovna logika za režim A/B (sastavljanje prompta, mehanička provera koda,
  poređenje sa očekivanim izlazom)
- `explanation_review.py`, `explanation_rating.py`, `explanation_prompts.py`,
  `prompts/explanation_*.txt`
- `evaluation_batches` mehanizam
- `EXPLANATION_DEFAULT_MODELS` (ni vrednosti ni ime)

---

*Anđa dopunjava ovaj fajl kako se rade preostali koraci (režim B, Gemini, ekrani za tvoj
modul, spajanje u glavnu granu). Andrej — javi ako nešto od navedenog ne odgovara
stvarnom stanju.*


---

## Dopuna 7. oktobar 2026 (važno pre eksperimenta)

1. **Nova migracija (jedanaesta, na kraj spiska):** `migration_exam_attempts_unique.sql`.
2. **Bezbednost testova:** submit/publish/get_exam_details su pooštreni (student ne vidi is_correct, predaja proverava objavljenost, predmet i prozor). Tvoje rute nisu menjane.
3. **Slepo ocenjivanje i na tvom delu:** na tvojim ekranima predlog objašnjenja u statusu `predlog` više ne prikazuje vreme generisanja ni identifikator pokretanja. Lista predloga je u slučajnom redosledu. Tvoje rute nikad nisu vraćale naziv modela. Namerno je, zadatak traži slepo ocenjivanje.
4. **Ponovni pokušaji:** isto pravilo za sva tri modela (do 2 ponavljanja za 429, 5xx i mrežne greške, pauze 5 s i 15 s). `attempts` i `finish_reason` se čuvaju u `params_used` tvojih pokretanja.
5. **Serija za eksperiment:** u modalu za generisanje postoji meni "Serija (opciono)". Serije se prave u svakoj bazi posebno, pa napravi svoju kroz POST /api/evaluation-batches (ADMIN) pre generisanja, ili ti ga neće biti u meniju. Probe radi sa "Bez serije".
6. **Lista modela je na dva mesta** (DEFAULT_MODELS u ai_provider.py i EXPLANATION_DEFAULT_MODELS u app.py). Trenutno iste; ne menjati samo jednu tokom eksperimenta.
7. **Otvoreno, tvoja odluka:** tvoje rute za pregled objašnjenja ne proveravaju predmet nastavnika.

## Dopuna 7. oktobar, popodne: pregled tvog modula prema tvom zadatku i podela rada

Uporedili smo tvoj modul sa fajlom Zadatak-Andrej-Resenja-i-objasnjenja. Osnova radi, ali ima rupa koje treba popuniti pre eksperimenta.

### Rupe koje treba popuniti (tvoj deo)

1. **Režim B za MC pitanja.** Sada backend vraća 400. Treba da radi: model ne sme da vidi koji je odgovor tačan, a provera tačnosti je 1 ako je izabrani odgovor is_correct.
2. **Dugme "Generiši objašnjenje" na svakom pitanju.** Sada ga nemaju otvorena pitanja bez reference_solution, a po zadatku bi režim B trebalo da radi za bilo koje pitanje.
3. **Nastavnička ocena "tačnost rešenja" u režimu B.** Rubrika (id 12-16) je nema. Obavezna, uz ocenu 2 ili manje se blokira odobravanje. Treba nova migracija (dodaj je na kraj liste migracija).
4. **Oznaka rizičnih slučajeva** (visoka korisnost za studenta, niska tačnost po nastavniku). Ne postoji ni u kodu ni u upitima.
5. **Beleženje:** model_version je uvek NULL, retry_count je uvek 0 (stvarna vrednost je u params_used.attempts), student se beleži stvarnim user_id, a ne anonimizovano.
6. **Pokazatelji:** nema CSV izvoza, raspodele studentskih ocena, stope formalne ispravnosti iz prve ni vremena odziva u upitima.
7. **Programskih pitanja u bazi ima samo jedno (#103).** Za režim B sa mehaničkom proverom potrebno je 20-30 pitanja sa reference_solution i test primerima.

### Podela rada i grane

- Ti radiš na grani `feature/dopune-objasnjenja` (od main-a), Anđa na `feature/dopune-pitanja`. Niko ne radi direktno na main-u.
- Pre početka: `git checkout main && git pull`, pa tek onda napravi granu.
- Migracije imenuj tako da se ne poklapaju sa Anđinim. Ako Git javi konflikt u app.py, nemoj ga sam rešavati bez dogovora.
- CSV izvoz i skriptu za grafikone radi Anđa, ti samo dodaš svoje kolone kad bude gotovo.
- Pre spajanja pokreni tri verify skripte (verify_exam_security.py, verify_ai_blind_review.py, verify_ai_provider_retry.py).

## Dopuna 9. oktobar: na šta da obratiš pažnju pre nego što kreneš

### Šta je tvoje (uglavnom backend, malo frontenda)
- **Backend:** rupe 1–7 iz prethodnog odeljka (režim B za MC, dugme na svakom pitanju, ocena "tačnost rešenja", oznaka rizičnih slučajeva, beleženje, pokazatelji, 20–30 programskih pitanja).
- **Frontend (malo):** dugme "Generiši objašnjenje" na svakom pitanju, polje "tačnost rešenja" u formi ocenjivanja, prikaz oznake rizika, izbor režima A/B. Na tvojoj staroj grani nema nijednog .vue fajla, pa ćeš ih dodavati na postojeće ekrane nakon spajanja.

### Grane i redosled
1. Prvo se `feature/dopune-pitanja` spaja u `main`. Tek tada praviš `feature/dopune-objasnjenja` od novog main-a (`git checkout main && git pull`).
2. Tvoja stara grana `feature/resenja-objasnjenja` je zastarela (nema novih commit-ova od 17. 9.). Ne radi na njoj.
3. Grana `feature/dizajn` je Anđina i menja izgled (theme.css, PageHeader.vue, AppNavbar, srpski tekstovi). Ne diraj stilove i ne menjaj tekstove u .vue fajlovima dok se ne spoji. Dodaj samo funkcionalnost, a izgled će se uskladiti posle.

### Šta je novo u kodu (koristi, ne piši ponovo)
- **Šest novih migracija** (label, reference_sets, edit_distance, duplicate_check, failure_type_retry, second_rater). Pogledaj `db/MIGRATIONS.md` i `db/schema.sql`. Svoju migraciju dodaj na kraj, sa jedinstvenim imenom, i ažuriraj oba fajla.
- **generation_failures.py:** 7 tipova grešaka i jedan ponovni pokušaj zbog formata (MAX_FORMAT_RETRIES=1). Iskoristi isto za objašnjenja.
- **agreement.py:** Cohenov kappa i Krippendorffov alfa.
- **CSV izvoz:** `GET /api/evaluation-batches/<id>/export.csv?kind=artifacts|runs|evaluations`, sa HMAC pseudonimima. Dodaj svoje kolone u taj izvoz, nemoj pravi novi.
- **tools/analyze_experiment.py** (grafikoni, SVG) i **tools/validate_batch.py** (provera serije). Proširi ih, ne dupliraj.
- **Testovi na čistoj bazi:** `tools/test_clean_db.py`. Pokreni ga posle svake migracije.
- **Drugi ocenjivač** vidi samo original_text. Slepo ocenjivanje važi i za tvoje ekrane (model, provajder, vreme i pokretanje skriveni dok je status `predlog`).

### Pravila koja se ne smeju pokvariti
- **Zamrznuti prompt-ovi:** mc-v3, open-v3, set-v1. Svaka izmena je nova verzija i nova serija. Za objašnjenja uvedi svoju verziju i zamrzni je pre eksperimenta.
- **Lista modela je na dva mesta** (`DEFAULT_MODELS` u ai_provider.py i `EXPLANATION_DEFAULT_MODELS` u app.py). Menjaj oba odjednom, nikad tokom eksperimenta.
- **Predlog nikad ne ulazi u test sam.** Samo nastavnik prihvata, i tek tada ide u banku (exam_id NULL). Ne dodaj nikakav automatski put do testa.
- **Registracija** više ne dozvoljava ulogu ADMIN (samo STUDENT/TEACHER). Ne vraćaj to.
- **Nastavnik i predmet:** tvoje rute za pregled objašnjenja i dalje ne proveravaju predmet nastavnika. Odluči i zatvori to.
- **Ista pitanja u obe baze** i serija se pravi u svakoj bazi posebno (POST /api/evaluation-batches, ADMIN).
- **Logovanje:** upiši model_version, stvarni retry_count, anonimizuj studenta.
- Pre spajanja: tri verify skripte + test_clean_db.py. Ako Git javi konflikt u app.py, ne rešavaj sam bez dogovora.

## Dopuna 10. oktobar: main je spreman, možeš da kreneš

**Stanje:** `main` je na commit-u `c022dfa` i sadrži sve: Anđin AI modul, dizajn i nove funkcije za predmete. Napravi granu od njega: `git checkout main && git pull && git checkout -b feature/dopune-objasnjenja`.

### Šta je novo u odnosu na prethodni rezime
- **Tri nove migracije (19, 20, 21):** `migration_lessons_subject.sql` (lessons.subject_id), `migration_lessons_language_nullable.sql` (lessons.language_id može NULL), `migration_lessons_area.sql` (lessons.area_id). Tvoja prva migracija je broj **22**, jedinstvenog imena. Ažuriraj `db/schema.sql` i `db/MIGRATIONS.md`.
- **Lekcije su vezane za predmet i oblast**, ne za jezik. Predmeti se prave u aplikaciji: Administracija → Upravljanje predmetima (ADMIN).
- **Dizajn je na `main`-u:** `theme.css`, `PageHeader.vue`, navbar, srpski tekstovi. Za nove ekrane koristi PageHeader (samo naslov i tanka linija), filter ide u traku iznad liste, bez dugmeta "Osveži", bez podnaslova. Dugmad: glavna radnja `btn-primary`, sporedna `btn-outline-secondary`, brisanje `btn-outline-danger`.
- **Backend poruke:** novi tekstovi na srpskom, bez engleskih poruka.
- **Testovi:** novi `verify_lessons_subject.py` i `verify_subjects_crud.py`. Pre spajanja pokreni sve verify skripte i `tools/test_clean_db.py`.

### Otvoreno na tvom ekranu (Objašnjenja)
- **Backend nastavniku vraća objašnjenja iz svih predmeta**, ne samo njegovih. Ograniči ih na predmete koje predaje (kao na listi AI predloga pitanja).
- Dodaj `subject_id` i `subject_name` u listu (bez modela i vremena dok je status `predlog`), pa filter po predmetu u traci iznad liste.
- Ekran koristi sopstveni naslov umesto `PageHeader`, pa to uskladi (samo izgled, ne logika). Prazno stanje neka koristi `empty-state` iz teme.
- Stranice "Predmeti" (SubjectsView i SubjectAreasView) imaju tvoje dugme "Generiši objašnjenje". Kad ga budeš dodavao, uskladi dugmad i prozor sa temom, i javi Anđi da ne bi radile istovremeno na istom fajlu.

### Pravila ostaju ista
Ne radi se na `main`-u, prompt-ovi `mc-v3`, `open-v3` i `set-v1` se ne menjaju, lista modela se menja na dva mesta odjednom, a konflikt u `app.py` se ne rešava sam.
