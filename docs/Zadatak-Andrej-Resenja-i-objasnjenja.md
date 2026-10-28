# Projektni zadatak: Uporedna analiza jezičkih modela za automatsko generisanje rešenja i objašnjenja zadataka

**Student:** Andrej Ćirić
**Predmet:** Web programiranje
**Osnova:** Postojeći web sistem za objavljivanje i sprovođenje onlajn testiranja

## 1. Kontekst i motivacija

U okviru predmeta Web programiranje razvijen je web sistem koji nastavniku omogućava da objavi testiranje, a studentima da u zadatom terminu rade onlajn test. Vredna dopuna takvog sistema jeste mogućnost da student, nakon urađenog testa, za svaki zadatak dobije kvalitetno objašnjenje — čime sistem prestaje da bude samo alat za proveru znanja i postaje i alat za učenje.

Cilj ovog zadatka je da se sistem proširi modulom koji, korišćenjem velikih jezičkih modela (LLM), podržava dva režima rada, kao i da se sprovede sistematična uporedna analiza više modela i izabere najbolji za integraciju:

- **Režim A — generisanje objašnjenja:** na osnovu zadatka i poznatog (tačnog) rešenja model piše pedagoški kvalitetno objašnjenje postupka i razloga zašto je rešenje tačno;
- **Režim B — generisanje rešenja i objašnjenja:** na osnovu samog zadatka model najpre generiše rešenje, a zatim i objašnjenje.

Razlika između režima je suštinska: u režimu A tačnost je garantovana ulazom, pa se ocenjuje isključivo kvalitet objašnjenja; u režimu B model može da pogreši i u samom rešenju, pa je tačnost rešenja prvi i eliminacioni kriterijum.

Ovaj zadatak se razrađuje samostalno, ali čini jednu od dve celine šireg poduhvata. Koleginica (Anđa Mitić, tema generisanja novih pitanja) radi odvojeno, dok je krajnji cilj da se oba rešenja objedine u jednu aplikaciju u kojoj postoje obe funkcionalnosti. Zbog toga se zajednička infrastruktura (sloj apstrakcije prema modelima, model podataka za evaluaciju i praćenje) projektuje usaglašeno od početka. Postupak objedinjavanja opisan je u posebnom dokumentu „Plan integracije i objedinjeni sistem".

## 2. Ciljevi zadatka

1. Projektovati i implementirati proširenje postojećeg sistema u vidu modula za integraciju jezičkih modela (u saradnji sa koleginicom Anđom Mitić, jer oba zadatka koriste istu infrastrukturu).
2. Implementirati oba režima rada (A i B) nad zadacima iz sistema.
3. Implementirati dvostrani modul za evaluaciju: student ocenjuje koliko mu je generisano objašnjenje pomoglo, a predmetni nastavnik ocenjuje ispravnost rešenja i objašnjenja; uz sistematično prikupljanje podataka o radu modela.
4. Uporediti najmanje tri besplatno dostupna jezička modela po jasno definisanim kriterijumima, odvojeno za svaki režim.
5. Izabrati najbolji model i obrazložiti izbor rezultatima evaluacije.

## 3. Arhitektura proširenja sistema

Pre same analize modela, sistem je potrebno proširiti odgovarajućim modulom. Preporučuje se sledeća struktura:

1. **Sloj apstrakcije prema modelima (provider layer).** Jedinstven interfejs iza koga stoje konkretne implementacije za svaki model/servis, tako da se modeli mogu menjati bez izmene ostatka sistema i porediti pod identičnim uslovima. Ovaj sloj projektovati i implementirati zajednički sa koleginicom.
2. **Modul za objašnjenja.** Prima zadatak (i rešenje, u režimu A), formira prompt prema definisanom šablonu i vraća strukturiran odgovor: u režimu A objašnjenje, u režimu B rešenje i objašnjenje kao odvojene celine.
3. **Radni tok odobravanja (review workflow).** Generisana objašnjenja se studentima prikazuju tek nakon što ih nastavnik pregleda i odobri. Sistem ni u jednom trenutku ne sme automatski da plasira neproveren sadržaj studentima — pogrešno objašnjenje je štetnije od izostanka objašnjenja.
4. **Dvostrani modul za evaluaciju (opisan u odeljku 5).** Omogućava studentu da oceni korisnost objašnjenja, a nastavniku da oceni ispravnost rešenja i objašnjenja.
5. **Sloj za prikupljanje i analitiku podataka (opisan u odeljku 6).** Svaka radnja generisanja i ocenjivanja se trajno beleži, čime se dobija skup podataka za uporednu analizu modela i za buduće naučne radove.
6. **Evidencija (logging).** Za svako generisanje čuvati: identifikator i verziju modela, prompt, parametre, sirov odgovor i ishod validacije, radi reproducibilnosti analize.

## 4. Predlog modela za poređenje

