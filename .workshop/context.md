# Tourist Agency Admin System — Context (compressed)

## Cenovnici — opcija „Kopiraj cene“ (2026-10-15, commit 7c29d3b)
- Checkbox „Kopiraj cene“ iznad matrice (u `UrednikCenovnika`, unutar grane gde ima soba+perioda; id `create-kopiraj` / `edit-kopiraj`; disabled kad je editor zaključan). JEDNO shared state `kopirajCene` za oba taba (ostaje čekiran preko resetovanja drafta — namerno)
- Kada je čekiran: svaki unos (`postaviCreateCenu`/`postaviEditCenu` → `ceneSaKopiranjem(prev, sobe, sobaId, periodId, vrednost)`) upisuje vrednost i u sve ostale sobe šablona sa istim `tip` + `opis` + isto `virtuelna` (realna→realne, virtuelna→virtuelne); SAMO isti period (kolona); `opis_dodatno` se NE gleda; `ceneSaKopiranjem` je čista fn pomoću koje se pravi novi Record —Radi i pri paste. Nema kopiranja unazad (postojeće vrednosti ciljnih ćelija se pregaze novom vrednošću)
- ELENI 2 primer: soba 12 (1/3·STD) → 18, 21, 22, 23, 24, 25, 26, 5, 6; v12 (1/2·STD) → v18, v21…, v5, v6; soba 31 (1/4+1·MEZ) nema parova → ostaje samo njoj
- Payload dolazi automatski (cene state već sadrži kopirane vrednosti); snapshot/dirty-guard se ponaša normalno
- Test `test_cenovnici_kopiraj.py` (20 provera): UI kreiranje (kopiranje realne/virtuelne, negativi, isključeno = bez kopiranja), POST payload (22 cene: 10×123 + 10×77 + 31=90 + 23 P2=55), tab Izmena (unos 150 sa kopiranjem, PUT → 150/77/90/55). Cleanup DELETE kroz API

## Stack
- React 19 + TS + Vite 7 + Tailwind + shadcn/ui; FastAPI + SQLAlchemy + eksterni Neon (`EXTERNAL_NEON_DATABASE_URL`)
- `verbatimModuleSyntax: true` → `import type` obavezno
- posle svake frontend izmene: `bun run build` = `tsc -b && vite build` — **OBAVEZNO sa tsc**: publish na serveru pokreće build iz package.json, TS greške obaraju deploy pa live verzija ostaje stara (dev `bunx --bun vite build` preskače tip-proveru — zato se greške ne vide lokalno)

## Konvencije
- `aranzman.kljuc` uvek `<broj>/<godina>`; import normalizuje gol broj → `/26`
- Import API: `http://188.255.223.36/api/uplatejson.php?ugovor=<gol broj>` (bez "/26" — ODBC)
- Obračun: `calc_ugovor_values` (EUR) / `calc_ugovor_d_values` (din) u routes.py; kurs kurs.resenje.org `exchange_middle`, keš `EUR_RATE_CACHE`
- Predračun numeracija: 0 → broj ugovora; n>0 → `{base}-{n}/{god}`
- JOIN subagenti uvek sa `AND s.naziv <> ''`
- Beskonačna skrola: IntersectionObserver (600px) + requestId guard + BATCH 100, debounce 400ms
- Playwright testovi: uvek `PLAYWRIGHT_BROWSERS_PATH=/tmp/pw-browsers` prefiks (sandbox setuje /usr/local/share/playwright koji je prazan; `os.environ.setdefault` u testu NE pomaže jer env već ima praznu vrednost); kalendar Radix → `[data-radix-popper-content-wrapper]`; posle sandbox restarta browseri nestaju → `PLAYWRIGHT_BROWSERS_PATH=/tmp/pw-browsers uv run playwright install chromium`

