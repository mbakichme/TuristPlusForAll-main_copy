# Tourist Agency Admin System — Context (compressed)

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
- Playwright testovi: uvek `PLAYWRIGHT_BROWSERS_PATH=/tmp/pw-browsers` prefiks (sandbox setuje /usr/local/share/playwright koji je prazan; `os.environ.setdefault` ne pomaže); kalendar Radix → `[data-radix-popper-content-wrapper]`

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

## Rezervacije (RezervacijePage) — Sačuvaj/Izmeni (gotovo)
- Backend: `POST /rezervacije` (novi) + `PUT /rezervacije/{kljuc}` (izmena); numeracija MAX(broj) unutar godine iz datumod + 1; advisory lock + UNIQUE(kljuc) + retry
- `tipOpcije`: nepoznat tiprezervacije iz baze se dodaje u Select; CUVAR sentinel za sačuvane nazive van referentnih lista
- **Zauzeće termina (sudar)**: `_rez_proveri_konflikt` (isti smeštaj+soba+overlap datumod<do AND datumdo>od); 409; test `test_rezervacija_konflikt.py`

## Status
- 2026-10-14: Pretraga — vezivanje Grupe termina za vilu u /slobodne-sobe (commit d51b08f); Sobe Tip+Opis spojene (bc1840f); Koeficijenti prodaje (6fcacfb); grafik tooltip fix (2be1415)
- 2026-10-13: Cenovnici (/agencija/cenovnici) — dva taba (Kreiranje + Izmena); `cenovnici_api.py`: tabele cenovnici (id + UUID UNIQUE, naziv mesto-smestaj-grupa, sobe/periodi JSONB SNIMAK), cenovnik_opcije (datumod/do), cenovnik_cene (NUMERIC 14,2); cena = ceo termin (osnova po sobi/osobi KASNIJE kroz opcije); više cenovnika po istoj kombinaciji; MatricaCena 76px kolone, cene cele bez .00 centrirane, header datumi bez godine jedan ispod drugog; DatumCenovnika (react-day-picker srLatn, weekStartsOn=1, dd.mm.yyyy prikaz, labele IZNAD); dirty-guard AlertDialog
- 2026-10-12: grafik Grupa termina scoping (aranzman.smestaj_id + legacy fallback); import soba Kasandra grupe 15/16/17; 21 TS grešaka popravljenо
- Gotovo: Ugovori, Subagenti, Predračuni, import, Izvodi, Rezervacije (Sačuvaj/Izmeni + zaključavanje), Grafik (sticky header datumi, pojasevi jedan red, broj na prvom periodu, Klasična/Brza rezervacija popup), Mesto multi-grupe, Pretraga
- Navigacija: Agencija → Prodaja (TrendingUp) → Knjigovodstvo → Podešavanje; Prodaja: Pretraga, Ugovori, Grafik (/agencija/grafik)
- Mesto: više grupa perioda (`mesto_grupa`); /slobodne-sobe prima mesto_id; Pretraga spaja periode svih grupa
- aranzman_dopuna (saputnici split); GET /ugovori/{kljuc} vraća putnici_detalji + smer
- Grafik klik slobodno → /prodaja/rezervacije?novi=1&...; GrafikPage prefill efekt čita parametre JEDNOM (prefillPrimenjen ref)
- Uplate (tabela uplate), PDF-ovi (predracun, uplate, priznanica, ugovor, dnevni izvestaj), Polazak (prevoz), Prava (prodaja-tip)
- Dev server: `./start.sh` (Vite $APP_PORT=3058, backend 3158); publikovana verzija se NE gradi automatski — user klikće Publish