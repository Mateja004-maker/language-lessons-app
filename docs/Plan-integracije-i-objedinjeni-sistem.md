# Plan integracije i objedinjeni sistem

**Namena:** zajednički dokument za studente Anđu Mitić i Andreja Ćirića
**Kontekst:** objedinjavanje dva odvojeno razvijena proširenja web sistema za onlajn testiranje u jednu aplikaciju

## 1. Cilj

Iako se dve teme razrađuju odvojeno — generisanje novih pitanja (Anđa Mitić) i generisanje rešenja i objašnjenja (Andrej Ćirić) — krajnji cilj je jedinstvena aplikacija u kojoj postoje obe funkcionalnosti. Ovaj dokument opisuje kako da se dva rešenja spoje uz što manje trvenja, uz pomoć alata Claude Code, i koje zajedničke elemente treba usaglasiti od početka kako bi objedinjavanje bilo jednostavno.

Osnovno načelo: **spajanje se ne odlaže za kraj.** Deo koji je oboma zajednički (pristup modelima, model podataka za evaluaciju, evidencija) dogovara se i usaglašava pre nego što svako krene u svoj deo. Time se izbegava skupo naknadno usklađivanje dva nezavisno donesena rešenja.

## 2. Zajednički elementi koji se usaglašavaju od početka

1. **Sloj apstrakcije prema modelima (provider layer).** Oba zadatka pozivaju jezičke modele preko istog interfejsa. Dogovoriti jedinstven potpis (npr. `generate(prompt, options)`), način konfigurisanja modela i jedinstveno rukovanje greškama i limitima. Ovaj sloj se piše jednom i koristi u oba modula.
2. **Model podataka za evaluaciju i praćenje.** Oba modula beleže generisanja i ocene. Umesto dve odvojene šeme, projektovati jedinstven model podataka koji pokriva obe namene (vidi odeljak 4).
3. **Radni tok odobravanja.** Isti obrazac „predlog → pregled → odobravanje" primenjuje se i na pitanja i na objašnjenja. Uputno je da deli istu logiku i interfejs.
4. **Evidencija (logging) i konvencije.** Isti format zapisa, isto imenovanje, ista organizacija promptova u repozitorijumu.
5. **Konvencije razvoja.** Zajednički stil koda, struktura direktorijuma, način grananja u sistemu za verzionisanje i format commit poruka.

## 3. Strategija spajanja pomoću sistema za verzionisanje

1. **Zajednički repozitorijum od početka.** Raditi u istom repozitorijumu, svako na svojoj grani (npr. `feature/generisanje-pitanja` i `feature/resenja-objasnjenja`), sa zajedničkom osnovom (`main` ili `develop`) na kojoj živi usaglašena zajednička infrastruktura.
2. **Zajednički deo prvo.** Sloj apstrakcije prema modelima i osnovni model podataka razviti i spojiti u zajedničku granu pre nego što se krene u pojedinačne module. Tako oboje grade na istoj, stabilnoj osnovi.
3. **Redovno usklađivanje.** Često povlačiti izmene sa zajedničke grane u svoju, da se razlike ne gomilaju. Male i česte integracije su daleko lakše od jednog velikog spajanja na kraju.
4. **Razdvojene odgovornosti u kodu.** Svaki modul drži svoj kod u zasebnim direktorijumima/prostorima imena; dodiruju se samo preko zajedničkih, unapred dogovorenih tačaka (interfejs modela, model podataka). Time se sukobi pri spajanju svode na najmanju meru.

## 4. Jedinstveni model podataka (konceptualno, tehnološki neutralno)

Predlaže se zajednički model koji pokriva oba modula. Naziv i tačan oblik prilagoditi tehnologiji sistema; ovde je dat konceptualno.

- **Model / verzija modela** — provajder, identifikator modela, verzija, podrazumevani parametri.
- **Prompt / verzija prompta** — tekst šablona, namena (generisanje pitanja / objašnjenje / rešenje), verzija.
- **Generisanje (generation run)** — veza ka modelu i promptu, tip (pitanje / objašnjenje / rešenje+objašnjenje), referenca na ulaz, sirov odgovor, isparsiran rezultat, ishod validacije, tehnički pokazatelji (vreme, tokeni), vremenska oznaka.
- **Generisani artefakt** — konkretno pitanje odnosno rešenje/objašnjenje, sa statusom (predlog / odobreno / izmenjeno / odbačeno) i vezom ka generisanju.
- **Ocena (evaluation)** — veza ka artefaktu, uloga ocenjivača (nastavnik / student), anonimizovani identifikator ocenjivača, ocene po dimenzijama, slobodni komentar, vremenska oznaka.
- **Definicija rubrike** — skup dimenzija ocenjivanja i skala, kako bi se rubrike (koje se razlikuju za pitanja i za objašnjenja) opisale podacima, a ne fiksirale u kodu.

Ovakav model istovremeno pokriva rubriku za pitanja (Anđa) i dvostranu evaluaciju rešenja/objašnjenja (Andrej), a jedinstvena tabela ocena i generisanja omogućava objedinjene izveštaje nad celim sistemom.

## 5. Uloga alata Claude Code u objedinjavanju

1. **Pregled i uparivanje interfejsa.** Zatražiti od asistenta pregled oba modula i proveru da li zaista koriste zajednički sloj na isti način; nesaglasnosti se otklanjaju pre spajanja.
2. **Pomoć pri razrešavanju konflikata.** Pri spajanju grana, asistent može da objasni i predloži razrešenje konflikata, ali svako spajanje mora biti praćeno pokretanjem testova.
3. **Objedinjeni testovi.** Nakon spajanja, uz pomoć asistenta napisati testove koji proveravaju da obe funkcionalnosti rade istovremeno u jednoj aplikaciji (npr. da deljeni sloj modela i model podataka korektno opslužuju oba modula).
4. **Provera regresije.** Posle spajanja proveriti da nijedna od dve funkcionalnosti nije narušena — po načelu da izmene koje ne smeju da promene ponašanje to moraju i da dokažu.

Sve smernice iz dokumenta „Vodič za rad sa Claude-om" (planiranje pre koda, male iteracije, obavezna verifikacija) važe i ovde.

## 6. Kontrolna lista za uspešno objedinjavanje

1. Sloj apstrakcije prema modelima je jedinstven i oba modula ga koriste na isti način.
2. Model podataka je zajednički; nema dupliranih ili nesaglasnih šema.
3. Radni tok odobravanja je usaglašen za obe vrste sadržaja.
4. Objedinjena aplikacija se podiže iz čistog okruženja i svi testovi (i pojedinačni i objedinjeni) prolaze.
5. Obe funkcionalnosti rade istovremeno, bez međusobnog ometanja.
6. Izveštaji o radu modela mogu se generisati nad objedinjenim podacima iz celog sistema.
7. Dokumentacija (uključujući `CLAUDE.md`) opisuje objedinjeni sistem i način njegovog pokretanja.