## Koeficijenti prodaje (/agencija/koeficijenti, Sigma ikona, posle Cenovnika)
- Tabela `koeficijenti_prodaje`: id SERIAL, struktura TEXT, adl/chd/inf INT 0-99, koeficijent DOUBLE PRECISION (finite, <1e6), rucno BOOLEAN, created/updated_at; `koeficijenti_api.py` + registracija u routes.py (init_koeficijenti + register_koeficijenti)
- Strukture se čitaju iz `sobe.tip` (DISTINCT, TRIM, prazne se ignorišu) — 12 struktura (1/2, 1/2 ECO, 1/2+1, 1/3, ... 1/6); svaka se prikazuje JEDNOM; struktura bez zapisa = auto-red sa nulama (merge u memoriji pri GET, persistira pri Sačuvaj)
- Ručni redovi (rucno=TRUE): "Dodaj red" → Select strukture (opcije = strukture iz soba + već upisane), više zapisa za istu strukturu dozvoljeno; trash samo na ručnim redovima; auto redovi struktura = tekst
- PUT = dif-based (čuva ID-jeve): DELETE obrisanih, UPDATE po id, INSERT novih; atomično u transakciji; nepoznat id → 400; vraća kanonsko stanje {strukture, redovi}
- Sortiranje struktura: regex `^(\d+)/(\d+)(.*)$` → (num1, num2, sufiks) — varijante (1/3 ECO, 1/3+1) ostaju pored osnovne
- Validacija na klijentu ogleda server (ceo broj 0-99, koef najviše 4 decimale, zarez→tačka SAMO za koeficijent, prazno=0); greška → toast + PUT se NE šalje + unos ostaje kako je kucan
- Dirty-guard: isti AlertDialog mehanizam kao Cenovnici (beforeunload + document click capture + "Odbaciti nesačuvane izmene?")
- Test: `test_koeficijenti_api.py` + `test_koeficijenti_ui.py` (Playwright; ručni red posle save-a tražiti preko filter(has=combobox) + get_by_role("textbox").nth(), NE po labeli sa red-br — sortiranje menja poziciju)

## Sobe (/agencija/sobe) + koeficijenti (2026-10-14, commit 90d6035; ispravka e499863)
- GET /sobe vraća i `mesto_naziv` (JOIN mesto) i `koeficijenti` kao NAZIVE (string[]): osnovni = soba.tip + dodati iz `soba_koeficijenti` (id, soba_id FK CASCADE, struktura, UNIQUE(soba_id,struktura)); server q-pretraga uključuje m.naziv
- POST /sobe i PUT /sobe (promena tipa) pozivaju `osiguraj_auto_red(conn, tip)` — soba 1/2 inicijalno dobija koeficijent (zapis sa vrednostima) 1/2 na Koeficijentima prodaje; druga soba istog tipa ne duplira red
- Koeficijent (naziv) = polje struktura iz koeficijenti_prodaje; kolona Sobe prikazuje nazive "1/2 · 1/3" (NE vrednosti)
- Endpointi: GET /sobe/{id}/koeficijenti → {tip, dodati[]}; POST /sobe/{id}/koeficijenti {struktura} (400: dupliran/osnovni/nedefinisan — definisan = postoji u sobe.tip ili koeficijenti_prodaje); DELETE /sobe/{id}/koeficijenti?struktura= (osnovni → 400, nepoznat → 404); GET /koeficijenti/struktura?struktura= i POST /koeficijenti/red + DELETE /koeficijenti/red/{id} (rucno-only) i dalje postoje
- SobePage: kolone Smeštaj | Mesto | Broj sobe | **Tip (opis)** (spojene, commit bc1840f — "1/2 (STD)", pun opis na hover) | Koeficijenti (dugme sa nazivima) | Status | Akcije; dialog: lista naziva sa Badge Osnovni/Dodatni, trash samo na dodatnim, "Dodaj koeficijent" → Select definisanih naziva (GET /koeficijenti strukture ∪ redovi struktura, minus već dodate)
- Test: `test_sobe_koeficijenti_ui.py` (kreira sobu TST/8 preko UI-ja, testira naziv u koloni, dialog, dodatni 1/2, brisanje; čisti svoje podatke); sheet polja NEMAJU programski vezane labele → test koristi get_by_placeholder; red ima 3 dugmeta (koef, pencil, trash=button.text-destructive)