Poređenje treba da obuhvati najmanje tri modela, po mogućstvu iz obe kategorije:

**Besplatni API servisi (free tier):**

- Google Gemini (Flash varijante) — besplatan API nivo sa dnevnim limitima
- Groq — besplatan pristup otvorenim modelima uz veoma brz odziv
- Mistral AI — besplatan eksperimentalni API nivo
- OpenRouter — objedinjen pristup većem broju besplatnih modela; obratiti pažnju na modele jače u rezonovanju (npr. DeepSeek varijante), jer režim B zahteva tačno rešavanje zadataka

**Lokalno pokretani otvoreni modeli (preko alata Ollama ili LM Studio):**

- Llama 3.1 / 3.3
- Qwen 2.5 / Qwen 3 (uključujući Coder varijante ako zadaci obuhvataju programiranje)
- Gemma 3
- DeepSeek-R1 destilovane varijante (pogodne za zadatke koji traže rezonovanje)

Napomena: dostupnost i uslovi besplatnih nivoa se menjaju, pa je prvi korak zadatka provera aktuelne dostupnosti i limita, uz obavezno dokumentovanje tačne verzije svakog modela i datuma pristupa.

## 5. Dvostrana evaluacija generisanog sadržaja

Ključno proširenje ovog zadatka jeste mogućnost da se generisani sadržaj oceni iz dve perspektive: studentske (koliko je objašnjenje bilo korisno za učenje) i nastavničke (koliko je sadržaj ispravan i pedagoški valjan). Ove dve perspektive mere različite stvari i ne smeju se mešati: korisno objašnjenje koje je stručno netačno je opasno, a tačno objašnjenje koje student ne razume promašuje svrhu. Prikupljanje obe vrste ocena omogućava da se to odvojeno prati.

### 5.1. Studentska ocena (percepcija korisnosti)

Nakon što student pogleda objašnjenje, može ga oceniti po sledećim stavkama (Likertova skala, npr. 1–5, uz opcioni komentar):

1. **Korisnost:** koliko mu je objašnjenje pomoglo da razume zadatak.
2. **Jasnoća:** da li je objašnjenje razumljivo i primereno njegovom nivou.
3. **Percepcija naučenog:** da li smatra da sada bolje razume gradivo.

Ove ocene su subjektivne i mere doživljaj studenta, što je legitiman i važan pokazatelj upotrebljivosti, ali same po sebi ne govore o tačnosti sadržaja.

### 5.2. Nastavnička ocena (ispravnost i kvalitet)

Predmetni nastavnik ocenjuje isti sadržaj po objektivnijim kriterijumima:

1. **Tačnost rešenja (u režimu B, eliminaciona stavka):** da li je generisano rešenje tačno; proverava se mehanički gde god je moguće (poređenje sa poznatim rešenjem, a za programske zadatke izvršavanje koda i automatski testovi).
2. **Tačnost objašnjenja:** da li je obrazloženje činjenično korektno i bez izmišljenih koraka.
3. **Vernost (faithfulness):** da li objašnjenje zaista odgovara rešenju koje prati, bez protivrečnosti.
4. **Potpunost:** da li su pokriveni svi ključni koraci postupka.
5. **Pedagoška vrednost:** postupnost, primerenost nivou, ukazivanje na tipične greške.
6. **Jezička ispravnost i preciznost terminologije.**

Posebno se obeležava rizični slučaj u kome je studentska ocena korisnosti visoka, a nastavnička ocena tačnosti niska — to jest, uverljivo ali netačno objašnjenje. Takvi slučajevi su najvažniji nalaz za bezbednu primenu sistema u nastavi.

## 6. Podaci i pokazatelji za praćenje (za naučne izveštaje)

Da bi sistem služio kao izvor podataka za buduće radove, potrebno je da za svaki događaj beleži dovoljno konteksta i da omogući izračunavanje zbirnih pokazatelja.

### 6.1. Podaci koji se beleže po događaju

- **Poreklo generisanja (provenance):** identifikator i verzija modela, verzija prompta, režim (A ili B), parametri, vremenska oznaka.
- **Ulaz i izlaz:** referenca na zadatak (i rešenje u režimu A), sirov odgovor modela, isparsiran rezultat (rešenje i objašnjenje odvojeno), ishod validacije formata i, u režimu B, ishod mehaničke provere tačnosti rešenja.
- **Tehnički pokazatelji:** vreme odziva, broj utrošenih tokena (gde je dostupno), broj ponavljanja zahteva.
- **Studentska evaluacija:** identifikator studenta (anonimizovan), ocene korisnosti/jasnoće/percepcije, komentar.
- **Nastavnička evaluacija:** identifikator ocenjivača, ocene po stavkama iz 5.2, konačna odluka (odobreno / izmenjeno / odbačeno) i eventualni izmenjeni tekst.

