## Ugovori — tabovi po tipu + prečica na naslovnoj (2026-11-08)
- `/ugovori` prima opcioni `tip=rezervacije|predrezervacija|storno` (grupa po `UPPER(TRIM(COALESCE(tiprezervacije,'')))`; rezervacije = sve osim PREDREZERVACIJA/STORNO, uklj. prazno); BEZ `tip` = svi ugovori (dashboard pretraga, Rezervacije, Knjiženje, PrebacivanjeUplatePopup to koriste — ne menjati); odgovor ima `po_tipu {predrezervacija, storno, rezervacije}` = brojači sa istom pretragom/filterima ali BEZ tip uslova
- UgovoriPage: shadcn Tabs iznad kartice, redosled REZERVACIJE (default, blue-600) | PREDREZERVACIJA (amber-500) | STORNO (red-600), brojač pill u tabu; tab u URL-u `?tab=` (replace) — podrazumevani se ne upisuje dok se ne promeni; loadBatch dobio 7. parametar `tip`; `replaceInFlight` ref blokira infinite-scroll dok traje učitavanje 1. strane
- Dashboard: 4. prečica „Ugovori“ (violet, FileText) → /knjigovodstvo/ugovori; grid `sm:grid-cols-2 xl:grid-cols-4`
- Test `test_ugovori_tabovi.py` (9 provera). ZAMKA: token u localStorage ključ `ta_token`, postavljati kroz `context.add_init_script` (goto /login + evaluate je flaky); `create_access_token` se importuje iz `routes`

## Rezervacija — opis sobe (2026-11-08)
- „Boravak i smeštaj“: polje „Opis sobe“ (readonly, `data-testid="opis-sobe"`) = `sobe.opis` izabrane sobe (`izabranaSoba` useMemo iz `boravak.soba`); Mesto polje se NE dira (korisnik izričito); grid red 2: Opis `xl:col-span-2` + Promena strukture `xl:col-span-3` + Viza 1
- Zaglavlje „Ugovor“: segment sobe = `broj · opis · tip` iz SAČUVANE sobe ugovora (`sobaUgovoraId` state postavljen u loaderu uz `setUcitanUgovor`), ne prati neusnimljenu promenu u formi
- Test `test_rez_opis_sobe.py` (4 provere, ništa ne čuva)

## Ostalo
- Pregled uplata (/pregledi/dnevni-izvestaji/uplate, `GET /pregledi/uplate?datum=` po `uplate.danas`), zajednički kalendar `src/components/DnevniKalendar.tsx` (koristi ga i Prodaja aranžmana); Prodaja aranžmana: kartica „ZA NAPLATU“, bez Naplaćeno; batch `dodatni_za_ugovori` (12s → 0.3s)

## Rezervacija — upis strukture i virtuelne sobe (2026-11-08)
- Korisnik je potvrdio da ponašanje dugmeta „Otključaj“ ostaje nepromenjeno (za učitan ugovor prvo „Izmeni“).
- `routes.py::rezervacija_vrednosti` (POST i PUT): `aranzman.apartman = sobe.tip` (max 10), `opis = sobe.opis` (max 20); `gde` = struktura dodatnog koeficijenta izabrane sobe kada se normalizovano razlikuje od stvarnog `sobe.tip`; inače NULL. Stara soba bez šifarnika ne menja te kolone.
- Virtuelne sobe Grafik/Pretraga šalju kao stvarni `sobaId` + `struktura` iz reda cenovnika. Primer FLORA A v15-1 / realna soba id750: apartman=1/4, opis=STD, gde=1/3. Provereno sa stvarnim SELECT podacima bez upisa.
- GET `/ugovori/{kljuc}` i `UgovorDetail` vraćaju opis/gde; Rezervacije loader koristi `gde.trim() || apartman` za strukturu. Log ima labele za opis/gde.
- `test_rez_smestajna_polja.py`: 9 unittest provera originalne funkcije preko AST i read-only lažne konekcije; prolaze, kao py_compile i tsc. Postojeći ugovori nisu masovno ažurirani; polja se popune pri sledećem čuvanju. Poseban endpoint prebacivanja sobe nije menjan i još upisuje samo apartman.