## Pretraga (/prodaja/pretraga) — vezivanje Grupe termina za vilu (2026-10-14, commit d51b08f)
- `/slobodne-sobe?mesto_id=&datum_od=&datum_do=`: smeštaj prolazi SAMO ako njegova grupa termina (`smestaj.grupa_datuma`) definiše TAČAN termin — EXISTS `period_datum pd WHERE pd.grupa_id = s.grupa_datuma AND pd.datum_od = :od AND pd.datum_do = :do` (EXACT match, ne containment — grupa 15 ima 19.06→29.06 (10 noći) pa 22.06→29.06 NE sme proći); + postojeća provera zauzeća (aranzman po nazivu vile + soba, overlap)
- Isti naziv vile = više instanci smeštaja (po jedna po grupi, npr. ELENI 2 id=10 grupa 6 + id=38 grupa 15); rezultat je sekcija po instanci; zauzeće se i dalje gleda po nazivu (legacy) pa instanca iste vile dele zauzeće
- Test `test_pretraga_termin.py`: API == SQL ground-truth za 22.06→29.06 (grupa 17), 24.06→04.07 (grupa 6), 19.06→29.06 (grupa 15); ELENI 2/ELENI 2 C/PENNY C ne smeju za 22.06; 401 bez tokena
- UI Playwright: kalendar se otvara u tekućem mesecu → "Sledeći mesec" navigacija; dani NEMAJU aria-label (filter has_text); nakon izbora dana popover OSTAJE otvoren — ne klikati trigger ponovo; dugme je "Pretraži" (ne "Pretraga"); TrajanjeOpcije dugme "7 noćenja | Povratak: ..." klik sa force=True (transition nestabilnost)

## Cenovnici — bez FK veza (2026-10-15)
- ODLUKA KORISNIKA: cenovnik NE nosi FK constraintove — samo id-jevi kao obične kolone: `cenovnici.mesto_id/grupa_id/smestaj_id` (NOT NULL) i `cenovnik_cene.soba_id` (NOT NULL). FK-ovi iz commita c14c222 su vraćeni (revert e76345b) i constrainti `fk_{table}_{col}` su ručno DROP-ovani iz baze
- NE dodavati ponovo FK na ove kolone; `init_cenovnici` kreira samo tabele. Grupa termina = `period_grupa(id)` (NE mesto_grupa); POST /cenovnici validira povezanost kroz `_sablon` (mesto-grupa-smestaj kombinacija mora postojati); JSONB sobe/periodi = snimak
- Brisanje mesta/smeštaja/sobe/grupe termina je bez ograničenja (nema 409) — cenovnik zadržava JSONB snimak kao istoriju

## Cenovnici — virtuelne sobe (2026-10-15, commit 77e0192)
- Kod kreiranja cenovnika (`_sablon` u cenovnici_api.py): za svaku sobu sa dodatnim koeficijentima (`soba_koeficijenti`) kreira se "virtuelna soba" ODMAH ISPOD nje — broj `v{broj_sobe}` (jedan dodatni koef) ili `v{broj}-1`, `v{broj}-2`… (više njih), tip = struktura iz koeficijenta, opis/opis_dodatno preuzeti iz izvorne sobe; red omogućava unos cena kao i svaki drugi
- Smestanje: u ISTOM JSONB snimku `cenovnici.sobe` (odluka: posebna tabela nepotrebna) — virtuelni red ima `id` NEGATIVAN (samo unutar cenovnika, -1, -2… deterministički pa preview==POST), `izvor_soba_id` (veza sa sobom od koje je nastala) i `virtuelna: true`; NE upisuje se u tabelu sobe
- `_save_values` validira soba_id protiv snimka pa negativni id-jevi prolaze, nepoznati → 400; PUT menja cene virtuelnih sobi normalno; postojeći cenovnici (pre feature-a) nemaju virtuelne redove — snimak se ne regeneriše pri izmeni
- UI: SablonSoba ima opciona `izvor_soba_id`/`virtuelna`; virtuelni red = bg-violet-500/5 + broj kao VIOLET PILL (rounded-full border-violet-500/40 bg-violet-500/10 text-violet-600 italic text-[11px], commit 470bb71) + 2px leva violet linija na sticky ćeliji + tooltip "Virtuelna soba — nastala iz sobe {izvor_soba_id}"; aria-label ćelije "Cena — soba v12, …"; STICKY ĆELIJE (Broj/Struktura) MORAJU biti bg-card (neprozirne) — tint ide kao `absolute inset-0 -z-10 bg-violet-500/5` overlay span unutar ćelije (commit b5205d4): direkt bg-violet-500/5 na sticky ćeliji je PROZIRAN pa se cena polja vide kroz njih pri horizontalnom skrolu
- Primer iz podataka: ELENI 2 soba 12 (1/3 STD, dodatni 1/2) → red v12 (1/2 · STD); soba 31 (1/4+1 MEZ, dodatni 1/4 i 1/3) → v31-1, v31-2
- Test `test_cenovnici_virtuelne.py` (API + UI, 17 provera): v901-1/v901-2 (2 koefa), v902 (1 koef), ništa (0 koefa), negativan id + izvor_soba_id, POST sa cenom na virtuelnoj → 201 i sačuvano, PUT → izmena, lažan id → 400, UI ELENI 2: v12 ispod 12 sa strukturom "1/2 · STD"; cleanup: DELETE cenovnik API + DELETE privremenih soba (broj_sobe 901-903, smestaj 8) — IN :ids sa tuple NE RADI u text(), koristiti direktno `broj_sobe IN ('901',...)`

