import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  BadgeCheck, Ban, BedDouble, Bus, CalendarDays, CalendarPlus, Check, ChevronDown, CreditCard, Download, FilePenLine, FileSignature, Loader2,
  FilePlus, FileText, Handshake, History, Info, Landmark, Lock, LockOpen, Plus, Receipt, Search, Send, Ticket, Trash2, X,
  Users, Wallet, ArrowRightLeft, Printer,
} from "lucide-react";
import { toast } from "sonner";
import { z } from "zod";
import ZaduzenjePartnerTab from "@/components/ZaduzenjePartnerTab";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { apiFetch, getToken } from "../lib/api";
import type { CekStavka, Destinacija, DodatnaStavka, KarticaPodaci, Mesto, Smestaj, Soba, UgovorDetail, UgovorRow, UgovoriResponse, UplataRow } from "../types";
import { cn } from "@/lib/utils";
import { CekPopup } from "@/components/CekPopup";
import { AdministrativnaZabranaPopup } from "@/components/AdministrativnaZabranaPopup";
import { DodatnaStavkaForma } from "@/components/DodatnaStavkaForma";
import { KarticaPopup } from "@/components/KarticaPopup";
import { PageLoader } from "@/components/PageLoader";
import { PrebacivanjeUplatePopup } from "@/components/PrebacivanjeUplatePopup";

// ── konstante ──────────────────────────────────────────────────────────────
const TIP_REZERVACIJE = ["Klasična rezervacija", "Predrezervacija", "Last minute", "First minute"];
const SMER_OPCIJE = ["Polazak", "Povratak"];
const NACIN_PLACANJA = ["Gotovina", "Kartica", "Ček", "Virman", "IPC", "Vaučer", "Ostalo"];
const SVRHA_UPLATE = ["Total aranžman", "Deo aranžmana", "Prevoz", "Osiguranje", "Odloženo - Ček", "Povraćaj"];
const UPLATA_PODRAZUMEVANO = { nacin: "Gotovina", svrha: "Deo aranžmana" };

/** Boja ikonice: zelena ako postoji bar jedan podatak, inače crvena. */
const STATUS_IKONA_PUNO = "text-emerald-600 hover:text-emerald-700";
const STATUS_IKONA_PRAZNO = "text-red-600 hover:text-red-700";
function karticaImaPodatke(u: UplataRow): boolean {
  return [u.broj_potvrde, u.tip_kartice, u.broj_kartice, u.broj_odobrenja].some((v) => (v ?? "").trim() !== "");
}
/** Crveni toast (gore desno) da podaci kartice nisu uneti; ostaje dok se ne zatvori ili ne sačuvaju podaci. */
const karticaToastId = (kljuc: number) => `kartica-${kljuc}`;
function prikaziKarticaNeunetu(kljuc: number, ugovor: string) {
  toast.error("Podaci kartice nisu uneti", {
    id: karticaToastId(kljuc),
    description: `Uplata ${kljuc} · Ugovor: ${ugovor}`,
    duration: Infinity,
  });
}
const MESTO_SEDENJA = ["DONJA PLATFORMA", "GORNJA PLATFORMA", "DOLE ZA STOLOM", "DOLE ZADNJI RED", "GORE IZLOG", "GORE STO", "ŠARAGE"];
// Doplata (EUR) po mestu za sedenje → kolona u parametri_obracuna
const DOPLATA_MESTA: Record<string, string> = {
  "DONJA PLATFORMA": "donja_platforma_eur", "GORNJA PLATFORMA": "gornja_platforma_eur",
  "DOLE ZA STOLOM": "dole_za_stolom_eur", "DOLE ZADNJI RED": "dole_zadnji_red_eur",
  "GORE IZLOG": "gore_izlog_eur", "GORE STO": "gore_sto_eur", "ŠARAGE": "sarage_eur",
};
// Dodatne usluge koje se računaju iz tabele Prevoz (ne unose ručno) — zamenjuju se pri snimanju
const IZRACUNATE_PREFIKSI = ["TRANSFER - ", "PLAĆENO MESTO - "];
const jeIzracunata = (usluga: string | null | undefined) => IZRACUNATE_PREFIKSI.some((p) => (usluga ?? "").startsWith(p));

