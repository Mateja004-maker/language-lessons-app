# Vodič za rad sa Claude-om tokom izrade projektnog zadatka

**Namena:** zajednički dokument za studente Anđu Mitić i Andreja Ćirića
**Kontekst:** proširenje web sistema za onlajn testiranje modulima zasnovanim na jezičkim modelima

## 1. Uvod

AI asistent (Claude, bilo kroz Claude Code u terminalu, bilo kroz web interfejs) može značajno da ubrza razvoj, ali kvalitet rezultata direktno zavisi od načina na koji se koristi. Ovaj dokument daje praktična pravila koja treba poštovati tokom rada na zadatku. Osnovno načelo glasi: **asistent predlaže, student proverava i odlučuje.** Odgovornost za tačnost koda, rezultata i teksta rada je uvek na studentu.

Dokument je zajednički za oba zadatka (generisanje pitanja i generisanje rešenja/objašnjenja). Iako se teme razrađuju odvojeno, krajnji cilj je jedinstvena aplikacija sa obe funkcionalnosti, pa se od početka radi na usaglašenoj zajedničkoj osnovi; postupak spajanja opisan je u dokumentu „Plan integracije i objedinjeni sistem".

## 2. Priprema projekta za rad sa asistentom

1. **Napraviti datoteku `CLAUDE.md` u korenu projekta.** U nju upisati: kratak opis sistema, strukturu direktorijuma, tehnologije, komande za pokretanje/build/testiranje, kao i pravila specifična za projekat. Asistent tu datoteku čita na početku svake sesije, pa se time izbegava ponavljanje istog konteksta.
2. **Dopunjavati `CLAUDE.md` tokom rada.** Kada asistent (ili student) napravi grešku koja se može ponoviti, iz nje izvesti pravilo i upisati ga u `CLAUDE.md`, kako se ista greška ne bi ponavljala u narednim sesijama.
3. **Koristiti sistem za verzionisanje (git) od prvog dana.** Male, česte commit-e sa jasnim porukama. Time se svaka izmena koju asistent predloži može bezbedno isprobati i po potrebi vratiti.

## 3. Kako formulisati zahtev (prompt) asistentu

Kvalitetan zahtev sadrži četiri elementa:

1. **Kontekst** — šta je sistem, koji deo se menja, koje tehnologije se koriste (ako `CLAUDE.md` postoji, veći deo konteksta je već pokriven).
2. **Cilj** — šta tačno treba da se postigne, jednim jasnim iskazom.
3. **Ograničenja** — šta ne sme da se menja, koji stil koda se prati, koje biblioteke su dozvoljene.
4. **Kriterijum uspeha** — kako će se proveriti da je rešenje ispravno (test, primer ulaza i očekivanog izlaza, ponašanje u graničnom slučaju).

Primer slabog zahteva: „Dodaj AI u moj projekat."

Primer dobrog zahteva: „U postojećem Laravel projektu (struktura opisana u CLAUDE.md) dodaj servisnu klasu `QuestionGeneratorService` koja preko postojećeg interfejsa `LlmProvider` šalje prompt i vraća listu pitanja kao validiran JSON. Ne menjaj postojeće kontrolere. Uspeh: jedinični test koji za zadati primer ulaza vraća strukturno ispravan rezultat prolazi."

## 4. Preporučeni radni tok

1. **Prvo plan, pa kod.** Za svaku veću izmenu najpre zatražiti od asistenta plan (koje datoteke se menjaju, kojim redom, kakav je rizik), pregledati ga i tek onda odobriti implementaciju. U Claude Code alatu za ovo postoji poseban režim planiranja (plan mode).
2. **Male iteracije.** Jedan zahtev — jedna zaokružena celina koja se može testirati. Izbegavati zahteve tipa „implementiraj ceo modul odjednom".
3. **Provera posle svakog koraka.** Nakon svake izmene pokrenuti aplikaciju i testove. Nikada ne prihvatati više uzastopnih neproverenih izmena, jer se greška tada teško locira.
4. **Tražiti objašnjenje.** Kada asistent predloži kod koji student ne razume u potpunosti, zatražiti objašnjenje pre prihvatanja. Na odbrani rada student mora umeti da objasni svaku liniju svog sistema.
5. **Koristiti asistenta i kao recenzenta.** Posle implementacije zatražiti kritički pregled: „Pronađi greške, granične slučajeve i bezbednosne propuste u ovoj izmeni." Predloge recenzije tretirati kao hipoteze koje se proveravaju, ne kao gotove činjenice.