## Cenovnici — Opis cenovnika (2026-10-15, commit dedc340)
- Nova kolona `cenovnici.opis` TEXT NOT NULL DEFAULT '' (init: CREATE + `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`); ide UZ cenovnik (putuje sa njim)
- Backend: `CenovnikIzmena.opis: str | None = None` (None = PUT NE dira postojeći opis — kompatibilnost sa starim klijentima/testovima), `CenovnikNovi.opis: str = ""`; validator strip + max 500 znakova (prekoračenje → 422); POST INSERT upisuje opis, `_save_values` radi UPDATE opisa kad nije None; `_sablon` vraća `"opis": ""`; `_detail` vraća opis kroz `c.*`; lista SELECT + q-pretraga pokriva i opis
- UI: OpcijeDatuma treći blok "Opis cenovnika" (Input id `{prefix}-opis`, w-72, maxLength 500, placeholder "npr. Termin 22.06–29.06, polazak iz Novog Sada") između Aktivan do i Sačuvaj; UrednikCenovnika prosleđuje `opisCenovnika`/`onOpisCenovnika` (stari `opis` prop = statički tekst CardDescription, ne mešati!); `snapshotStringa(cene, od, ddo, opis)` — dirty-guard uključuje opis; create: `createOpis` (reset u resetujCreateDraft, disabled kad je zaključano posle Sačuvaj); edit: `editOpis` puni se iz detail-a; red u listi taba Izmena prikazuje opis malim tekstom ispod naziva
- Test `test_cenovnici_opis.py` (15 provera): POST sa opisom + trim, lista vraća opis, PUT menja, PUT bez opisa ne dira, 501 znak → 422, POST bez opisa → "", UI: #create-opis uz datume, sačuvan u bazi posle POST-a, disabled kad je Zaključano, #edit-opis pokazuje sačuvani opis, izmena + Sačuvaj izmene → DB; cleanup DELETE kroz API

