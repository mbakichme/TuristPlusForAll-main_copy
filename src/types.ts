export type ApiStatus = "checking" | "connected" | "error";
export interface HealthResponse { ok: boolean }

export interface UserType {
  id: number;
  name: string;
  slug: string;
  description?: string;
  created_at?: string;
}

export interface User {
  id: number;
  first_name: string;
  last_name: string;
  email: string;
  phone?: string;
  address?: string;
  city?: string;
  status: string;
  username: string;
  is_superadmin: boolean;
  user_type_id?: number;
  user_type_name?: string;
  user_type_slug?: string;
  poslovnica_id?: number | null;
  poslovnica_naziv?: string | null;
  created_at?: string;
}

export interface AuthUser {
  id: number;
  first_name: string;
  last_name: string;
  email: string;
  username: string;
  is_superadmin: boolean;
  user_type_slug?: string;
  user_type_name?: string;
}

export interface TipPonude { id: number; naziv: string; }
export interface Drzava { id: number; id_cis?: string; naziv: string; naziv_cis?: string; }
export interface Destinacija { id: number; naziv: string; drzava?: number; drzava_naziv?: string; status: number; organizator?: number; predstavnik?: number; naziv_cis?: string; }
export interface DestinacijaPrevoz { id: number; id_destinacije: number; naziv: string; grupe: { id: number; naziv: string }[]; }
export interface ZauzecePrevoza { datum: string; smer: "Odlazak" | "Povratak"; putnici: number; placeno: { mesto: string; broj: number }[]; limit_mesta: number | null; dodatna_mesta: number | null; }
export interface Mesto { id: number; naziv: string; drzava?: number; drzava_naziv?: string; destinacija?: number; destinacija_naziv?: string; grupa_datuma?: number; grupa_datuma_naziv?: string; grupe?: number[]; grupe_nazivi?: string[]; status: number; organizator?: number; predstavnik?: number; grafik: number; cis?: string; }
export interface TipSmestaja { id: number; naziv: string; }
export interface Smestaj { id: number; naziv: string; drzava?: number; drzava_naziv?: string; destinacija?: number; destinacija_naziv?: string; mesto?: number; mesto_naziv?: string; tip_smestaja?: number; tip_smestaja_naziv?: string; grupa_datuma?: number | null; grupa_datuma_naziv?: string | null; status: number; organizator?: number; predstavnik?: number; grafik: number; granica_chd: number; prima_decu: boolean; ne_prima_ispod_godina: number | null; popular: boolean; provizija: number; napomena?: string | null; }

export interface Soba { id: number; veza_id_smestaj: number; smestaj_naziv?: string | null; mesto_naziv?: string | null; grupa_datuma_naziv?: string | null; broj_sobe: string; opis: string; tip: string; status: number; opis_dodatno: string; veliki_opis: string; opis_ugovor?: string; koeficijenti?: string[]; }

export interface Polazak { id: number; destinacija: string | null; polazak: string | null; sat: string | null; valuta: string | null; adlrt: number | null; chdrt: number | null; infrt: number | null; adlow: number | null; chdow: number | null; infow: number | null; cena_transfera: number | null; destinacija_id: number | null; mesto_id: number | null; grupa_id: number | null; mesto_naziv: string | null; grupa_naziv: string | null; }

export interface Dokument { tip: string; naziv: string; napomena: string | null; slika: string | null; updated_at?: string | null; }

export interface PeriodDatum {
  id: number;
  grupa_id: number;
  datum_od: string;   // dd.mm.yyyy
  datum_do: string;   // dd.mm.yyyy
}

export interface PeriodGrupa {
  id: number;
  naziv: string;
  created_at?: string;
  datumi: PeriodDatum[];
}

export interface UgovorRow {
  kljuc: string;
  danas: string;
  putnik: string;
  putnici?: string[] | null;
  mesto: string;
  naziv: string;
  struktura?: string | null;
  soba?: string | null;
  subagent?: string | null;
  datumod: string;
  datumdo: string;
  ukupna_vrednost?: number | null;
}

export interface PutnikDetalj {
  saputnik: string;
  rodjen?: string | null;
  pasos?: string | null;
  adresa?: string | null;
  grad?: string | null;
  email?: string | null;
  telefon?: string | null;
  uzrast?: string | null;
  dodatno_sediste?: boolean | null;
  prevozow?: number | null;
  prevozrt?: number | null;
  prevozsp?: number | null;
  viza?: number | null;
  ulazak?: string | null;
  mesto_izlaska?: string | null;
  smer?: string | null;
  mesto_sedenja?: string | null;
  placeno_prevoz?: boolean | null;
  zelja_prevoz?: boolean | null;
  datum_ow?: string | null;
  destinacija_ow?: string | null;
  datum_polaska?: string | null;
  destinacija_polaska?: string | null;
  datum_povratka?: string | null;
  destinacija_povratka?: string | null;
  destinacija_ow_id?: number | null;
  destinacija_polaska_id?: number | null;
  destinacija_povratka_id?: number | null;
}

