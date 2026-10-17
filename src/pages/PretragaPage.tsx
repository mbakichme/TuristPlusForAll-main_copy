import { useState, useEffect, useMemo } from "react";
import type { Mesto, PeriodGrupa, PeriodDatum } from "../types";
import { apiFetch } from "../lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue
} from "@/components/ui/select";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Loader2, Search, MapPin, Bus, Car, CalendarDays, Users, Plus, Minus,
  ChevronLeft, ChevronRight, BedDouble, Hotel
} from "lucide-react";
import { toast } from "sonner";

interface SlobodnaSoba {
  id: number; broj_sobe: string; tip: string; opis: string; opis_dodatno: string;
}
interface SlobodniSmestaj {
  smestaj_id: number; smestaj_naziv: string; sobe: SlobodnaSoba[];
}
/** Jedan termin (od Grupe termina) sa raspoloživim smeštajem */
interface SlobodanTermin {
  datum_od: string; datum_do: string; nocenja: number; smestaji: SlobodniSmestaj[];
}

/** DD.MM.YYYY → Date */
function pDate(s: string): Date {
  const [d, m, y] = s.split(".").map(Number);
  return new Date(y, m - 1, d);
}

/** Ikona unutar Select polja */
function SelIcon({ icon: Icon }: { icon: React.ElementType }) {
  return <Icon className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />;
}

// Privremena fiksna cena sobe — računanje se definiše kasnije
const CENA_PLACEHOLDER = 500;

/** "1 odrasao / 2 odrasla / 5 odraslih" */
function odrasliLabel(n: number): string {
  if (n === 1) return "1 odrasao";
  const m10 = n % 10, m100 = n % 100;
  if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return `${n} odrasla`;
  return `${n} odraslih`;
}

/** "1 dete / 2 dece" */
function decaLabel(n: number): string {
  return n === 1 ? "1 dete" : `${n} dece`;
}

/** "1 godina / 3 godine / 5 godina" */
function godinaLabel(n: number): string {
  if (n === 1) return "1 godina";
  const m10 = n % 10, m100 = n % 100;
  if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return `${n} godine`;
  return `${n} godina`;
}