## Cenovnici — osvežavanje soba pri IZMENI (2026-10-15, commit 945940a)
- `_osvezi_sobe(conn, smestaj_id, stari_sobe=None, taguj_nove=False)` u cenovnici_api.py: realne sobe smeštaja iz žive baze + virtuelne po `soba_koeficijenti`; ako je dat stari snimak, virtuelna zadržava stari id dok se poklapa (izvor_soba_id, tip/struktura) — cene ostaju vezane za ispravan red; nove virtuelne dobijaju id ispod najnižeg starog; nestale (obrisana soba/ukonjen koef) nestaju. `_sablon` poziva je bez starog snimka (deterministički -1, -2… — preview==POST i dalje)
- GET /cenovnici/{id} (`_detail`) UVEK vraća osvežen spisak + `nova: true` na sobama čiji id nije u snimku (i realne i virtuelne); PUT (`izmeni`) nakon `_save_values` upisuje osvežen snimak nazad u `cenovnici.sobe` (bez `nova` tagova) — cene za nestale sobe briše se automatski ( postojeći DELETE-all + reinsert u `_save_values`)
- LEGACY cenovnici (pre virtuelnih soba) dobijaju virtuelne redove pri prvom otvaranju izmene; stara napomena "snimak se ne regeneriše" više ne važi
- UI: `SablonSoba.nova?` + mali violet italic "nova" tekst u Struktura ćeliji (nestaje posle Sačuvaj); edit tok prosleđuje ceo detail pa virtuelna/nova polja teku automatski
- Test `test_cenovnici_osvezavanje.py` (31 provera): dodat/uklonjen koeficijent (id čuvanje + labela v902→v902-1), dodata/obrisana prava soba, legacy snimak, UI (Izmena tab: red 905 + "nova", v902-2 pill, snimanje cene). ZAMKE: smeštaj 8 (DIMITRA) ima i PRAVE sobe 3/4/5 (soba 3 ima koef → v3!) — asercije filtrirati na TEMP_IDS; u edit editoru `get_by_role("textbox").first` pogađa #edit-opis/listu PRE nego se matrica renderuje (detail je async) → čekati row905/celiju eksplicitno pre count() provera; broj ćelije sadrži overlay span (sticky fix) pa pill class tražiti preko querySelectorAll

## Cenovnici — tab Izmena: zaključavanje, reset drafta, paginacija (2026-10-15, commit aa3d842)
- **Zaključavanje edit editora**: `editZakljucano` — posle "Sačuvaj izmene" cene + Aktivan od/do + opis disabled + badge "Zaključano" + dugme "Izmeni cenovnik" otključava (isto ponašanje kao create tab / createZakljucano); tek otvoren cenovnik uvek otključan (ucitajEdit resetuje); obrisiCenovnik resetuje
- **Reset drafta pri prelasku na Izmenu**: Tabs onValueChange — ako v==="izmena" i tab!=="izmena" → resetujCreateDraft() BEZ potvrde (čak i sa nesačuvanim izmenama; user zahtev: da cene dva editora ne preklapaju); izbori mesta/grupe/smeštaja ostaju
- **Paginacija liste cenovnika**: 5 po strani (STRANICA=5), lista je id DESC pa je strana 1 = poslednjih 5 kreiranih; `strana` state resetuje se na 1 pri promeni q (u debounce effect-u); footer (Prethodna/Sledeća + "Ukupno N · strana X od Y") samo kad ukupnoStrana>1; render clamp aktivnaStrana = min(strana, ukupnoStrana) pokriva brisanje/skupspremanje
- Test `test_cenovnici_edit_tab.py` (15 provera): draft reset bez AlertDialog-a + tabela nestala, paginacija (5 redova, najnoviji prvi, footer, Sledeća disabled na kraju, Prethodna, footer skriven kad pretraga da 1 rezultat), zaključavanje edit editora (disabled + badge + Izmeni cenovnik otključava). Batch privremenih cenovnika: n0=(5-n%5)+5 da garantuje strane; cleanup DELETE kroz API

## Rezervacije (RezervacijePage) — Sačuvaj/Izmeni (gotovo)
- Backend: `POST /rezervacije` (novi) + `PUT /rezervacije/{kljuc}` (izmena); numeracija MAX(broj) unutar godine iz datumod + 1; advisory lock + UNIQUE(kljuc) + retry
- `tipOpcije`: nepoznat tiprezervacije iz baze se dodaje u Select; CUVAR sentinel za sačuvane nazive van referentnih lista
- **Zauzeće termina (sudar)**: `_rez_proveri_konflikt` (isti smeštaj+soba+overlap datumod<do AND datumdo>od); 409; test `test_rezervacija_konflikt.py`