### 6.2. Zbirni pokazatelji za poređenje modela

- **Tačnost rešenja u režimu B** (udeo tačnih), po modelu — osnovni pokazatelj upotrebljivosti u tom režimu.
- **Prosečne nastavničke ocene po dimenzijama** (tačnost objašnjenja, vernost, potpunost, pedagoška vrednost), po modelu i po režimu.
- **Prosečne studentske ocene korisnosti** i njihova raspodela, po modelu.
- **Neslaganje perspektiva:** učestalost slučajeva „visoka korisnost / niska tačnost" i njihova korelacija — po modelu.
- **Stopa formalne ispravnosti** (validan format iz prve) i **stopa odobravanja** od strane nastavnika.
- **Tehnički pokazatelji:** prosečno vreme odziva, stabilnost, ograničenja besplatnog nivoa.
- **Saglasnost ocenjivača** (ako je više nastavnika ocenjivalo), radi procene pouzdanosti ocena.

Ovi pokazatelji se generišu skriptom iz zabeleženih podataka, tako da tabele i grafikoni u radu uvek odgovaraju izvornim podacima.

## 7. Metodologija evaluacije

1. **Referentni skup zadataka.** Izdvojiti reprezentativan skup zadataka sa proverenim tačnim rešenjima (preporuka: 20–30 zadataka različitih tipova i težina). Isti skup koristiti za sve modele i oba režima.
2. **Identičan protokol.** Svi modeli dobijaju identične promptove i podešavanja; svaki zadatak se obrađuje istim brojem pokušaja kod svakog modela.
3. **Slepo ocenjivanje.** Prilikom ručnog ocenjivanja kvaliteta objašnjenja, ocenjivač ne sme da zna koji je model autor (odgovori se mešaju i anonimizuju).
4. **Tehničke karakteristike.** Zabeležiti vreme odziva, procenat odgovora u neispravnom formatu, ograničenja besplatnog nivoa i praktičnost integracije.

## 8. Obezbeđivanje ispravnosti rešenja

- Napisati automatsku validacionu skriptu koja proverava strukturu svakog odgovora modela (odvojeno rešenje i objašnjenje, neprazna polja, očekivani format) sa jasnim ishodom PASS/FAIL.
- Za programske zadatke pripremiti automatske testove kojima se generisana rešenja izvršavaju i proveravaju — tačnost rešenja ne sme da se ocenjuje „od oka".
- Testirati ponašanje modula u graničnim slučajevima: nevalidan odgovor modela, nedostupan servis, prekoračen limit. Sistem mora da reaguje kontrolisano, uz smislenu poruku korisniku.
- Rezultate evaluacije voditi u tabelarnom obliku (CSV ili slično) iz koga se tabele i grafikoni generišu programski, čime se obezbeđuje da su brojevi u tekstu, tabelama i figurama uvek usaglašeni.
- Ceo eksperiment mora biti ponovljiv na osnovu dokumentacije.

## 9. Očekivani rezultati

1. Prošireni web sistem sa funkcionalnim modulom za oba režima rada, radnim tokom nastavničkog odobravanja i dvostranim modulom za evaluaciju.
2. Model podataka i sloj za prikupljanje podataka koji omogućavaju praćenje rada modela i izradu izveštaja.
3. Dokumentovan skup promptova, validaciona skripta i testovi za proveru tačnosti rešenja.
4. Uporedna analiza modela po režimima: tabelarni i grafički prikaz rezultata, sa diskusijom.
5. Izbor najboljeg modela sa obrazloženjem, uz osvrt na rizike (pre svega netačna rešenja u režimu B) i predlog mera zaštite u produkcionoj upotrebi.
6. Pisani izveštaj u akademskom stilu, pripremljen tako da može poslužiti kao osnova za budući naučni rad.

## 10. Preporučeni tok rada

1. Analiza postojećeg sistema i projektovanje modula (zajednički deo sa koleginicom, uključujući zajednički model podataka za evaluaciju).
2. Implementacija sloja apstrakcije i integracija prvog modela; uspostavljanje funkcionalnog toka kraj-na-kraj za režim A (jednostavniji režim).
3. Definisanje prompt šablona i strukture izlaza; iterativno usavršavanje na malom uzorku.
4. Proširenje na režim B i priprema automatske provere tačnosti rešenja.
5. Implementacija dvostranog modula za evaluaciju i sloja za prikupljanje podataka.
6. Priključivanje preostalih modela i sprovođenje evaluacije po protokolu iz odeljka 7.
7. Obrada rezultata, izbor modela, izrada tabela i grafikona, pisanje izveštaja.

Za smernice o efikasnom korišćenju AI asistenta (Claude) tokom razvoja, pogledati prateći dokument „Vodič za rad sa Claude-om". Za postupak objedinjavanja sa rešenjem koleginice, pogledati dokument „Plan integracije i objedinjeni sistem".