/** Red sa − / + koracima unutar Popover-a Putnici */
function StepperRow({ label, subtitle, value, onDec, onInc, decDisabled, incDisabled }: {
  label: string; subtitle?: string; value: number;
  onDec: () => void; onInc: () => void; decDisabled: boolean; incDisabled: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-3 py-1">
      <div className="min-w-0">
        <div className="text-sm font-semibold">{label}</div>
        {subtitle && <div className="text-xs text-muted-foreground">{subtitle}</div>}
      </div>
      <div className="flex items-center gap-2.5 shrink-0">
        <button
          type="button" onClick={onDec} disabled={decDisabled} aria-label="Manje"
          className="h-9 w-9 rounded-full border border-border flex items-center justify-center text-muted-foreground hover:bg-muted transition-colors disabled:opacity-40 disabled:hover:bg-transparent"
        >
          <Minus className="w-4 h-4" />
        </button>
        <span className="w-4 text-center text-sm font-semibold tabular-nums">{value}</span>
        <button
          type="button" onClick={onInc} disabled={incDisabled} aria-label="Više"
          className="h-9 w-9 rounded-full border border-primary text-primary flex items-center justify-center hover:bg-primary hover:text-primary-foreground transition-colors disabled:opacity-40"
        >
          <Plus className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}

const MESECI = ["Januar", "Februar", "Mart", "April", "Maj", "Jun", "Jul", "Avgust", "Septembar", "Oktobar", "Novembar", "Decembar"];
const DANI_U_NED = ["Pon", "Uto", "Sre", "Čet", "Pet", "Sub", "Ned"];

/** Ključ dana (YYYY-M-D) za poređenje datuma */
function keyOf(d: Date): string {
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

/** "1 noćenje / 2 noćenja / 5 noćenja" */
function nocenjaLabel(n: number): string {
  if (n % 10 === 1 && n % 100 !== 11) return `${n} noćenje`;
  return `${n} noćenja`;
}

/** Mini kalendar (ponedeljak-first) — klikabilni su samo počeci perioda */
function MiniKalendar({ view, onView, odSet, selectedKey, onPick }: {
  view: { y: number; m: number };
  onView: (v: { y: number; m: number }) => void;
  odSet: Set<string>;
  selectedKey: string | null;
  onPick: (d: Date) => void;
}) {
  const firstIdx = (new Date(view.y, view.m, 1).getDay() + 6) % 7;
  const daysInMonth = new Date(view.y, view.m + 1, 0).getDate();
  const cells: (Date | null)[] = [
    ...Array.from({ length: firstIdx }, () => null as Date | null),
    ...Array.from({ length: daysInMonth }, (_, i) => new Date(view.y, view.m, i + 1)),
  ];
  while (cells.length % 7 !== 0) cells.push(null);
  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <button
          type="button" aria-label="Prethodni mesec"
          onClick={() => onView(view.m === 0 ? { y: view.y - 1, m: 11 } : { y: view.y, m: view.m - 1 })}
          className="h-8 w-8 rounded-md flex items-center justify-center text-muted-foreground hover:bg-muted transition-colors"
        >
          <ChevronLeft className="w-4 h-4" />
        </button>
        <div className="text-sm font-semibold">{MESECI[view.m]} {view.y}</div>
        <button
          type="button" aria-label="Sledeći mesec"
          onClick={() => onView(view.m === 11 ? { y: view.y + 1, m: 0 } : { y: view.y, m: view.m + 1 })}
          className="h-8 w-8 rounded-md flex items-center justify-center text-muted-foreground hover:bg-muted transition-colors"
        >
          <ChevronRight className="w-4 h-4" />
        </button>
      </div>
      <div className="grid grid-cols-7 mb-1">
        {DANI_U_NED.map((d) => (
          <div key={d} className="h-7 flex items-center justify-center text-[11px] font-medium text-muted-foreground">
            {d}
          </div>
        ))}
      </div>
      <div className="grid grid-cols-7 gap-y-0.5">
        {cells.map((d, i) => {
          if (!d) return <div key={`e-${i}`} />;
          const k = keyOf(d);
          const selectable = odSet.has(k);
          const selected = selectedKey === k;
          return (
            <button
              key={k} type="button" disabled={!selectable} onClick={() => onPick(d)}
              className={cn(
                "h-8 w-8 mx-auto rounded-md text-sm flex items-center justify-center transition-colors",
                selected
                  ? "bg-primary text-primary-foreground font-semibold"
                  : selectable
                    ? "text-foreground font-medium hover:bg-muted"
                    : "text-muted-foreground/50 cursor-default"
              )}
            >
              {d.getDate()}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export default function PretragaPage() {
  const [mesta, setMesta] = useState<Mesto[]>([]);
  const [grupe, setGrupe] = useState<PeriodGrupa[]>([]);
  const [initialLoading, setInitialLoading] = useState(true);

  const [mestoId, setMestoId] = useState("");
  const [od, setOd] = useState("");
  const [prevoz, setPrevoz] = useState("Autobuski prevoz");
  const [odrasli, setOdrasli] = useState(2);
  const [deca, setDeca] = useState(0);
  const [godineDeca, setGodineDeca] = useState<number[]>([]);
  const [putniciOpen, setPutniciOpen] = useState(false);
  const [draft, setDraft] = useState({ odrasli: 2, deca: 0, godine: [] as number[] });
  const [kalendarOpen, setKalendarOpen] = useState(false);
  const [view, setView] = useState({ y: new Date().getFullYear(), m: new Date().getMonth() });

  const [results, setResults] = useState<SlobodanTermin[] | null>(null);
  const [info, setInfo] = useState<{ od: string; mesto: string } | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    Promise.all([
      apiFetch<Mesto[]>("/mesto"),
      apiFetch<PeriodGrupa[]>("/period-grupa"),
    ])
      .then(([m, g]) => { setMesta(m); setGrupe(g); })
      .catch(() => toast.error("Greška pri učitavanju podataka"))
      .finally(() => setInitialLoading(false));
  }, []);

  const selMesto = mesta.find((m) => String(m.id) === mestoId);
  // Periodi SVIH grupa perioda izabranog mesta (bez duplikata, hronološki)
  const periodi = useMemo(() => {
    if (!selMesto?.grupe?.length) return [];
    const vidjeno = new Set<string>();
    const sve: PeriodDatum[] = [];
    for (const g of grupe) {
      if (!selMesto.grupe.includes(g.id)) continue;
      for (const d of g.datumi ?? []) {
        const k = `${d.datum_od}|${d.datum_do}`;
        if (vidjeno.has(k)) continue;
        vidjeno.add(k);
        sve.push(d);
      }
    }
    return sve.sort((a, b) => pDate(a.datum_od).getTime() - pDate(b.datum_od).getTime());
  }, [selMesto, grupe]);

  // Datum do: više se NE bira — pretraga ide na SVE termine koji počinju na
  // izabrani "datum od" (grupe perioda mesta); rezultati su grupisani po terminu

  // Počeci perioda koji su klikabilni u kalendaru
  const odSet = useMemo(
    () => new Set(periodi.map((p) => keyOf(pDate(p.datum_od)))),
    [periodi]
  );

  function resetRezultate() {
    setResults(null);
    setInfo(null);
  }

  function onOdChange(v: string) {
    setOd(v);
    resetRezultate();
  }

  function onKalendarOpenChange(o: boolean) {
    setKalendarOpen(o);
    if (o) {
      const base = od ? pDate(od) : periodi.length > 0 ? pDate(periodi[0].datum_od) : new Date();
      setView({ y: base.getFullYear(), m: base.getMonth() });
    }
  }

  function izaberiDan(d: Date) {
    const key = `${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")}.${d.getFullYear()}`;
    const p = periodi.find((x) => x.datum_od === key);
    if (p) {
      onOdChange(p.datum_od);
      setKalendarOpen(false); // nema više izbora trajanja — tražimo sve termine odmah
    }
  }

  function onMestoChange(v: string) {
    setMestoId(v);
    setOd("");
    resetRezultate();
  }

  const MAX_ODRASLI = 8;
  const MAX_DECA = 6;

  function onPutniciOpenChange(o: boolean) {
    setPutniciOpen(o);
    if (o) setDraft({ odrasli, deca, godine: [...godineDeca] });
  }

  function stepDraftOdrasli(d: number) {
    setDraft((p) => ({ ...p, odrasli: Math.min(MAX_ODRASLI, Math.max(1, p.odrasli + d)) }));
  }

  function stepDraftDeca(d: number) {
    setDraft((p) => {
      const n = Math.min(MAX_DECA, Math.max(0, p.deca + d));
      const godine = p.godine.slice(0, n);
      while (godine.length < n) godine.push(6);
      return { ...p, deca: n, godine };
    });
  }

  function setDraftGodina(i: number, v: number) {
    setDraft((p) => ({ ...p, godine: p.godine.map((g, j) => (j === i ? v : g)) }));
  }

  function primeniPutnike() {
    setOdrasli(draft.odrasli);
    setDeca(draft.deca);
    setGodineDeca([...draft.godine]);
    setPutniciOpen(false);
    resetRezultate();
  }

  const mozePretraga = !!(mestoId && od && prevoz && selMesto?.grupe?.length);

  function pretrazi() {
    if (!mozePretraga || !selMesto?.grupe?.length) {
      toast.error("Popunite mesto, tip prevoza i datum polaska");
      return;
    }
    setLoading(true);
    apiFetch<SlobodanTermin[]>(
      `/slobodne-sobe?mesto_id=${mestoId}&datum_od=${encodeURIComponent(od)}`
    )
      .then((r) => {
        setResults(r);
        setInfo({ od, mesto: selMesto.naziv });
      })
      .catch(() => toast.error("Greška pri pretrazi"))
      .finally(() => setLoading(false));
  }

  return (
    <div className="p-6 space-y-4">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Search className="w-6 h-6" />Pretraga
        </h1>
        <p className="text-muted-foreground text-sm">Pronađite slobodne kapacitete po mestu i periodu</p>
      </div>

      {/* Forma za pretragu */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <BedDouble className="w-5 h-5 text-primary" />
            Pretraga slobodnih kapaciteta
          </CardTitle>
          <CardDescription>Izaberite mesto, datum polaska i podatke o putnicima — pretražuju se svi termini koji počinju na izabrani datum</CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="grid gap-4 grid-cols-1 md:grid-cols-4">
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Izaberite mesto</Label>
              <div className="relative">
                <SelIcon icon={MapPin} />
                <Select value={mestoId} onValueChange={onMestoChange} disabled={initialLoading}>
                  <SelectTrigger className="pl-9 w-full">
                    <SelectValue placeholder={initialLoading ? "Učitavanje..." : "Izaberite mesto"} />
                  </SelectTrigger>
                  <SelectContent>
                    {mesta.map((m) => (
                      <SelectItem key={m.id} value={String(m.id)}>{m.naziv}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Izaberite tip prevoza</Label>
              <div className="relative">
                <SelIcon icon={prevoz === "Sopstveni prevoz" ? Car : Bus} />
                <Select value={prevoz} onValueChange={setPrevoz}>
                  <SelectTrigger className="pl-9 w-full">
                    <SelectValue placeholder="Izaberite tip prevoza" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="Autobuski prevoz">Autobuski prevoz</SelectItem>
                    <SelectItem value="Sopstveni prevoz">Sopstveni prevoz</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Datum od</Label>
              <div className="relative">
                <SelIcon icon={CalendarDays} />
                <Popover open={kalendarOpen} onOpenChange={onKalendarOpenChange}>
                  <PopoverTrigger asChild>
                    <Button
                      variant="outline"
                      className="pl-9 w-full justify-start font-normal"
                      disabled={!mestoId || periodi.length === 0}
                    >
                      {od
                        ? <span>{od}</span>
                        : <span className="text-muted-foreground">Izaberite datum polaska</span>}
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent align="start" className="w-80 p-4 space-y-3">
                    <MiniKalendar
                      view={view}
                      onView={setView}
                      odSet={odSet}
                      selectedKey={od ? keyOf(pDate(od)) : null}
                      onPick={izaberiDan}
                    />
                  </PopoverContent>
                </Popover>
              </div>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Putnici</Label>
              <div className="relative">
                <SelIcon icon={Users} />
                <Popover open={putniciOpen} onOpenChange={onPutniciOpenChange}>
                  <PopoverTrigger asChild>
                    <Button variant="outline" className="pl-9 w-full justify-start font-normal">
                      {odrasliLabel(odrasli)}, {decaLabel(deca)}
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent align="start" className="w-80 space-y-4">
                    <StepperRow
                      label="Odrasli"
                      value={draft.odrasli}
                      onDec={() => stepDraftOdrasli(-1)}
                      onInc={() => stepDraftOdrasli(1)}
                      decDisabled={draft.odrasli <= 1}
                      incDisabled={draft.odrasli >= MAX_ODRASLI}
                    />
                    <div className="border-t" />
                    <StepperRow
                      label="Deca"
                      subtitle="Uzrasta od 0 do 17,99 godina"
                      value={draft.deca}
                      onDec={() => stepDraftDeca(-1)}
                      onInc={() => stepDraftDeca(1)}
                      decDisabled={draft.deca <= 0}
                      incDisabled={draft.deca >= MAX_DECA}
                    />
                    {draft.deca > 0 && (
                      <div className="space-y-2">
                        <div className="text-sm font-semibold leading-snug">
                          Molimo da unesete broj godina dece u času boravka
                        </div>
                        <div className="grid grid-cols-2 gap-2">
                          {draft.godine.map((g, i) => (
                            <Select
                              key={i}
                              value={String(g)}
                              onValueChange={(v) => setDraftGodina(i, Number(v))}
                            >
                              <SelectTrigger className="w-full bg-muted/50">
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent className="max-h-56">
                                {Array.from({ length: 18 }).map((_, n) => (
                                  <SelectItem key={n} value={String(n)}>{godinaLabel(n)}</SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          ))}
                        </div>
                      </div>
                    )}
                    <Button onClick={primeniPutnike} className="w-full">Primeni</Button>
                  </PopoverContent>
                </Popover>
              </div>
            </div>
          </div>

          <Button onClick={pretrazi} disabled={loading || !mozePretraga} className="w-full h-12 text-base">
            {loading ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Search className="w-4 h-4 mr-2" />}
            Pretraži
          </Button>
        </CardContent>
      </Card>

      {/* Rezultati pretrage — grupisani po terminu */}
      {results && info && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <BedDouble className="w-5 h-5 text-primary" />
              Slobodni kapaciteti
            </CardTitle>
            <CardDescription>
              Polazak {info.od} · {info.mesto} · Odrasli: {odrasli}
              {deca > 0 ? ` · Deca: ${deca}` : ""}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            {results.length === 0 ? (
              <div className="py-10 text-center text-sm text-muted-foreground">
                Nema slobodnih kapaciteta ni za jedan termin sa izabranim polaskom.
              </div>
            ) : (
              results.map((t) => (
                <div key={`${t.datum_od}-${t.datum_do}`} className="space-y-2">
                  {/* Naslov termina */}
                  <div className="flex items-center gap-2 rounded-md bg-primary/10 px-3 py-2">
                    <CalendarDays className="w-4 h-4 text-primary shrink-0" />
                    <span className="text-sm font-bold text-primary">
                      {t.datum_od} – {t.datum_do}
                    </span>
                    <span className="text-xs font-medium text-primary/80">
                      ({nocenjaLabel(t.nocenja)})
                    </span>
                  </div>
                  {t.smestaji.map((g) => (
                    <div key={`${t.datum_od}-${t.datum_do}-${g.smestaj_id}`} className="space-y-2 pl-3">
                      <h3 className="text-sm font-semibold flex items-center gap-2">
                        <Hotel className="w-4 h-4 text-primary" />
                        {g.smestaj_naziv}
                        <span className="text-xs font-normal text-muted-foreground">({g.sobe.length} slobodno)</span>
                      </h3>
                      <div className="grid gap-2 grid-cols-1 md:grid-cols-3">
                        {g.sobe.map((s) => (
                          <div
                            key={s.id}
                            className="flex items-center justify-between gap-3 rounded-md border p-3 hover:bg-muted/40 transition-colors"
                          >
                            <div className="min-w-0">
                              <div className="text-sm font-medium truncate">
                                Soba: {s.broj_sobe}
                                {s.tip ? ` (${s.tip})` : ""}
                                {s.opis ? ` ${s.opis}` : ""}
                              </div>
                              {s.opis_dodatno && (
                                <div className="text-xs text-muted-foreground truncate">{s.opis_dodatno}</div>
                              )}
                            </div>
                            <div className="flex items-center gap-3 shrink-0">
                              <span className="font-mono font-bold text-xl text-primary whitespace-nowrap">
                                {CENA_PLACEHOLDER} €
                              </span>
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => toast.info("Rezervacija je u pripremi")}
                              >
                                Rezerviši
                              </Button>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              ))
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}