export interface DodatnaStavka {
  stavka_id: number;
  usluga: string | null;
  eur: number | null;
  din: number | null;
  dodatna_usluga_id?: number | null;
}

export interface DodatnaUslugaKatalog {
  id: number;
  naziv: string;
  iznos_eur: number;
  iznos_din: number;
}

export interface DodatniPopust {
  id: number;
  naziv: string;
  /** procenat od bruto smeštaja (EUR i RSD); kad je zadat, eur/rsd su null */
  procenat: number | null;
  eur: number | null;
  rsd: number | null;
  /** iznosi koje računa server (iz procenta ili unetog iznosa) */
  eur_iznos: number;
  rsd_iznos: number;
}

export interface UgovorDetail {
  kljuc: string;
  danas: string | null;
  putnik: string | null;
  rodjen?: string | null;
  pasos?: string | null;
  uzrast?: string | null;
  putnici?: string[] | null;
  putnici_detalji?: PutnikDetalj[] | null;
  dodatne?: DodatnaStavka[] | null;
  dodatni_popusti?: DodatniPopust[] | null;
  smer?: string | null;
  tiprezervacije?: string | null;
  timelimit?: string | null;
  adresa?: string | null;
  grad?: string | null;
  telefon?: string | null;
  refno?: string | null;
  prevozow?: number | null;
  prevozrt?: number | null;
  prevozsp?: number | null;
  mesto_sedenja?: string | null;
  placeno_prevoz?: boolean | null;
  zelja_prevoz?: boolean | null;
  datum_ow?: string | null;
  destinacija_ow?: string | null;
  datum_polaska?: string | null;
  destinacija_polaska?: string | null;
  datum_povratka?: string | null;
  destinacija_povratka?: string | null;
  destinacija_ow_id?: number | null;
  destinacija_polaska_id?: number | null;
  destinacija_povratka_id?: number | null;
  napomena_prevoz?: string | null;
  destinacija_prevoz_id?: number | null;
  nacin_placanja?: string | null;
  osiguranje?: number | null; // RSD
  osiguranje1?: number | null; // EUR
  soba?: string | null;
  apartman?: string | null;
  napomena?: string | null;
  napomena1?: string | null;
  obradio?: string | null;
  ulazak?: string | null;
  mesto_izlaska?: string | null;
  cenaaranz?: number | null;
  kolaranz?: number | null;
  popustar?: number | null;
  cenaow?: number | null;
  kolow?: number | null;
  cenart?: number | null;
  kolrt?: number | null;
  popustpr?: number | null;
  cenadod?: number | null;
  uplacenod?: number | null;
  procenatar?: number | null;
  procenatpr?: number | null; // provizija prevoza, iznos po osobi
  mesto: string | null;
  naziv: string | null;
  datumod: string | null;
  datumdo: string | null;
  destinacija: string | null;
  subagent: string | null;
  subagent_info: {
    naziv: string | null;
    provizija: number | null;
    racun: string | null;
    tel: string | null;
    kontakt: string | null;
  } | null;
  kurs: number | null;
  ukupna_vrednost: number | null;
  smestaj: number;
  prevoz: number;
  viza: number;
  popust: number;
  provizija: number;
  naplata: number;
  uplaceno: number;
  saldo: number;
}

export interface Subagent {
  id: number;
  naziv: string;
  adresa: string | null;
  mesto: string | null;
  osoba: string | null;
  pib: string | null;
  matbroj: string | null;
  email: string | null;
  ugovor_broj: string | null;
  ugovor_datumod: string | null;
  ugovor_datumdo: string | null;
  ta: boolean | null;
  tel: string | null;
  tel1: string | null;
  tel2: string | null;
  fax: string | null;
  racun: string | null;
  provizija: number | null;
  provizija1: number | null;
  provizija1a: number | null;
  provizija2: number | null;
  punnaziv: string | null;
  kontakt: string | null;
  broj_ugovora?: number;
}

export interface SubagentiResponse {
  rows: Subagent[];
  total: number;
  page: number;
  page_size: number;
}

export interface RacunOpcija {
  label: string;
  racun: string;
  banka: string;
}

export interface PredracunPripremi {
  broj_predracuna: string;
  datum: string;
  nosilac: string | null;
  saputnik: string;
  destinacija: string | null;
  period: string | null;
  provizija: number;
  zaduzenje: number | null;
  kurs: number | null;
  subagent: string | null;
  adresa: string;
  mesto: string;
  ugovor: string | null;
  organizator: string | null;
  poslovnica: string | null;
  racuni: RacunOpcija[];
  nacini: string[];
}