## Status
- 2026-10-15: Cenovnici — opcija „Kopiraj cene“: unos se usput kopira na sobe iste strukture+opisa (realne↔realne, virtuelne↔virtuelne), checkbox iznad matrice u oba editora (7c29d3b); tab Izmena: zaključavanje posle snimanja + reset drafta pri prelasku + paginacija liste 5/strani (aa3d842); osvežavanje soba pri izmeni: sobe/koeficijenti sinhronizovani sa snimkom pri otvaranju editora i snimanju, virtuelne čuvaju id, 'nova' oznaka (945940a); virtuelne sobe vizuelno obeležene violet pill oznakom broja + tint reda (470bb71); Opis cenovnika uz Aktivan od/do + izmena u tabu Izmena (dedc340); virtuelne sobe po dodatnim koeficijentima (77e0192); FK veze vraćeno (revert e76345b), ostaju samo id-jevi bez constrainta; brisanje mesta/smeštaja/sobe/grupe bez ograničenja; tabovi veći (deed2bc)
- 2026-10-14: Pretraga — vezivanje Grupe termina za vilu u /slobodne-sobe (commit d51b08f); Sobe Tip+Opis spojene (bc1840f); Koeficijenti prodaje (6fcacfb); grafik tooltip fix (2be1415)
- 2026-10-13: Cenovnici (/agencija/cenovnici) — dva taba (Kreiranje + Izmena); `cenovnici_api.py`: tabele cenovnici (id + UUID UNIQUE, naziv mesto-smestaj-grupa, mesto_id/grupa_id/smestaj_id NOT NULL, sobe/periodi JSONB SNIMAK), cenovnik_opcije (datumod/do), cenovnik_cene (NUMERIC 14,2, soba_id → sobe); cena = ceo termin (osnova po sobi/osobi KASNIJE kroz opcije); više cenovnika po istoj kombinaciji; MatricaCena 76px kolone, cene cele bez .00 centrirane, header datumi bez godine jedan ispod drugog; DatumCenovnika (react-day-picker srLatn, weekStartsOn=1, dd.mm.yyyy prikaz, labele IZNAD); dirty-guard AlertDialog; **tabovi h-14 px-7 16px semibold (d49f49a); zaključavanje: posle Sačuvaj cene + Aktivan od/do disabled + badge "Zaključano" + dugme "Izmeni cenovnik" otključava (createZakljucano state; novi šablon uvek otključan; test test_cenovnici_zakljucavanje.py, cleanup SQL DELETE cenovnici — CASCADE)**; **brisanje: DELETE /cenovnici/{id} (404 nepoznat; cene/opcije CASCADE) + korpa u redu liste taba Izmena → AlertDialog "Obrisati cenovnik?" sa "Brisanje je trajno i ne može se opozvati." → Obriši trajno briše red, čisti editor ako je otvoren; test test_cenovnici_brisanje.py (red selektuj po cell name=exact ID — naziv vile nije unique, UUID sadrži cifre)**
- 2026-10-12: grafik Grupa termina scoping (aranzman.smestaj_id + legacy fallback); import soba Kasandra grupe 15/16/17; 21 TS grešaka popravljenо
- Gotovo: Ugovori, Subagenti, Predračuni, import, Izvodi, Rezervacije (Sačuvaj/Izmeni + zaključavanje), Grafik (sticky header datumi, pojasevi jedan red, broj na prvom periodu, Klasična/Brza rezervacija popup), Mesto multi-grupe, Pretraga
- Navigacija: Agencija → Prodaja (TrendingUp) → Knjigovodstvo → Podešavanje; Prodaja: Pretraga, Ugovori, Grafik (/agencija/grafik)
- Mesto: više grupa perioda (`mesto_grupa`); /slobodne-sobe prima mesto_id; Pretraga spaja periode svih grupa
- aranzman_dopuna (saputnici split); GET /ugovori/{kljuc} vraća putnici_detalji + smer
- Grafik klik slobodno → /prodaja/rezervacije?novi=1&...; GrafikPage prefill efekt čita parametre JEDNOM (prefillPrimenjen ref)
- Uplate (tabela uplate), PDF-ovi (predracun, uplate, priznanica, ugovor, dnevni izvestaj), Polazak (prevoz), Prava (prodaja-tip)
- Dev server: `./start.sh` (Vite $APP_PORT=3058, backend 3158); publikovana verzija se NE gradi automatski — user klikće Publish