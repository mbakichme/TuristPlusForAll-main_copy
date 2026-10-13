import { useState, useEffect, useMemo, useRef } from "react";
import type { Mesto, Smestaj, Soba, PeriodGrupa, UgovorDetail } from "../types";
import { apiFetch } from "../lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue
} from "@/components/ui/select";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Calendar } from "@/components/ui/calendar";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle
} from "@/components/ui/dialog";
import { Loader2, ArrowLeft, Check, CalendarDays } from "lucide-react";
import { toast } from "sonner";

interface PromenaSmestajaDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  ugovorKljuc: string;
  detail: UgovorDetail | null;
  /** Poziva se nakon uspešnog PATCH-a — osvežava grafik. */
  onSuccess: () => void;
  /** Nazad — vraća na prvi popup bez ikakvih izmena. */
  onBack: () => void;
}

/** dd.mm.yyyy → yyyy-mm-dd (ISO) */
function toIsoDate(s: string | null | undefined): string {
  if (!s) return "";
  const [d, m, y] = s.split(".").map(Number);
  if (!d || !m || !y) return "";
  return `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

/** ISO "yyyy-mm-dd" → lokalni Date (bez UTC konverzije) */
function isoToDatum(v: string): Date | undefined {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(v);
  return m ? new Date(+m[1], +m[2] - 1, +m[3]) : undefined;
}

/** lokalni Date → ISO "yyyy-mm-dd" */
function datumToIso(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** ISO "yyyy-mm-dd" → dd.mm.yyyy za prikaz */
function isoToPrikaz(v: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(v);
  return m ? `${m[3]}.${m[2]}.${m[1]}` : "";
}

/* eslint-disable react-refresh/only-export-components -- čisti helperi izvoženi samo za inline bun testove */

/** Uklanja "APP" (case-insensitive) i sav razmak iz tipa sobe; ostatak zadržava. Npr. "APP 1/2" → "1/2". */
export function ocistiTipSobe(tip: string | null | undefined): string {
  return (tip ?? "").replace(/app/gi, "").replace(/\s+/g, "");
}

/** Soba za prikaz: broj + očišćen tip, npr. "6 (1/2)". */
export function formatSobaLabel(brojSobe: string | null | undefined, tip: string | null | undefined): string {
  const broj = (brojSobe ?? "").trim();
  const cistTip = ocistiTipSobe(tip);
  if (broj && cistTip) return `${broj} (${cistTip})`;
  return broj || cistTip || "—";
}

/** Skupovi dozvoljenih početaka i krajeva perioda grupe (ISO stringovi). */
export function skupoviGrupe(grupa: PeriodGrupa | undefined | null): { poceci: Set<string>; krajevi: Set<string> } {
  const datumi = grupa?.datumi ?? [];
  return {
    poceci: new Set(datumi.map((d) => toIsoDate(d.datum_od)).filter(Boolean)),
    krajevi: new Set(datumi.map((d) => toIsoDate(d.datum_do)).filter(Boolean)),
  };
}

/**
 * Validira par (od, do) prema skupovima grupe perioda.
 * "od" mora biti početak nekog perioda; "do" kraj nekog perioda posle "od".
 * Prvo se resetuje nevažeći "od", pa zatim "do" — važeći unosi se zadržavaju (prefill).
 */
export function validirajDatume(
  od: string, doVrednost: string,
  poceci: ReadonlySet<string>, krajevi: ReadonlySet<string>,
): [string, string] {
  const odNovi = od && poceci.has(od) ? od : "";
  const doNovi = doVrednost && krajevi.has(doVrednost) && odNovi !== "" && doVrednost > odNovi ? doVrednost : "";
  return [odNovi, doNovi];
}

const MESECI = ["januar", "februar", "mart", "april", "maj", "jun", "jul", "avgust", "septembar", "oktobar", "novembar", "decembar"];
const MESECI_KAL = MESECI.map((m) => m.charAt(0).toUpperCase() + m.slice(1));
const DANI = ["Ned", "Pon", "Uto", "Sre", "Čet", "Pet", "Sub"];
const formatteriKalendara = {
  formatWeekdayName: (day: Date) => DANI[day.getDay()],
  formatMonthDropdown: (date: Date) => MESECI_KAL[date.getMonth()],
};

/** Opseg meseci kalendara izvrnut iz skupa dozvoljenih datuma. */
function opsegMeseci(skup: ReadonlySet<string>): { startMonth?: Date; endMonth?: Date } {
  const arr = [...skup].filter(Boolean).sort();
  if (!arr.length) return {};
  const prvi = isoToDatum(arr[0]);
  const poslednji = isoToDatum(arr[arr.length - 1]);
  if (!prvi || !poslednji) return {};
  return {
    startMonth: new Date(prvi.getFullYear(), prvi.getMonth(), 1),
    endMonth: new Date(poslednji.getFullYear(), poslednji.getMonth(), 1),
  };
}

/** Read-only vrednost trenutnog stanja — ista visina i ritam kao polja za unos (h-9). */
function TrenutnoPolje({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <span className="block text-xs leading-4 text-muted-foreground mt-1">{label}</span>
      <div className="mt-1.5 flex h-9 items-center rounded-md border border-input bg-muted/40 px-3">
        <span className="truncate text-sm font-medium">{value || "—"}</span>
      </div>
    </div>
  );
}

/** Datum picker — Popover + Calendar (ponedeljak-prvi, samo dozvoljeni datumi iz grupe perioda). */
function DatumPicker({
  id, label, value, allowed, onSelect, disabled, placeholder,
}: {
  id: string;
  label: string;
  value: string;
  allowed: ReadonlySet<string>;
  onSelect: (iso: string) => void;
  disabled?: boolean;
  placeholder?: string;
}) {
  const [open, setOpen] = useState(false);
  const opseg = useMemo(() => opsegMeseci(allowed), [allowed]);
  return (
    <div className="min-w-0 space-y-1.5">
      <Label htmlFor={id} className="block text-xs leading-4 text-muted-foreground mt-1">{label}</Label>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            id={id}
            type="button"
            variant="outline"
            disabled={disabled}
            className={cn("w-full justify-start gap-2 px-3 font-normal", !value && "text-muted-foreground")}
          >
            <CalendarDays className="size-4 shrink-0" aria-hidden />
            <span className="truncate">{value ? isoToPrikaz(value) : (placeholder ?? "dd.mm.yyyy")}</span>
          </Button>
        </PopoverTrigger>
        <PopoverContent align="start" className="w-auto p-0">
          <Calendar
            mode="single"
            selected={isoToDatum(value)}
            defaultMonth={isoToDatum(value) ?? opseg.startMonth}
            onSelect={(d) => { onSelect(d ? datumToIso(d) : ""); setOpen(false); }}
            weekStartsOn={1}
            captionLayout="dropdown"
            startMonth={opseg.startMonth}
            endMonth={opseg.endMonth}
            formatters={formatteriKalendara}
            disabled={(d) => !allowed.has(datumToIso(d))}
            initialFocus
          />
        </PopoverContent>
      </Popover>
    </div>
  );
}

/**
 * Drugi popup grafika — promena smeštaja ugovora.
 * Jedna mreža sa 2 kolone: levo trenutno stanje (read-only), desno novi izbor (mesto → smeštaj → soba, datumi).
 * Datumi su ograničeni na grupu perioda izabranog smeštaja (fallback: mesto) —
 * "od" samo počeci perioda, "do" samo krajevi posle izabranog "od".
 * Backend sve izvodi iz sobe: PATCH /ugovori/{kljuc}/smestaj { soba_id, datum_od, datum_do }.
 */
export default function PromenaSmestajaDialog({
  open, onOpenChange, ugovorKljuc, detail, onSuccess, onBack,
}: PromenaSmestajaDialogProps) {
  const [mesta, setMesta] = useState<Mesto[]>([]);
  const [smestaji, setSmestaji] = useState<Smestaj[]>([]);
  const [sobe, setSobe] = useState<Soba[]>([]);
  const [periodGrupe, setPeriodGrupe] = useState<PeriodGrupa[]>([]);
  const [loadingData, setLoadingData] = useState(false);
  const [saving, setSaving] = useState(false);
  const [placeId, setPlaceId] = useState("");
  const [smestajSel, setSmestajSel] = useState("");
  const [sobaSel, setSobaSel] = useState("");
  const [datumOd, setDatumOd] = useState("");
  const [datumDo, setDatumDo] = useState("");
  const savingRef = useRef(false);

  // Pri svakom otvaranju: reset forme, učitavanje opcija (uklj. grupe perioda) i prefill po trenutnom ugovoru
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setPlaceId(""); setSmestajSel(""); setSobaSel(""); setDatumOd(""); setDatumDo("");
    setLoadingData(true);
    Promise.all([
      apiFetch<Mesto[]>("/mesto"),
      apiFetch<Smestaj[]>("/smestaj"),
      apiFetch<Soba[]>("/sobe"),
      apiFetch<PeriodGrupa[]>("/period-grupa"),
    ])
      .then(([m, s, b, pg]) => {
        if (cancelled) return;
        setMesta(m); setSmestaji(s); setSobe(b); setPeriodGrupe(pg);
        if (detail) {
          // prefill: smeštaj po nazivu, mesto preko smeštaja (ili nazivom mesta), soba po broju
          const naziv = (detail.naziv || "").trim();
          const sm = naziv ? s.find((x) => (x.naziv || "").trim() === naziv) : undefined;
          let pl: Mesto | undefined;
          if (sm?.mesto != null) {
            setPlaceId(String(sm.mesto));
            setSmestajSel(String(sm.id));
            pl = m.find((x) => x.id === sm.mesto);
          } else {
            const mn = (detail.mesto || "").trim();
            pl = mn ? m.find((x) => (x.naziv || "").trim() === mn) : undefined;
            if (pl) setPlaceId(String(pl.id));
          }
          if (sm) {
            const sb = (detail.soba || "").trim();
            const room = sb
              ? b.find((x) => x.veza_id_smestaj === sm.id && (x.broj_sobe || "").trim() === sb)
              : undefined;
            if (room) setSobaSel(String(room.id));
          }
          // Inicijalni datumi ostaju samo ako pripadaju grupi perioda izabranog smeštaja (fallback: mesto)
          const gid = sm?.grupa_datuma ?? pl?.grupe?.[0];
          const grupa = gid != null ? pg.find((g) => g.id === gid) : undefined;
          const { poceci, krajevi } = skupoviGrupe(grupa);
          const [od, doVrednost] = validirajDatume(
            toIsoDate(detail.datumod), toIsoDate(detail.datumdo), poceci, krajevi,
          );
          setDatumOd(od);
          setDatumDo(doVrednost);
        }
      })
      .catch(() => { if (!cancelled) toast.error("Greška pri učitavanju podataka"); })
      .finally(() => { if (!cancelled) setLoadingData(false); });
    return () => { cancelled = true; };
  }, [open, ugovorKljuc, detail]);

  const smestajiFiltrirani = useMemo(
    () => smestaji.filter((s) => placeId && s.mesto === Number(placeId)),
    [smestaji, placeId]
  );
  const sobeFiltrirane = useMemo(
    () => sobe.filter((x) => smestajSel && x.veza_id_smestaj === Number(smestajSel)),
    [sobe, smestajSel]
  );

  // Aktivna grupa perioda: izabran smeštaj → fallback izabrano mesto
  const aktivnaGrupa = useMemo<PeriodGrupa | undefined>(() => {
    const gid = smestaji.find((x) => String(x.id) === smestajSel)?.grupa_datuma
      ?? mesta.find((x) => String(x.id) === placeId)?.grupe?.[0];
    return gid != null ? periodGrupe.find((g) => g.id === gid) : undefined;
  }, [periodGrupe, smestaji, mesta, smestajSel, placeId]);

  const dozvoljeniPoceci = useMemo(
    () => skupoviGrupe(aktivnaGrupa).poceci,
    [aktivnaGrupa]
  );
  const sviKrajevi = useMemo(
    () => skupoviGrupe(aktivnaGrupa).krajevi,
    [aktivnaGrupa]
  );
  // "do" — samo krajevi perioda posle izabranog "od"
  const dozvoljeniKrajevi = useMemo(() => {
    if (!datumOd) return new Set<string>();
    return new Set([...sviKrajevi].filter((k) => k > datumOd));
  }, [sviKrajevi, datumOd]);

  // Kaskadno resetovanje nizvodnih selekcija + brisanje datuma nevažećih pod novom grupom perioda
  function onPlaceChange(v: string) {
    setPlaceId(v);
    setSmestajSel("");
    setSobaSel("");
    const gid = mesta.find((x) => String(x.id) === v)?.grupe?.[0];
    const { poceci, krajevi } = skupoviGrupe(gid != null ? periodGrupe.find((g) => g.id === gid) : undefined);
    const [od, doVrednost] = validirajDatume(datumOd, datumDo, poceci, krajevi);
    setDatumOd(od);
    setDatumDo(doVrednost);
  }
  function onSmestajChange(v: string) {
    setSmestajSel(v);
    setSobaSel("");
    const sm = smestaji.find((x) => String(x.id) === v);
    const gid = sm?.grupa_datuma ?? mesta.find((x) => String(x.id) === placeId)?.grupe?.[0];
    const { poceci, krajevi } = skupoviGrupe(gid != null ? periodGrupe.find((g) => g.id === gid) : undefined);
    const [od, doVrednost] = validirajDatume(datumOd, datumDo, poceci, krajevi);
    setDatumOd(od);
    setDatumDo(doVrednost);
  }
  function onOdIzabran(iso: string) {
    setDatumOd(iso);
    // "do" ostaje samo ako je i dalje kraj perioda posle novog "od"
    setDatumDo((d) => (d && iso !== "" && d > iso && sviKrajevi.has(d) ? d : ""));
  }

  // Zabrana zatvaranja (X, Esc, klik van) dok traje čuvanje
  function handleOpenChange(next: boolean) {
    if (savingRef.current) return;
    onOpenChange(next);
  }

  function handleNazad() {
    if (savingRef.current) return;
    onBack();
  }

  async function handleSave() {
    if (savingRef.current) return;
    if (!placeId || !smestajSel || !sobaSel) {
      toast.error("Izaberite mesto, smeštaj i sobu.");
      return;
    }
    if (!datumOd || !datumDo) {
      toast.error("Unesite oba datuma.");
      return;
    }
    if (dozvoljeniPoceci.size === 0) {
      toast.error("Izabrani smeštaj nema definisanu grupu perioda.");
      return;
    }
    // Ponovna validacija prema skupovima grupe perioda, neposredno pre PATCH-a
    if (!dozvoljeniPoceci.has(datumOd)) {
      toast.error("Datum \u2018od\u2019 mora biti početak jednog od perioda izabrane grupe.");
      return;
    }
    if (!dozvoljeniKrajevi.has(datumDo)) {
      toast.error("Datum \u2018do\u2019 mora biti kraj nekog od perioda, posle datuma \u2018od\u2019.");
      return;
    }
    savingRef.current = true;
    setSaving(true);
    try {
      await apiFetch(`/ugovori/${encodeURIComponent(ugovorKljuc)}/smestaj`, {
        method: "PATCH",
        body: JSON.stringify({
          soba_id: Number(sobaSel),
          datum_od: datumOd,
          datum_do: datumDo,
        }),
      });
      toast.success("Smeštaj je uspešno promenjen.");
      onSuccess();
      onOpenChange(false);
    } catch (e) {
      // forma ostaje popunjena — korisnik može da ispravi i ponovi
      toast.error(e instanceof Error ? e.message : "Greška pri promeni smeštaja.");
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }

  const fieldsDisabled = saving || loadingData;
  const nemaPerioda = Boolean(placeId && smestajSel) && (!aktivnaGrupa || dozvoljeniPoceci.size === 0);
  const hintZaDatume = !placeId || !smestajSel
    ? "Izaberite mesto i smeštaj da biste videli dostupne periode."
    : nemaPerioda
      ? "Izabrani smeštaj nema definisanu grupu perioda — izbor datuma nije moguć."
      : "";

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-3xl" aria-busy={saving}>
        <DialogHeader>
          <DialogTitle>Promena smeštaja</DialogTitle>
          <DialogDescription>
            Izaberite novi smeštaj i period. Ostale podatke sistem izvodi iz sobe.
          </DialogDescription>
        </DialogHeader>

        {/* Ključ ugovora i nosilac */}
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg border bg-muted/40 px-3 py-2">
          <span className="font-mono text-xs font-semibold text-primary">{ugovorKljuc}</span>
          <span className="text-muted-foreground/60 text-xs" aria-hidden>·</span>
          <span className="text-sm font-medium truncate min-w-0">
            {detail?.putnik?.trim() || "Nosilac nije upisan"}
          </span>
        </div>

        {loadingData ? (
          <div className="py-10 text-center">
            <Loader2 className="w-6 h-6 animate-spin mx-auto text-muted-foreground" aria-label="Učitavanje" />
          </div>
        ) : (
          <div className="relative isolate grid grid-cols-2 gap-x-4 gap-y-3 py-3 [&>div:not([aria-hidden])]:mx-3">
            <div aria-hidden="true" className="pointer-events-none absolute inset-y-0 left-0 -z-10 w-[calc(50%-0.5rem)] rounded-lg border bg-muted/30" />
            <div aria-hidden="true" className="pointer-events-none absolute inset-y-0 right-0 -z-10 w-[calc(50%-0.5rem)] rounded-lg border bg-white" />
            {/* Naslovi iznad jasno odvojenih trenutnih i novih podataka. */}
            <h3 className="px-3 text-sm font-semibold text-foreground">
              Trenutno
            </h3>
            <h3 className="px-3 text-sm font-semibold text-foreground">
              Novo
            </h3>

            {/* Mesto */}
            <TrenutnoPolje label="Trenutno mesto" value={detail?.mesto || ""} />
            <div className="min-w-0 space-y-1.5">
              <Label htmlFor="pm-mesto" className="block text-xs leading-4 text-muted-foreground mt-1">Mesto</Label>
              <Select value={placeId} onValueChange={onPlaceChange} disabled={fieldsDisabled}>
                <SelectTrigger id="pm-mesto" className="w-full">
                  <SelectValue placeholder="Izaberite mesto" />
                </SelectTrigger>
                <SelectContent>
                  {mesta.map((m) => (
                    <SelectItem key={m.id} value={String(m.id)}>{m.naziv}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Smeštaj */}
            <TrenutnoPolje label="Smeštaj" value={detail?.naziv || ""} />
            <div className="min-w-0 space-y-1.5">
              <Label htmlFor="pm-smestaj" className="block text-xs leading-4 text-muted-foreground mt-1">Smeštaj</Label>
              <Select
                value={smestajSel}
                onValueChange={onSmestajChange}
                disabled={!placeId || fieldsDisabled}
              >
                <SelectTrigger id="pm-smestaj" className="w-full">
                  <SelectValue placeholder={placeId ? "Izaberite smeštaj" : "Prvo izaberite mesto"} />
                </SelectTrigger>
                <SelectContent>
                  {smestajiFiltrirani.map((s) => (
                    <SelectItem key={s.id} value={String(s.id)}>{s.naziv}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {placeId && smestajiFiltrirani.length === 0 && (
                <p className="text-xs text-muted-foreground">Nema smeštaja na izabranom mestu.</p>
              )}
            </div>

            {/* Soba — broj + očišćen tip, npr. "6 (1/2)" */}
            <TrenutnoPolje label="Soba" value={formatSobaLabel(detail?.soba, detail?.apartman)} />
            <div className="min-w-0 space-y-1.5">
              <Label htmlFor="pm-soba" className="block text-xs leading-4 text-muted-foreground mt-1">Soba</Label>
              <Select
                value={sobaSel}
                onValueChange={setSobaSel}
                disabled={!smestajSel || fieldsDisabled}
              >
                <SelectTrigger id="pm-soba" className="w-full">
                  <SelectValue placeholder={smestajSel ? "Izaberite sobu" : "Prvo izaberite smeštaj"} />
                </SelectTrigger>
                <SelectContent>
                  {sobeFiltrirane.map((b) => (
                    <SelectItem key={b.id} value={String(b.id)}>
                      {formatSobaLabel(b.broj_sobe, b.tip)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {smestajSel && sobeFiltrirane.length === 0 && (
                <p className="text-xs text-muted-foreground">Izabrani smeštaj nema definisane sobe.</p>
              )}
            </div>

            {/* Datumi — od/do upareno u obe kolone, isti red mreže */}
            <div className="grid min-w-0 grid-cols-2 gap-2">
              <TrenutnoPolje label="Datum od" value={detail?.datumod || ""} />
              <TrenutnoPolje label="Datum do" value={detail?.datumdo || ""} />
            </div>
            <div className="grid min-w-0 grid-cols-2 gap-2">
              <DatumPicker
                id="pm-od"
                label="Datum od"
                value={datumOd}
                allowed={dozvoljeniPoceci}
                onSelect={onOdIzabran}
                disabled={fieldsDisabled || dozvoljeniPoceci.size === 0}
                placeholder="Početak perioda"
              />
              <DatumPicker
                id="pm-do"
                label="Datum do"
                value={datumDo}
                allowed={dozvoljeniKrajevi}
                onSelect={setDatumDo}
                disabled={fieldsDisabled || !datumOd || dozvoljeniKrajevi.size === 0}
                placeholder="Kraj perioda"
              />
            </div>

            {/* Objašnjenje / upozorenje za grupe perioda */}
            <p className={cn(
              "-mt-1 text-xs md:col-span-2",
              nemaPerioda ? "text-amber-600 dark:text-amber-500" : "text-muted-foreground",
            )}>
              {hintZaDatume}
            </p>
          </div>
        )}

        <DialogFooter className="sm:justify-between gap-2 border-t pt-4">
          <Button variant="outline" onClick={handleNazad} disabled={saving}>
            <ArrowLeft className="w-4 h-4 mr-2" />Nazad
          </Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving
              ? <Loader2 className="w-4 h-4 mr-2 animate-spin" aria-hidden />
              : <Check className="w-4 h-4 mr-2" aria-hidden />}
            {saving ? "Čuvanje…" : "Potvrdi"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