export interface Predracun {
  id: number;
  broj_predracuna: string;
  ugovor: string;
  datum_fmt: string;
  nosilac: string | null;
  saputnik: string | null;
  destinacija: string | null;
  period: string | null;
  racun: string | null;
  nacin: string | null;
  napomena: string | null;
  provizija: number | null;
  zaduzenje: number | null;
  subagent: string | null;
  adresa: string | null;
  mesto: string | null;
  organizator: string | null;
  poslovnica: string | null;
}

export interface PredracuniResponse {
  rows: Predracun[];
  total: number;
  page: number;
  page_size: number;
}

export interface UplataRow {
  id: number;
  danas: string | null;
  ime: string | null;
  nacin: string | null;
  din: number | null;
  evro: number | null;
  uevro: number | null;
  svrha: string | null;
  vrsta: string | null;
  kljuc: number | null;
  broj: string | null;
  faktura: string | null;
  obradio: string | null;
  kurs: number | null;
  kurs_datum: string | null;
  suma_eur: number | null;
  broj_potvrde: string | null;
  tip_kartice: string | null;
  broj_kartice: string | null;
  broj_odobrenja: string | null;
  broj_cekova?: number;
}

/** Podaci kartice uz uplatu (način plaćanja = Kartica). */
export interface KarticaPodaci {
  brojPotvrde: string;
  tipKartice: string;
  brojKartice: string;
  brojOdobrenja: string;
}

/** Jedan ček uz uplatu (tabela cekovi). Iznos u RSD. */
export interface CekStavka {
  redni: number;
  datum: string; // YYYY-MM-DD
  iznos: number;
  banka: string;
  brojRacunaBanke: string;
  brojRacunaKlijenta: string;
  serijskiBroj: string;
}

/** Red iz tabele banke (GET /banke). */
export interface BankaRow {
  id: number;
  sifra: string;
  naziv: string;
  racun: string;
  mesto: string;
}

export interface UgovoriResponse {
  rows: UgovorRow[];
  total: number;
  page: number;
  page_size: number;
}

export interface IzvodRow {
  id: number;
  izvod_id: number;
  racun: string;
  broj_izvoda: string;
  datum_izvoda: string | null;
  datum_unosa: string | null;
  korisnik: string;
  broj_transakcija: number | null;
  valuta: string | null;
  saldo: number | null;
}

export interface IzvodUploadResult {
  ok: boolean;
  uneseno: number;
  preskoceno: string[];
  izvodi: {
    id: number;
    racun: string;
    broj_izvoda: string;
    datum_izvoda: string | null;
    broj_transakcija: number;
  }[];
}

export interface BankaOption {
  racun: string;
  izvoda: number;
}

export interface KnjizenjeStavka {
  fitid: string;
  racun: string;
  broj_izvoda: string;
  datum_izvoda: string | null;
  poziv_na_broj: string;
  naziv_primaoca: string;
  mesto_primaoca: string;
  svrha_kod: string;
  svrha: string;
  iznos: number;
  datum_knjizenja: string | null;
  smer: string;
  veza: string | null;
  predracun: string | null;
}

export interface KnjizenjeStavkeResponse {
  izvodi: { racun: string; broj_izvoda: string; datum_izvoda: string | null }[];
  stavke: KnjizenjeStavka[];
}

export interface ProdajaAranzmanaRow {
  kljuc: string;
  danas: string | null;
  vreme: string | null;
  putnik: string | null;
  broj_putnika: number;
  mesto: string | null;
  smestaj: string | null;
  soba: string | null;
  datum_od: string | null;
  datum_do: string | null;
  tiprezervacije: string | null;
  struktura: string | null;
  subagent: string | null;
  obradio: string | null;
  naplata: number;
  provizija: number;
  ukupno: number;
  uplaceno: number;
}

export interface ProdajaAranzmanaResp {
  datum: string;
  kurs: number | null;
  rows: ProdajaAranzmanaRow[];
  totals: {
    broj: number;
    putnika: number;
    naplata: number;
    provizija: number;
    ukupno_eur: number;
    ukupno_din: number | null;
  };
}

export interface Notifikacija {
  id: number;
  poruka: string;
  autor_id: number | null;
  autor_ime: string;
  autor_username: string;
  created_at: string | null;
}

export interface NotifikacijeResponse {
  najnovija: Notifikacija | null;
  rows: Notifikacija[];
  ukupno: number;
}

export interface NotifikacijeNoviji {
  max_id: number;
  rows: Notifikacija[];
}