## 5. Pravila verifikacije (obavezna)

1. **Nijedna tvrdnja ne ulazi u rad neproverena.** Broj se reprodukuje skriptom, kod se pokreće i testira, referenca se proverava u izvoru. Formulacije „verovatno" i „čini se" nisu prihvatljive u izveštaju.
2. **Asistent može da izmisli sadržaj (halucinacija).** Nazivi biblioteka, parametri API-ja, limiti besplatnih nivoa i bibliografske reference moraju se proveriti u zvaničnoj dokumentaciji. Ovo posebno važi za podatke o modelima, jer se oni brzo menjaju.
3. **Ponovljena provera = skripta.** Ako se ista provera radi drugi put ručno, vreme je da se napiše skripta sa jasnim ishodom PASS/FAIL. Validacija formata generisanih pitanja, provera tačnosti rešenja i konzistentnost rezultata u tabelama tipični su kandidati.
4. **Izmene koje ne smeju da promene ponašanje moraju to da dokažu.** Pri refaktorisanju uporediti izlaze sistema pre i posle izmene na istom ulaznom skupu.
5. **Brojevi moraju biti usaglašeni kroz ceo rad.** Pri svakoj izmeni rezultata pretražiti stare vrednosti u tekstu, tabelama i figurama. Najbolja zaštita: tabele i grafikoni se generišu programski iz jedne izvorne datoteke sa rezultatima.

## 6. Saveti specifični za rad sa jezičkim modelima u ovom zadatku

1. **Strukturiran izlaz.** Od modela uvek zahtevati odgovor u strogo definisanom JSON formatu i taj format programski validirati. Odgovor koji ne prolazi validaciju se odbacuje i beleži, a zahtev se po potrebi ponavlja.
2. **Verzionisanje promptova.** Promptove čuvati kao datoteke u repozitorijumu (ne u kodu razbacane niske) i menjati ih kroz git, kako bi se znalo koja verzija prompta je dala koje rezultate.
3. **Few-shot primeri.** U prompt uključiti jedan do dva primera željenog ulaza i izlaza — po pravilu značajno popravlja doslednost formata i kvalitet sadržaja.
4. **Kontrola parametara.** Zabeležiti i fiksirati parametre generisanja (pre svega temperaturu) tokom evaluacije; poređenje modela sa različitim podešavanjima nije validno.
5. **Odvojiti razvoj od evaluacije.** Prompt se usavršava na malom razvojnom uzorku, a konačna evaluacija se sprovodi jednom, na referentnom skupu, bez naknadnog podešavanja. U suprotnom rezultati poređenja nisu verodostojni.
6. **Očekivati i meriti neuspehe.** Procenat nevalidnih odgovora je legitiman rezultat poređenja, a ne smetnja koju treba prećutati.
7. **Prikupljanje podataka je deo sistema, ne naknadna misao.** Oba zadatka zahtevaju modul za ljudsku evaluaciju (nastavnik ocenjuje kvalitet i ispravnost, a kod objašnjenja i student ocenjuje korisnost) i trajno beleženje svake ocene i svakog generisanja. Ovi podaci su osnova za uporednu analizu modela i za buduće naučne radove, pa model podataka treba projektovati pažljivo i od početka (vidi „Plan integracije i objedinjeni sistem"). Svaki zapis mora imati dovoljno konteksta (koji model, koja verzija prompta, koji parametri, koja ocena) da rezultat kasnije bude reproducibilan i da se pokazatelji mogu izračunati skriptom.

## 7. Akademski integritet

1. U radu jasno opisati ulogu AI asistenta u razvoju, u skladu sa pravilima fakulteta.
2. Asistent je alat za razvoj i proveru, a ne autor rada: analizu rezultata, diskusiju i zaključke student piše samostalno i mora umeti da ih brani.
3. Svi eksperimentalni rezultati u radu moraju poticati iz stvarno sprovedenih merenja, evidentiranih u repozitorijumu projekta.

## 8. Kontrolna lista pre predaje

1. Sistem se podiže i svi testovi prolaze na čistom okruženju, prateći isključivo uputstva iz dokumentacije.
2. Validaciona skripta prolazi (PASS) nad konačnim skupom generisanih rezultata.
3. Svi brojevi u tekstu, tabelama i figurama potiču iz iste izvorne datoteke sa rezultatima.
4. Sve reference i tvrdnje o modelima proverene su u zvaničnim izvorima, sa navedenim datumom pristupa.
5. `CLAUDE.md` i prateća dokumentacija odražavaju stvarno stanje projekta.