/** Select sa pretragom i opcijom „Prazno“ (Radix Select ne dozvoljava value=""). */
function PretraznaSelect({ value, opcije, placeholder, ariaLabel, onChange, disabled }: {
  value: string;
  opcije: { value: string; label: string }[];
  placeholder: string;
  ariaLabel: string;
  onChange: (v: string) => void;
  disabled?: boolean;
}) {
  const [otvoreno, setOtvoreno] = useState(false);
  const izabrana = opcije.find((o) => o.value === value);
  const izbor = (v: string) => { onChange(v); setOtvoreno(false); };
  return (
    <Popover open={otvoreno} onOpenChange={setOtvoreno}>
      <PopoverTrigger asChild>
        <Button type="button" variant="outline" disabled={disabled} aria-label={ariaLabel}
          className="w-full h-8 justify-between font-normal text-xs">
          <span className={cn("truncate", !value && "text-muted-foreground")}>
            {value ? (izabrana?.label ?? value) : placeholder}
          </span>
          <ChevronDown className="size-3.5 opacity-50 shrink-0" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[--radix-popover-trigger-width] p-0 bg-card" align="start">
        <Command>
          <CommandInput placeholder="Pretraga…" />
          <CommandList>
            <CommandEmpty>Nema rezultata za zadatu pretragu.</CommandEmpty>
            <CommandGroup>
              <CommandItem value="prazno bez izbora" onSelect={() => izbor("")}>
                <span className="italic text-muted-foreground">Prazno (bez izbora)</span>
              </CommandItem>
              {opcije.map((o) => (
                <CommandItem key={o.value} value={o.label} onSelect={() => izbor(o.value)}>
                  {o.label}
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

const nf = new Intl.NumberFormat("sr-RS", { maximumFractionDigits: 2 });
const nf2 = new Intl.NumberFormat("sr-RS", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const kursFormat = new Intl.NumberFormat("sr-RS", { minimumFractionDigits: 4, maximumFractionDigits: 4 });
const formatDatumRodjenja = (value: string) => {
  const digits = value.replace(/\D/g, "").slice(0, 8);
  return [digits.slice(0, 2), digits.slice(2, 4), digits.slice(4)].filter(Boolean).join(".");
};
const prikazTimeLimita = (datum: Date | undefined, sat: string) =>
  datum ? `${String(datum.getDate()).padStart(2, "0")}.${String(datum.getMonth() + 1).padStart(2, "0")}.${datum.getFullYear()} ${sat}:00` : ""; // lokalni datum bez UTC konverzije
const SATI = Array.from({ length: 24 }, (_, i) => String(i).padStart(2, "0"));
const MESECI = ["januar", "februar", "mart", "april", "maj", "jun", "jul", "avgust", "septembar", "oktobar", "novembar", "decembar"];
const DANI = ["Ned", "Pon", "Uto", "Sre", "Čet", "Pet", "Sub"];
const datumZaInput = (v: string | null | undefined) => {
  const m = /^(\d{2})\.(\d{2})\.(\d{4})$/.exec(v ?? "");
  return m ? `${m[3]}-${m[2]}-${m[1]}` : "";
};
const brojUString = (v: number | null | undefined) => v == null ? "" : String(v);
const formattersKalendara = {
  formatCaption: (month: Date) => `${MESECI[month.getMonth()]} ${month.getFullYear()}`,
  formatWeekdayName: (day: Date) => DANI[day.getDay()],
};
const MESECI_KAL = MESECI.map((m) => m.charAt(0).toUpperCase() + m.slice(1));
/** Broj ugovora po strani u padajućoj listi pretrage (backend maksimum je 100). */
const PRETRAGA_STRANA = 100;
const formattersKalendaraDatum = {
  formatWeekdayName: (day: Date) => DANI[day.getDay()],
  formatMonthDropdown: (date: Date) => MESECI_KAL[date.getMonth()],
};
/** ISO "yyyy-mm-dd" → Date (lokalno, bez UTC) */
const isoToDatum = (v: string) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(v);
  return m ? new Date(+m[1], +m[2] - 1, +m[3]) : undefined;
};
const datumToIso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const isoToPrikaz = (v: string) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(v);
  return m ? `${m[3]}.${m[2]}.${m[1]}` : "";
};
/** "02.09 - 12.09.2026" (godina samo na kraju kad su datumi iste godine) */
const prikazPeriodaUgovora = (od: string | null | undefined, doDatum: string | null | undefined): string => {
  const a = isoToPrikaz(datumZaInput(od) ?? "");
  const b = isoToPrikaz(datumZaInput(doDatum) ?? "");
  if (!a || !b) return "";
  return a.slice(-4) === b.slice(-4) ? `${a.slice(0, 5)} - ${b}` : `${a} - ${b}`;
};
/** broj iz inputa; prazno → 0 */
const num = (v: string) => {
  const x = parseFloat(v.replace(",", "."));
  return Number.isNaN(x) ? 0 : x;
};
/** količina iz inputa; prazno → 1 (podrazumevano) */
const qty = (v: string) => {
  const x = parseFloat(v.replace(",", "."));
  return !Number.isFinite(x) ? 1 : Math.max(0, x);
};
/** zaokruživanje iznosa iz procenta na 2 decimale */
const round2 = (x: number) => Math.round(x * 100) / 100;

/** Podaci sobe iz /slobodne-sobe potrebni za ponovni obračun popusta pri promeni načina plaćanja. */
type IzvorPopusta = {
  osnovna: number;
  varijante: { vazi: boolean; cena_snizena: number | null; tip_placanja?: string | null }[];
};

/** Maksimalni važeći popust (procenat) sobe za izabrani način plaćanja ("" = bez izbora). "" ako nema popusta. */
function popustZaPlacanje(izvor: IzvorPopusta, placanje: string): string {
  const kandidati = izvor.varijante.filter((v) =>
    v.vazi && v.cena_snizena != null && (!placanje || v.tip_placanja === placanje));
  if (kandidati.length === 0 || izvor.osnovna <= 0) return "";
  const maxPopust = izvor.osnovna - Math.min(...kandidati.map((v) => v.cena_snizena as number));
  if (maxPopust <= 0) return "";
  return String(round2((maxPopust / izvor.osnovna) * 100));
}
/** procenat iz inputa; prazno ili neispravno → null */
const procenat = (v: string) => {
  const x = parseFloat(v.replace(",", "."));
  return Number.isNaN(x) ? null : x;
};
/** "dd.mm.yyyy" (unos) → ISO "yyyy-mm-dd"; prazno/neispravno → null */
const datumRodjenjaIso = (v: string) => {
  const m = /^(\d{2})\.(\d{2})\.(\d{4})$/.exec(v.trim());
  return m ? `${m[3]}-${m[2]}-${m[1]}` : null;
};
/** sentinel vrednost: sačuvani naziv van referentne liste (stari ugovori) */
const CUVAR = "__cuvano__";

// ── tipovi forme ───────────────────────────────────────────────────────────
interface Nosilac {
  ime: string;
  datumRodjenja: string;
  pasos: string;
  uzrast: string;
  ow: boolean;
  rt: boolean;
  sp: boolean;
  osiguranje: boolean;
  smer: string;
  datumOw: string;
  destinacijaOw: string;
  datumPolaska: string;
  datumPovratka: string;
  destinacijaPolaska: string;
  destinacijaPovratka: string;
  adresa: string;
  grad: string;
  telefon: string;
  email: string;
}
interface Saputnik {
  adresa: string;
  grad: string;
  email: string;
  telefon: string;
  kopiranKontakt: boolean;
  uid: string;
  ime: string;
  datumRodjenja: string;
  pasos: string;
  uzrast: string;
  ow: boolean;
  rt: boolean;
  sp: boolean;
  osiguranje: boolean;
  smer: string;
  datumOw: string;
  destinacijaOw: string;
  datumPolaska: string;
  datumPovratka: string;
  destinacijaPolaska: string;
  destinacijaPovratka: string;
}
interface KeptpInfo {
  broj_keptp: number;
  datum: string;
}

// tipovi bez KEPTP evidencije; viza štiklirana → KEPTP se ne traži
const KEPTP_BEZ_EVIDENCIJE = ["PREDREZERVACIJA", "BLOK"];
const keptpNijePotreban = (tip: string, viza: boolean) =>
  viza || KEPTP_BEZ_EVIDENCIJE.includes(tip.trim().toUpperCase());

interface Boravak {
  datumOd: string;
  datumDo: string;
  smestaj: string;
  soba: string;
  mesto: string;
  struktura: string;
  promenaStrukture: string;
  viza: boolean;
  napomena: string;
  napomenaInterna: string;
  napomenaPrevoz: string;
}
interface Cene {
  cenaSmestaj: string;
  kolSmestaj: string;
  cenaSmestajRSD: string;
  kolSmestajRSD: string;
  popustSmestajPct: string;
  popustSmestaj: string;
  popustSmestajRSD: string;
  cenaPrevoz: string;
  kolPrevoz: string;
  cenaPrevozRSD: string;
  kolPrevozRSD: string;
  popustPrevozPct: string;
  popustPrevoz: string;
  popustPrevozRSD: string;
  osiguranjeEUR: string;
  osiguranjeRSD: string;
  provizijaSmestajPct: string;
  provizijaSmestaj: string;
  provizijaSmestajRSD: string;
  provizijaPrevozPct: string;
  provizijaPrevoz: string;
  provizijaPrevozRSD: string;
  uplaceno: string;
}
interface PrevozRed {
  mestoUlaska: string;
  mestoIzlaska: string;
  mestoSedenja: string;
  placeno: boolean;
  zelja: boolean;
}
/** Minimalni oblik reda iz registra prevoza (tabela polazak, GET /polazak). */
interface PolazakUlazak {
  id: number;
  destinacija: string | null;
  polazak: string | null;
  sat: string | null;
  cena_transfera: number | null;
}
/** Administrativna zabrana vezana za ugovor (GET /ugovori/{kljuc}/zabrane). */
interface ZabranaVezana {
  broj: string;
  datum: string | null;
  ukupno: number | null;
  valuta: string;
  preuzeta_datum: string;
}

interface Uplata {
  uplatilac: string;
  nacin: string;
  iznos: string;
  svrha: string;
}
const prazanNosilac: Nosilac = {
  ime: "", datumRodjenja: "", pasos: "", uzrast: "",
  ow: false, rt: false, sp: false, osiguranje: false, smer: "",
  datumOw: "", destinacijaOw: "", datumPolaska: "", datumPovratka: "",
  destinacijaPolaska: "", destinacijaPovratka: "",
  adresa: "", grad: "", telefon: "", email: "",
};
const prazanSaputnik = (uid: string): Saputnik => ({
  uid, ime: "", datumRodjenja: "", pasos: "", uzrast: "",
  adresa: "", grad: "", email: "", telefon: "", kopiranKontakt: false,
  ow: false, rt: false, sp: false, osiguranje: false, smer: "",
  datumOw: "", destinacijaOw: "", datumPolaska: "", datumPovratka: "",
  destinacijaPolaska: "", destinacijaPovratka: "",
});

// ── pomoćne komponente ─────────────────────────────────────────────────────
function EmailInput({ value, onChange, disabled }: { value: string; onChange: (value: string) => void; disabled?: boolean }) {
  const [touched, setTouched] = useState(false);
  const invalid = touched && !!value.trim() && !z.string().email().safeParse(value.trim()).success;
  return (
    <div className="space-y-1">
      <Input type="email" autoComplete="email" value={value} disabled={disabled}
        aria-invalid={invalid} className={cn(invalid && "border-destructive")}
        onChange={(e) => onChange(e.target.value)} onBlur={() => setTouched(true)} />
      {invalid && <p role="alert" className="text-xs text-destructive">Unesite ispravnu email adresu (npr. ime@domen.rs).</p>}
    </div>
  );
}
/** Uzrast putnika: ADL / CHD / INF. Ponovni klik na izabrani uzrast ga poništava (prazno). */
const UZRASTI = ["ADL", "CHD", "INF"] as const;
function UzrastIzbor({ value, onChange, disabled, label }: { value: string; onChange: (value: string) => void; disabled?: boolean; label: string }) {
  return (
    <div role="radiogroup" aria-label={label} className="flex h-8 items-center gap-1">
      {UZRASTI.map((u) => {
        const aktivan = value === u;
        return (
          <button
            key={u}
            type="button"
            role="radio"
            aria-checked={aktivan}
            aria-label={`${label} — ${u}`}
            disabled={disabled}
            onClick={() => onChange(aktivan ? "" : u)}
            className={cn(
              "h-7 flex-1 rounded-md border text-xs font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50",
              aktivan ? "border-blue-600 bg-blue-600 text-white" : "border-input bg-background text-muted-foreground hover:bg-accent hover:text-accent-foreground",
            )}
          >
            {u}
          </button>
        );
      })}
    </div>
  );
}
/** Kompaktni raspored tabova Aranžman i Obračun — niži inputi/selecti/datumi, manji razmaci (više polja na ekranu). */
const KOMPAKT_TAB = "mt-3 space-y-3 [&_input]:h-8 [&_button[role=combobox]]:h-8 [&_button[aria-haspopup=dialog]]:h-8 [&_textarea]:min-h-0 [&_label]:leading-none";
const KOMPAKT_HEADER = "px-4 pt-3 pb-2";
const KOMPAKT_CONTENT = "px-4 pb-3";

// Boja po sekciji: leva traka kartice + tonirano zaglavlje + kolor pločica ikone
type Ton = "blue" | "violet" | "emerald" | "sky" | "orange" | "rose" | "amber" | "teal" | "indigo";
const TON: Record<Ton, { kartica: string; zaglavlje: string; plocica: string }> = {
  blue: { kartica: "border-l-4 border-l-blue-500", zaglavlje: "bg-blue-50/70", plocica: "bg-blue-100 text-blue-700" },
  violet: { kartica: "border-l-4 border-l-violet-500", zaglavlje: "bg-violet-50/70", plocica: "bg-violet-100 text-violet-700" },
  emerald: { kartica: "border-l-4 border-l-emerald-500", zaglavlje: "bg-emerald-50/70", plocica: "bg-emerald-100 text-emerald-700" },
  sky: { kartica: "border-l-4 border-l-sky-500", zaglavlje: "bg-sky-50/70", plocica: "bg-sky-100 text-sky-700" },
  orange: { kartica: "border-l-4 border-l-orange-500", zaglavlje: "bg-orange-50/70", plocica: "bg-orange-100 text-orange-700" },
  rose: { kartica: "border-l-4 border-l-rose-500", zaglavlje: "bg-rose-50/70", plocica: "bg-rose-100 text-rose-700" },
  amber: { kartica: "border-l-4 border-l-amber-500", zaglavlje: "bg-amber-50/70", plocica: "bg-amber-100 text-amber-700" },
  teal: { kartica: "border-l-4 border-l-teal-500", zaglavlje: "bg-teal-50/70", plocica: "bg-teal-100 text-teal-700" },
  indigo: { kartica: "border-l-4 border-l-indigo-500", zaglavlje: "bg-indigo-50/70", plocica: "bg-indigo-100 text-indigo-700" },
};

function SekcijaIkona({ ton, children }: { ton: Ton; children: ReactNode }) {
  return (
    <span className={cn("inline-flex size-6 shrink-0 items-center justify-center rounded-md [&>svg]:size-3.5", TON[ton].plocica)}>
      {children}
    </span>
  );
}

function Fld({
  label, children, className, labelClassName,
}: { label: string; children: ReactNode; className?: string; labelClassName?: string }) {
  return (
    <div className={cn("space-y-1.5", className)}>
      <Label className={cn("text-xs text-muted-foreground", labelClassName)}>{label}</Label>
      {children}
    </div>
  );
}

function Chk({
  label, checked, onChange, labelClassName, disabled,
}: { label: ReactNode; checked: boolean; onChange: (v: boolean) => void; labelClassName?: string; disabled?: boolean }) {
  return (
    <label className={cn("flex items-center gap-2 cursor-pointer select-none", disabled && "cursor-not-allowed opacity-60")}>
      <Checkbox checked={checked} onCheckedChange={(v) => onChange(v === true)} disabled={disabled} />
      <span className={cn("text-sm", labelClassName)}>{label}</span>
    </label>
  );
}

function SmerSelect({ value, onChange, disabled }: { value: string; onChange: (v: string) => void; disabled?: boolean }) {
  return (
    <Select value={value} onValueChange={onChange} disabled={disabled}>
      <SelectTrigger className="w-full"><SelectValue placeholder="Izaberite" /></SelectTrigger>
      <SelectContent>
        {SMER_OPCIJE.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}
      </SelectContent>
    </Select>
  );
}

/** Moderni date picker — Popover + kalendar (ponedeljak-first, dropdown mesec/godina) */
function DatumField({
  label, value, onChange, className, disabled,
}: { label: string; value: string; onChange: (v: string) => void; className?: string; disabled?: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <Fld label={label} className={className}>
      <Popover open={open} onOpenChange={disabled ? undefined : setOpen}>
        <PopoverTrigger asChild>
          <Button
            type="button"
            variant="outline"
            disabled={disabled}
            className={cn("w-full justify-start gap-2 font-normal", !value && "text-muted-foreground")}
          >
            <CalendarDays className="size-4 shrink-0" />
            {value ? isoToPrikaz(value) : "dd.mm.yyyy"}
          </Button>
        </PopoverTrigger>
        <PopoverContent align="start" className="w-auto p-0">
          <Calendar
            mode="single"
            selected={isoToDatum(value)}
            defaultMonth={isoToDatum(value)}
            onSelect={(d) => { onChange(d ? datumToIso(d) : ""); setOpen(false); }}
            weekStartsOn={1}
            captionLayout="dropdown"
            startMonth={new Date(2024, 0)}
            endMonth={new Date(2032, 11)}
            formatters={formattersKalendaraDatum}
            initialFocus
          />
        </PopoverContent>
      </Popover>
    </Fld>
  );
}

function UkupnoInput({ vrednost }: { vrednost: number | null }) {
  return (
    <Input
      readOnly
      value={vrednost != null ? nf.format(vrednost) : ""}
      placeholder="—"
      className="bg-muted/50 font-medium"
      tabIndex={-1}
    />
  );
}

/** Desna panela sažetka — zajednička za sve kartice: vertikalna linija na desktopu, bledo plava pozadina. */
function PanelaSazetka({ children, className, kompaktno }: { children: ReactNode; className?: string; kompaktno?: boolean }) {
  return (
    <div className={cn("lg:border-l lg:border-dashed", kompaktno ? "lg:pl-3" : "lg:pl-4", className)}>
      <div className={cn("flex flex-col rounded-lg border border-blue-200/70 bg-blue-50 dark:border-blue-500/20 dark:bg-blue-950/30", kompaktno ? "gap-2 p-2" : "gap-3 p-3")}>
        {children}
      </div>
    </div>
  );
}

/** Red popusta/provizije: Procenat (%), Iznos EUR, Iznos RSD + ukupno po redu (neto, desno). */
function ProcenatRed({
  naslov, pct, iznosEUR, iznosRSD, netoEUR, netoRSD, onPct, onIznosEUR, onIznosRSD, disabled,
}: {
  naslov: string;
  pct: string;
  iznosEUR: string;
  iznosRSD: string;
  netoEUR: number | null;
  netoRSD: number | null;
  onPct: (v: string) => void;
  onIznosEUR: (v: string) => void;
  onIznosRSD: (v: string) => void;
  disabled?: boolean;
}) {
  return (
    <div>
      <p className="mb-1 text-xs font-semibold text-blue-600">{naslov}</p>
      <div className="grid gap-x-3 gap-y-2 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <div className="grid gap-x-3 gap-y-2 sm:grid-cols-2 lg:grid-cols-3">
          <Fld label="Procenat (%)">
            <Input
              inputMode="decimal"
              aria-label={`${naslov} — procenat (%)`}
              value={pct}
              onChange={(e) => onPct(e.target.value)}
              placeholder="0"
              disabled={disabled}
            />
          </Fld>
          <Fld label="Iznos (EUR)">
            <Input
              inputMode="decimal"
              aria-label={`${naslov} — iznos (EUR)`}
              value={iznosEUR}
              onChange={(e) => onIznosEUR(e.target.value)}
              placeholder="0,00"
              disabled={disabled}
            />
          </Fld>
          <Fld label="Iznos (RSD)">
            <Input
              inputMode="decimal"
              aria-label={`${naslov} — iznos (RSD)`}
              value={iznosRSD}
              onChange={(e) => onIznosRSD(e.target.value)}
              placeholder="0,00"
              disabled={disabled}
            />
          </Fld>
        </div>
        <PanelaSazetka kompaktno>
          <div className="grid grid-cols-2 gap-x-3 gap-y-2">
            <Fld label="Ukupno (EUR)">
              <UkupnoInput vrednost={netoEUR} />
            </Fld>
            <Fld label="Ukupno (RSD)">
              <UkupnoInput vrednost={netoRSD} />
            </Fld>
          </div>
        </PanelaSazetka>
      </div>
    </div>
  );
}

// ── stranica ───────────────────────────────────────────────────────────────
type IstorijaPromena = { polje: string; stara: string | null; nova: string | null };
type IstorijaRed = {
  id: number;
  oblast: string;
  dogadjaj: string;
  user_ime: string | null;
  created_at: string | null;
  promene: IstorijaPromena[];
};

const ISTORIJA_OBLAST: Record<string, string> = {
  rezervacija: "Rezervacija",
  prevoz: "Prevoz",
  obracun: "Obračun",
  uplata: "Uplata",
  saputnici: "Saputnici",
};

const ISTORIJA_DOGADJAJ: Record<string, string> = {
  kreirana: "Kreirana",
  izmena: "Izmena",
  usluga_dodata: "Dodata usluga",
  usluga_izmenjena: "Izmenjena usluga",
  usluga_obrisana: "Obrisana usluga",
  uplata_dodata: "Nova uplata",
  smestaj_promenjen: "Promena smeštaja",
};

function istorijaVreme(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("sr-RS", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export default function RezervacijePage() {
  const [searchParams] = useSearchParams();
  const ugovorIzLinka = searchParams.get("u");
  const linkUcitavanja = useRef<string | null>(null);
  const [referenceSpremne, setReferenceSpremne] = useState(false);
  const [tipRezervacije, setTipRezervacije] = useState(TIP_REZERVACIJE[0]);
  const [subagent, setSubagent] = useState("");
  const [subagentOtvoren, setSubagentOtvoren] = useState(false);
  const [subagentPretraga, setSubagentPretraga] = useState("");
  const [subagentOpcije, setSubagentOpcije] = useState<string[]>([]);
  // provizija izabranog subagenta (kolona subagenti.provizija) i globalni parametri obračuna
  const [subagentProvizija, setSubagentProvizija] = useState<number | null>(null);
  // adl (maks. broj ADL osoba) strukture iz koeficijenti_prodaje — određuje saputnike i količinu smeštaja (Grafik prefill)
  const [adlStrukture, setAdlStrukture] = useState<number | null>(null);
  // koeficijent strukture (kolona koeficijent, red sa max ADL) — količina smeštaja; cena iz Grafika je po osobi
  const [koefStrukture, setKoefStrukture] = useState<number | null>(null);
  const [parametriObr, setParametriObr] = useState<{ visina_popusta: number; visina_provizije: number } & Partial<Record<string, number>> | null>(null);

  // pretraga subagenata iz tabele subagenti (po nazivu, mestu, osobi, telefonu…)
  useEffect(() => {
    if (!subagentOtvoren) return;
    let aktivan = true;
    const t = setTimeout(() => {
      const params = new URLSearchParams({ search: subagentPretraga.trim(), page_size: "50", sort: "naziv", dir: "asc" });
      apiFetch<{ rows: { naziv: string }[] }>(`/subagenti?${params}`)
        .then((d) => { if (aktivan) setSubagentOpcije(d.rows.map((r) => r.naziv).filter((n) => n && n.trim())); })
        .catch(() => { if (aktivan) setSubagentOpcije([]); });
    }, 250);
    return () => { aktivan = false; clearTimeout(t); };
  }, [subagentOtvoren, subagentPretraga]);
  const [timeLimitDatum, setTimeLimitDatum] = useState<Date>();
  const [timeLimitSat, setTimeLimitSat] = useState("12");
  const [timeLimitOtvoren, setTimeLimitOtvoren] = useState(false);
  const [pretraga, setPretraga] = useState("");
  const [pretragaRezultati, setPretragaRezultati] = useState<UgovorRow[]>([]);
  const [pretragaUkupno, setPretragaUkupno] = useState(0);
  const [pretragaUcitava, setPretragaUcitava] = useState(false);
  const [izborUcitava, setIzborUcitava] = useState(false);
  const [izabraniUgovor, setIzabraniUgovor] = useState<string | null>(null);
  const [ucitanUgovor, setUcitanUgovor] = useState<UgovorDetail | null>(null);
  const navigate = useNavigate();
  const aktivniUgovor = useRef<string | null>(null);
  // sinhronizacija ref-a: async tokovi (potvrda uplate, keptp) proveravaju da li je ugovor još izabran
  useEffect(() => { aktivniUgovor.current = izabraniUgovor; }, [izabraniUgovor]);
  const [pretragaOtvorena, setPretragaOtvorena] = useState(false);
  const pretragaRequest = useRef(0);
  const izborRequest = useRef(0);

  // putnici (deljeni između tabova)
  const [nosilac, setNosilac] = useState<Nosilac>(prazanNosilac);
  const [saputnici, setSaputnici] = useState<Saputnik[]>([]);
  const uidRef = useRef(0);
  const dodajSaputnika = () =>
    setSaputnici((prev) => [...prev, prazanSaputnik(`s${++uidRef.current}`)]);
  const ukloniSaputnika = (uid: string) =>
    setSaputnici((prev) => prev.filter((s) => s.uid !== uid));

  const [boravak, setBoravak] = useState<Boravak>({
    datumOd: "", datumDo: "", smestaj: "", soba: "", mesto: "",
    struktura: "", promenaStrukture: "", viza: false, napomena: "", napomenaInterna: "", napomenaPrevoz: "",
  });
  const [cene, setCene] = useState<Cene>({
    cenaSmestaj: "", kolSmestaj: "", cenaSmestajRSD: "", kolSmestajRSD: "",
    popustSmestajPct: "", popustSmestaj: "", popustSmestajRSD: "",
    cenaPrevoz: "", kolPrevoz: "", cenaPrevozRSD: "", kolPrevozRSD: "",
    popustPrevozPct: "", popustPrevoz: "", popustPrevozRSD: "",
    osiguranjeEUR: "", osiguranjeRSD: "",
    provizijaSmestajPct: "", provizijaSmestaj: "", provizijaSmestajRSD: "",
    provizijaPrevozPct: "", provizijaPrevoz: "", provizijaPrevozRSD: "",
    uplaceno: "",
  });
  const [dodatneStavke, setDodatneStavke] = useState<NonNullable<UgovorDetail["dodatne"]>>([]);
  const [dodatnaIzmena, setDodatnaIzmena] = useState<NonNullable<UgovorDetail["dodatne"]>[number] | "nova" | null>(null);
  // brisanje dodatne stavke: stavka u dijalogu potvrde + id stavke koja se trenutno briše (spinner/lock)
  const [brisanjeStavka, setBrisanjeStavka] = useState<DodatnaStavka | null>(null);
  const [dodatnaBrisanje, setDodatnaBrisanje] = useState<number | null>(null);
  const brisanjeZakljucana = useRef(false);
  /** broj sesije liste dodatnih stavki — raste pri svakom uspešnom učitavanju ugovora (čuvar protiv zastarelog brisanja) */
  const dodatneSesija = useRef(0);
  const [ugovorPdfUcitava, setUgovorPdfUcitava] = useState(false);
  const montirano = useRef(true);
  useEffect(() => {
    montirano.current = true;
    return () => { montirano.current = false; };
  }, []);
  const [prevozRedovi, setPrevozRedovi] = useState<Record<string, PrevozRed>>({});
  const [prevozDetaljiOtvoreni, setPrevozDetaljiOtvoreni] = useState<Record<string, boolean>>({});
  const [destinacijaZaSve, setDestinacijaZaSve] = useState("");
  const [polasci, setPolasci] = useState<PolazakUlazak[]>([]);
  const [polasciGreska, setPolasciGreska] = useState(false);
  const [polasciOsvezi, setPolasciOsvezi] = useState(0);
  const [uplata, setUplata] = useState<Uplata>({ uplatilac: "nosilac", ...UPLATA_PODRAZUMEVANO, iznos: "" });
  // popup kartice: uvek za postojeću uplatu (dugme "Kartica" u redu tabele)
  const [karticaPopup, setKarticaPopup] = useState<{ kljuc: number; vrednost: KarticaPodaci } | null>(null);
  const [karticaCuva, setKarticaCuva] = useState(false);
  // popup administrativne zabrane: za sačuvani ugovor (dugme u zajedničkoj traci)
  const [zabranaOtvorena, setZabranaOtvorena] = useState(false);
  // popup čekova: uvek za postojeću uplatu (dugme "Čekovi" u redu tabele)
  const [cekPopup, setCekPopup] = useState<{ kljuc: number; iznos: number; pocetni: CekStavka[] } | null>(null);
  const [cekCuva, setCekCuva] = useState(false);
  const [cekUcitavaKljuc, setCekUcitavaKljuc] = useState<number | null>(null);
  const [tipoviKartica, setTipoviKartica] = useState<string[]>([]);
  const [uplateRedovi, setUplateRedovi] = useState<UplataRow[] | null>(null);
  const [prebacivanjeUplata, setPrebacivanjeUplata] = useState<UplataRow | null>(null);
  const [uplateUcitavaju, setUplateUcitavaju] = useState(false);
  const [uplataSeCuva, setUplataSeCuva] = useState(false);
  const uplataZakljucana = useRef(false);
  const [uplateOsvezi, setUplateOsvezi] = useState(0);
  const [uplatePdfUcitava, setUplatePdfUcitava] = useState(false);
  // administrativne zabrane vezane za izabrani ugovor (prikaz u tabu Uplate + štampa)
  const [zabraneUgovora, setZabraneUgovora] = useState<ZabranaVezana[]>([]);
  const [zabranaPdfBroj, setZabranaPdfBroj] = useState<string | null>(null);
  const [saglasnostPdfUcitava, setSaglasnostPdfUcitava] = useState(false);
  const [priznanicaKljuc, setPriznanicaKljuc] = useState<number | null>(null);
  const [istorija, setIstorija] = useState<IstorijaRed[] | null>(null);
  const [istorijaUcitava, setIstorijaUcitava] = useState(false);
  const [istorijaOtvorena, setIstorijaOtvorena] = useState(false);
  const uplateRequest = useRef(0);
  const karticaToastIds = useRef<number[]>([]);

  // Sačuvaj / Izmeni — snimanje u bazu i zaključavanje forme
  const [izmena, setIzmena] = useState(false);
  const [rezSeCuva, setRezSeCuva] = useState(false);
  const rezZakljucana = useRef(false);
  /** zaključano: ugovor je učitan/sačuvan i nije u režimu izmene (osim pretrage) */
  const zakljucano = izabraniUgovor !== null && !izmena;
  /** postojeća rezervacija: datumi, smeštaj, mesto i struktura se ne menjaju ni u režimu izmene */
  /** Boravak i smeštaj su uvek zaključani (i kad su prazni, i kod postojeće rezervacije) dok korisnik ne klikne „Otključaj“ */
  const [boravakOtkljucan, setBoravakOtkljucan] = useState(false);
  const boravakZakljucan = zakljucano || !boravakOtkljucan;
  // opcije Tipa rezervacije — proširene sačuvanom vrednošću van standardnog spiska
  const [tipOpcije, setTipOpcije] = useState<string[]>(TIP_REZERVACIJE);
  // sačuvani nazivi van referentnih lista (stari ugovori) — prikaz + čuvanje bez gubitka
  const [smestajSacuvan, setSmestajSacuvan] = useState<string | null>(null);
  const [sobaSacuvana, setSobaSacuvana] = useState<string | null>(null);
  const [mestoSacuvano, setMestoSacuvano] = useState<string | null>(null);
  const [destinacijaSacuvana, setDestinacijaSacuvana] = useState<string | null>(null);
  /** mesto u trenutku učitavanja ugovora — vezivanje destinacije za mesto se pauzira dok se mesto ne promeni */
  const mestoUgovoraRef = useRef<string | null>(null);

  // referentni podaci (read-only)
  const [mesta, setMesta] = useState<Mesto[]>([]);
  const [smestaji, setSmestaji] = useState<Smestaj[]>([]);
  const [sobe, setSobe] = useState<Soba[]>([]);
  const [destinacije, setDestinacije] = useState<Destinacija[]>([]);
  const [kurs, setKurs] = useState<{ kurs: number | null; datum: string } | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      apiFetch<Mesto[]>("/mesto"), apiFetch<Smestaj[]>("/smestaj"),
      apiFetch<Soba[]>("/sobe"), apiFetch<Destinacija[]>("/destinacija"),
    ]).then(([m, s, sobeData, d]) => {
      if (cancelled) return;
      setMesta(m); setSmestaji(s); setSobe(sobeData); setDestinacije(d);
      setReferenceSpremne(true);
    }).catch(() => { if (!cancelled) toast.error("Učitavanje podataka za rezervaciju nije uspelo"); });
    apiFetch<{ kurs: number | null; datum: string }>("/kurs").then(setKurs).catch(() => {});
    apiFetch<string[]>("/tipovi-kartica").then(setTipoviKartica).catch(() => {});
    return () => { cancelled = true; };
  }, []);

  // Izbor destinacije je vezan za mesto: prati destinaciju povezanu sa izabranim mestom (boravak.mesto).
  // Kod učitanog ugovora veza se pauzira dok se mesto ne promeni — sačuvana destinacija
  // ugovora se ne pregaza automatski vezom mesta.
  useEffect(() => {
    if (mestoUgovoraRef.current !== null && boravak.mesto === mestoUgovoraRef.current) return;
    mestoUgovoraRef.current = null;
    if (!boravak.mesto || boravak.mesto === CUVAR) { setDestinacijaZaSve(""); return; }
    const m = mesta.find((x) => String(x.id) === boravak.mesto);
    setDestinacijaZaSve(m?.destinacija ? String(m.destinacija) : "");
  }, [boravak.mesto, mesta]);

  // Registar prevoza — mesta ulaska (tabela polazak): jedan poziv pri montiranju,
  // uz mogućnost ponavljanja iz taba Prevoz ako učitavanje ne uspe.
  useEffect(() => {
    let cancelled = false;
    setPolasciGreska(false);
    apiFetch<PolazakUlazak[]>("/polazak")
      .then((redovi) => { if (!cancelled) setPolasci(redovi); })
      .catch(() => { if (!cancelled) { setPolasciGreska(true); toast.error("Učitavanje mesta ulaska nije uspelo"); } });
    return () => { cancelled = true; };
  }, [polasciOsvezi]);

  // Ista pretraga kao na naslovnoj: putnik/broj ugovora, 400 ms debounce.
  useEffect(() => {
    const request = ++pretragaRequest.current;
    if (pretraga.trim().length < 3 || pretraga.trim() === izabraniUgovor) {
      setPretragaRezultati([]); setPretragaUkupno(0); setPretragaUcitava(false);
      return;
    }
    setPretragaRezultati([]);
    setPretragaUcitava(true);
    const timer = setTimeout(() => {
      const params = new URLSearchParams({ search: pretraga.trim(), search_in: "putnik,kljuc", page_size: String(PRETRAGA_STRANA), sort: "kljuc", dir: "asc" });
      apiFetch<UgovoriResponse>(`/ugovori?${params}`)
        .then((data) => { if (request === pretragaRequest.current) { setPretragaRezultati(data.rows); setPretragaUkupno(data.total); } })
        .catch(() => { if (request === pretragaRequest.current) { setPretragaRezultati([]); setPretragaUkupno(0); toast.error("Pretraga ugovora nije uspela"); } })
        .finally(() => { if (request === pretragaRequest.current) setPretragaUcitava(false); });
    }, 400);
    return () => clearTimeout(timer);
  }, [pretraga, izabraniUgovor]);

  // Sledeća strana pretrage ugovora (dopunjava listu; zaštićeno od zastarelih odgovora)
  const [pretragaDopunjava, setPretragaDopunjava] = useState(false);
  async function ucitajVisePretrage() {
    const request = pretragaRequest.current;
    const strana = Math.floor(pretragaRezultati.length / PRETRAGA_STRANA) + 1;
    setPretragaDopunjava(true);
    try {
      const params = new URLSearchParams({ search: pretraga.trim(), search_in: "putnik,kljuc", page: String(strana), page_size: String(PRETRAGA_STRANA), sort: "kljuc", dir: "asc" });
      const data = await apiFetch<UgovoriResponse>(`/ugovori?${params}`);
      if (request === pretragaRequest.current) {
        setPretragaRezultati((prev) => [...prev, ...data.rows]);
        setPretragaUkupno(data.total);
      }
    } catch {
      toast.error("Učitavanje dodatnih ugovora nije uspelo");
    } finally {
      setPretragaDopunjava(false);
    }
  }

  // Skrol-učitavanje: kad sentinel na dnu liste uđe u vidljivo polje liste, učitaj sledeću stranu
  const pretragaListaRef = useRef<HTMLDivElement | null>(null);
  const pretragaCuvarRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const root = pretragaListaRef.current;
    const cuvar = pretragaCuvarRef.current;
    if (!root || !cuvar || pretragaDopunjava) return;
    const posmatrac = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) void ucitajVisePretrage();
      },
      { root, rootMargin: "0px 0px 40px 0px" },
    );
    posmatrac.observe(cuvar);
    return () => posmatrac.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pretragaRezultati.length, pretragaUkupno, pretragaDopunjava, pretragaOtvorena, pretraga]);

  const [stornoOtvoren, setStornoOtvoren] = useState(false);
  const [stornoSeCuva, setStornoSeCuva] = useState(false);
  const stornoLock = useRef(false);

  async function stornirajRezervaciju() {
    if (!izabraniUgovor || stornoLock.current) return;
    const kljuc = izabraniUgovor;
    stornoLock.current = true;
    setStornoSeCuva(true);
    try {
      await apiFetch(`/rezervacije/${encodeURIComponent(kljuc)}/storno`, { method: "POST" });
      setStornoOtvoren(false);
      await izaberiUgovor(kljuc);
      toast.success(`Rezervacija ${kljuc} je stornirana`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Storniranje nije uspelo");
    } finally {
      stornoLock.current = false;
      setStornoSeCuva(false);
    }
  }

  const izaberiUgovor = async (kljuc: string) => {
    const request = ++izborRequest.current;
    setBrisanjeStavka(null);
    dodatneSesija.current += 1;
    setIzborUcitava(true);
    try {
      const d = await apiFetch<UgovorDetail>(`/ugovori/${encodeURIComponent(kljuc)}`);
      if (request !== izborRequest.current) return;
      // Upisujemo samo polja sa jasnom vezom u bazi; nepotvrđena polja ostaju prazna.
      const naziv = (v: string | null | undefined) => (v ?? "").trim().toLocaleLowerCase();
      const mestoId = mesta.find((m) => naziv(m.naziv) === naziv(d.mesto))?.id;
      const kandidati = smestaji.filter((s) => naziv(s.naziv) === naziv(d.naziv));
      const smestajId = (kandidati.find((s) =>
        (!mestoId || s.mesto === mestoId) && sobe.some((r) => r.veza_id_smestaj === s.id && naziv(r.broj_sobe) === naziv(d.soba))
      ) ?? kandidati.find((s) => !mestoId || s.mesto === mestoId) ?? kandidati[0])?.id;
      const sobaId = smestajId && sobe.find((s) => s.veza_id_smestaj === smestajId && naziv(s.broj_sobe) === naziv(d.soba))?.id;
      // tip: poznata vrednost → normalizovana opcija; nepoznata → ostaje kakva jeste (bez gubitka pri čuvanju)
      const ucitanTip = (d.tiprezervacije ?? "").trim();
      const tip = TIP_REZERVACIJE.find((t) => naziv(t) === naziv(ucitanTip) || naziv(t.split(" ")[0]) === naziv(ucitanTip));
      if (ucitanTip && !tip) setTipOpcije((prev) => (prev.includes(ucitanTip) ? prev : [...prev, ucitanTip]));
      setTipRezervacije(tip ?? ucitanTip ?? TIP_REZERVACIJE[0]);
      setSubagent((d.subagent ?? "").trim());
      // sačuvani nazivi van referentnih lista → fallback opcija "(sačuvano)" umesto praznog izbora
      setSmestajSacuvan(smestajId ? null : (d.naziv ?? "").trim() || null);
      setSobaSacuvana(sobaId ? null : (d.soba ?? "").trim() || null);
      setMestoSacuvano(mestoId ? null : (d.mesto ?? "").trim() || null);
      const destinacijaId = destinacije.find((x) => naziv(x.naziv) === naziv(d.destinacija))?.id;
      setDestinacijaSacuvana(destinacijaId ? null : (d.destinacija ?? "").trim() || null);
      setDestinacijaZaSve(destinacijaId ? String(destinacijaId) : (d.destinacija ?? "").trim() ? CUVAR : "");
      const tl = /^(\d{2})\.(\d{2})\.(\d{4}) (\d{2}):\d{2}$/.exec(d.timelimit ?? "");
      setTimeLimitDatum(tl && tip === "Predrezervacija" ? new Date(+tl[3], +tl[2] - 1, +tl[1]) : undefined);
      setTimeLimitSat(tl ? tl[4] : "12");
      setPrevozDetaljiOtvoreni({});
      const nosilacOw = !!d.prevozow;
      setNosilac({ ...prazanNosilac, ime: d.putnik ?? "", datumRodjenja: d.rodjen ?? "", pasos: d.pasos ?? "", uzrast: d.uzrast ?? "", adresa: d.adresa ?? "", grad: d.grad ?? "", telefon: d.telefon ?? "", email: d.refno ?? "", ow: nosilacOw, rt: !nosilacOw && !!d.prevozrt, smer: nosilacOw ? d.smer ?? "" : "", datumOw: d.datum_ow ?? "", destinacijaOw: d.destinacija_ow ?? "", datumPolaska: d.datum_polaska ?? "", datumPovratka: d.datum_povratka ?? "", destinacijaPolaska: d.destinacija_polaska ?? "", destinacijaPovratka: d.destinacija_povratka ?? "" });
      const dopuna = (d.putnici_detalji ?? []).filter((p) => !!p.saputnik?.trim());
      const dodati = dopuna.map((p) => {
        const uid = `s${++uidRef.current}`;
        const ow = !!p.prevozow;
        return { ...prazanSaputnik(uid), ime: p.saputnik, datumRodjenja: p.rodjen ?? "", pasos: p.pasos ?? "", uzrast: p.uzrast ?? "", adresa: p.adresa ?? "", grad: p.grad ?? "", email: p.email ?? "", telefon: p.telefon ?? "", ow, rt: !ow && !!p.prevozrt, smer: ow ? p.smer ?? "" : "", datumOw: p.datum_ow ?? "", destinacijaOw: p.destinacija_ow ?? "", datumPolaska: p.datum_polaska ?? "", datumPovratka: p.datum_povratka ?? "", destinacijaPolaska: p.destinacija_polaska ?? "", destinacijaPovratka: p.destinacija_povratka ?? "" };
      });
      setSaputnici(dodati);
      setDodatneStavke(d.dodatne ?? []);
      setDodatnaIzmena(null);
      dodatneSesija.current += 1; // nova sesija liste dodatnih stavki
      const novoMesto = mestoId ? String(mestoId) : (d.mesto ?? "").trim() ? CUVAR : "";
      mestoUgovoraRef.current = novoMesto || null; // destinacija se ne veže ponovo dok se mesto ne promeni
      setBoravak({ datumOd: datumZaInput(d.datumod), datumDo: datumZaInput(d.datumdo), smestaj: smestajId ? String(smestajId) : (d.naziv ?? "").trim() ? CUVAR : "", soba: sobaId ? String(sobaId) : (d.soba ?? "").trim() ? CUVAR : "", mesto: novoMesto, struktura: d.apartman ?? "", promenaStrukture: "", viza: Number(d.viza) === 1, napomena: d.napomena ?? "", napomenaInterna: d.napomena1 ?? "", napomenaPrevoz: d.napomena_prevoz ?? "" });
      // način plaćanja iz baze (promena se kasnije potvrđuje dijalogom)
      setPlacanje(d.nacin_placanja === "delimicno" || d.nacin_placanja === "u_celosti" ? d.nacin_placanja : "");
      setPlacanjeZahtev(null);
      // Cena smeštaja i uplaćeno dolaze iz ugovora; dodatne stavke (i njihove sume) iz d.dodatne —
      // cenadod se ne upisuje u formu da se sa dodatenSume ne bi sabiralo dvostruko.
      // Osiguranje se učitava iz aranzman.osiguranje (RSD) / osiguranje1 (EUR).
      // RSD cene/količine ostaju lokalna polja i resetuju se pri izboru ugovora.
      // Popusti i provizije se vraćaju iz baze: popustar/popustpr/procenatar su procenti, procenatpr je iznos po osobi (EUR).
      setCene({ cenaSmestaj: brojUString(d.cenaaranz), kolSmestaj: brojUString(d.kolaranz), cenaSmestajRSD: "", kolSmestajRSD: "", popustSmestajPct: "", popustSmestaj: "", popustSmestajRSD: "", cenaPrevoz: "", kolPrevoz: "", cenaPrevozRSD: "", kolPrevozRSD: "", popustPrevozPct: "", popustPrevoz: "", popustPrevozRSD: "", osiguranjeEUR: brojUString(d.osiguranje1), osiguranjeRSD: brojUString(d.osiguranje), provizijaSmestajPct: "", provizijaSmestaj: "", provizijaSmestajRSD: "", provizijaPrevozPct: "", provizijaPrevoz: "", provizijaPrevozRSD: "", uplaceno: brojUString(d.uplacenod) });
      // Vraćanje popusta i provizija iz baze: procenat ide u polje %, iznosi se izvode preko updCene
      // (isto kao ručni unos, sa cenom i količinom koje su upravo postavljene).
      const procenatUcitan = (v: number | null | undefined) => (v && v > 0 ? brojUString(v) : "");
      const kolPrevozUcitan = Math.max(d.kolow ?? 0, d.kolrt ?? 0) || 1;
      updCene({
        popustSmestajPct: procenatUcitan(d.popustar),
        popustPrevozPct: procenatUcitan(d.popustpr),
        provizijaSmestajPct: procenatUcitan(d.procenatar),
        provizijaPrevoz: d.procenatpr && d.procenatpr > 0 ? brojUString(round2(d.procenatpr * kolPrevozUcitan)) : "",
      });
      setPrevozRedovi({ nosilac: { mestoUlaska: d.ulazak ?? "", mestoIzlaska: d.mesto_izlaska ?? d.ulazak ?? "", mestoSedenja: d.mesto_sedenja ?? "", placeno: !!d.placeno_prevoz, zelja: !!d.zelja_prevoz }, ...Object.fromEntries(dodati.map((p, i) => [p.uid, { mestoUlaska: dopuna[i].ulazak ?? "", mestoIzlaska: dopuna[i].mesto_izlaska ?? dopuna[i].ulazak ?? "", mestoSedenja: dopuna[i].mesto_sedenja ?? "", placeno: !!dopuna[i].placeno_prevoz, zelja: !!dopuna[i].zelja_prevoz }])) });
      setUplata({ uplatilac: "nosilac", ...UPLATA_PODRAZUMEVANO, iznos: "" });
      setIzabraniUgovor(d.kljuc);
      setUcitanUgovor(d);
      void osveziKeptp(d.kljuc);
      setIzmena(false); // učitavam postojeći ugovor → polja zaključana do klika na „Izmeni“
      setBoravakOtkljucan(false);
      setPretraga(d.kljuc);
      setUplateOsvezi((n) => n + 1);
      setPretragaOtvorena(false);
    } catch {
      if (request === izborRequest.current) toast.error("Ugovor nije mogao da se učita");
    } finally {
      if (request === izborRequest.current) setIzborUcitava(false);
    }
  };

  // KEPTP — evidencija prodatih aranžmana (tabela keptp, numeracija od 1; aranzman.keptp se ne dira)
  const [keptp, setKeptp] = useState<KeptpInfo | null>(null);
  const [keptpSeDodeljuje, setKeptpSeDodeljuje] = useState(false);
  const [keptpUpit, setKeptpUpit] = useState<{ kljuc: string; izmena: boolean } | null>(null);

  const osveziKeptp = async (kljuc: string): Promise<KeptpInfo | null> => {
    try {
      const r = await apiFetch<KeptpInfo | null>(`/keptp/ugovor/${encodeURIComponent(kljuc)}`);
      if (aktivniUgovor.current === kljuc) setKeptp(r);
      return r;
    } catch {
      return null;
    }
  };

  const keptpDodeli = async (kljuc: string) => {
    if (keptpSeDodeljuje || keptpNijePotreban(tipRezervacije, boravak.viza)) return;
    setKeptpSeDodeljuje(true);
    try {
      const r = await apiFetch<KeptpInfo>("/keptp/dodeli", { method: "POST", body: JSON.stringify({ kljuc }) });
      if (aktivniUgovor.current === kljuc) setKeptp(r);
      toast.success(`Dodeljen KEPTP broj ${r.broj_keptp}`, { description: `Ugovor: ${kljuc}` });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "KEPTP broj nije dodeljen");
    } finally {
      setKeptpSeDodeljuje(false);
    }
  };

  useEffect(() => {
    if (!ugovorIzLinka) { linkUcitavanja.current = null; return; }
    if (!referenceSpremne || linkUcitavanja.current === ugovorIzLinka) return;
    linkUcitavanja.current = ugovorIzLinka;
    void izaberiUgovor(ugovorIzLinka);
    // Učitavanje samo pri promeni URL ključa, tek nakon referentnih podataka.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ugovorIzLinka, referenceSpremne]);

  // Prefill iz Grafika/Pretrage: /prodaja/rezervacije?novi=1&datumod=…&datumdo=…&soba=…&smestaj=…&mesto=…
  // Pretraga dodaje i: struktura, cena (EUR, cela soba), popust (EUR iznos), odrasli, deca (godine), prevoz (autobuski|sopstveni)
  const noviIzLinka = searchParams.get("novi") === "1";
  const noviPrimljen = useRef<string | null>(null);
  useEffect(() => {
    if (!noviIzLinka) { noviPrimljen.current = null; return; }
    if (!referenceSpremne || ugovorIzLinka) return; // ugovor iz linka ima prednost
    const sig = searchParams.toString();
    if (noviPrimljen.current === sig) return;
    noviPrimljen.current = sig;
    const struktura = searchParams.get("struktura");
    const subagentIzLinka = searchParams.get("subagent");
    if (subagentIzLinka) setSubagent(subagentIzLinka.trim());
    setBoravak((prev) => ({
      ...prev,
      datumOd: datumZaInput(searchParams.get("datumod")),
      datumDo: datumZaInput(searchParams.get("datumdo")),
      smestaj: searchParams.get("smestaj") || prev.smestaj,
      soba: searchParams.get("soba") || prev.soba,
      mesto: searchParams.get("mesto") || prev.mesto,
      struktura: struktura || prev.struktura,
    }));
    const odrasli = Number(searchParams.get("odrasli") ?? "");
    const deca = (searchParams.get("deca") ?? "").split(",").filter((x) => x.trim() !== "").length;
    // Cena iz pretrage je ukupna cena sobe → rastavlja se po osobama: količina = broj osoba, jedinična = cena / broj osoba.
    const brojOsoba = Number.isFinite(odrasli) && odrasli >= 1 ? odrasli + deca : 1;
    const cena = searchParams.get("cena");
    if (cena && Number.isFinite(Number(cena))) {
      const popust = searchParams.get("popust");
      const popustPct = searchParams.get("popustPct");
      // Popust ostaje ukupan iznos: bruto (jedinična × količina) − popust.
      // Iz Grafika stiže kao procenat (popustPct) → upisuje se u „Popust smeštaja %“.
      setCene((prev) => ({
        ...prev,
        cenaSmestaj: (Number(cena) / brojOsoba).toFixed(2),
        kolSmestaj: String(brojOsoba),
        popustSmestajPct: popustPct && Number(popustPct) > 0 ? popustPct : "",
        popustSmestaj: !popustPct && popust && Number(popust) > 0 ? popust : "",
      }));
    }
    const prevozParam = searchParams.get("prevoz");
    if (Number.isFinite(odrasli) && odrasli >= 1) {
      const rt = prevozParam === "autobuski";
      const sp = prevozParam === "sopstveni";
      setNosilac((prev) => ({ ...prev, rt, sp, ow: false }));
      const brojSaputnika = Math.max(0, odrasli + deca - 1);
      setSaputnici(Array.from({ length: brojSaputnika }, () => ({ ...prazanSaputnik(`s${++uidRef.current}`), rt, sp })));
    }
    // Primena samo pri promeni parametara linka, tek nakon referentnih podataka.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [noviIzLinka, referenceSpremne, ugovorIzLinka, searchParams]);

  const sobeSmestaja = useMemo(
    () => sobe.filter((s) => String(s.veza_id_smestaj) === boravak.smestaj),
    [sobe, boravak.smestaj],
  );

  // spisak putnika za tabove Prevoz i Uplate
  const putnici = useMemo(() => [
    { uid: "nosilac", ime: nosilac.ime.trim() || "Nosilac aranžmana", osnovni: true as const },
    ...saputnici.map((s, i) => ({
      uid: s.uid,
      ime: s.ime.trim() || `Saputnik ${i + 1}`,
      osnovni: false as const,
    })),
  ], [nosilac.ime, saputnici]);

  // Mesta ulaska iz registra prevoza: opciono sužena na izabranu destinaciju — po nazivu,
  // jer je polazak.destinacija tekst, ne ID (ako nema poklapanja, ostaju svi redovi).
  // Jedinstveni, trimovani, neprazni, sortirani sr-lokalno.
  const mestaUlaskaOpcije = useMemo(() => {
    const naziv = (v: string | null | undefined) => (v ?? "").trim().toLocaleLowerCase();
    const sel = destinacije.find((d) => String(d.id) === destinacijaZaSve);
    let redovi = polasci;
    if (sel) {
      const filtrirani = polasci.filter((p) => naziv(p.destinacija) === naziv(sel.naziv));
      if (filtrirani.length > 0) redovi = filtrirani;
    }
    const skup = new Set<string>();
    for (const r of redovi) {
      const v = (r.polazak ?? "").trim();
      if (v) skup.add(v);
    }
    return [...skup].sort((a, b) => a.localeCompare(b, "sr"));
  }, [polasci, destinacije, destinacijaZaSve]);

  // TRANSFER stavke: po mestu ulaska zbir transfera svih putnika (nosilac + saputnici) iz registra prevoza.
  // Red registra = prvi po satu/id koji se poklapa sa mestom ulaska i izabranom destinacijom.
  // Zbir 0 → stavka se ne prikazuje (nestaje kad putnik pređe na mesto bez transfera).
  const transferStavke = useMemo<NonNullable<UgovorDetail["dodatne"]>>(() => {
    const naziv = (v: string | null | undefined) => (v ?? "").trim().toLocaleLowerCase();
    const nazivDest = destinacijaZaSve === CUVAR
      ? destinacijaSacuvana
      : destinacije.find((x) => String(x.id) === destinacijaZaSve)?.naziv ?? null;
    const satBroj = (v: string | null | undefined) => {
      const n = parseFloat(v ?? "");
      return Number.isNaN(n) ? Number.POSITIVE_INFINITY : n;
    };
    const ulazi = [
      prevozRedovi["nosilac"]?.mestoUlaska ?? "",
      ...saputnici.filter((s) => s.ime.trim()).map((s) => prevozRedovi[s.uid]?.mestoUlaska ?? ""),
    ];
    const zbir = new Map<string, number>();
    for (const u of ulazi) {
      const mesto = u.trim();
      if (!mesto) continue;
      const kandidati = polasci
        .filter((p) => (p.polazak ?? "").trim() === mesto && (!nazivDest || naziv(p.destinacija) === naziv(nazivDest)))
        .sort((a, b) => {
          const sa = satBroj(a.sat);
          const sb = satBroj(b.sat);
          return sa === sb ? a.id - b.id : sa < sb ? -1 : 1;
        });
      const cena = kandidati[0]?.cena_transfera ?? 0;
      if (!cena) continue;
      const kljuc = mesto.toLocaleUpperCase("sr");
      zbir.set(kljuc, (zbir.get(kljuc) ?? 0) + cena);
    }
    const out: NonNullable<UgovorDetail["dodatne"]> = [];
    let redni = 0;
    for (const [mesto, eur] of zbir) {
      if (!eur) continue;
      redni += 1;
      // negativan stavka_id = izračunata stavka (nije u tabeli dodatne); ključ reda u React listi
      out.push({ stavka_id: -redni, usluga: `TRANSFER - ${mesto}`, eur: Math.round(eur * 100) / 100, din: null });
    }
    return out;
  }, [prevozRedovi, saputnici, polasci, destinacije, destinacijaZaSve, destinacijaSacuvana]);

  // PLAĆENO MESTO: po mestu za sedenje zbir doplata za putnike koji su izabrali mesto i „Plaćeno“
  // (nosilac + saputnici). Iznos po mestu = parametri obračuna (EUR) × broj putnika. Iznos 0 → ne prikazuje se.
  const placenaMestaStavke = useMemo<NonNullable<UgovorDetail["dodatne"]>>(() => {
    if (!parametriObr) return [];
    const brojPoMestu = new Map<string, number>();
    const redovi = [
      prevozRedovi["nosilac"],
      ...saputnici.filter((s) => s.ime.trim()).map((s) => prevozRedovi[s.uid]),
    ];
    for (const red of redovi) {
      const mesto = (red?.mestoSedenja ?? "").trim();
      if (!red?.placeno || !mesto) continue;
      brojPoMestu.set(mesto, (brojPoMestu.get(mesto) ?? 0) + 1);
    }
    const out: NonNullable<UgovorDetail["dodatne"]> = [];
    let redni = 0;
    for (const [mesto, broj] of brojPoMestu) {
      const kljuc = DOPLATA_MESTA[mesto];
      const iznos = kljuc ? parametriObr[kljuc] ?? 0 : 0;
      if (!iznos) continue;
      redni += 1;
      // negativan stavka_id = izračunata stavka (nije u tabeli dodatne); ključ reda u React listi
      out.push({ stavka_id: -(100 + redni), usluga: `PLAĆENO MESTO - ${mesto}`, eur: Math.round(broj * iznos * 100) / 100, din: null });
    }
    return out;
  }, [prevozRedovi, saputnici, parametriObr]);

  // Prikaz dodatnih usluga = sačuvane stavke bez izračunatih redova + izračunate (TRANSFER, PLAĆENO MESTO)
  // (izračunati redovi iz baze se zamenjuju pri Sačuvaj, pa se ne prikazuju dvaput).
  const sveDodatne = useMemo(
    () => [...dodatneStavke.filter((s) => !jeIzracunata(s.usluga)), ...transferStavke, ...placenaMestaStavke],
    [dodatneStavke, transferStavke, placenaMestaStavke],
  );
  const sveDodatneSume = sveDodatne.reduce((suma, stavka) => ({
    eur: suma.eur + (stavka.eur ?? 0),
    din: suma.din + (stavka.din ?? 0),
  }), { eur: 0, din: 0 });

  useEffect(() => {
    // ako je izabrani uplatilac obrisan, vrati se na nosioca
    if (uplata.uplatilac !== "nosilac" && !putnici.some((p) => p.uid === uplata.uplatilac)) {
      setUplatilac("nosilac");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [saputnici]);

  const setUplatilac = (v: string) => setUplata((u) => ({ ...u, uplatilac: v }));
  const updPrevoz = (uid: string, patch: Partial<PrevozRed>) =>
    setPrevozRedovi((prev) => ({ ...prev, [uid]: { mestoUlaska: "", mestoIzlaska: "", mestoSedenja: "", placeno: false, zelja: false, ...(prev[uid] as Partial<PrevozRed>), ...patch } }));

  // Ažuriranje cena: dok je procenat aktivan, iznosi prate promene bruto subtotale (ista valuta);
  // direktna izmena iznosa briše procenat (pozivalac šalje i prazan procenat) — nema dvostrukog računanja.
  const updCene = (patch: Partial<Cene>) =>
    setCene((prev) => {
      const next = { ...prev, ...patch };
      // Brisanje samog procenta uklanja izvedene iznose; ručni iznos ostaje sačuvan.
      for (const [pct, eur, rsd] of [
        ["popustSmestajPct", "popustSmestaj", "popustSmestajRSD"],
        ["popustPrevozPct", "popustPrevoz", "popustPrevozRSD"],
        ["provizijaSmestajPct", "provizijaSmestaj", "provizijaSmestajRSD"],
        ["provizijaPrevozPct", "provizijaPrevoz", "provizijaPrevozRSD"],
      ] as const) {
        if (patch[pct] !== undefined && procenat(patch[pct]) == null
          && patch[eur] === undefined && patch[rsd] === undefined) {
          next[eur] = "";
          next[rsd] = "";
        }
      }
      const izProcenata = (pct: string, cena: string, kol: string) => {
        const p = procenat(pct);
        return p == null ? "" : brojUString(round2((p / 100) * (num(cena) * qty(kol))));
      };
      if (procenat(next.popustSmestajPct) != null) {
        next.popustSmestaj = izProcenata(next.popustSmestajPct, next.cenaSmestaj, next.kolSmestaj);
        next.popustSmestajRSD = izProcenata(next.popustSmestajPct, next.cenaSmestajRSD, next.kolSmestajRSD);
      }
      if (procenat(next.popustPrevozPct) != null) {
        next.popustPrevoz = izProcenata(next.popustPrevozPct, next.cenaPrevoz, next.kolPrevoz);
        next.popustPrevozRSD = izProcenata(next.popustPrevozPct, next.cenaPrevozRSD, next.kolPrevozRSD);
      }
      if (procenat(next.provizijaSmestajPct) != null) {
        // provizija smeštaja se računa na neto smeštaj (bruto − popust), ne na bruto
        const p = procenat(next.provizijaSmestajPct) ?? 0;
        const netoEUR = num(next.cenaSmestaj) * qty(next.kolSmestaj) - num(next.popustSmestaj);
        const netoRSD = num(next.cenaSmestajRSD) * qty(next.kolSmestajRSD) - num(next.popustSmestajRSD);
        next.provizijaSmestaj = brojUString(round2((p / 100) * Math.max(0, netoEUR)));
        next.provizijaSmestajRSD = brojUString(round2((p / 100) * Math.max(0, netoRSD)));
      }
      if (procenat(next.provizijaPrevozPct) != null) {
        // provizija prevoza se računa na neto prevoz (bruto − popust)
        const p = procenat(next.provizijaPrevozPct) ?? 0;
        const netoEUR = num(next.cenaPrevoz) * qty(next.kolPrevoz) - num(next.popustPrevoz);
        const netoRSD = num(next.cenaPrevozRSD) * qty(next.kolPrevozRSD) - num(next.popustPrevozRSD);
        next.provizijaPrevoz = brojUString(round2((p / 100) * Math.max(0, netoEUR)));
        next.provizijaPrevozRSD = brojUString(round2((p / 100) * Math.max(0, netoRSD)));
      }
      return next;
    });

  // Parametri obračuna (visina popusta / visina provizije) — jednom pri učitavanju
  useEffect(() => {
    apiFetch<{ visina_popusta: number; visina_provizije: number } & Partial<Record<string, number>>>("/parametri-obracuna")
      .then(setParametriObr)
      .catch(() => setParametriObr(null));
  }, []);

  // Provizija subagenta: kolona subagenti.provizija za tačno izabran naziv
  useEffect(() => {
    const naziv = subagent.trim();
    if (!naziv) { setSubagentProvizija(null); return; }
    let aktivan = true;
    apiFetch<{ rows: { naziv: string; provizija: number | null }[] }>(
      `/subagenti?${new URLSearchParams({ search: naziv, page_size: "100" })}`
    )
      .then((d) => { if (aktivan) setSubagentProvizija(d.rows.find((r) => (r.naziv ?? "").trim() === naziv)?.provizija ?? null); })
      .catch(() => { if (aktivan) setSubagentProvizija(null); });
    return () => { aktivan = false; };
  }, [subagent]);

  // Grafik/prefill bez broja osoba: struktura → adl (maks. broj ADL osoba iz koeficijenti_prodaje)
  // → saputnici = adl − 1, količina smeštaja = adl, cena iz Grafika se rastavlja po količini.
  const odrasliIzLinka = Number(searchParams.get("odrasli") ?? "");
  const bezOdrasliIzLinka = !(odrasliIzLinka >= 1);
  useEffect(() => {
    const st = boravak.struktura?.trim();
    if (!noviIzLinka || ugovorIzLinka || !bezOdrasliIzLinka || !st) { setAdlStrukture(null); setKoefStrukture(null); return; }
    let aktivan = true;
    apiFetch<{ redovi: { adl: number; chd: number; inf: number; koeficijent: number }[] }>(
      `/koeficijenti/struktura?${new URLSearchParams({ struktura: st })}`
    )
      .then((d) => {
        const red = d.redovi
          .filter((r) => r.chd === 0 && r.inf === 0)
          .reduce<{ adl: number; koeficijent: number } | null>((najbolji, r) => (!najbolji || r.adl > najbolji.adl ? r : najbolji), null);
        if (!aktivan) return;
        setAdlStrukture(red && red.adl > 0 ? red.adl : null);
        setKoefStrukture(red && red.koeficijent > 0 ? red.koeficijent : null);
      })
      .catch(() => { if (aktivan) { setAdlStrukture(null); setKoefStrukture(null); } });
    return () => { aktivan = false; };
  }, [boravak.struktura, noviIzLinka, ugovorIzLinka, bezOdrasliIzLinka]);

  useEffect(() => {
    if (adlStrukture == null || koefStrukture == null) return;
    setSaputnici((prev) => Array.from({ length: adlStrukture - 1 }, (_, i) => prev[i] ?? prazanSaputnik(`s${++uidRef.current}`)));
    // cena iz Grafika je po osobi → jedinična ostaje, količina = koeficijent strukture
    setCene((prev) => ({ ...prev, kolSmestaj: String(koefStrukture) }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [adlStrukture, koefStrukture]);

  // Način plaćanja i prevoz iz Grafika: plaćanje bira koji popust sobe važi; sopstveni prevoz menja cenu
  const placanjeIzLinka = noviIzLinka ? (searchParams.get("placanje") ?? "") : "";
  const prevozIzLinka = searchParams.get("prevoz") === "sopstveni" ? "sopstveni" : "autobuski";
  // Način plaćanja (delimično | u celosti | "" = bez izbora) — bira koji popust sobe važi
  const [placanje, setPlacanje] = useState(placanjeIzLinka);
  // Izvor za obračun popusta (podaci sobe iz /slobodne-sobe) + zahtev za promenu plaćanja (čeka potvrdu)
  const [izvorPopusta, setIzvorPopusta] = useState<IzvorPopusta | null>(null);
  const [placanjeZahtev, setPlacanjeZahtev] = useState<string | null>(null);

  // Maksimalni važeći popust sobe za izabrani način plaćanja → Popust smeštaja %
  // (samo kad je izabrana soba i boravak; izvor se čuva da bi promena plaćanja mogla ponovo da obračuna)
  useEffect(() => {
    setIzvorPopusta(null);
    if (adlStrukture == null) return;
    if (!boravak.smestaj || !boravak.soba || !boravak.datumOd || !boravak.datumDo || boravak.datumDo <= boravak.datumOd) return;
    const ddmm = (iso: string) => `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}`;
    const params = new URLSearchParams({
      datum_od: ddmm(boravak.datumOd),
      datum_do: ddmm(boravak.datumDo),
      odrasli: String(adlStrukture),
      prevoz: prevozIzLinka,
      // postojeći ugovor: njegova soba se ne računa kao zauzeta (inače nestaje iz liste)
      ...(izabraniUgovor ? { iskluci_kljuc: izabraniUgovor } : {}),
    });
    let aktivan = true;
    apiFetch<{ smestaj_id: number; sobe: { id: number; cena_osnovna: number | null; tip_cene?: string | null; varijante?: { vazi: boolean; cena_snizena: number | null; tip_placanja?: string | null }[] }[] }[]>(
      `/slobodne-sobe?${params}`
    )
      .then((grupe) => {
        if (!aktivan) return;
        const soba = grupe.find((g) => String(g.smestaj_id) === boravak.smestaj)?.sobe.find((s) => String(s.id) === boravak.soba);
        if (!soba || soba.cena_osnovna == null || soba.cena_osnovna <= 0) return;
        const osnovna = soba.cena_osnovna;
        const izvor: IzvorPopusta = { osnovna, varijante: soba.varijante ?? [] };
        setIzvorPopusta(izvor);
        // postojeći ugovor: sačuvani popust/cena ostaju; obračun se menja samo kroz promenu plaćanja
        if (!noviIzLinka || izabraniUgovor) return;
        // sopstveni prevoz: umanjenje je već u obračunu → jedinična (po osobi) = ukupno / koeficijent
        if (prevozIzLinka === "sopstveni" && soba.tip_cene === "po_osobi" && koefStrukture) {
          updCene({ cenaSmestaj: String(round2(osnovna / koefStrukture)) });
        }
        // pri učitavanju primenjuje se način plaćanja koji je već izabran (iz Grafika ili polja)
        const pct = popustZaPlacanje(izvor, placanje);
        if (pct) updCene({ popustSmestajPct: pct });
        else if (placanje) updCene({ popustSmestajPct: "" });
      })
      .catch(() => { /* bez popusta: polje ostaje kako je uneto */ });
    return () => { aktivan = false; };
    // promena plaćanja NE ide kroz ovaj efekt — samo kroz potvrdu (promeniPlacanje → potvrdiPlacanje)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [adlStrukture, koefStrukture, boravak.smestaj, boravak.soba, boravak.datumOd, boravak.datumDo, noviIzLinka, izabraniUgovor, prevozIzLinka]);

  // Promena načina plaćanja: ako postoji obračun (izabrana soba) → traži potvrdu; inače samo postavlja
  const promeniPlacanje = (novi: string) => {
    if (novi === placanje) return;
    if (izvorPopusta) setPlacanjeZahtev(novi);
    else setPlacanje(novi);
  };
  const potvrdiPlacanje = () => {
    if (placanjeZahtev == null || !izvorPopusta) { setPlacanjeZahtev(null); return; }
    setPlacanje(placanjeZahtev);
    updCene({ popustSmestajPct: popustZaPlacanje(izvorPopusta, placanjeZahtev) });
    setPlacanjeZahtev(null);
  };


  // Automatska provizija (samo nova rezervacija): popularan smeštaj → smestaj.provizija;
  // inače popust na smeštaj > visina_popusta → visina_provizije; inače provizija subagenta.
  const smestajIzabran = smestaji.find((s) => String(s.id) === boravak.smestaj);
  useEffect(() => {
    if (izabraniUgovor || !subagent.trim() || !parametriObr) return;
    // stvarni procenat popusta na smeštaj: iz procenta, ili iz iznosa (EUR) / bruto smeštaja
    const bruto = num(cene.cenaSmestaj) * qty(cene.kolSmestaj);
    const popustPct = procenat(cene.popustSmestajPct) ?? (bruto > 0 ? (num(cene.popustSmestaj) / bruto) * 100 : 0);
    let pct: number | null;
    if (smestajIzabran?.popular) pct = smestajIzabran.provizija;
    else if (popustPct > parametriObr.visina_popusta) pct = parametriObr.visina_provizije;
    else pct = subagentProvizija;
    if (pct == null) return;
    updCene({ provizijaSmestajPct: String(pct) });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [subagent, subagentProvizija, smestajIzabran?.popular, smestajIzabran?.provizija, cene.popustSmestajPct, cene.popustSmestaj, cene.cenaSmestaj, cene.kolSmestaj, parametriObr, izabraniUgovor]);

  useEffect(() => {
    const request = ++uplateRequest.current;
    if (!izabraniUgovor) {
      setUplateRedovi(null);
      setUplateUcitavaju(false);
      return;
    }
    setUplateRedovi(null);
    setUplateUcitavaju(true);
    apiFetch<{ rows: UplataRow[]; total: number }>(`/ugovori/${encodeURIComponent(izabraniUgovor)}/uplate`)
      .then((data) => { if (request === uplateRequest.current) setUplateRedovi(data.rows); })
      .catch(() => { if (request === uplateRequest.current) { setUplateRedovi(null); toast.error("Učitavanje uplata nije uspelo"); } })
      .finally(() => { if (request === uplateRequest.current) setUplateUcitavaju(false); });
  }, [izabraniUgovor, uplateOsvezi]);

  // Administrativne zabrane ugovora: osvežava se pri izboru ugovora i posle zatvaranja popupa zabrane
  useEffect(() => {
    if (!izabraniUgovor) { setZabraneUgovora([]); return; }
    let aktivan = true;
    apiFetch<{ rows: ZabranaVezana[] }>(`/ugovori/${encodeURIComponent(izabraniUgovor)}/zabrane`)
      .then((data) => { if (aktivan) setZabraneUgovora(data.rows); })
      .catch(() => { if (aktivan) setZabraneUgovora([]); });
    return () => { aktivan = false; };
  }, [izabraniUgovor, zabranaOtvorena]);

  async function preuzmiZabranuPdf(broj: string) {
    if (zabranaPdfBroj) return;
    setZabranaPdfBroj(broj);
    try {
      const token = getToken();
      const res = await fetch(`/api/zabrane/pdf?${new URLSearchParams({ broj })}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `Administrativna_zabrana_${broj.replace("/", "-")}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch {
      toast.error("Greška pri generisanju PDF-a zabrane");
    } finally {
      setZabranaPdfBroj(null);
    }
  }

  // Pri promeni ugovora zatvori toaste kartica prethodnog ugovora
  useEffect(() => {
    karticaToastIds.current.forEach((kljuc) => toast.dismiss(karticaToastId(kljuc)));
    karticaToastIds.current = [];
  }, [izabraniUgovor]);

  // Pri učitavanju uplata: uplate kartice bez podataka → crveni toast (izabraniUgovor je tu već novi,
  // a uplateRedovi su sveži jer se efekat okida samo na promenu redova)
  useEffect(() => {
    if (!uplateRedovi || !izabraniUgovor) return;
    for (const u of uplateRedovi) {
      if (u.kljuc != null && u.nacin?.trim() === "Kartica" && !karticaImaPodatke(u)) {
        prikaziKarticaNeunetu(u.kljuc, izabraniUgovor);
        karticaToastIds.current.push(u.kljuc);
      }
    }
  }, [uplateRedovi]); // eslint-disable-line react-hooks/exhaustive-deps

  // Istorija promena (rezervacija_log) izabranog ugovora; osvežava se pri izboru, snimanju i uplati
  useEffect(() => {
    if (!izabraniUgovor) {
      setIstorija(null);
      setIstorijaUcitava(false);
      return;
    }
    let aktivno = true;
    setIstorijaUcitava(true);
    apiFetch<{ rows: IstorijaRed[] }>(`/rezervacije-istorija?kljuc=${encodeURIComponent(izabraniUgovor)}&limit=200`)
      .then((data) => { if (aktivno) setIstorija(data.rows); })
      .catch(() => { if (aktivno) { setIstorija(null); toast.error("Istorija nije učitana"); } })
      .finally(() => { if (aktivno) setIstorijaUcitava(false); });
    return () => { aktivno = false; };
  }, [izabraniUgovor, ucitanUgovor, uplateOsvezi, dodatneStavke]);

  async function potvrdiUplatu() {
    if (uplataZakljucana.current) return;
    if (!izabraniUgovor) { toast.error("Prvo izaberite ugovor"); return; }
    const tekstIznosa = uplata.iznos.trim();
    if (!/^-?\d+(?:[.,]\d{1,2})?$/.test(tekstIznosa)) {
      toast.error("Unesite ispravan iznos sa najviše dve decimale"); return;
    }
    const din = Number(tekstIznosa.replace(",", "."));
    if (!Number.isFinite(din) || din === 0) { toast.error("Iznos mora biti različit od nule"); return; }
    if (!uplata.nacin || !uplata.svrha) { toast.error("Izaberite način plaćanja i svrhu uplate"); return; }
    const platilac = uplata.uplatilac === "nosilac"
      ? nosilac : saputnici.find((p) => p.uid === uplata.uplatilac);
    if (!platilac?.ime.trim()) { toast.error("Ime uplatioca je obavezno"); return; }
    const ugovor = izabraniUgovor;
    uplataZakljucana.current = true;
    setUplataSeCuva(true);
    try {
      const result = await apiFetch<{ kljuc: number; message: string }>("/uplate", {
        method: "POST",
        body: JSON.stringify({ ugovor, ime: platilac.ime.trim(),
          adresa: (platilac.adresa ?? "").trim(),
          nacin: uplata.nacin, din, svrha: uplata.svrha }),
      });
      toast.success("Uplata je uspešno uneta", { description: `Broj uplate: ${result.kljuc} · Ugovor: ${ugovor}` });
      if (uplata.nacin.trim() === "Kartica" && ugovor === aktivniUgovor.current) {
        prikaziKarticaNeunetu(result.kljuc, ugovor);
        karticaToastIds.current.push(result.kljuc);
      }
      if (ugovor === aktivniUgovor.current) {
        setUplata((u) => ({ ...u, iznos: "" }));
        setUplateOsvezi((n) => n + 1);
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Uplata nije uneta");
    } finally {
      uplataZakljucana.current = false;
      setUplataSeCuva(false);
    }
  }

  // popup kartice: PUT na postojeću uplatu
  async function sacuvajKarticu(k: KarticaPodaci) {
    if (!karticaPopup) return;
    setKarticaCuva(true);
    try {
      await apiFetch(`/uplate/${karticaPopup.kljuc}/kartica`, { method: "PUT", body: JSON.stringify(k) });
      toast.success("Podaci kartice su sačuvani", { description: `Uplata ${karticaPopup.kljuc}` });
      toast.dismiss(karticaToastId(karticaPopup.kljuc));
      setKarticaPopup(null);
      setUplateOsvezi((n) => n + 1);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Podaci kartice nisu sačuvani");
    } finally {
      setKarticaCuva(false);
    }
  }

  // čekovi: PUT na postojeću uplatu (zamenjuje sve čekove te uplate)
  async function sacuvajCekove(stavke: CekStavka[]) {
    if (!cekPopup) return;
    setCekCuva(true);
    try {
      await apiFetch(`/uplate/${cekPopup.kljuc}/cekovi`, { method: "PUT", body: JSON.stringify({ cekovi: stavke }) });
      toast.success("Čekovi su sačuvani", { description: `Uplata ${cekPopup.kljuc}` });
      setCekPopup(null);
      setUplateOsvezi((n) => n + 1);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Čekovi nisu sačuvani");
    } finally {
      setCekCuva(false);
    }
  }

  async function otvoriCekove(u: UplataRow) {
    if (u.kljuc == null) return;
    const kljuc = u.kljuc;
    setCekUcitavaKljuc(kljuc);
    try {
      const rows = await apiFetch<CekStavka[]>(`/uplate/${kljuc}/cekovi`);
      setCekPopup({ kljuc, iznos: u.din ?? 0, pocetni: rows });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Čekovi nisu učitani");
    } finally {
      setCekUcitavaKljuc(null);
    }
  }

  // zbirovi kolona RSD i Suma € (negativan din = storno/povraćaj — ide u zbir kakav jeste)
  const uplateSumaRSD = useMemo(
    () => Math.round((uplateRedovi ?? []).reduce((s, u) => s + (u.din ?? 0), 0) * 100) / 100,
    [uplateRedovi],
  );
  const uplateSumaEUR = useMemo(
    () => Math.round((uplateRedovi ?? []).reduce((s, u) => s + (u.suma_eur ?? 0), 0) * 100) / 100,
    [uplateRedovi],
  );

  // PDF "Pregled uplata" (šablon starog sistema + logo) — preuzimanje fajla
  // Saglasnost za obradu podataka o ličnosti — PDF (zaglavlje iz Osnovnih podataka)
  async function preuzmiSaglasnostPdf() {
    if (!izabraniUgovor || saglasnostPdfUcitava) return;
    setSaglasnostPdfUcitava(true);
    try {
      const token = getToken();
      const res = await fetch(`/api/saglasnost/pdf?kljuc=${encodeURIComponent(izabraniUgovor)}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `Saglasnost_${izabraniUgovor.replace("/", "-")}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.error(
        err instanceof TypeError
          ? "Server nije dostupan — osveži stranicu i pokušaj ponovo"
          : "Greška pri generisanju saglasnosti",
      );
    } finally {
      setSaglasnostPdfUcitava(false);
    }
  }

  async function preuzmiUplatePdf() {
    if (!izabraniUgovor || uplatePdfUcitava) return;
    setUplatePdfUcitava(true);
    try {
      const token = getToken();
      const res = await fetch(`/api/ugovori/${encodeURIComponent(izabraniUgovor)}/uplate/pdf`, {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `Pregled_uplata_${izabraniUgovor.replace("/", "-")}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.error(
        err instanceof TypeError
          ? "Server nije dostupan — osveži stranicu i pokušaj ponovo"
          : "Greška pri generisanju PDF-a",
      );
    } finally {
      setUplatePdfUcitava(false);
    }
  }

  // priznanica za pojedinačnu uplatu (dva primerka na A4)
  async function preuzmiPriznanicu(kljuc: number) {
    if (priznanicaKljuc != null) return;
    setPriznanicaKljuc(kljuc);
    try {
      const token = getToken();
      const res = await fetch(`/api/uplate/${kljuc}/priznanica`, {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `Priznanica_${kljuc}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.error(
        err instanceof TypeError
          ? "Server nije dostupan — osveži stranicu i pokušaj ponovo"
          : "Greška pri generisanju priznanice",
      );
    } finally {
      setPriznanicaKljuc(null);
    }
  }

  // brisanje dodatne stavke — DELETE sa originalnim iznosima (backend vraća 409 pri istovremenoj izmeni)
  async function obrisiDodatnuStavku(stavka: DodatnaStavka) {
    if (brisanjeZakljucana.current) return;
    const ugovor = izabraniUgovor;
    if (!ugovor) return;
    const sesija = dodatneSesija.current;
    brisanjeZakljucana.current = true;
    setDodatnaBrisanje(stavka.stavka_id);
    try {
      await apiFetch<{ message: string }>(`/ugovori/${encodeURIComponent(ugovor)}/dodatne/${stavka.stavka_id}`, {
        method: "DELETE",
        body: JSON.stringify({ original: { usluga: stavka.usluga, eur: stavka.eur, din: stavka.din } }),
      });
      toast.success("Dodatna stavka je obrisana", { description: `Ugovor: ${ugovor}` });
      // Red se uklanja (a zbirovi preračunavaju) samo ako u međuvremenu nije učitan isti/drugi ugovor iznova.
      if (montirano.current && ugovor === aktivniUgovor.current && sesija === dodatneSesija.current) {
        setDodatneStavke((prev) => prev.filter((s) => s.stavka_id !== stavka.stavka_id));
        setBrisanjeStavka(null);
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Brisanje dodatne stavke nije uspelo");
    } finally {
      brisanjeZakljucana.current = false;
      if (montirano.current) setDodatnaBrisanje(null);
    }
  }

  // Ugovor (PDF) — uvek se generiše iz SAČUVANOG ugovora, ne iz nesnimljenih izmena forme
  async function preuzmiUgovorPdf() {
    if (!izabraniUgovor || ugovorPdfUcitava) return;
    setUgovorPdfUcitava(true);
    try {
      const token = getToken();
      const res = await fetch(`/api/ugovori/${encodeURIComponent(izabraniUgovor)}/pdf`, {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `Ugovor_${izabraniUgovor.replace("/", "-")}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.error(
        err instanceof TypeError
          ? "Server nije dostupan — osveži stranicu i pokušaj ponovo"
          : "Greška pri generisanju ugovora (PDF)",
      );
    } finally {
      setUgovorPdfUcitava(false);
    }
  }

  // Sačuvaj / Izmeni — snimanje rezervacije u bazu (aranzman + aranzman_dopuna)
  async function sacuvajRezervaciju() {
    if (rezSeCuva || rezZakljucana.current) return;
    // zaključan ugovor → dugme je „Izmeni“: samo otključava formu
    if (izabraniUgovor && !izmena) { setIzmena(true); return; }
    if (!nosilac.ime.trim()) { toast.error("Unesite ime nosioca aranžmana"); return; }
    if (!UZRASTI.includes(nosilac.uzrast as (typeof UZRASTI)[number])) { toast.error("Izaberite uzrast nosioca (ADL / CHD / INF)"); return; }
    const saputnikBezUzrasta = saputnici.findIndex((s) => s.ime.trim() && !UZRASTI.includes(s.uzrast as (typeof UZRASTI)[number]));
    if (saputnikBezUzrasta !== -1) { toast.error(`Izaberite uzrast saputnika ${saputnikBezUzrasta + 1} (ADL / CHD / INF)`); return; }
    if (!boravak.datumOd || !boravak.datumDo) { toast.error("Unesite datum od i datum do boravka"); return; }
    if (boravak.datumDo <= boravak.datumOd) { toast.error("Datum do mora biti posle Datuma od"); return; }

    // nazivi referenci: izabrani ID pobeđuje; fallback je sačuvani naziv van liste
    const smestajNaziv = boravak.smestaj === CUVAR ? smestajSacuvan : smestaji.find((s) => String(s.id) === boravak.smestaj)?.naziv ?? null;
    const sobaBroj = boravak.soba === CUVAR ? sobaSacuvana : sobe.find((b) => String(b.id) === boravak.soba)?.broj_sobe ?? null;
    const mestoNaziv = boravak.mesto === CUVAR ? mestoSacuvano : mesta.find((m) => String(m.id) === boravak.mesto)?.naziv ?? null;
    const destinacijaNaziv = destinacijaZaSve === CUVAR ? destinacijaSacuvana : destinacije.find((x) => String(x.id) === destinacijaZaSve)?.naziv ?? null;
    const idIliNull = (v: string) => (v && v !== CUVAR ? Number(v) : null);
    // popust/provizija: procenat ima prednost; inače direktno unet iznos (EUR pa RSD)
    const cenaRed = (pct: string, eur: string, rsd: string) => {
      const p = procenat(pct);
      if (p != null) return { pct: p };
      if (eur.trim()) return { eur: num(eur) };
      if (rsd.trim()) return { rsd: num(rsd) };
      return {};
    };
    // polja taba Prevoz po putniku; datumi/destinacije samo za uključeni smer (OW/RT)
    const prevozPolja = (o: Nosilac | Saputnik, red: PrevozRed | undefined) => ({
      mestoSedenja: red?.mestoSedenja ?? "",
      placeno: !!red?.placeno,
      zelja: !!red?.zelja,
      datumOw: o.ow ? o.datumOw : "",
      destinacijaOw: o.ow ? o.destinacijaOw : "",
      datumPolaska: o.rt ? o.datumPolaska : "",
      destinacijaPolaska: o.rt ? o.destinacijaPolaska : "",
      datumPovratka: o.rt ? o.datumPovratka : "",
      destinacijaPovratka: o.rt ? o.destinacijaPovratka : "",
    });
    const payload = {
      tiprezervacije: tipRezervacije,
      subagent: subagent.trim(),
      timelimit: tipRezervacije === "Predrezervacija" && timeLimitDatum
        ? `${datumToIso(timeLimitDatum)}T${timeLimitSat}:00:00`
        : null,
      nosilac: {
        ime: nosilac.ime.trim(), datumRodjenja: datumRodjenjaIso(nosilac.datumRodjenja),
        pasos: nosilac.pasos.trim(), uzrast: nosilac.uzrast, ow: nosilac.ow, rt: nosilac.rt, sp: nosilac.sp,
        smer: nosilac.smer, adresa: nosilac.adresa.trim(), grad: nosilac.grad.trim(), telefon: nosilac.telefon.trim(),
        email: nosilac.email.trim(),
        ...prevozPolja(nosilac, prevozRedovi["nosilac"]),
      },
      saputnici: saputnici.filter((s) => s.ime.trim()).map((s) => ({
        ime: s.ime.trim(), datumRodjenja: datumRodjenjaIso(s.datumRodjenja),
        pasos: s.pasos.trim(), uzrast: s.uzrast, ow: s.ow, rt: s.rt, sp: s.sp, smer: s.smer,
        adresa: s.adresa.trim(), grad: s.grad.trim(), telefon: s.telefon.trim(), email: s.email.trim(),
        ulazak: prevozRedovi[s.uid]?.mestoUlaska ?? "",
        mestoIzlaska: prevozRedovi[s.uid]?.mestoIzlaska ?? "",
        ...prevozPolja(s, prevozRedovi[s.uid]),
      })),
      boravak: {
        datumOd: boravak.datumOd || null, datumDo: boravak.datumDo || null,
        smestajId: idIliNull(boravak.smestaj), sobaId: idIliNull(boravak.soba),
        mestoId: idIliNull(boravak.mesto),
        smestajNaziv, sobaBroj, mestoNaziv,
        struktura: boravak.struktura.trim(),
        napomena: boravak.napomena, napomenaInterna: boravak.napomenaInterna,
      },
      destinacijaId: idIliNull(destinacijaZaSve), destinacijaNaziv,
      ulazak: prevozRedovi["nosilac"]?.mestoUlaska ?? "",
      izlazak: prevozRedovi["nosilac"]?.mestoIzlaska ?? "",
      napomenaPrevoz: boravak.napomenaPrevoz,
      nacinPlacanja: placanje,
      transferi: [...transferStavke, ...placenaMestaStavke].map((t) => ({ usluga: t.usluga ?? "", eur: t.eur ?? 0 })),
      cene: {
        cenaSmestajEUR: num(cene.cenaSmestaj), kolSmestajEUR: qty(cene.kolSmestaj),
        cenaSmestajRSD: num(cene.cenaSmestajRSD), kolSmestajRSD: qty(cene.kolSmestajRSD),
        popustSmestaj: cenaRed(cene.popustSmestajPct, cene.popustSmestaj, cene.popustSmestajRSD),
        cenaPrevozEUR: num(cene.cenaPrevoz), kolPrevozEUR: qty(cene.kolPrevoz),
        cenaPrevozRSD: num(cene.cenaPrevozRSD), kolPrevozRSD: qty(cene.kolPrevozRSD),
        popustPrevoz: cenaRed(cene.popustPrevozPct, cene.popustPrevoz, cene.popustPrevozRSD),
        osiguranjeEUR: num(cene.osiguranjeEUR), osiguranjeRSD: num(cene.osiguranjeRSD),
        provizijaSmestaj: cenaRed(cene.provizijaSmestajPct, cene.provizijaSmestaj, cene.provizijaSmestajRSD),
        provizijaPrevoz: cenaRed(cene.provizijaPrevozPct, cene.provizijaPrevoz, cene.provizijaPrevozRSD),
      },
    };
    const cilj = izabraniUgovor;
    const tipZaProveru = tipRezervacije;
    const vizaZaProveru = boravak.viza;
    rezZakljucana.current = true;
    setRezSeCuva(true);
    try {
      let zaCitanje = cilj;
      if (cilj) {
        await apiFetch<{ ok: boolean; kljuc: string }>(`/rezervacije/${encodeURIComponent(cilj)}`, {
          method: "PUT", body: JSON.stringify(payload),
        });
        toast.success("Izmene su sačuvane", { description: `Ugovor: ${cilj}` });
      } else {
        const r = await apiFetch<{ kljuc: string; message: string }>("/rezervacije", {
          method: "POST", body: JSON.stringify(payload),
        });
        zaCitanje = r.kljuc;
        toast.success("Rezervacija je sačuvana", { description: `Broj rezervacije: ${r.kljuc}` });
      }
      // ponovno učitavanje iz baze — potvrda upisa, polja se zaključavaju, dugme → „Izmeni“
      if (zaCitanje) {
        await izaberiUgovor(zaCitanje);
        // KEPTP: opomena ako nema broja i nije viza / Predrezervacija / BLOK
        if (!keptpNijePotreban(tipZaProveru, vizaZaProveru)) {
          const kp = await osveziKeptp(zaCitanje);
          if (!kp) setKeptpUpit({ kljuc: zaCitanje, izmena: cilj !== null });
        }
      }
    } catch (error) {
      const msg = error instanceof Error ? error.message : "Čuvanje rezervacije nije uspelo";
      if (msg.includes("zauzet")) {
        // sudar termina (409): izdvojeno obaveštenje sa detaljima postojećeg zapisa
        toast.error("Rezervacija nije upisana — termin je zauzet", { description: msg, duration: 12000 });
      } else {
        toast.error(msg);
      }
    } finally {
      rezZakljucana.current = false;
      setRezSeCuva(false);
    }
  }

  // obračun (privremeni prikaz, pravila se definišu kasnije)
  // bruto subtotale po redu i valuti (cena × količina)
  const brutoSmestajEUR =
    cene.cenaSmestaj.trim() || cene.kolSmestaj.trim()
      ? num(cene.cenaSmestaj) * qty(cene.kolSmestaj)
      : null;
  const brutoSmestajRSD =
    cene.cenaSmestajRSD.trim() || cene.kolSmestajRSD.trim()
      ? num(cene.cenaSmestajRSD) * qty(cene.kolSmestajRSD)
      : null;
  const brutoPrevozEUR =
    cene.cenaPrevoz.trim() || cene.kolPrevoz.trim()
      ? num(cene.cenaPrevoz) * qty(cene.kolPrevoz)
      : null;
  const brutoPrevozRSD =
    cene.cenaPrevozRSD.trim() || cene.kolPrevozRSD.trim()
      ? num(cene.cenaPrevozRSD) * qty(cene.kolPrevozRSD)
      : null;

  // neto po redu = bruto − popust (ista valuta); prikazuje se kad bilo šta u redu postoji
  const netoSmestajEUR =
    brutoSmestajEUR != null || cene.popustSmestaj.trim() || cene.popustSmestajPct.trim()
      ? Math.max(0, (brutoSmestajEUR ?? 0) - num(cene.popustSmestaj))
      : null;
  const netoSmestajRSD =
    brutoSmestajRSD != null || cene.popustSmestajRSD.trim() || cene.popustSmestajPct.trim()
      ? Math.max(0, (brutoSmestajRSD ?? 0) - num(cene.popustSmestajRSD))
      : null;
  const netoPrevozEUR =
    brutoPrevozEUR != null || cene.popustPrevoz.trim() || cene.popustPrevozPct.trim()
      ? Math.max(0, (brutoPrevozEUR ?? 0) - num(cene.popustPrevoz))
      : null;
  const netoPrevozRSD =
    brutoPrevozRSD != null || cene.popustPrevozRSD.trim() || cene.popustPrevozPct.trim()
      ? Math.max(0, (brutoPrevozRSD ?? 0) - num(cene.popustPrevozRSD))
      : null;

  // dodatne stavke su sačuvane u ugovoru (dodatneSume) — sabiraju se jednom, po svojoj valuti,
  // bez konverzije i bez ponovnog dodavanja cenadod-a (nema dvostrukog prebrojavanja)
  const imaDodatnih = sveDodatne.length > 0;

  // Provizije (smeštaj + prevoz, EUR i RSD) se oduzimaju od ukupne vrednosti aranžmana.
  const provizijaEURUkupno = num(cene.provizijaSmestaj) + num(cene.provizijaPrevoz);
  const provizijaRSDUkupno = num(cene.provizijaSmestajRSD) + num(cene.provizijaPrevozRSD);
  // Ukupna cena pre popusta i provizije (bruto + osiguranje + dodatne stavke) i zbir popusta
  const brutoEURUkupno = (brutoSmestajEUR ?? 0) + (brutoPrevozEUR ?? 0) + sveDodatneSume.eur + num(cene.osiguranjeEUR);
  const brutoRSDUkupno = (brutoSmestajRSD ?? 0) + (brutoPrevozRSD ?? 0) + sveDodatneSume.din + num(cene.osiguranjeRSD);
  const popustEURUkupno = (brutoSmestajEUR ?? 0) + (brutoPrevozEUR ?? 0) - (netoSmestajEUR ?? 0) - (netoPrevozEUR ?? 0);
  const popustRSDUkupno = (brutoSmestajRSD ?? 0) + (brutoPrevozRSD ?? 0) - (netoSmestajRSD ?? 0) - (netoPrevozRSD ?? 0);

  // Svaka valuta se sabira nezavisno; osiguranje je deo ukupne cene.
  const ukupnoAranzmanEUR =
    netoSmestajEUR != null || netoPrevozEUR != null || imaDodatnih || cene.osiguranjeEUR.trim()
      ? (netoSmestajEUR ?? 0) + (netoPrevozEUR ?? 0) + sveDodatneSume.eur + num(cene.osiguranjeEUR) - provizijaEURUkupno
      : null;
  const ukupnoAranzmanRSD =
    netoSmestajRSD != null || netoPrevozRSD != null || imaDodatnih || cene.osiguranjeRSD.trim()
      ? (netoSmestajRSD ?? 0) + (netoPrevozRSD ?? 0) + sveDodatneSume.din + num(cene.osiguranjeRSD) - provizijaRSDUkupno
      : null;

  // Uplaćeno dolazi isključivo iz stvarnih uplata ugovora, uključujući storna.
  const uplacenoObracun = izabraniUgovor && !uplateUcitavaju && uplateRedovi !== null
    ? uplateSumaRSD : null;
  // Vrednost aranžmana u RSD: EUR deo po kursu + zasebni RSD deo.
  const vrednostAranzmanaRSD = ukupnoAranzmanEUR != null && !kurs?.kurs
    ? null
    : ukupnoAranzmanEUR != null || ukupnoAranzmanRSD != null
      ? round2((ukupnoAranzmanEUR ?? 0) * (kurs?.kurs ?? 0) + (ukupnoAranzmanRSD ?? 0))
      : null;
  // Vrednost aranžmana already net of provizija; saldo = vrednost − uplaćeno.
  const saldo = vrednostAranzmanaRSD !== null && uplacenoObracun !== null
    ? round2(vrednostAranzmanaRSD - uplacenoObracun)
    : null;

  // Uplate v EUR po istorijskom kursu svake uplate (isti zbir kao u tabu Uplate).
  const vrednostAranzmanaEUR = ukupnoAranzmanRSD && !kurs?.kurs
    ? null
    : ukupnoAranzmanEUR != null || ukupnoAranzmanRSD != null
      ? round2((ukupnoAranzmanEUR ?? 0) + (ukupnoAranzmanRSD ?? 0) / (kurs?.kurs || 1))
      : null;
  const saldoEUR = uplacenoObracun !== null && vrednostAranzmanaEUR !== null
    ? round2(vrednostAranzmanaEUR - uplateSumaEUR)
    : null;

  const akcija = (naziv: string) => () => toast.info(`${naziv} je u pripremi`);

  // Grafik — otvara /agencija/grafik sa mestom, grupom datuma i vilom izabranog ugovora
  const grafikPodaci = () => {
    const mestoId = boravak.mesto && boravak.mesto !== CUVAR ? boravak.mesto : "";
    const smestajId = boravak.smestaj && boravak.smestaj !== CUVAR ? boravak.smestaj : "";
    const mestoNaziv = mestoId
      ? (mesta.find((m) => String(m.id) === mestoId)?.naziv ?? "")
      : (mestoSacuvano ?? ucitanUgovor?.mesto ?? "").trim();
    const smestajNaziv = smestajId
      ? (smestaji.find((s) => String(s.id) === smestajId)?.naziv ?? "")
      : (smestajSacuvan ?? ucitanUgovor?.naziv ?? "").trim();
    const smestaj = smestaji.find((s) => String(s.id) === smestajId);
    const grafikMestoId = smestaj?.mesto ? String(smestaj.mesto) : mestoId;
    const mesto = mesta.find((m) => String(m.id) === grafikMestoId);
    const grupa = smestaj?.grupa_datuma ?? mesto?.grupe?.[0] ?? mesto?.grupa_datuma ?? null;
    return { mestoId: grafikMestoId, smestajId, mestoNaziv, smestajNaziv, grupa };
  };
  const gp = grafikPodaci();
  const grafikDostupan =
    !!izabraniUgovor || !!(gp.mestoId || gp.smestajId || gp.mestoNaziv || gp.smestajNaziv);
  const otvoriGrafik = () => {
    if (!grafikDostupan) {
      toast.error("Izaberite ugovor da otvorite grafik");
      return;
    }
    const params = new URLSearchParams();
    if (gp.mestoId) params.set("mesto", gp.mestoId);
    else if (gp.mestoNaziv) params.set("mestoNaziv", gp.mestoNaziv);
    if (gp.grupa) params.set("grupa", String(gp.grupa));
    if (gp.smestajId) params.set("smestaj", gp.smestajId);
    else if (gp.smestajNaziv) params.set("smestajNaziv", gp.smestajNaziv);
    const qs = params.toString();
    navigate(`/agencija/grafik${qs ? `?${qs}` : ""}`);
  };

  // Sve dok referentni podaci ili ugovor iz linka nisu učitani — bez delimičnog prikaza forme
  if (!referenceSpremne || izborUcitava) {
    return <PageLoader />;
  }

  return (
    <div className="p-6 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <CalendarPlus className="w-6 h-6" />Rezervacije
          </h1>
          <p className="text-muted-foreground text-sm">Unos / izmena rezervacije — aranžman, prevoz i uplate</p>
        </div>
        <div className="flex flex-col gap-2 sm:items-end">
          <div className="flex items-center gap-4 sm:justify-end">
          {ucitanUgovor?.danas && (
            <p className="text-xs text-muted-foreground">
              Datum rezervacije: <span className="font-semibold text-foreground tabular-nums">{ucitanUgovor.danas}</span>
            </p>
          )}
          {ucitanUgovor?.danas && izabraniUgovor && ucitanUgovor && (keptp || !keptpNijePotreban(tipRezervacije, boravak.viza)) && (
            <span className="text-xs text-muted-foreground" aria-hidden="true">|</span>
          )}
          {izabraniUgovor && ucitanUgovor && (keptp || !keptpNijePotreban(tipRezervacije, boravak.viza)) && (
            <p className="text-xs text-muted-foreground">
              KEPTP:{" "}
              {keptp ? (
                <span className="rounded border border-emerald-300 bg-emerald-50 px-1.5 py-px text-xs font-semibold leading-4 text-emerald-700 tabular-nums" title={`Datum: ${keptp.datum}`}>{keptp.broj_keptp}</span>
              ) : (
                <button
                  type="button"
                  disabled={keptpSeDodeljuje}
                  onClick={() => void keptpDodeli(izabraniUgovor)}
                  className="font-semibold text-orange-600 underline underline-offset-2 hover:text-orange-700 disabled:opacity-50"
                  title="Dodeli sledeći broj KEPTP"
                >
                  nema KEPTP
                </button>
              )}
            </p>
          )}
          </div>
          <div className="flex items-center gap-2 rounded-lg border bg-muted/30 px-3 py-2 text-sm" role="status">
            <Info className="w-4 h-4 text-primary shrink-0" />
            {kurs?.kurs != null ? (
              <span>Kurs EUR <span className="text-muted-foreground">({kurs.datum})</span>: <span className="font-semibold tabular-nums">{kursFormat.format(kurs.kurs)} RSD</span></span>
            ) : (
              <span className="text-muted-foreground">Kurs trenutno nije dostupan.</span>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" variant="outline"
              className="border-red-200 bg-red-50 text-red-700 hover:bg-red-100 hover:text-red-800"
              disabled={!ucitanUgovor || izmena || rezSeCuva || izborUcitava || stornoSeCuva || (ucitanUgovor.tiprezervacije ?? "").trim().toUpperCase() === "STORNO"}
              title={izmena ? "Sačuvajte ili odbacite izmene pre storniranja" : "Storniraj rezervaciju"}
              onClick={() => setStornoOtvoren(true)}>
              <Ban className="mr-1.5 size-4" /> STORNO
            </Button>
            <Button
              type="button"
              variant="outline"
              size="icon"
              disabled={!izabraniUgovor}
              title={izabraniUgovor ? "Istorija promena" : "Izaberite ugovor da vidite istoriju"}
              aria-label="Otvori istoriju promena"
              className="relative size-9"
              onClick={() => setIstorijaOtvorena(true)}
            >
              <History className="size-4" />
              {istorija && istorija.length > 0 && (
                <span className="absolute -right-1 -top-1 min-w-4 rounded-full bg-blue-600 px-1 text-[10px] leading-4 text-white tabular-nums">
                  {istorija.length}
                </span>
              )}
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={!grafikDostupan}
              title={grafikDostupan
                ? "Otvara grafik za mesto, grupu datuma i vilu ovog ugovora"
                : "Izaberite ugovor ili sačuvajte rezervaciju da otvorite grafik"}
              aria-label="Otvori grafik za izabrani ugovor"
              onClick={otvoriGrafik}
            >
              <CalendarDays className="mr-1.5 size-4" />
              Grafik
            </Button>
          </div>
        </div>
      </div>

      <Dialog open={keptpUpit !== null} onOpenChange={(open) => { if (!open) setKeptpUpit(null); }}>
        <DialogContent className="max-w-md bg-card">
          <DialogHeader>
            <DialogTitle>Nema broja KEPTP</DialogTitle>
            <DialogDescription>
              {keptpUpit?.izmena
                ? "Molimo evidentirajte ugovor u Knjigu evidencije prodatih turističkih aranžmana."
                : "Ne postoji broj KEPTP za ovaj ugovor."}{" "}
              Želite li da dodate broj KEPTP?
            </DialogDescription>
          </DialogHeader>
          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="outline" onClick={() => setKeptpUpit(null)}>Ne sada</Button>
            <Button
              type="button"
              className="bg-orange-500 hover:bg-orange-600"
              disabled={keptpSeDodeljuje}
              onClick={() => {
                const kljuc = keptpUpit?.kljuc;
                setKeptpUpit(null);
                if (kljuc) void keptpDodeli(kljuc);
              }}
            >
              Dodaj KEPTP
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={stornoOtvoren} onOpenChange={(open) => { if (!stornoSeCuva) setStornoOtvoren(open); }}>
        <DialogContent className="max-w-lg bg-card" onEscapeKeyDown={(e) => { if (stornoSeCuva) e.preventDefault(); }}>
          <DialogHeader>
            <DialogTitle>Storniranje ugovora broj {ucitanUgovor?.kljuc}</DialogTitle>
            <DialogDescription>Potvrdite storniranje rezervacije. Smeštaj i soba biće sačuvani u napomeni, a soba oslobođena.</DialogDescription>
          </DialogHeader>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-3 rounded-lg border bg-muted/30 p-4 text-sm">
            {([
              ["Nosilac", ucitanUgovor?.putnik], ["Mesto", ucitanUgovor?.mesto],
              ["Smeštaj", ucitanUgovor?.naziv], ["Soba", ucitanUgovor?.soba],
              ["Datum od", ucitanUgovor?.datumod], ["Datum do", ucitanUgovor?.datumdo],
              ["Tip rezervacije", ucitanUgovor?.tiprezervacije],
            ] as const).map(([label, value]) => (
              <div key={label}><dt className="text-xs text-muted-foreground">{label}</dt><dd className="break-words font-medium">{value || "—"}</dd></div>
            ))}
          </dl>
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="outline" disabled={stornoSeCuva} onClick={() => setStornoOtvoren(false)}>Odustani</Button>
            <Button className="bg-red-600 text-white hover:bg-red-700" disabled={stornoSeCuva} onClick={() => void stornirajRezervaciju()}>
              {stornoSeCuva ? <Loader2 className="mr-2 size-4 animate-spin" /> : <Ban className="mr-2 size-4" />}Storniraj rezervaciju
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <Tabs defaultValue="aranzman">
        <TabsList className="grid h-auto w-full grid-cols-2 gap-1 rounded-xl border bg-white p-1.5 sm:grid-cols-5 md:w-auto md:inline-flex">
          <TabsTrigger value="aranzman" className="gap-1.5 px-2 py-3 text-sm text-muted-foreground hover:text-foreground sm:px-4 sm:text-base md:px-6 data-[state=active]:bg-blue-600 data-[state=active]:font-semibold data-[state=active]:text-white data-[state=active]:shadow-md data-[state=active]:hover:text-white"><CalendarPlus className="size-4 sm:size-5" />Aranžman</TabsTrigger>
          <TabsTrigger value="prevoz" className="gap-1.5 px-2 py-3 text-sm text-muted-foreground hover:text-foreground sm:px-4 sm:text-base md:px-6 data-[state=active]:bg-blue-600 data-[state=active]:font-semibold data-[state=active]:text-white data-[state=active]:shadow-md data-[state=active]:hover:text-white"><Bus className="size-4 sm:size-5" />Prevoz</TabsTrigger>
          <TabsTrigger value="obracun" className="gap-1.5 px-2 py-3 text-sm text-muted-foreground hover:text-foreground sm:px-4 sm:text-base md:px-6 data-[state=active]:bg-blue-600 data-[state=active]:font-semibold data-[state=active]:text-white data-[state=active]:shadow-md data-[state=active]:hover:text-white"><Receipt className="size-4 sm:size-5" />Obračun</TabsTrigger>
          <TabsTrigger value="uplate" className="gap-1.5 px-2 py-3 text-sm text-muted-foreground hover:text-foreground sm:px-4 sm:text-base md:px-6 data-[state=active]:bg-blue-600 data-[state=active]:font-semibold data-[state=active]:text-white data-[state=active]:shadow-md data-[state=active]:hover:text-white"><Wallet className="size-4 sm:size-5" />Uplate</TabsTrigger>
          <TabsTrigger value="zaduzenje" className="gap-1.5 px-2 py-3 text-sm text-muted-foreground hover:text-foreground sm:px-4 sm:text-base md:px-6 data-[state=active]:bg-blue-600 data-[state=active]:font-semibold data-[state=active]:text-white data-[state=active]:shadow-md data-[state=active]:hover:text-white"><Handshake className="size-4 sm:size-5" />Zaduženje partner</TabsTrigger>
        </TabsList>

        {/* ════════════════ TAB: ARANŽMAN ════════════════ */}
        <TabsContent value="aranzman" className={KOMPAKT_TAB}>
          {/* Ugovor */}
          <Card className={TON.blue.kartica}>
            <CardHeader className={cn(KOMPAKT_HEADER, TON.blue.zaglavlje)}>
              <CardTitle className="text-sm flex items-center gap-2 min-w-0">
                <SekcijaIkona ton="blue"><FileText />
                </SekcijaIkona>
                <span className="shrink-0">Ugovor</span>
                {ucitanUgovor && (
                  <span aria-label="Pregled učitanog ugovora" className="ml-1 flex min-w-0 flex-1 flex-wrap items-center justify-end gap-x-2 gap-y-0.5 text-right text-sm font-medium text-foreground">
                    {([
                      ucitanUgovor.kljuc,
                      ucitanUgovor.putnik,
                      ucitanUgovor.mesto,
                      ucitanUgovor.naziv,
                      ucitanUgovor.soba,
                      prikazPeriodaUgovora(ucitanUgovor.datumod, ucitanUgovor.datumdo),
                    ].filter((v): v is string => !!v)).map((v, i) => (
                      <span key={i} className="flex items-center gap-2">
                        {i > 0 && <span aria-hidden className="text-muted-foreground/50">|</span>}
                        <span className="truncate" title={v}>{v}</span>
                      </span>
                    ))}
                    <span aria-hidden className="text-muted-foreground/50">|</span>
                    <span aria-live="polite" className={cn("tabular-nums", saldoEUR !== null && saldoEUR < 0 && "text-destructive")}>
                      {izborUcitava || uplateUcitavaju ? "Učitavanje…" : saldoEUR !== null ? `${nf2.format(saldoEUR)} €${saldo !== null && !izborUcitava ? ` (${nf2.format(saldo)} din)` : ""}` : "—"}
                    </span>
                  </span>
                )}
              </CardTitle>
            </CardHeader>
            <CardContent className={KOMPAKT_CONTENT}>
              <div className="grid gap-x-3 gap-y-2 grid-cols-1 md:grid-cols-[minmax(0,1.5fr)_minmax(0,0.9fr)_minmax(0,1.2fr)_minmax(0,0.9fr)]">
                <Fld label="Pretraga ugovora">
                  <div className="relative">
                    <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
                    <Input
                      value={pretraga}
                      onChange={(e) => { ++izborRequest.current; setIzborUcitava(false); setPretraga(e.target.value); setPretragaOtvorena(true); }}
                      onFocus={() => setPretragaOtvorena(true)}
                      onKeyDown={(e) => { if (e.key === "Escape") setPretragaOtvorena(false); }}
                      placeholder="Broj ugovora ili nosilac (min. 3 karaktera)"
                      className="pl-9 pr-9"
                      role="combobox"
                      aria-expanded={pretragaOtvorena && pretraga.trim().length >= 3}
                      aria-controls="rezervacije-ugovori-rezultati"
                    />
                    {(pretragaUcitava || izborUcitava) && <Loader2 className="absolute right-3 top-1/2 size-4 -translate-y-1/2 animate-spin text-muted-foreground" />}
                    {pretragaOtvorena && pretraga.trim().length >= 3 && pretraga.trim() !== izabraniUgovor && (
                      <div id="rezervacije-ugovori-rezultati" ref={pretragaListaRef} className="absolute left-0 right-0 top-full z-20 mt-1 max-h-80 overflow-auto rounded-md border bg-popover shadow-lg">
                        {pretragaUcitava ? <p className="px-3 py-3 text-sm text-muted-foreground">Pretraga ugovora…</p> : pretragaRezultati.length ? (
                          <>
                            {pretragaRezultati.map((r) => (
                              <button key={r.kljuc} type="button" disabled={izborUcitava} onClick={() => void izaberiUgovor(r.kljuc)} className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 border-b px-3 py-2 text-left text-sm transition-colors last:border-0 hover:bg-accent focus-visible:bg-accent focus-visible:outline-none">
                                <span className="shrink-0 font-mono font-semibold">{r.kljuc}</span>
                                <span className="min-w-0 flex-1 truncate">{r.putnik || "—"}</span>
                                <span className="text-xs text-muted-foreground">{r.mesto || ""}</span>
                              </button>
                            ))}
                            {pretragaUkupno > pretragaRezultati.length && (
                              <div ref={pretragaCuvarRef} className="flex items-center justify-center gap-2 px-3 py-2 text-xs text-muted-foreground">
                                {pretragaDopunjava && <Loader2 className="size-3.5 animate-spin" />}
                                {pretragaDopunjava ? "Učitavanje…" : `Skrolujte za još ${pretragaUkupno - pretragaRezultati.length} od ${pretragaUkupno}`}
                              </div>
                            )}
                          </>
                        ) : <p className="px-3 py-3 text-sm text-muted-foreground">Nema rezultata za „{pretraga.trim()}”.</p>}
                      </div>
                    )}
                  </div>

                </Fld>
                <Fld label="Tip rezervacije">
                  <Select value={tipRezervacije} onValueChange={(v) => { setTipRezervacije(v); if (v !== "Predrezervacija") { setTimeLimitDatum(undefined); setTimeLimitOtvoren(false); } }} disabled={zakljucano}>
                    <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {tipOpcije.map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </Fld>
                <Fld label="Subagent">
                  <Popover open={subagentOtvoren} onOpenChange={(o) => { setSubagentOtvoren(o); if (!o) setSubagentPretraga(""); }}>
                    <PopoverTrigger asChild>
                      <Button variant="outline" disabled={zakljucano} className={cn("w-full justify-start font-normal truncate", !subagent && "text-muted-foreground")}>
                        {subagent || "Izaberite subagenta"}
                      </Button>
                    </PopoverTrigger>
                    <PopoverContent align="start" className="w-[var(--radix-popover-trigger-width)] p-0">
                      <Command shouldFilter={false}>
                        <CommandInput placeholder="Naziv, mesto, osoba…" value={subagentPretraga} onValueChange={setSubagentPretraga} />
                        <CommandList>
                          <CommandEmpty>Nema subagenta.</CommandEmpty>
                          <CommandGroup>
                            {subagent && (
                              <CommandItem value="__ukloni__" onSelect={() => { setSubagent(""); setSubagentOtvoren(false); }}>
                                <span className="text-muted-foreground">Bez subagenta</span>
                              </CommandItem>
                            )}
                            {subagentOpcije.map((n) => (
                              <CommandItem key={n} value={n} onSelect={() => { setSubagent(n); setSubagentOtvoren(false); }}>
                                <span className={cn("truncate", n === subagent && "font-semibold")}>{n}</span>
                              </CommandItem>
                            ))}
                          </CommandGroup>
                        </CommandList>
                      </Command>
                    </PopoverContent>
                  </Popover>
                </Fld>
                <Fld label="Time limit">
                  <Popover open={timeLimitOtvoren} onOpenChange={setTimeLimitOtvoren}>
                    <PopoverTrigger asChild>
                      <Button
                        variant="outline"
                        disabled={zakljucano || tipRezervacije !== "Predrezervacija"}
                        className={cn("w-full justify-start gap-2 font-normal", !timeLimitDatum && "text-muted-foreground")}
                      >
                        <CalendarDays className="size-4 shrink-0" />
                        {timeLimitDatum ? prikazTimeLimita(timeLimitDatum, timeLimitSat) : "Izaberite datum i sat"}
                      </Button>
                    </PopoverTrigger>
                    <PopoverContent align="start" className="w-auto p-0">
                      <Calendar
                        mode="single"
                        selected={timeLimitDatum}
                        onSelect={setTimeLimitDatum}
                        weekStartsOn={1}
                        formatters={formattersKalendara}
                        initialFocus
                      />
                      <div className="flex items-center gap-3 border-t px-4 py-3">
                        <Label htmlFor="time-limit-sat" className="text-sm">Sat</Label>
                        <Select value={timeLimitSat} onValueChange={setTimeLimitSat}>
                          <SelectTrigger id="time-limit-sat" className="ml-auto w-28"><SelectValue /></SelectTrigger>
                          <SelectContent className="max-h-52">
                            {SATI.map((sat) => <SelectItem key={sat} value={sat}>{sat}:00</SelectItem>)}
                          </SelectContent>
                        </Select>
                      </div>
                    </PopoverContent>
                  </Popover>
                </Fld>
              </div>
            </CardContent>
          </Card>

          {/* Putnici */}
          <Card className={TON.violet.kartica}>
            <CardHeader className={cn(KOMPAKT_HEADER, TON.violet.zaglavlje)}>
              <CardTitle className="text-sm flex items-center gap-2">
                <SekcijaIkona ton="violet"><Users /></SekcijaIkona>Putnici
              </CardTitle>
            </CardHeader>
            <CardContent className={cn(KOMPAKT_CONTENT, "space-y-3")}>
              {/* Nosilac */}
              <div className="space-y-2">
                <div className="grid gap-x-3 gap-y-2 grid-cols-1 md:grid-cols-4 xl:grid-cols-[1.4fr_0.8fr_0.7fr_0.9fr_1.3fr_0.9fr_1.2fr_0.7fr]">
                  <Fld label="Nosilac aranžmana" labelClassName="text-sm font-semibold text-blue-600">
                    <Input
                      className="font-medium"
                      value={nosilac.ime}
                      onChange={(e) => setNosilac({ ...nosilac, ime: e.target.value })}
                      placeholder="Ime i prezime"
                      disabled={zakljucano}
                    />
                  </Fld>
                  <Fld label="Datum rođenja">
                    <Input
                      type="text"
                      inputMode="numeric"
                      autoComplete="bday"
                      placeholder="dd.mm.yyyy"
                      maxLength={10}
                      value={nosilac.datumRodjenja}
                      onChange={(e) => setNosilac({ ...nosilac, datumRodjenja: formatDatumRodjenja(e.target.value) })}
                      disabled={zakljucano}
                    />
                  </Fld>
                  <Fld label="Uzrast">
                    <UzrastIzbor label="Uzrast nosioca" value={nosilac.uzrast} onChange={(uzrast) => setNosilac({ ...nosilac, uzrast })} disabled={zakljucano} />
                  </Fld>
                  <Fld label="Broj pasoša">
                    <Input
                      value={nosilac.pasos}
                      onChange={(e) => setNosilac({ ...nosilac, pasos: e.target.value })}
                      placeholder="Broj pasoša"
                      disabled={zakljucano}
                    />
                  </Fld>
                  <Fld label="Adresa">
                    <Input value={nosilac.adresa} onChange={(e) => setNosilac({ ...nosilac, adresa: e.target.value })} disabled={zakljucano} />
                  </Fld>
                  <Fld label="Grad">
                    <Input value={nosilac.grad} onChange={(e) => setNosilac({ ...nosilac, grad: e.target.value })} disabled={zakljucano} />
                  </Fld>
                  <Fld label="Telefon">
                    <Input value={nosilac.telefon} onChange={(e) => setNosilac({ ...nosilac, telefon: e.target.value })} disabled={zakljucano} />
                  </Fld>
                  <Fld label="Email">
                    <EmailInput value={nosilac.email} onChange={(email) => setNosilac({ ...nosilac, email })} disabled={zakljucano} />
                  </Fld>
                  <Fld label="Osiguranje">
                    <div className="flex min-h-8 items-center">
                      <Chk label="Osiguranje" checked={nosilac.osiguranje} onChange={(v) => setNosilac({ ...nosilac, osiguranje: v })} disabled={zakljucano} />
                    </div>
                  </Fld>
                </div>
              </div>

              <Separator />

              {/* Saputnici */}
              <div className="space-y-2">
                <div className="text-xs font-semibold uppercase tracking-wide text-blue-600">
                  Saputnici{saputnici.length > 0 ? ` (${saputnici.length})` : ""}
                </div>
                {saputnici.length === 0 && (
                  <p className="text-sm text-muted-foreground">Nema dodate saputnike.</p>
                )}
                {saputnici.map((s, i) => (
                  <div key={s.uid} className="rounded-lg border px-3 py-2 space-y-2">
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-sm font-semibold text-blue-600">Saputnik {i + 1}</span>
                      <div className="flex items-center gap-3">
                        <Chk label="Kopiraj kontakt nosioca" labelClassName="text-xs" checked={s.kopiranKontakt} disabled={zakljucano}
                          onChange={(checked) => setSaputnici((prev) => prev.map((p) => p.uid === s.uid
                            ? { ...p, kopiranKontakt: checked, ...(checked ? { adresa: nosilac.adresa, grad: nosilac.grad, email: nosilac.email, telefon: nosilac.telefon } : {}) } : p))} />
                        <Button
                          variant="ghost" size="icon"
                          className="h-7 w-7 text-muted-foreground hover:text-destructive"
                          disabled={zakljucano}
                          onClick={() => ukloniSaputnika(s.uid)}
                          title="Ukloni saputnika"
                        >
                          <Trash2 className="w-4 h-4" />
                        </Button>
                      </div>
                    </div>
                    <div className="grid gap-x-3 gap-y-2 grid-cols-1 md:grid-cols-4 xl:grid-cols-[1.4fr_0.8fr_0.7fr_0.9fr_1.3fr_0.9fr_1.2fr_0.7fr]">
                      <Fld label="Ime i prezime">
                        <Input
                          className="font-medium"
                          value={s.ime}
                          onChange={(e) => setSaputnici((prev) => prev.map((p) => p.uid === s.uid ? { ...p, ime: e.target.value } : p))}
                          placeholder="Ime i prezime"
                          disabled={zakljucano}
                        />
                      </Fld>
                      <Fld label="Datum rođenja">
                        <Input
                          type="text"
                          inputMode="numeric"
                          autoComplete="bday"
                          placeholder="dd.mm.yyyy"
                          maxLength={10}
                          value={s.datumRodjenja}
                          onChange={(e) => setSaputnici((prev) => prev.map((p) => p.uid === s.uid ? { ...p, datumRodjenja: formatDatumRodjenja(e.target.value) } : p))}
                          disabled={zakljucano}
                        />
                      </Fld>
                      <Fld label="Uzrast">
                        <UzrastIzbor label={`Uzrast saputnika ${i + 1}`} value={s.uzrast} disabled={zakljucano}
                          onChange={(uzrast) => setSaputnici((prev) => prev.map((p) => p.uid === s.uid ? { ...p, uzrast } : p))} />
                      </Fld>
                      <Fld label="Broj pasoša">
                        <Input
                          value={s.pasos}
                          onChange={(e) => setSaputnici((prev) => prev.map((p) => p.uid === s.uid ? { ...p, pasos: e.target.value } : p))}
                          disabled={zakljucano}
                        />
                      </Fld>
                      <Fld label="Adresa">
                        <Input value={s.adresa} onChange={(e) => setSaputnici((prev) => prev.map((p) => p.uid === s.uid ? { ...p, adresa: e.target.value, kopiranKontakt: false } : p))} disabled={zakljucano} />
                      </Fld>
                      <Fld label="Grad">
                        <Input value={s.grad} onChange={(e) => setSaputnici((prev) => prev.map((p) => p.uid === s.uid ? { ...p, grad: e.target.value, kopiranKontakt: false } : p))} disabled={zakljucano} />
                      </Fld>
                      <Fld label="Telefon">
                        <Input type="tel" value={s.telefon} onChange={(e) => setSaputnici((prev) => prev.map((p) => p.uid === s.uid ? { ...p, telefon: e.target.value, kopiranKontakt: false } : p))} disabled={zakljucano} />
                      </Fld>
                      <Fld label="Email">
                        <EmailInput value={s.email} onChange={(email) => setSaputnici((prev) => prev.map((p) => p.uid === s.uid ? { ...p, email, kopiranKontakt: false } : p))} disabled={zakljucano} />
                      </Fld>
                      <Fld label="Osiguranje">
                        <div className="flex min-h-8 items-center">
                          <Chk label="Osiguranje" checked={s.osiguranje} onChange={(v) => setSaputnici((prev) => prev.map((p) => p.uid === s.uid ? { ...p, osiguranje: v } : p))} disabled={zakljucano} />
                        </div>
                      </Fld>
                    </div>
                  </div>
                ))}
                <Button variant="outline" size="sm" className="w-full border-dashed" onClick={dodajSaputnika} disabled={zakljucano}>
                  <Plus className="w-4 h-4 mr-1.5" />Dodaj saputnika
                </Button>
              </div>
            </CardContent>
          </Card>

          {/* Boravak i smeštaj */}
          <Card className={TON.emerald.kartica}>
            <CardHeader className={cn(KOMPAKT_HEADER, TON.emerald.zaglavlje)}>
              <CardTitle className="text-sm flex items-center gap-2">
                <SekcijaIkona ton="emerald"><BedDouble /></SekcijaIkona>Boravak i smeštaj
                {!zakljucano && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="ml-auto h-7 gap-1.5 px-2 text-xs"
                    onClick={() => setBoravakOtkljucan((v) => !v)}
                  >
                    {boravakOtkljucan ? <Lock className="size-3.5" /> : <LockOpen className="size-3.5" />}
                    {boravakOtkljucan ? "Zaključaj" : "Otključaj"}
                  </Button>
                )}
              </CardTitle>
            </CardHeader>
            <CardContent className={KOMPAKT_CONTENT}>
              <div className="grid gap-x-3 gap-y-2 grid-cols-1 md:grid-cols-3 xl:grid-cols-6">
                <DatumField
                  label="Datum od"
                  value={boravak.datumOd}
                  onChange={(v) => setBoravak({ ...boravak, datumOd: v })}
                  disabled={boravakZakljucan}
                />
                <DatumField
                  label="Datum do"
                  value={boravak.datumDo}
                  onChange={(v) => setBoravak({ ...boravak, datumDo: v })}
                  disabled={boravakZakljucan}
                />
                <Fld label="Smeštaj">
                  <Select
                    value={boravak.smestaj}
                    onValueChange={(v) => { if (v !== CUVAR) setSmestajSacuvan(null); setBoravak({ ...boravak, smestaj: v, soba: "" }); }}
                    disabled={boravakZakljucan}
                  >
                    <SelectTrigger className="w-full"><SelectValue placeholder="Izaberite smeštaj" /></SelectTrigger>
                    <SelectContent>
                      {smestajSacuvan && <SelectItem value={CUVAR}>{smestajSacuvan} (sačuvano)</SelectItem>}
                      {smestaji.map((s) => (
                        <SelectItem key={s.id} value={String(s.id)}>{s.naziv}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Fld>
                <Fld label="Soba">
                  <Select
                    value={boravak.soba}
                    onValueChange={(v) => { if (v !== CUVAR) setSobaSacuvana(null); setBoravak({ ...boravak, soba: v }); }}
                    disabled={boravakZakljucan || !boravak.smestaj || boravak.smestaj === CUVAR}
                  >
                    <SelectTrigger className="w-full">
                      <SelectValue placeholder={boravak.smestaj ? "Izaberite sobu" : "Prvo izaberite smeštaj"} />
                    </SelectTrigger>
                    <SelectContent>
                      {sobaSacuvana && <SelectItem value={CUVAR}>{sobaSacuvana} (sačuvano)</SelectItem>}
                      {sobeSmestaja.map((b) => (
                        <SelectItem key={b.id} value={String(b.id)}>
                          {b.broj_sobe}{b.tip ? ` (${b.tip})` : ""}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Fld>
                <Fld label="Mesto">
                  <Select value={boravak.mesto} onValueChange={(v) => { if (v !== CUVAR) setMestoSacuvano(null); setBoravak({ ...boravak, mesto: v }); }} disabled={boravakZakljucan}>
                    <SelectTrigger className="w-full"><SelectValue placeholder="Izaberite mesto" /></SelectTrigger>
                    <SelectContent>
                      {mestoSacuvano && <SelectItem value={CUVAR}>{mestoSacuvano} (sačuvano)</SelectItem>}
                      {mesta.map((m) => (
                        <SelectItem key={m.id} value={String(m.id)}>{m.naziv}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Fld>
                <Fld label="Struktura">
                  <Input
                    value={boravak.struktura}
                    onChange={(e) => setBoravak({ ...boravak, struktura: e.target.value })}
                    placeholder="npr. 1/2 + 1/2"
                    disabled={boravakZakljucan}
                  />
                </Fld>
                <Fld label="Promena strukture" className="md:col-span-2 xl:col-span-5">
                  <Input
                    value={boravak.promenaStrukture}
                    onChange={(e) => setBoravak({ ...boravak, promenaStrukture: e.target.value })}
                    disabled={zakljucano}
                  />
                </Fld>
                <Fld label="Viza" className="md:col-span-1 xl:col-span-1">
                  <label className="flex h-8 items-center gap-2 text-sm">
                    <Checkbox
                      checked={boravak.viza}
                      onCheckedChange={(v) => setBoravak({ ...boravak, viza: v === true })}
                      disabled={zakljucano}
                    />
                    <span className="text-muted-foreground">Viza</span>
                  </label>
                </Fld>
                <Fld label="Napomena (interna)" className="md:col-span-3">
                  <Textarea
                    rows={2}
                    className="min-h-0"
                    value={boravak.napomena}
                    onChange={(e) => setBoravak({ ...boravak, napomena: e.target.value })}
                    disabled={zakljucano}
                  />
                </Fld>
                <Fld label="Napomena (prikazuje se na prijavi)" className="md:col-span-3">
                  <Textarea
                    rows={2}
                    className="min-h-0"
                    value={boravak.napomenaInterna}
                    onChange={(e) => setBoravak({ ...boravak, napomenaInterna: e.target.value })}
                    disabled={zakljucano}
                  />
                </Fld>
              </div>
            </CardContent>
          </Card>

        </TabsContent>

        {/* ════════════════ TAB: OBRAČUN ════════════════ */}
        <TabsContent value="obracun" className={KOMPAKT_TAB}>
          {/* Smeštaj · Prevoz · Osiguranje — tri reda u jednoj kartici */}
          <Card className={TON.sky.kartica}>
            <CardHeader className={cn(KOMPAKT_HEADER, TON.sky.zaglavlje)}>
              <CardTitle className="text-sm flex items-center gap-2 uppercase tracking-wide text-sky-800">
                <SekcijaIkona ton="sky"><BedDouble /></SekcijaIkona>Smeštaj · Prevoz · Osiguranje
              </CardTitle>
            </CardHeader>
            <CardContent className={cn(KOMPAKT_CONTENT, "space-y-2")}>
              <div className="grid gap-x-3 gap-y-2 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
                <div className="grid gap-x-3 gap-y-2 sm:grid-cols-2 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,0.6fr)_minmax(0,1.4fr)_minmax(0,0.6fr)]">
                  <Fld label="Cena smeštaja (EUR)">
                    <Input inputMode="decimal" aria-label="Cena smeštaja (EUR)" value={cene.cenaSmestaj} onChange={(e) => updCene({ cenaSmestaj: e.target.value })} placeholder="0,00" disabled={zakljucano} />
                  </Fld>
                  <Fld label="Količina">
                    <Input inputMode="decimal" aria-label="Količina za cenu smeštaja (EUR)" value={cene.kolSmestaj} onChange={(e) => updCene({ kolSmestaj: e.target.value })} placeholder="1" disabled={zakljucano} />
                  </Fld>
                  <Fld label="Cena smeštaja (RSD)">
                    <Input inputMode="decimal" aria-label="Cena smeštaja (RSD)" value={cene.cenaSmestajRSD} placeholder="0,00" disabled className="bg-muted text-muted-foreground" />
                  </Fld>
                  <Fld label="Količina">
                    <Input inputMode="decimal" aria-label="Količina za cenu smeštaja (RSD)" value={cene.kolSmestajRSD} placeholder="1" disabled className="bg-muted text-muted-foreground" />
                  </Fld>
                </div>
                <PanelaSazetka kompaktno>
                  <div className="grid grid-cols-2 gap-x-3 gap-y-2">
                    <Fld label="Ukupno (EUR)">
                      <UkupnoInput vrednost={brutoSmestajEUR} />
                    </Fld>
                    <Fld label="Ukupno (RSD)">
                      <UkupnoInput vrednost={brutoSmestajRSD} />
                    </Fld>
                  </div>
                </PanelaSazetka>
              </div>
              <div className="grid gap-x-3 gap-y-2 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
                <div className="grid gap-x-3 gap-y-2 sm:grid-cols-2 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,0.6fr)_minmax(0,1.4fr)_minmax(0,0.6fr)]">
                  <Fld label="Cena prevoza (EUR)">
                    <Input inputMode="decimal" aria-label="Cena prevoza (EUR)" value={cene.cenaPrevoz} onChange={(e) => updCene({ cenaPrevoz: e.target.value })} placeholder="0,00" disabled={zakljucano} />
                  </Fld>
                  <Fld label="Količina">
                    <Input inputMode="decimal" aria-label="Količina za cenu prevoza (EUR)" value={cene.kolPrevoz} onChange={(e) => updCene({ kolPrevoz: e.target.value })} placeholder="1" disabled={zakljucano} />
                  </Fld>
                  <Fld label="Cena prevoza (RSD)">
                    <Input inputMode="decimal" aria-label="Cena prevoza (RSD)" value={cene.cenaPrevozRSD} placeholder="0,00" disabled className="bg-muted text-muted-foreground" />
                  </Fld>
                  <Fld label="Količina">
                    <Input inputMode="decimal" aria-label="Količina za cenu prevoza (RSD)" value={cene.kolPrevozRSD} placeholder="1" disabled className="bg-muted text-muted-foreground" />
                  </Fld>
                </div>
                <PanelaSazetka kompaktno>
                  <div className="grid grid-cols-2 gap-x-3 gap-y-2">
                    <Fld label="Ukupno (EUR)">
                      <UkupnoInput vrednost={brutoPrevozEUR} />
                    </Fld>
                    <Fld label="Ukupno (RSD)">
                      <UkupnoInput vrednost={brutoPrevozRSD} />
                    </Fld>
                  </div>
                </PanelaSazetka>
              </div>
              <div className="grid gap-x-3 gap-y-2 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
                <div className="grid gap-x-3 gap-y-2 sm:grid-cols-2 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,0.6fr)_minmax(0,1.4fr)_minmax(0,0.6fr)]">
                  <Fld label="Osiguranje (EUR)">
                    <Input inputMode="decimal" aria-label="Osiguranje — iznos (EUR)" value={cene.osiguranjeEUR} onChange={(e) => updCene({ osiguranjeEUR: e.target.value })} placeholder="0,00" disabled={zakljucano} />
                  </Fld>
                  <Fld label="Osiguranje (RSD)" className="lg:col-start-3">
                    <Input inputMode="decimal" aria-label="Osiguranje — iznos (RSD)" value={cene.osiguranjeRSD} onChange={(e) => updCene({ osiguranjeRSD: e.target.value })} placeholder="0,00" disabled={zakljucano} />
                  </Fld>
                </div>
                <PanelaSazetka kompaktno>
                  <div className="grid grid-cols-2 gap-x-3 gap-y-2">
                    <Fld label="Ukupno (EUR)">
                      <UkupnoInput vrednost={cene.osiguranjeEUR.trim() ? num(cene.osiguranjeEUR) : null} />
                    </Fld>
                    <Fld label="Ukupno (RSD)">
                      <UkupnoInput vrednost={cene.osiguranjeRSD.trim() ? num(cene.osiguranjeRSD) : null} />
                    </Fld>
                  </div>
                </PanelaSazetka>
              </div>
            </CardContent>
          </Card>

          {/* Dodatne usluge */}
          <Card className={TON.orange.kartica}>
            <CardHeader className={cn(KOMPAKT_HEADER, TON.orange.zaglavlje, "flex-row flex-wrap items-center justify-between gap-3 space-y-0")}>
              <div className="space-y-0.5">
                <CardTitle className="text-sm flex items-center gap-2 uppercase tracking-wide text-orange-800">
                  <SekcijaIkona ton="orange"><Receipt /></SekcijaIkona>Dodatne usluge
                </CardTitle>
                <CardDescription className="text-xs">{izabraniUgovor ? `Ugovor ${izabraniUgovor} — ` : ""}stavke se čuvaju direktno u ugovoru</CardDescription>
              </div>
              <Button type="button" size="sm" variant="outline" disabled={!izabraniUgovor || zakljucano || izborUcitava || dodatnaIzmena !== null || dodatnaBrisanje !== null} onClick={() => setDodatnaIzmena("nova")}><Plus className="size-4" />Dodaj</Button>
            </CardHeader>
            <CardContent className={KOMPAKT_CONTENT}>
              <div className="grid items-start gap-x-3 gap-y-2 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
                <div className="min-w-0">
                  <div className="overflow-hidden rounded-lg border">
                    {izabraniUgovor && dodatnaIzmena !== null && (
                      <DodatnaStavkaForma
                        key={`${izabraniUgovor}-${dodatnaIzmena === "nova" ? "nova" : dodatnaIzmena.stavka_id}`}
                        ugovor={izabraniUgovor}
                        original={dodatnaIzmena === "nova" ? null : dodatnaIzmena}
                        onCancel={() => setDodatnaIzmena(null)}
                        onSaved={(stavka) => {
                          if (aktivniUgovor.current !== izabraniUgovor) return;
                          setDodatneStavke((prev) => prev.some((s) => s.stavka_id === stavka.stavka_id)
                            ? prev.map((s) => s.stavka_id === stavka.stavka_id ? stavka : s) : [...prev, stavka]);
                          setDodatnaIzmena(null);
                        }}
                      />
                    )}
                    {!izabraniUgovor && sveDodatne.length === 0 ? (
                      <p className="px-4 py-4 text-sm text-muted-foreground">Izaberite ugovor za pregled dodatnih stavki.</p>
                    ) : (
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Naziv</TableHead>
                            <TableHead className="text-right">Cena (EUR)</TableHead>
                            <TableHead className="text-right">Cena (RSD)</TableHead>
                            <TableHead className="text-right">Akcija</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {sveDodatne.length === 0 ? (
                            <TableRow><TableCell colSpan={4} className="text-center text-muted-foreground">Nema dodatnih stavki za ovaj ugovor.</TableCell></TableRow>
                          ) : sveDodatne.map((stavka) => (
                            <TableRow key={stavka.stavka_id}>
                              <TableCell>{stavka.usluga || "—"}</TableCell>
                              <TableCell className="text-right tabular-nums whitespace-nowrap">{stavka.eur == null ? "—" : `${nf2.format(stavka.eur)} €`}</TableCell>
                              <TableCell className="text-right tabular-nums whitespace-nowrap">{stavka.din == null ? "—" : `${nf2.format(stavka.din)} din`}</TableCell>
                              <TableCell className="text-right">
                                {stavka.stavka_id < 0 ? (
                                  <span className="text-xs text-muted-foreground">iz registra prevoza</span>
                                ) : (
                                <div className="flex items-center justify-end gap-1">
                                  <Button type="button" size="sm" variant="ghost" disabled={zakljucano || izborUcitava || dodatnaIzmena !== null || dodatnaBrisanje !== null} onClick={() => setDodatnaIzmena(stavka)}><FilePenLine className="size-4" />Izmeni</Button>
                                  <Button
                                    type="button"
                                    size="icon"
                                    variant="ghost"
                                    className="size-7 text-muted-foreground hover:text-destructive"
                                    disabled={zakljucano || izborUcitava || dodatnaIzmena !== null || dodatnaBrisanje !== null}
                                    title="Obriši stavku"
                                    aria-label={`Obriši stavku ${stavka.usluga?.trim() || stavka.stavka_id}`}
                                    onClick={() => setBrisanjeStavka(stavka)}
                                  >
                                    {dodatnaBrisanje === stavka.stavka_id
                                      ? <Loader2 className="size-4 animate-spin" />
                                      : <Trash2 className="size-4" />}
                                  </Button>
                                </div>
                                )}
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    )}
                  </div>
                </div>
                <PanelaSazetka kompaktno>
                  <div className="grid grid-cols-2 gap-x-3 gap-y-2">
                    <Fld label="Ukupno (EUR)">
                      <UkupnoInput vrednost={sveDodatne.length ? sveDodatneSume.eur : null} />
                    </Fld>
                    <Fld label="Ukupno (RSD)">
                      <UkupnoInput vrednost={sveDodatne.length ? sveDodatneSume.din : null} />
                    </Fld>
                  </div>
                </PanelaSazetka>
              </div>
              <AlertDialog
                open={brisanjeStavka !== null}
                onOpenChange={(open) => { if (!open) setBrisanjeStavka(null); }}
              >
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>Obrisati dodatnu stavku?</AlertDialogTitle>
                    <AlertDialogDescription>
                      Stavka „{brisanjeStavka?.usluga?.trim() || "—"}”
                      ({brisanjeStavka?.eur == null ? "—" : `${nf2.format(brisanjeStavka.eur)} €`} / {brisanjeStavka?.din == null ? "—" : `${nf2.format(brisanjeStavka.din)} din`})
                      biće trajno obrisana iz ugovora <span className="font-mono font-medium text-foreground">{izabraniUgovor}</span>.
                      Ova radnja se ne može poništiti.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>Otkaži</AlertDialogCancel>
                    <AlertDialogAction
                      className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                      disabled={dodatnaBrisanje !== null}
                      onClick={(e) => { e.preventDefault(); if (brisanjeStavka) void obrisiDodatnuStavku(brisanjeStavka); }}
                    >
                      {dodatnaBrisanje !== null && <Loader2 className="size-4 animate-spin" />}
                      {dodatnaBrisanje !== null ? "Brisanje…" : "Obriši"}
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            </CardContent>
          </Card>

          {/* Popust */}
          <Card className={TON.rose.kartica}>
            <CardHeader className={cn(KOMPAKT_HEADER, TON.rose.zaglavlje)}>
              <CardTitle className="text-sm flex items-center gap-2 uppercase tracking-wide text-rose-800">
                <SekcijaIkona ton="rose"><Info /></SekcijaIkona>Popust
                <span className="ml-1 text-xs font-normal normal-case tracking-normal text-muted-foreground">procenat ili iznos — izmena iznosa briše procenat</span>
              </CardTitle>
            </CardHeader>
            <CardContent className={cn(KOMPAKT_CONTENT, "space-y-2")}>
              <Fld label="Način plaćanja">
                <Select value={placanje || "nista"} onValueChange={(v) => promeniPlacanje(v === "nista" ? "" : v)} disabled={zakljucano}>
                  <SelectTrigger aria-label="Način plaćanja" className="h-8 w-56"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="nista">Bez izbora</SelectItem>
                    <SelectItem value="delimicno">Delimično</SelectItem>
                    <SelectItem value="u_celosti">U celosti</SelectItem>
                  </SelectContent>
                </Select>
              </Fld>
              <ProcenatRed
                naslov="Smeštaj"
                pct={cene.popustSmestajPct}
                iznosEUR={cene.popustSmestaj}
                iznosRSD={cene.popustSmestajRSD}
                netoEUR={netoSmestajEUR}
                netoRSD={netoSmestajRSD}
                onPct={(v) => updCene({ popustSmestajPct: v })}
                onIznosEUR={(v) => updCene({ popustSmestaj: v, popustSmestajPct: "" })}
                onIznosRSD={(v) => updCene({ popustSmestajRSD: v, popustSmestajPct: "" })}
                disabled={zakljucano}
              />
              <ProcenatRed
                naslov="Prevoz"
                pct={cene.popustPrevozPct}
                iznosEUR={cene.popustPrevoz}
                iznosRSD={cene.popustPrevozRSD}
                netoEUR={netoPrevozEUR}
                netoRSD={netoPrevozRSD}
                onPct={(v) => updCene({ popustPrevozPct: v })}
                onIznosEUR={(v) => updCene({ popustPrevoz: v, popustPrevozPct: "" })}
                onIznosRSD={(v) => updCene({ popustPrevozRSD: v, popustPrevozPct: "" })}
                disabled={zakljucano}
              />
            </CardContent>
          </Card>

          {/* Promena načina plaćanja — potvrda pre ponovnog obračuna popusta */}
          <AlertDialog
            open={placanjeZahtev !== null}
            onOpenChange={(open) => { if (!open) setPlacanjeZahtev(null); }}
          >
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Promena načina plaćanja</AlertDialogTitle>
                <AlertDialogDescription>
                  Dolazi do promene obračuna. Popust smeštaja biće ponovo određen za način plaćanja „
                  {placanjeZahtev === "u_celosti" ? "u celosti" : placanjeZahtev === "delimicno" ? "delimično" : "bez izbora"}”.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Odustani</AlertDialogCancel>
                <AlertDialogAction onClick={(e) => { e.preventDefault(); potvrdiPlacanje(); }}>Promeni</AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>

          {/* Provizija */}
          <Card className={TON.amber.kartica}>
            <CardHeader className={cn(KOMPAKT_HEADER, TON.amber.zaglavlje)}>
              <CardTitle className="text-sm flex items-center gap-2 uppercase tracking-wide text-amber-800">
                <SekcijaIkona ton="amber"><Wallet /></SekcijaIkona>Provizija
                <span className="ml-1 text-xs font-normal normal-case tracking-normal text-muted-foreground">procenat ili iznos; ispod ukupan obračun aranžmana</span>
              </CardTitle>
            </CardHeader>
            <CardContent className={cn(KOMPAKT_CONTENT, "space-y-2")}>
              <ProcenatRed
                naslov="Smeštaj"
                pct={cene.provizijaSmestajPct}
                iznosEUR={cene.provizijaSmestaj}
                iznosRSD={cene.provizijaSmestajRSD}
                netoEUR={netoSmestajEUR != null || cene.provizijaSmestaj.trim() || cene.provizijaSmestajPct.trim()
                  ? Math.max(0, (netoSmestajEUR ?? 0) - num(cene.provizijaSmestaj))
                  : null}
                netoRSD={netoSmestajRSD != null || cene.provizijaSmestajRSD.trim() || cene.provizijaSmestajPct.trim()
                  ? Math.max(0, (netoSmestajRSD ?? 0) - num(cene.provizijaSmestajRSD))
                  : null}
                onPct={(v) => updCene({ provizijaSmestajPct: v })}
                onIznosEUR={(v) => updCene({ provizijaSmestaj: v, provizijaSmestajPct: "" })}
                onIznosRSD={(v) => updCene({ provizijaSmestajRSD: v, provizijaSmestajPct: "" })}
                disabled={zakljucano}
              />
              <ProcenatRed
                naslov="Prevoz"
                pct={cene.provizijaPrevozPct}
                iznosEUR={cene.provizijaPrevoz}
                iznosRSD={cene.provizijaPrevozRSD}
                netoEUR={netoPrevozEUR != null || cene.provizijaPrevoz.trim() || cene.provizijaPrevozPct.trim()
                  ? Math.max(0, (netoPrevozEUR ?? 0) - num(cene.provizijaPrevoz))
                  : null}
                netoRSD={netoPrevozRSD != null || cene.provizijaPrevozRSD.trim() || cene.provizijaPrevozPct.trim()
                  ? Math.max(0, (netoPrevozRSD ?? 0) - num(cene.provizijaPrevozRSD))
                  : null}
                onPct={(v) => updCene({ provizijaPrevozPct: v })}
                onIznosEUR={(v) => updCene({ provizijaPrevoz: v, provizijaPrevozPct: "" })}
                onIznosRSD={(v) => updCene({ provizijaPrevozRSD: v, provizijaPrevozPct: "" })}
                disabled={zakljucano}
              />
              <Separator />
              <div className="grid gap-x-3 gap-y-2 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
                <PanelaSazetka kompaktno className="lg:col-start-2">
                  <div className="grid grid-cols-2 gap-x-3 gap-y-2">
                    <Fld label="Ukupno aranžman (EUR)">
                      <UkupnoInput vrednost={ukupnoAranzmanEUR} />
                    </Fld>
                    <Fld label="Ukupno aranžman (RSD)">
                      <UkupnoInput vrednost={ukupnoAranzmanRSD} />
                    </Fld>
                  </div>
                  <div data-testid="obracun-pregled" className="rounded-md border border-border/60 bg-muted/30 p-2 text-xs">
                    <div className="mb-1 font-semibold text-muted-foreground">Obračun</div>
                    <div className="grid grid-cols-[1fr_auto_auto] gap-x-3 gap-y-1 tabular-nums">
                      <span className="text-muted-foreground">Ukupna cena pre odbijanja popusta i provizije</span>
                      <span className="text-right">{nf2.format(brutoEURUkupno)} €</span>
                      <span className="text-right">{nf2.format(brutoRSDUkupno)} din</span>
                      <span className="text-muted-foreground">Popust</span>
                      <span className="text-right">− {nf2.format(popustEURUkupno)} €</span>
                      <span className="text-right">− {nf2.format(popustRSDUkupno)} din</span>
                      <span className="text-muted-foreground">Provizija</span>
                      <span className="text-right">− {nf2.format(provizijaEURUkupno)} €</span>
                      <span className="text-right">− {nf2.format(provizijaRSDUkupno)} din</span>
                    </div>
                  </div>
                  <div className="flex items-baseline justify-between gap-3">
                    <Label htmlFor="obracun-uplaceno" className="text-xs text-muted-foreground">Uplaćeno (RSD):</Label>

                    <Input
                      id="obracun-uplaceno"
                      inputMode="decimal"
                      className="w-36 text-right"
                      readOnly
                      value={uplacenoObracun === null ? "" : nf2.format(uplacenoObracun)}
                      placeholder={uplateUcitavaju ? "Učitavanje…" : "—"}
                    />
                  </div>
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="text-xs text-muted-foreground">Saldo (RSD):</span>
                    <span className={cn("text-base font-bold tabular-nums", saldo != null && saldo < 0 && "text-destructive")}>
                      {saldo != null ? `${nf2.format(saldo)} din` : "—"}
                    </span>
                  </div>
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="text-xs text-muted-foreground">Uplaćeno (EUR):</span>
                    <span className="text-sm font-medium tabular-nums">{uplacenoObracun !== null ? `${nf2.format(uplateSumaEUR)} €` : "—"}</span>
                  </div>
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="text-xs text-muted-foreground">Saldo (EUR):</span>
                    <span className={cn("text-base font-bold tabular-nums", saldoEUR !== null && saldoEUR < 0 && "text-destructive")}>
                      {saldoEUR !== null ? `${nf2.format(saldoEUR)} €` : "—"}
                    </span>
                  </div>
                  <p className="text-right text-xs text-muted-foreground">Uplaćeno: zbir svih uplata ugovora, uključujući storna. EUR uplate su po kursu na dan uplate. Saldo: vrednost aranžmana − uplaćeno.</p>
                  {izabraniUgovor && !uplateUcitavaju && uplateRedovi === null && (
                    <Button type="button" size="sm" variant="outline" onClick={() => setUplateOsvezi((n) => n + 1)}>Ponovi učitavanje uplata</Button>
                  )}
                  <p className="text-right text-xs text-muted-foreground">Izmene obračunskih polja se čuvaju dugmetom „Sačuvaj“ u donjoj traci.</p>
                </PanelaSazetka>
              </div>
            </CardContent>
          </Card>

        </TabsContent>

        {/* ════════════════ TAB: PREVOZ ════════════════ */}
        <TabsContent value="prevoz" className="mt-4">
          <Card className={TON.teal.kartica}>
            <CardHeader className={TON.teal.zaglavlje}>
              <CardTitle className="text-base flex items-center gap-2">
                <SekcijaIkona ton="teal"><Bus /></SekcijaIkona>Prevoz
              </CardTitle>
              <CardDescription>Destinacija, mesta ulaska i sedišta po putniku</CardDescription>
            </CardHeader>
            <CardContent className="space-y-5">
              <div className="grid gap-4 md:grid-cols-2 items-start">
                <Fld label="Izbor destinacije">
                  <Select value={destinacijaZaSve} onValueChange={(v) => { if (v !== CUVAR) setDestinacijaSacuvana(null); setDestinacijaZaSve(v); }} disabled={zakljucano}>
                    <SelectTrigger className="w-full"><SelectValue placeholder="Izaberite destinaciju" /></SelectTrigger>
                    <SelectContent>
                      {destinacijaSacuvana && <SelectItem value={CUVAR}>{destinacijaSacuvana} (sačuvano)</SelectItem>}
                      {destinacije.map((d) => (
                        <SelectItem key={d.id} value={String(d.id)}>{d.naziv}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Fld>
                <Fld label="Napomena prevoz">
                  <Input
                    value={boravak.napomenaPrevoz}
                    onChange={(e) => setBoravak({ ...boravak, napomenaPrevoz: e.target.value })}
                    maxLength={500}
                    disabled={zakljucano}
                    aria-label="Napomena prevoz"
                  />
                </Fld>
              </div>

              {polasciGreska && (
                <div className="flex flex-wrap items-center gap-2 text-sm text-destructive">
                  <span>Mesta ulaska iz registra prevoza nisu učitana.</span>
                  <Button type="button" size="sm" variant="outline" onClick={() => setPolasciOsvezi((n) => n + 1)}>Pokušaj ponovo</Button>
                </div>
              )}

              {putnici.length === 0 ? (
                <p className="text-sm text-muted-foreground py-4 text-center">
                  Dodajte putnike u tabu Aranžman.
                </p>
              ) : (
                <div className="space-y-2">
                  {putnici.map((p) => {
                    const red = prevozRedovi[p.uid] ?? { mestoUlaska: "", mestoIzlaska: "", mestoSedenja: "", placeno: false, zelja: false };
                    const osoba = p.osnovni ? nosilac : saputnici.find((s) => s.uid === p.uid)!;
                    const updOsoba = (patch: Partial<Nosilac>) => {
                      if (patch.rt !== undefined || patch.ow !== undefined || patch.sp !== undefined) {
                        setPrevozDetaljiOtvoreni((prev) => ({ ...prev, [p.uid]: false }));
                      }
                      if (patch.rt === false) {
                        patch = { ...patch, destinacijaPolaska: "", destinacijaPovratka: "" };
                      }
                      if (p.osnovni) setNosilac((prev) => ({ ...prev, ...patch }));
                      else setSaputnici((prev) => prev.map((s) => s.uid === p.uid ? { ...s, ...patch } : s));
                    };
                    // nasleđeno mesto ulaska van spiska ostaje izabrano kroz fallback opciju
                    const stariUlaz = red.mestoUlaska.trim() && !mestaUlaskaOpcije.includes(red.mestoUlaska) ? red.mestoUlaska : "";
                    const stariIzlaz = red.mestoIzlaska.trim() && !mestaUlaskaOpcije.includes(red.mestoIzlaska) ? red.mestoIzlaska : "";
                    return (
                      <div
                        key={p.uid}
                        className="grid gap-3 gap-x-3 grid-cols-1 md:grid-cols-[minmax(0,1.3fr)_repeat(3,max-content)_minmax(0,1.2fr)_minmax(0,1.2fr)_minmax(0,1.2fr)_repeat(2,max-content)] md:items-center rounded-lg border md:border-0 p-3 md:p-0 md:py-1"
                      >
                        <div className="space-y-1 min-w-0">
                          <div className="text-sm font-medium flex items-center gap-2 min-w-0">
                            <span className="truncate" title={p.ime}>{p.ime}</span>
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon"
                              className="size-7 shrink-0"
                              disabled={!osoba.ow && !osoba.rt}
                              aria-label={`${prevozDetaljiOtvoreni[p.uid] ? "Zatvori" : "Otvori"} detalje prevoza — ${p.ime}`}
                              aria-expanded={!!prevozDetaljiOtvoreni[p.uid] && (osoba.ow || osoba.rt)}
                              aria-controls={`prevoz-detalji-${p.uid}`}
                              title={osoba.ow || osoba.rt ? "Detalji prevoza" : "Prvo izaberite OW ili RT"}
                              onClick={() => setPrevozDetaljiOtvoreni((prev) => ({ ...prev, [p.uid]: !prev[p.uid] }))}
                            >
                              <Plus className={cn("size-4 transition-transform", prevozDetaljiOtvoreni[p.uid] && "rotate-45")} />
                            </Button>
                            {p.osnovni && <Badge variant="secondary">Nosilac</Badge>}
                          </div>
                        </div>
                        <Chk label="RT" labelClassName="text-xs" checked={osoba.rt} onChange={(v) => updOsoba({ rt: v, ow: v ? false : osoba.ow, sp: v ? false : osoba.sp, smer: v ? "" : osoba.smer, datumOw: v ? "" : osoba.datumOw, destinacijaOw: v ? "" : osoba.destinacijaOw, datumPolaska: v ? osoba.datumPolaska : "", datumPovratka: v ? osoba.datumPovratka : "", destinacijaPolaska: v ? osoba.destinacijaPolaska : "", destinacijaPovratka: v ? osoba.destinacijaPovratka : "" })} disabled={zakljucano} />
                        <Chk label="OW" labelClassName="text-xs" checked={osoba.ow} onChange={(v) => updOsoba({ ow: v, rt: v ? false : osoba.rt, sp: v ? false : osoba.sp, smer: v ? osoba.smer : "", datumOw: v ? osoba.datumOw : "", destinacijaOw: v ? osoba.destinacijaOw : "", datumPolaska: v ? "" : osoba.datumPolaska, datumPovratka: v ? "" : osoba.datumPovratka })} disabled={zakljucano} />
                        <Chk label="SP" labelClassName="text-xs" checked={osoba.sp} onChange={(v) => updOsoba({ sp: v, ow: v ? false : osoba.ow, rt: v ? false : osoba.rt, smer: v ? "" : osoba.smer, datumOw: v ? "" : osoba.datumOw, destinacijaOw: v ? "" : osoba.destinacijaOw, datumPolaska: v ? "" : osoba.datumPolaska, datumPovratka: v ? "" : osoba.datumPovratka })} disabled={zakljucano} />
                        <div className="space-y-1">
                          <PretraznaSelect
                            value={red.mestoUlaska}
                            onChange={(v) => updPrevoz(p.uid, { mestoUlaska: v, ...(red.mestoIzlaska === "" || red.mestoIzlaska === red.mestoUlaska ? { mestoIzlaska: v } : {}) })}
                            disabled={zakljucano}
                            ariaLabel={`Mesto ulaska — ${p.ime}`}
                            placeholder="Izaberite mesto ulaska"
                            opcije={[
                              ...(stariUlaz ? [{ value: stariUlaz, label: `${stariUlaz} (sačuvano)` }] : []),
                              ...mestaUlaskaOpcije.map((m) => ({ value: m, label: m })),
                            ]}
                          />
                        </div>
                        <div className="space-y-1">
                          <PretraznaSelect
                            value={red.mestoIzlaska}
                            onChange={(v) => updPrevoz(p.uid, { mestoIzlaska: v })}
                            disabled={zakljucano}
                            ariaLabel={`Mesto izlaska — ${p.ime}`}
                            placeholder="Izaberite mesto izlaska"
                            opcije={[
                              ...(stariIzlaz ? [{ value: stariIzlaz, label: `${stariIzlaz} (sačuvano)` }] : []),
                              ...mestaUlaskaOpcije.map((m) => ({ value: m, label: m })),
                            ]}
                          />
                        </div>
                        <div className="space-y-1">
                          <PretraznaSelect
                            value={red.mestoSedenja}
                            onChange={(v) => updPrevoz(p.uid, { mestoSedenja: v })}
                            disabled={zakljucano}
                            ariaLabel={`Mesto za sedenje — ${p.ime}`}
                            placeholder="Izaberite mesto za sedenje"
                            opcije={MESTO_SEDENJA.map((m) => ({ value: m, label: m }))}
                          />
                        </div>
                        <Chk label="Plaćeno" labelClassName="text-xs" checked={red.placeno} onChange={(v) => updPrevoz(p.uid, { placeno: v, zelja: v ? false : red.zelja })} disabled={zakljucano} />
                        <Chk label="Želja" labelClassName="text-xs" checked={red.zelja} onChange={(v) => updPrevoz(p.uid, { zelja: v, placeno: v ? false : red.placeno })} disabled={zakljucano} />
                        {prevozDetaljiOtvoreni[p.uid] && (osoba.ow || osoba.rt) && (
                          <div id={`prevoz-detalji-${p.uid}`} className="space-y-3 border-t pt-3 md:col-span-9">
                            {osoba.ow && (
                              <div className="flex flex-wrap gap-4">
                                <Fld label="Smer" className="w-full sm:w-48">
                                  <SmerSelect value={osoba.smer} onChange={(v) => updOsoba({ smer: v })} disabled={zakljucano} />
                                </Fld>
                                <DatumField label="Datum OW" className="w-full sm:w-40" value={osoba.datumOw} onChange={(v) => updOsoba({ datumOw: v })} disabled={zakljucano} />
                                <Fld label="Destinacija OW" className="w-full sm:w-64">
                                  <Select value={osoba.destinacijaOw} onValueChange={(v) => updOsoba({ destinacijaOw: v })} disabled={zakljucano}>
                                    <SelectTrigger className="w-full" aria-label={`Destinacija OW — ${p.ime}`}><SelectValue placeholder="Izaberite destinaciju OW" /></SelectTrigger>
                                    <SelectContent>
                                      {destinacije.map((d) => <SelectItem key={d.id} value={d.naziv}>{d.naziv}</SelectItem>)}
                                    </SelectContent>
                                  </Select>
                                </Fld>
                              </div>
                            )}
                            {osoba.rt && (
                              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                                <DatumField label="Datum polaska" value={osoba.datumPolaska} onChange={(v) => updOsoba({ datumPolaska: v })} disabled={zakljucano} />
                                <Fld label="Destinacija polaska">
                                  <Select value={osoba.destinacijaPolaska} onValueChange={(v) => updOsoba({ destinacijaPolaska: v })} disabled={zakljucano}>
                                    <SelectTrigger className="w-full" aria-label={`Destinacija polaska — ${p.ime}`}><SelectValue placeholder="Izaberite destinaciju polaska" /></SelectTrigger>
                                    <SelectContent>
                                      {destinacije.map((d) => <SelectItem key={d.id} value={d.naziv}>{d.naziv}</SelectItem>)}
                                    </SelectContent>
                                  </Select>
                                </Fld>
                                <DatumField label="Datum povratka" value={osoba.datumPovratka} onChange={(v) => updOsoba({ datumPovratka: v })} disabled={zakljucano} />
                                <Fld label="Destinacija povratka">
                                  <Select value={osoba.destinacijaPovratka} onValueChange={(v) => updOsoba({ destinacijaPovratka: v })} disabled={zakljucano}>
                                    <SelectTrigger className="w-full" aria-label={`Destinacija povratka — ${p.ime}`}><SelectValue placeholder="Izaberite destinaciju povratka" /></SelectTrigger>
                                    <SelectContent>
                                      {destinacije.map((d) => <SelectItem key={d.id} value={d.naziv}>{d.naziv}</SelectItem>)}
                                    </SelectContent>
                                  </Select>
                                </Fld>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* ════════════════ TAB: UPLATE ════════════════ */}
        <TabsContent value="uplate" className="mt-4">
          <Card className={TON.indigo.kartica}>
            <CardHeader className={TON.indigo.zaglavlje}>
              <CardTitle className="text-base flex items-center gap-2">
                <SekcijaIkona ton="indigo"><Wallet /></SekcijaIkona>Uplate
              </CardTitle>
              <CardDescription>Evidencija uplata za ovu rezervaciju</CardDescription>
            </CardHeader>
            <CardContent className="space-y-5">
              <div className="grid gap-4 grid-cols-1 md:grid-cols-4">
                <Fld label="Uplatilac">
                  <Select value={uplata.uplatilac} onValueChange={setUplatilac}>
                    <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {putnici.map((p) => (
                        <SelectItem key={p.uid} value={p.uid}>{p.ime}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Fld>
                <Fld label="Način plaćanja">
                  <Select
                    value={uplata.nacin}
                    onValueChange={(v) => setUplata({ ...uplata, nacin: v })}
                  >
                    <SelectTrigger className="w-full"><SelectValue placeholder="Izaberite" /></SelectTrigger>
                    <SelectContent>
                      {NACIN_PLACANJA.map((n) => <SelectItem key={n} value={n}>{n}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </Fld>
                <Fld label="Iznos (RSD)">
                  <Input
                    inputMode="decimal"
                    value={uplata.iznos}
                    onChange={(e) => setUplata({ ...uplata, iznos: e.target.value })}
                    placeholder="0,00"
                  />
                </Fld>
                <Fld label="Svrha uplate">
                  <Select value={uplata.svrha} onValueChange={(v) => setUplata({ ...uplata, svrha: v })}>
                    <SelectTrigger className="w-full"><SelectValue placeholder="Izaberite" /></SelectTrigger>
                    <SelectContent>
                      {SVRHA_UPLATE.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </Fld>
              </div>

              <div className="flex flex-wrap gap-2">
                <Button disabled={!izabraniUgovor || izborUcitava || uplataSeCuva} onClick={() => void potvrdiUplatu()}>
                  {uplataSeCuva ? <Loader2 className="w-4 h-4 mr-1.5 animate-spin" /> : <Check className="w-4 h-4 mr-1.5" />}
                  {uplataSeCuva ? "Upisivanje…" : "Potvrdi"}
                </Button>
                <Button variant="outline" disabled={!izabraniUgovor || uplatePdfUcitava} onClick={() => void preuzmiUplatePdf()}>
                  {uplatePdfUcitava
                    ? <Loader2 className="w-4 h-4 mr-1.5 animate-spin" />
                    : <Download className="w-4 h-4 mr-1.5" />}
                  Pregled uplata (PDF)
                </Button>
              </div>

              {!izabraniUgovor && (
                <p className="text-sm text-muted-foreground">
                  Pregled uplata se prikazuje nakon izbora ugovora u tabu Aranžman.
                </p>
              )}

              {izabraniUgovor && (
                <div className="overflow-hidden rounded-lg border">
                  <div className="flex flex-wrap items-center gap-2 border-b bg-muted/40 px-4 py-2.5">
                    <Receipt className="w-4 h-4 text-muted-foreground" />
                    <span className="text-sm font-semibold">Uplate za ugovor {izabraniUgovor}</span>

                    {uplateRedovi && uplateRedovi.length > 0 && (
                      <Badge variant="secondary" className="ml-auto">{uplateRedovi.length}</Badge>
                    )}
                  </div>
                  {uplateUcitavaju ? (
                    <div className="py-8 text-center">
                      <Loader2 className="w-5 h-5 animate-spin mx-auto text-muted-foreground" />
                    </div>
                  ) : uplateRedovi && uplateRedovi.length > 0 ? (
                    <div className="overflow-x-auto">
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Datum</TableHead>
                            <TableHead>Način plaćanja</TableHead>
                            <TableHead className="text-right">RSD</TableHead>
                            <TableHead className="text-right">Suma u €</TableHead>
                            <TableHead>Svrha Uplate</TableHead>
                            <TableHead>Operater</TableHead>
                            <TableHead className="text-right">Ključ</TableHead>
                            <TableHead className="w-14 text-center">Kartica</TableHead>
                            <TableHead className="w-14 text-center">Čekovi</TableHead>
                            <TableHead className="w-14 text-center">PDF</TableHead>
                            <TableHead className="w-14 text-center">Prebacivanje</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {uplateRedovi.map((u, i) => (
                            <TableRow key={u.kljuc ?? `${u.id}-${u.danas}-${i}`}>
                              <TableCell className="whitespace-nowrap">{u.danas ?? "—"}</TableCell>
                              <TableCell>{u.nacin?.trim() || "—"}</TableCell>
                              <TableCell className="whitespace-nowrap text-right">{u.din != null ? `${nf2.format(u.din)} din` : "—"}</TableCell>
                              <TableCell
                                className="whitespace-nowrap text-right"
                                title={u.kurs ? `Kurs ${kursFormat.format(u.kurs)}${u.kurs_datum && u.kurs_datum !== u.danas ? ` (datum kursa ${u.kurs_datum})` : ""}` : undefined}
                              >
                                {u.suma_eur != null ? `${nf2.format(u.suma_eur)}€` : "—"}
                              </TableCell>
                              <TableCell>{u.svrha?.trim() || "—"}</TableCell>
                              <TableCell>{u.obradio?.trim() || "—"}</TableCell>
                              <TableCell className="text-right">{u.kljuc ?? "—"}</TableCell>
                              <TableCell className="text-center">
                                {u.kljuc != null && u.nacin?.trim() === "Kartica" && (
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    className={cn("size-7", karticaImaPodatke(u) ? STATUS_IKONA_PUNO : STATUS_IKONA_PRAZNO)}
                                    title={karticaImaPodatke(u) ? "Podaci kartice (uneti)" : "Podaci kartice (nisu uneti)"}
                                    aria-label={`Podaci kartice — uplata ${u.kljuc}`}
                                    onClick={() => setKarticaPopup({
                                      kljuc: u.kljuc as number,
                                      vrednost: {
                                        brojPotvrde: u.broj_potvrde ?? "",
                                        tipKartice: u.tip_kartice ?? "",
                                        brojKartice: u.broj_kartice ?? "",
                                        brojOdobrenja: u.broj_odobrenja ?? "",
                                      },
                                    })}
                                  >
                                    <CreditCard className="size-4" />
                                  </Button>
                                )}
                              </TableCell>
                              <TableCell className="text-center">
                                {u.kljuc != null && u.nacin?.trim() === "Ček" && (
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    className={cn("size-7", (u.broj_cekova ?? 0) > 0 ? STATUS_IKONA_PUNO : STATUS_IKONA_PRAZNO)}
                                    title={(u.broj_cekova ?? 0) > 0 ? `Čekovi uplate (${u.broj_cekova} uneto)` : "Čekovi uplate (nisu uneti)"}
                                    aria-label={`Čekovi — uplata ${u.kljuc}`}
                                    disabled={cekUcitavaKljuc === u.kljuc}
                                    onClick={() => void otvoriCekove(u)}
                                  >
                                    {cekUcitavaKljuc === u.kljuc
                                      ? <Loader2 className="size-4 animate-spin" />
                                      : <Landmark className="size-4" />}
                                  </Button>
                                )}
                              </TableCell>
                              <TableCell className="text-center">
                                {u.kljuc != null && (
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    className="size-7"
                                    title="Priznanica (PDF)"
                                    disabled={priznanicaKljuc === u.kljuc}
                                    onClick={() => void preuzmiPriznanicu(u.kljuc as number)}
                                  >
                                    {priznanicaKljuc === u.kljuc
                                      ? <Loader2 className="size-4 animate-spin" />
                                      : <Download className="size-4" />}
                                  </Button>
                                )}
                              </TableCell>
                              <TableCell className="text-center">
                                {u.kljuc != null && (
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    className="size-7"
                                    title="Povraćaj — prebaci uplatu na drugi ugovor"
                                    aria-label={`Prebaci uplatu ${u.kljuc}`}
                                    onClick={() => setPrebacivanjeUplata(u)}
                                  >
                                    <ArrowRightLeft className="size-4" />
                                  </Button>
                                )}
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                        <TableFooter>
                          <TableRow>
                            <TableCell colSpan={2}>Ukupno uplaćeno:</TableCell>
                            <TableCell className="whitespace-nowrap text-right font-semibold">{nf2.format(uplateSumaRSD)} din</TableCell>
                            <TableCell className="whitespace-nowrap text-right font-semibold">{nf2.format(uplateSumaEUR)}€</TableCell>
                            <TableCell colSpan={7} />
                          </TableRow>
                        </TableFooter>
                      </Table>
                    </div>
                  ) : (
                    <div className="py-6 text-center text-sm text-muted-foreground">Nema uplata za ovaj ugovor.</div>
                  )}
                </div>
              )}

              {izabraniUgovor && zabraneUgovora.length > 0 && (
                <div className="flex flex-wrap items-center gap-2 rounded-lg border px-4 py-2.5">
                  <Ban className="w-4 h-4 text-muted-foreground" />
                  <>
                    <span className="text-sm font-semibold">Administrativna zabrana:</span>
                      {zabraneUgovora.map((z) => (
                        <div key={z.broj} className="flex flex-wrap items-center gap-2 rounded-md bg-muted/40 px-2.5 py-1">
                          <Badge variant="secondary">{z.broj}</Badge>
                          <span className="text-sm">
                            {z.datum ? z.datum.split("-").reverse().join(".") : "—"}
                            {z.ukupno != null && ` · ${nf2.format(z.ukupno)} ${z.valuta || "RSD"}`}
                          </span>
                          {z.preuzeta_datum && (
                            <Badge variant="outline">Preuzeta {z.preuzeta_datum}</Badge>
                          )}
                          <Button
                            variant="outline"
                            size="sm"
                            className="h-7"
                            disabled={zabranaPdfBroj !== null}
                            onClick={() => void preuzmiZabranuPdf(z.broj)}
                          >
                            {zabranaPdfBroj === z.broj
                              ? <Loader2 className="w-4 h-4 mr-1.5 animate-spin" />
                              : <Printer className="w-4 h-4 mr-1.5" />}
                            Štampaj (PDF)
                          </Button>
                        </div>
                      ))}
                  </>
                </div>
              )}
            </CardContent>
          </Card>
          {karticaPopup && (
            <KarticaPopup
              open
              onOpenChange={(o) => { if (!o && !karticaCuva) setKarticaPopup(null); }}
              vrednost={karticaPopup.vrednost}
              tipovi={tipoviKartica}
              naslov={`Podaci kartice — uplata ${karticaPopup.kljuc}`}
              opis="Unesite ili izmenite podatke kartice za ovu uplatu."
              cuva={karticaCuva}
              onSacuvaj={(k) => void sacuvajKarticu(k)}
            />
          )}
          {cekPopup && (
            <CekPopup
              open
              onOpenChange={(o) => { if (!o && !cekCuva) setCekPopup(null); }}
              iznos={cekPopup.iznos}
              pocetni={cekPopup.pocetni}
              cuva={cekCuva}
              onSacuvaj={(s) => void sacuvajCekove(s)}
            />
          )}
          {prebacivanjeUplata && izabraniUgovor && (
            <PrebacivanjeUplatePopup
              open
              onOpenChange={(o) => { if (!o) setPrebacivanjeUplata(null); }}
              uplata={{ kljuc: prebacivanjeUplata.kljuc as number, din: prebacivanjeUplata.din, danas: prebacivanjeUplata.danas }}
              izvorUgovor={izabraniUgovor}
              onPrebaceno={() => {
                // napomena interna izvornog ugovora se promenila na serveru → osveži formu i listu uplata
                setUplateOsvezi((n) => n + 1);
                void izaberiUgovor(izabraniUgovor);
              }}
            />
          )}
        </TabsContent>

        <TabsContent value="zaduzenje" className="mt-4">
          <ZaduzenjePartnerTab kljuc={izabraniUgovor} zakljucano={zakljucano} />
        </TabsContent>
      </Tabs>

      <Dialog open={istorijaOtvorena} onOpenChange={setIstorijaOtvorena}>
        <DialogContent className="max-w-2xl bg-card">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <History className="size-4 text-primary" />Istorija promena
              {izabraniUgovor && <span className="text-sm font-normal text-muted-foreground">· {izabraniUgovor}</span>}
            </DialogTitle>
            <DialogDescription className="sr-only">Zabeležene izmene rezervacije za izabrani ugovor</DialogDescription>
          </DialogHeader>
          <div className="max-h-[65vh] overflow-y-auto pr-1">
            {istorijaUcitava && !istorija && (
              <div className="flex justify-center py-6"><Loader2 className="size-5 animate-spin text-muted-foreground" /></div>
            )}
            {istorija && istorija.length > 0 ? (
              <ul className="divide-y text-sm">
                {istorija.map((r) => (
                  <li key={r.id} className="py-2 space-y-1">
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                      <span className="whitespace-nowrap text-xs text-muted-foreground">{istorijaVreme(r.created_at)}</span>
                      <Badge variant="outline">{ISTORIJA_OBLAST[r.oblast] ?? r.oblast}</Badge>
                      <span className="font-medium">{ISTORIJA_DOGADJAJ[r.dogadjaj] ?? r.dogadjaj}</span>
                      <span className="text-xs text-muted-foreground">· {r.user_ime || "nepoznat korisnik"}</span>
                    </div>
                    {r.promene.length > 0 && (
                      <ul className="space-y-0.5 pl-1 text-xs">
                        {r.promene.map((p, i) => (
                          <li key={i} className="flex flex-wrap gap-x-1">
                            <span className="text-muted-foreground">{p.polje}:</span>
                            <span className="line-through text-muted-foreground">{p.stara ?? "—"}</span>
                            <span>→</span>
                            <span className="font-medium">{p.nova ?? "—"}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </li>
                ))}
              </ul>
            ) : istorija ? (
              <div className="py-6 text-center text-sm text-muted-foreground">Nema zabeleženih promena.</div>
            ) : null}
          </div>
        </DialogContent>
      </Dialog>

      {izabraniUgovor && (
        <AdministrativnaZabranaPopup
          open={zabranaOtvorena}
          onOpenChange={setZabranaOtvorena}
          kljuc={izabraniUgovor}
        />
      )}

      {/* Zajedničke akcije ostaju dostupne na svim tabovima. */}
      <div className="sticky bottom-0 z-10 -mx-6 flex flex-wrap gap-2 border-t bg-background/95 px-6 py-3 backdrop-blur">
        <Button variant="outline" onClick={akcija("Potvrda")}>
          <BadgeCheck className="mr-1.5 size-4" />Potvrda
        </Button>
        <Button
          variant="outline"
          disabled={!izabraniUgovor || ugovorPdfUcitava}
          title={izabraniUgovor
            ? "Preuzima se sačuvani ugovor (PDF) — nesnimljene izmene forme nisu uključene"
            : "Izaberite sačuvan ugovor za preuzimanje PDF-a"}
          aria-label="Preuzmi sačuvani ugovor kao PDF"
          onClick={() => void preuzmiUgovorPdf()}
        >
          {ugovorPdfUcitava ? <Loader2 className="mr-1.5 size-4 animate-spin" /> : <FileText className="mr-1.5 size-4" />}
          Ugovor
        </Button>
        <Button variant="outline" onClick={akcija("Vaučer")}>
          <Ticket className="mr-1.5 size-4" />Vaučer
        </Button>
        <Button variant="outline" onClick={akcija("Karta")}>
          <CreditCard className="mr-1.5 size-4" />Karta
        </Button>
        <Button
          variant="outline"
          disabled={!izabraniUgovor || izborUcitava || rezSeCuva}
          title={izabraniUgovor
            ? "Kreiraj predračun za sačuvani ugovor"
            : "Najpre sačuvajte rezervaciju ili izaberite postojeći ugovor"}
          onClick={() => {
            if (izabraniUgovor) navigate(`/knjigovodstvo/predracuni/novi/${izabraniUgovor}`);
          }}
        >
          <FilePlus className="mr-1.5 size-4" />Predračun
        </Button>
        <Button
          variant="outline"
          disabled={!izabraniUgovor}
          title={izabraniUgovor
            ? "Kreiraj administrativnu zabranu za sačuvani ugovor"
            : "Najpre sačuvajte rezervaciju ili izaberite postojeći ugovor"}
          onClick={() => setZabranaOtvorena(true)}
        >
          <Ban className="mr-1.5 size-4" />Adm. zabrana
        </Button>
        <Button
          variant="outline"
          disabled={!izabraniUgovor || saglasnostPdfUcitava}
          title={izabraniUgovor
            ? "Preuzmi saglasnost za obradu podataka o ličnosti (PDF)"
            : "Najpre sačuvajte rezervaciju ili izaberite postojeći ugovor"}
          onClick={() => void preuzmiSaglasnostPdf()}
        >
          {saglasnostPdfUcitava
            ? <Loader2 className="mr-1.5 size-4 animate-spin" />
            : <FileSignature className="mr-1.5 size-4" />}
          Saglasnost
        </Button>
        <Button variant="outline" onClick={akcija("Najava")}>
          <Send className="mr-1.5 size-4" />Najava
        </Button>
        <Button
          disabled={rezSeCuva || izborUcitava}
          className={izabraniUgovor && !izmena ? "bg-amber-400 text-amber-950 shadow-sm hover:bg-amber-500 focus-visible:ring-amber-500" : "bg-blue-600 text-white shadow-sm hover:bg-blue-700 focus-visible:ring-blue-500"}
          title={izabraniUgovor && !izmena ? "Otključaj polja za izmenu" : "Sačuvaj rezervaciju u bazu"}
          onClick={() => void sacuvajRezervaciju()}
        >
          {rezSeCuva
            ? <Loader2 className="mr-1.5 size-4 animate-spin" />
            : izabraniUgovor && !izmena ? <FilePenLine className="mr-1.5 size-4" /> : <CalendarPlus className="mr-1.5 size-4" />}
          {rezSeCuva ? "Čuvanje…" : izabraniUgovor && !izmena ? "Izmeni" : "Sačuvaj"}
        </Button>
        <Button variant="outline" onClick={akcija("Odustani")}>
          <X className="mr-1.5 size-4" />Odustani
        </Button>
        <div
          data-testid="saldo-traka"
          aria-label="Saldo rezervacije"
          className={cn(
            "ml-auto flex items-baseline gap-2 rounded-md border-2 px-4 py-1.5 tabular-nums",
            saldoEUR !== null && saldoEUR < 0
              ? "border-destructive/60 bg-destructive/10 text-destructive"
              : "border-emerald-500/60 bg-emerald-50 text-emerald-800",
          )}
        >
          <span className="text-lg font-bold">
            {izborUcitava || uplateUcitavaju
              ? "Učitavanje…"
              : saldoEUR !== null && saldo !== null
                ? <>{nf2.format(saldoEUR)} € <span className="font-light">| {nf2.format(saldo)} RSD</span></>
                : "—"}
          </span>
        </div>
      </div>
    </div>
  );
}
