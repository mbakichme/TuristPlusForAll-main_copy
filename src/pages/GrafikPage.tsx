import { useState, useEffect, useMemo, useRef, Fragment } from "react";
import type { CSSProperties, ReactNode, MouseEvent as ReactMouseEvent, RefObject } from "react";
import { createPortal } from "react-dom";
import { useNavigate, useSearchParams } from "react-router-dom";
import type { Mesto, Smestaj, PeriodGrupa, UgovorDetail } from "../types";
import { apiFetch } from "../lib/api";
import { cn } from "@/lib/utils";
import { fmtPutnici } from "@/lib/putnici";
import PromenaSmestajaDialog from "@/components/PromenaSmestajaDialog";
import PretraznaSelect from "@/components/PretraznaSelect";
import { Button } from "@/components/ui/button";
import { PageLoader } from "@/components/PageLoader";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue
} from "@/components/ui/select";
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Loader2, ChartGantt, Printer, ArrowLeft, ExternalLink, ArrowRightLeft, CalendarDays, CalendarCheck2, ClipboardList, Zap, BedDouble } from "lucide-react";
import { toast } from "sonner";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

interface GrafikSoba { id: number; broj_sobe: string; tip: string; opis: string; opis_dodatno: string; }
const GRAFIK_BOJE = {
  zelena: { pozadina: "bg-green-600", tekst: "text-white" },
  plava: { pozadina: "bg-blue-600", tekst: "text-white" },
  crvena: { pozadina: "bg-red-600", tekst: "text-white" },
  zuta: { pozadina: "bg-yellow-400", tekst: "text-black" },
  ljubicasta: { pozadina: "bg-purple-600", tekst: "text-white" },
  narandzasta: { pozadina: "bg-orange-500", tekst: "text-black" },
  crna: { pozadina: "bg-black", tekst: "text-white" },
  roze: { pozadina: "bg-pink-500", tekst: "text-black" },
} as const;
type GrafikBoja = keyof typeof GRAFIK_BOJE;
const stilBoje = (boja?: GrafikBoja) => GRAFIK_BOJE[boja ?? "zelena"] ?? GRAFIK_BOJE.zelena;
interface GrafikUgovor { kljuc: string; soba: string; datum_od: string; datum_do: string; putnik: string; subagent: string; saldo: number; boja?: GrafikBoja; }
interface GrafikPeriod { datum_od: string; datum_do: string; }
interface GrafikCenovnik {
  sobe: { id: number; broj_sobe: string; tip: string; izvor_soba_id: number | null }[];
  cene: { soba_id: number; datum_od: string; datum_do: string; cena: number; blokirano: boolean;
    popusti?: { redni: number; tip_popusta: string | null; tip_placanja: string | null; vrsta: string; umanjenje: number; vazi: boolean }[] }[];
}
interface GrafikData {
  smestaj: { id: number; naziv: string };
  periodi: GrafikPeriod[];
  sobe: GrafikSoba[];
  ugovori: GrafikUgovor[];
  cenovnik: GrafikCenovnik | null;
}

/** DD.MM.YYYY → Date */
function pDate(s: string): Date {
  const [d, m, y] = s.split(".").map(Number);
  return new Date(y, m - 1, d);
}

/** Date → DD.MM.YYYY */
const fmtDatum = (d: Date) =>
  `${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")}.${d.getFullYear()}`;

interface PonudaStavka { naziv: string; cena: string | null; glavna: boolean; blokirano: boolean; popusti: { tip: string; procenat: number | null; iznos: number | null }[]; }
interface PonudaInfo { naslov: string; napomena: string | null; stavke: PonudaStavka[]; }
/** Obračun slobodnog termina (maks. ADL strukture; osnovna već umanjena za sopstveni prevoz). */
interface SlotObracun { adl: number; struktura: string; osnovna: number | null; snizena: number | null; popust: number; napomena: string | null; }
interface SlobodnaSoba { id: number; struktura?: string; cena_osnovna: number | null; nema_cene?: boolean; obracun?: string[]; varijante?: { vazi: boolean; cena_snizena: number | null; tip_placanja?: string | null }[]; }
interface SlobodnaGrupa { smestaj_id: number; sobe: SlobodnaSoba[]; }

/** Način plaćanja → naziv za prikaz (popust po tipu plaćanja). */
const PLACANJE_NAZIV: Record<string, string> = { delimicno: "delimično", u_celosti: "u celosti" };

/** Red cenovnika za sobu: realna soba ili njena virtuelna soba (struktura = `tip`). */
interface CenaOpcija {
  sobaId: number;        // id reda u cenovniku (negativan za virtuelnu)
  izvorId: number;       // stvarna soba (id u tabeli sobe) — ide u polje „Soba“
  broj: string;          // broj reda (npr. 6 ili v6)
  tip: string;           // struktura (npr. 1/3, 1/2)
  virtuelna: boolean;
  glavna: boolean;       // red same sobe
  cena: number | null;   // EUR za najuži period cenovnika koji obuhvata slobodan deo
  blokirano: boolean;
  popusti: { tip: string; procenat: number | null; iznos: number | null }[]; // samo važeći popusti
}

/** Redovi cena za slobodan termin: soba + njene virtuelne sobe iz aktivnog cenovnika.
 *  Period = najuži period cenovnika koji obuhvata slobodan deo. */
function cenaOpcije(sec: GrafikData, soba: GrafikSoba, p: GrafikPeriod):
  { napomena: string | null; period: GrafikPeriod | null; opcije: CenaOpcija[] } {
  const c = sec.cenovnik;
  if (!c) return { napomena: "Nema aktivnog cenovnika", period: null, opcije: [] };
  const od = pDate(p.datum_od).getTime();
  const doo = pDate(p.datum_do).getTime();
  const parovi = new Map<string, GrafikPeriod>();
  for (const x of c.cene) parovi.set(`${x.datum_od}|${x.datum_do}`, { datum_od: x.datum_od, datum_do: x.datum_do });
  let period: GrafikPeriod | null = null;
  let najuzi = Number.POSITIVE_INFINITY;
  for (const q of parovi.values()) {
    const a = pDate(q.datum_od).getTime();
    const b = pDate(q.datum_do).getTime();
    if (a <= od && doo <= b && b - a < najuzi) { period = q; najuzi = b - a; }
  }
  if (!period) return { napomena: "Nema cene za ovaj period", period: null, opcije: [] };
  const per = period;
  const redovi = c.sobe
    .filter((s) => s.id === soba.id || s.izvor_soba_id === soba.id)
    .sort((a, b) => (a.id === soba.id ? -1 : 0) - (b.id === soba.id ? -1 : 0));
  const opcije = redovi.map((s): CenaOpcija => {
    const zapis = c.cene.find((x) => x.soba_id === s.id && x.datum_od === per.datum_od && x.datum_do === per.datum_do);
    return {
      sobaId: s.id,
      izvorId: soba.id,
      broj: s.broj_sobe || "—",
      tip: s.tip || "",
      virtuelna: s.id !== soba.id,
      glavna: s.id === soba.id,
      cena: zapis ? zapis.cena : null,
      blokirano: zapis ? zapis.blokirano : false,
      popusti: (zapis?.popusti ?? []).filter((x) => x.vazi).map((x) => ({
        tip: x.tip_placanja ? (PLACANJE_NAZIV[x.tip_placanja] ?? x.tip_placanja) : (x.tip_popusta ?? "popust"),
        procenat: x.vrsta === "procenat" ? x.umanjenje
          : (zapis && zapis.cena > 0 ? Math.round((x.umanjenje / zapis.cena) * 1000) / 10 : null),
        iznos: x.vrsta === "procenat" ? null : x.umanjenje,
      })),
    };
  });
  return { napomena: null, period, opcije };
}

/** Podaci tooltipa praznog polja: slobodan period + cene (blokirane cene se NE prikazuju). */
function ponudaInfo(sec: GrafikData, soba: GrafikSoba, p: GrafikPeriod): PonudaInfo {
  const naslov = `Soba ${soba.broj_sobe || "—"} · ${p.datum_od} – ${p.datum_do}`;
  const { napomena, opcije } = cenaOpcije(sec, soba, p);
  if (napomena) return { naslov, napomena, stavke: [] };
  const stavke = opcije.map((o) => ({
    naziv: `${o.broj}${o.tip ? ` (${o.tip})` : ""}`,
    cena: o.blokirano || o.cena == null ? null : `${o.cena.toLocaleString("sr-RS", { maximumFractionDigits: 2 })} €`,
    glavna: o.glavna,
    blokirano: o.blokirano,
    popusti: o.blokirano ? [] : o.popusti,
  }));
  return { naslov, napomena: null, stavke };
}


const fmtEur = (v: number | null | undefined) =>
  v == null ? "—" : `${v.toLocaleString("sr-RS", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`;

function PfRow({ label, value, mono }: { label: string; value: ReactNode; mono?: boolean }) {
  return (
    <div className="flex justify-between gap-4 py-1.5 border-b last:border-0">
      <span className="text-muted-foreground text-xs shrink-0">{label}</span>
      <span className={cn("text-sm font-medium text-right", mono && "font-mono")}>{value}</span>
    </div>
  );
}

/** Broj ugovora na traci: tooltip ostaje otvoren dok kursor ide sa broja na sam tooltip. */
function UgovorBroj({ u, broj, className, style, onClick }: {
  u: GrafikUgovor;
  broj: string;
  className: string;
  style: CSSProperties;
  onClick: () => void;
}) {
  const [otvoren, setOtvoren] = useState(false);
  const tajmer = useRef<number | null>(null);

  const otkazi = () => {
    if (tajmer.current !== null) {
      window.clearTimeout(tajmer.current);
      tajmer.current = null;
    }
  };
  const otvori = () => {
    otkazi();
    setOtvoren(true);
  };
  const zakazi = () => {
    otkazi();
    tajmer.current = window.setTimeout(() => setOtvoren(false), 200);
  };
  useEffect(() => () => otkazi(), []);

  return (
    <Tooltip open={otvoren} onOpenChange={() => { /* zatvaranje samo preko tajmera */ }}>
      <TooltipTrigger asChild>
        <span className={className} style={style} onClick={onClick} onPointerEnter={otvori} onPointerLeave={zakazi}>
          {broj}
        </span>
      </TooltipTrigger>
      <TooltipContent
        side="top"
        className="bg-slate-900/95 text-white border-slate-700 shadow-lg"
        onPointerEnter={otvori}
        onPointerLeave={zakazi}
      >
        <UgovorTooltip u={u} />
      </TooltipContent>
    </Tooltip>
  );
}

/** Podaci o ugovoru u lebdećem prikazu iznad broja u tabeli grafika. */
function UgovorTooltip({ u }: { u: GrafikUgovor }) {
  return (
    <div className="min-w-48 space-y-1">
      <p className="font-mono text-[11px] font-semibold text-primary-foreground/80">{u.kljuc}</p>
      <p className="text-sm font-semibold">{u.putnik?.trim() || "Nosilac nije upisan"}</p>
      <p className="text-xs text-primary-foreground/80">{u.datum_od} – {u.datum_do}</p>
      {u.subagent?.trim() ? (
        <p className="text-xs text-primary-foreground/80">Subagent: {u.subagent.trim()}</p>
      ) : null}
      <p className="text-xs text-primary-foreground/80">Saldo: <span className="font-mono font-semibold text-primary-foreground">{fmtEur(u.saldo)}</span></p>
    </div>
  );
}

/** Izbor cene za slobodan termin u popupu: soba + virtuelne sobe, jedna cena (radio).
 *  Blokirane i cene bez vrednosti su onemogućene. */
function SlotCene({ sec, soba, p, izabrana, onIzbor }: {
  sec: GrafikData; soba: GrafikSoba; p: GrafikPeriod;
  izabrana: CenaOpcija | null; onIzbor: (o: CenaOpcija) => void;
}) {
  const { napomena, opcije } = useMemo(() => cenaOpcije(sec, soba, p), [sec, soba, p]);
  return (
    <div className="space-y-2">
      <p className="text-xs font-medium text-muted-foreground">Cena za izabrani termin</p>
      {napomena ? (
        <p className="rounded-xl border border-dashed border-border p-3 text-xs text-muted-foreground">{napomena}</p>
      ) : (
        <div role="radiogroup" aria-label="Cena sobe" className="grid gap-2">
          {opcije.map((o) => {
            const izabran = izabrana?.sobaId === o.sobaId;
            const nedostupna = o.blokirano || o.cena == null;
            return (
              <button
                key={o.sobaId}
                type="button"
                role="radio"
                aria-checked={izabran}
                aria-label={`Soba ${o.broj}${o.tip ? ` ${o.tip}` : ""} — ${o.blokirano ? "blokirano" : o.cena == null ? "nema cene" : fmtEur(o.cena)}`}
                disabled={nedostupna}
                onClick={() => onIzbor(o)}
                className={cn(
                  "flex w-full items-center gap-3 rounded-xl border px-3 py-2 text-left transition-colors",
                  izabran ? "border-green-600 bg-green-600/10" : "border-border bg-card hover:bg-muted/50",
                  o.blokirano && "border-red-300 bg-red-50 text-red-700 hover:bg-red-50",
                  nedostupna && "cursor-not-allowed opacity-80",
                )}
              >
                <span className={cn(
                  "flex h-4 w-4 shrink-0 items-center justify-center rounded-full border",
                  izabran ? "border-green-600 bg-green-600" : "border-muted-foreground/40",
                )}>
                  {izabran ? <span className="h-1.5 w-1.5 rounded-full bg-white" /> : null}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">
                    Soba {o.broj}{o.tip ? ` · ${o.tip}` : ""}
                  </span>
                  {o.virtuelna ? (
                    <span className="block text-[11px] text-muted-foreground">virtuelna · stvarna soba {soba.broj_sobe || "—"}</span>
                  ) : null}
                </span>
                <span className="shrink-0 text-right">
                  {o.blokirano ? (
                    <span className="text-xs font-semibold">blokirano</span>
                  ) : o.cena == null ? (
                    <span className="text-xs text-muted-foreground">nema cene</span>
                  ) : (
                    <span className="font-mono text-sm font-semibold tabular-nums">{fmtEur(o.cena)}</span>
                  )}
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

/** Lebdeći prikaz cene praznog polja — renderuje se u body (portal), prati miša
 *  i nestaje čim kursor napusti polje (onMouseLeave na ćeliji). */
function PonudaTooltip({ info, tipRef, pos }: {
  info: PonudaInfo; tipRef: RefObject<HTMLDivElement | null>; pos: { x: number; y: number };
}) {
  return createPortal(
    <div
      ref={tipRef}
      className="pointer-events-none fixed left-0 top-0 z-[100] w-64 overflow-hidden rounded-xl border border-border bg-card text-card-foreground shadow-xl"
      style={{ transform: `translate(${pos.x}px, ${pos.y}px)` }}
    >
      <div className="flex items-center gap-2 border-b border-border bg-emerald-50 px-3 py-2">
        <span className="h-2 w-2 shrink-0 rounded-full bg-emerald-500" />
        <div className="min-w-0">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-emerald-700">Slobodno</p>
          <p className="truncate text-xs font-medium">{info.naslov}</p>
        </div>
      </div>
      {info.napomena ? (
        <p className="px-3 py-2.5 text-xs text-muted-foreground">{info.napomena}</p>
      ) : (
        <div className="px-3 py-2">
          <p className="pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Cena</p>
          <ul className="space-y-1">
            {info.stavke.map((s, i) => (
              <li key={i} className={cn("flex items-baseline justify-between gap-3 text-xs", !s.glavna && "text-muted-foreground")}>
                <span className="min-w-0">
                  <span className={cn("block truncate", s.glavna && "font-semibold text-foreground")}>
                    {s.naziv}
                  </span>
                  {s.popusti.map((p, j) => (
                    <span key={j} className="block truncate text-[10px] font-medium text-emerald-700">
                      −{p.procenat != null ? `${p.procenat.toLocaleString("sr-RS", { maximumFractionDigits: 1 })}%` : ""}
                      {p.procenat != null && p.iznos != null ? " · " : ""}
                      {p.iznos != null ? `${p.iznos.toLocaleString("sr-RS", { maximumFractionDigits: 2 })} €` : ""}
                      {` ${p.tip}`}
                    </span>
                  ))}
                </span>
                <span className={cn("shrink-0 font-mono tabular-nums", s.blokirano ? "text-[11px] font-sans font-medium text-red-600" : s.glavna ? "text-sm font-semibold text-foreground" : "text-xs")}>
                  {s.blokirano ? "blokirano" : (s.cena ?? "nema cene")}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>,
    document.body
  );
}

/** Geometrija grafika za jedan smeštaj — JEDINSTVENA vremenska osa.
 *  Kolone se gradi od SVIH unikatnih granica perioda (počeci + krajevi), pa se
 *  preklapajući periodi (npr. 20.05–27.05 i 20.05–30.05) crtaju na zajedničkoj osi:
 *  20.05 je zajednička granica, a 27.05 i 30.05 odvojene. Širine kolona su
 *  proporcionalne trajanju, a pojasevi/beline su procenti te iste ose. */
function grafikGeometrija(data: GrafikData) {
  // 1) granice ose = unikatni datumi svih početaka i krajeva perioda, hronološki
  const mapa = new Map<number, Date>();
  for (const x of data.periodi) {
    const a = pDate(x.datum_od), b = pDate(x.datum_do);
    mapa.set(a.getTime(), a);
    mapa.set(b.getTime(), b);
  }
  const granice = [...mapa.keys()].sort((x, y) => x - y).map((t) => mapa.get(t)!);
  const t0 = granice.length ? granice[0].getTime() : 0;
  const t1 = granice.length ? granice[granice.length - 1].getTime() : 0;
  const total = t1 - t0;
  const pct = (d: Date) => (total > 0 ? ((d.getTime() - t0) / total) * 100 : 0);
  // kolone = intervali između susednih granica (klik na slobodnu kolonu)
  const kolone = granice.slice(0, -1).map((od, i) => ({
    datum_od: fmtDatum(od),
    datum_do: fmtDatum(granice[i + 1]),
    leftPct: pct(od),
    widthPct: pct(granice[i + 1]) - pct(od),
  }));
  // unutrašnje linije — granice između kolona (bez prve i poslednje ivice ose)
  const linije = granice.slice(1, -1).map(pct);
  // 2) pojasevi + zauzeća po sobi — JEDAN pojas po ugovoru na celoj osi,
  //    sužen na stvarne datume (1px bela ivica na svakom stvarnom početku/kraju)
  const spans = new Map<string, { kljuc: string; leftPct: number; rightPct: number }[]>();
  const segs = new Map<string, { od: Date; doo: Date }[]>();
  for (const u of data.ugovori) {
    const od = pDate(u.datum_od), doo = pDate(u.datum_do);
    if (total <= 0 || doo.getTime() <= t0 || od.getTime() >= t1) continue;
    const key = (u.soba || "").trim();
    const leftPct = Math.max(0, pct(od));
    const rightPct = Math.max(0, 100 - pct(doo));
    const arr = spans.get(key);
    if (arr) arr.push({ kljuc: u.kljuc, leftPct, rightPct });
    else spans.set(key, [{ kljuc: u.kljuc, leftPct, rightPct }]);
    const segOd = od.getTime() < t0 ? new Date(t0) : od;
    const segDoo = doo.getTime() > t1 ? new Date(t1) : doo;
    const z = segs.get(key);
    if (z) z.push({ od: segOd, doo: segDoo });
    else segs.set(key, [{ od: segOd, doo: segDoo }]);
  }
  // 3) beline = slobodni intervali između zauzeća na osi (klik šalje TAČNE datume)
  const gaps = new Map<string, { leftPct: number; widthPct: number; od: string; doo: string }[]>();
  for (const [key, ss] of segs) {
    const arr2: { leftPct: number; widthPct: number; od: string; doo: string }[] = [];
    let cursor = new Date(t0);
    for (const s of [...ss].sort((x, y) => x.od.getTime() - y.od.getTime())) {
      if (s.od.getTime() > cursor.getTime() + 1000) {
        arr2.push({ leftPct: pct(cursor), widthPct: pct(s.od) - pct(cursor), od: fmtDatum(cursor), doo: fmtDatum(s.od) });
      }
      if (s.doo.getTime() > cursor.getTime()) cursor = s.doo;
    }
    if (t1 > cursor.getTime() + 1000) {
      arr2.push({ leftPct: pct(cursor), widthPct: 100 - pct(cursor), od: fmtDatum(cursor), doo: fmtDatum(new Date(t1)) });
    }
    if (arr2.length > 0) gaps.set(key, arr2);
  }
  return { kolone, linije, spans, gaps, t0, t1 };
}

/** Slobodni pod-intervali [od, doo] nakon odbijanja zauzeća sobe (preklapanja). */
function slobodniIntervali(od: Date, doo: Date, zauzeca: { od: Date; doo: Date }[]): { od: Date; doo: Date }[] {
  let rez: { od: Date; doo: Date }[] = [{ od, doo }];
  for (const z of zauzeca) {
    const sledeci: { od: Date; doo: Date }[] = [];
    for (const r of rez) {
      if (z.doo.getTime() <= r.od.getTime() || z.od.getTime() >= r.doo.getTime()) {
        sledeci.push(r);
        continue;
      }
      if (z.od.getTime() > r.od.getTime()) sledeci.push({ od: r.od, doo: z.od });
      if (z.doo.getTime() < r.doo.getTime()) sledeci.push({ od: z.doo, doo: r.doo });
    }
    rez = sledeci;
  }
  return rez.filter((r) => r.doo.getTime() > r.od.getTime());
}

/** Ponuda za klik na slobodan termin: period Grupe na poziciji klika (prefereira
 *  se najuži period koji sadrži i celu kliknutu zonu), sužen na SLOBODAN deo
 *  sobe. Primeri: klik u zoni 27.05–30.05 (soba slobodna) → period 20.05–30.05;
 *  DIMITRA 14.07–20.07 sa rezervacijom 14.07–17.07 → slobodni deo 17.07–20.07;
 *  belina 04.06–02.10 kroz više smena, klik u smeni 04.06–14.06 → 04.06–14.06.
 *  Klik van svih perioda vraća kliknute datume neizmenjene. */
function ponudaZaKlik(
  periodi: GrafikPeriod[],
  zauzeca: { od: Date; doo: Date }[],
  zod: Date,
  zdo: Date,
  klik: Date,
): GrafikPeriod {
  const tk = klik.getTime();
  const uZoni = periodi.filter((p) => {
    const a = pDate(p.datum_od).getTime();
    const b = pDate(p.datum_do).getTime();
    return a <= tk && tk <= b;
  });
  const celeZone = uZoni.filter((p) => {
    const a = pDate(p.datum_od).getTime();
    const b = pDate(p.datum_do).getTime();
    return a <= zod.getTime() && zdo.getTime() <= b;
  });
  const kandidati = celeZone.length > 0 ? celeZone : uZoni;
  let najbolji: GrafikPeriod | null = null;
  let najuzi = Number.POSITIVE_INFINITY;
  for (const p of kandidati) {
    const span = pDate(p.datum_do).getTime() - pDate(p.datum_od).getTime();
    if (span < najuzi) {
      najbolji = p;
      najuzi = span;
    }
  }
  if (!najbolji) return { datum_od: fmtDatum(zod), datum_do: fmtDatum(zdo) };
  const slobodni = slobodniIntervali(pDate(najbolji.datum_od), pDate(najbolji.datum_do), zauzeca);
  if (slobodni.length === 0) return najbolji; // ceo period zauzet — provera na dugmetu obaveštava
  const uKliku = slobodni.find((s) => s.od.getTime() <= tk && tk <= s.doo.getTime());
  const izbor = uKliku ?? slobodni[0];
  return { datum_od: fmtDatum(izbor.od), datum_do: fmtDatum(izbor.doo) };
}

/** DD.MM.YYYY → ISO yyyy-mm-dd */
const isoOdPrikaza = (v: string) => {
  const m = /^(\d{2})\.(\d{2})\.(\d{4})$/.exec(v ?? "");
  return m ? `${m[3]}-${m[2]}-${m[1]}` : "";
};
/** Date → ISO yyyy-mm-dd (lokalno, bez UTC konverzije) */
const isoOdDatuma = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const SATI = Array.from({ length: 24 }, (_, i) => String(i).padStart(2, "0"));
const MESECI = ["januar", "februar", "mart", "april", "maj", "jun", "jul", "avgust", "septembar", "oktobar", "novembar", "decembar"];
const DANI = ["Ned", "Pon", "Uto", "Sre", "Čet", "Pet", "Sub"];
const formattersKalendara = {
  formatCaption: (month: Date) => `${MESECI[month.getMonth()]} ${month.getFullYear()}`,
  formatWeekdayName: (day: Date) => DANI[day.getDay()],
};

function DatumBoravka({ label, value, onChange, smene }: {
  label: string; value: string; onChange: (value: string) => void; smene?: GrafikPeriod[];
}) {
  const [open, setOpen] = useState(false);
  const datum = value ? new Date(`${value}T12:00:00`) : undefined;
  // Datumi smena (početak i kraj perioda grupe) — samo oznaka, ostali datumi ostaju slobodni
  const smeneDatumi = (smene ?? []).flatMap((p) => [pDate(p.datum_od), pDate(p.datum_do)]);
  return (
    <div className="min-w-0 space-y-1.5">
      <Label className="text-xs text-muted-foreground">{label}</Label>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button variant="outline" aria-label={label} className="w-full justify-start gap-2 rounded-lg bg-card px-3 font-normal tabular-nums">
            <CalendarDays className="h-4 w-4 shrink-0 text-muted-foreground" />
            {datum ? fmtDatum(datum) : "dd.mm.yyyy"}
          </Button>
        </PopoverTrigger>
        <PopoverContent align="start" className="w-auto rounded-xl bg-card p-0 shadow-lg">
          <Calendar mode="single" selected={datum} defaultMonth={datum} weekStartsOn={1}
            formatters={formattersKalendara} initialFocus
            modifiers={{ smena: smeneDatumi }}
            modifiersClassNames={{ smena: "bg-blue-500 text-white rounded-md font-semibold" }}
            onSelect={(d) => { if (d) { onChange(isoOdDatuma(d)); setOpen(false); } }} />
        </PopoverContent>
      </Popover>
    </div>
  );
}

/** Tabela grafika za JEDAN smeštaj — redovi su sobe, zeleni pojasevi su ugovori. */
function GrafikTabela({ sec, onRez, onUgovor }: {
  sec: GrafikData;
  onRez: (sec: GrafikData, soba: GrafikSoba, p: GrafikPeriod) => void;
  onUgovor: (kljuc: string) => void;
}) {
  const { kolone, linije, spans, gaps, t0, t1 } = useMemo(() => grafikGeometrija(sec), [sec]);
  const sobeSorted = useMemo(
    () => [...sec.sobe].sort((a, b) =>
      (a.broj_sobe || "").localeCompare(b.broj_sobe || "", "sr", { numeric: true })),
    [sec.sobe]
  );
  // kljuc ugovora → podaci za tooltip (nosilac, period, subagent, saldo)
  const ugovorPoKljucu = useMemo(() => {
    const m = new Map<string, GrafikUgovor>();
    for (const u of sec.ugovori) m.set(u.kljuc, u);
    return m;
  }, [sec.ugovori]);
  // zauzeća po sobi (broj_sobe → Date parovi) — za sužavanje ponude na slobodan deo
  const zauzecaPoSobi = useMemo(() => {
    const m = new Map<string, { od: Date; doo: Date }[]>();
    for (const u of sec.ugovori) {
      const key = (u.soba || "").trim();
      const z = { od: pDate(u.datum_od), doo: pDate(u.datum_do) };
      const arr = m.get(key);
      if (arr) arr.push(z);
      else m.set(key, [z]);
    }
    return m;
  }, [sec.ugovori]);
  // pozicija klika unutar ćelije (td pokriva celu vremensku osu) → datum na osi
  const klikDatum = (e: ReactMouseEvent<HTMLDivElement>) => {
    const td = e.currentTarget.closest("td");
    const rect = (td ?? e.currentTarget).getBoundingClientRect();
    const frac = rect.width > 0 ? Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width)) : 0;
    return new Date(t0 + frac * (t1 - t0));
  };
  // Tooltip cene praznog polja: sadržaj menja samo kad se promeni slobodan period
  // (ključ), a pozicija se ažurira direktno u DOM-u da ne bi bilo re-rendera na svaki pokret.
  const [tip, setTip] = useState<PonudaInfo | null>(null);
  const tipRef = useRef<HTMLDivElement | null>(null);
  const tipPos = useRef({ x: 0, y: 0 });
  const tipKljuc = useRef("");
  const ponudaMove = (e: ReactMouseEvent<HTMLDivElement>, info: PonudaInfo) => {
    const h = 96 + info.stavke.length * 22;
    let x = e.clientX + 16;
    if (x + 256 > window.innerWidth) x = e.clientX - 256 - 8;
    let y = e.clientY + 16;
    if (y + h > window.innerHeight) y = Math.max(8, e.clientY - h - 8);
    tipPos.current = { x, y };
    if (tipRef.current) tipRef.current.style.transform = `translate(${x}px, ${y}px)`;
    const k = `${info.naslov}|${info.napomena ?? ""}|${info.stavke.map((s) => `${s.naziv}=${s.cena}`).join(";")}`;
    if (k !== tipKljuc.current) { tipKljuc.current = k; setTip(info); }
  };
  const ponudaKraj = () => { tipKljuc.current = ""; setTip(null); };
  return (
    <>
    <table className="table-fixed text-[11px]" style={{ width: "100%", minWidth: `${144 + Math.max(kolone.length, 1) * 110}px`, borderCollapse: "separate", borderSpacing: 0 }}>
      <tbody>
        {/* Datumi u VRHU — sticky header: fiksira se na vrh scroll polja dok se skroluje na dole.
            JEDNA kolona sa apsolutno pozicioniranim granicama (unikatni datumi perioda) —
            zajednički počeci se crtaju JEDNOM, a odvojeni krajevi svaki na svojoj granici. */}
        <tr>
          <td className="sticky left-0 top-0 z-50 bg-background border-r border-b-2 border-b-red-600 px-2 py-0.5 w-36 min-w-36" />
          <td className="sticky top-0 z-40 bg-background border-b-2 border-b-red-600 px-1 py-0.5 text-[9px] text-muted-foreground">
            <div className="relative h-4">
              {kolone.map((k, i) => (
                <span key={`d-${i}`} className="absolute top-0.5 whitespace-nowrap" style={{ left: `${k.leftPct}%` }}>
                  {k.datum_od.slice(0, 5)}
                </span>
              ))}
              {kolone.length > 0 && (
                <span className="absolute right-1 top-0.5 whitespace-nowrap">
                  {kolone[kolone.length - 1].datum_do.slice(0, 5)}
                </span>
              )}
            </div>
          </td>
        </tr>
        {sobeSorted.map((soba) => {
          const label = `${soba.broj_sobe || "—"}${soba.tip ? ` (${soba.tip})` : ""}${soba.opis ? ` ${soba.opis}` : ""}`;
          const labelFull = soba.opis_dodatno ? `${label} — ${soba.opis_dodatno}` : label;
          const rkey = (soba.broj_sobe || "").trim();
          const bandovi = spans.get(rkey) || [];
          return (
            <tr key={`r-${soba.id}`}>
              {/* Zelena linija sa brojevima ugovora */}
              <td
                className="sticky left-0 z-[45] bg-background border-r border-b-2 border-b-red-600 px-2 py-0.5 align-top w-36 min-w-36"
                title={labelFull}
              >
                <div className="text-red-600 font-semibold text-[11px] truncate">{label}</div>
                {soba.opis_dodatno ? (
                  <div className="text-red-600/70 text-[9px] leading-tight truncate">{soba.opis_dodatno}</div>
                ) : null}
              </td>
              <td className="relative bg-background border-b-2 border-b-red-600 text-white text-center font-mono font-medium text-[10px] whitespace-nowrap overflow-hidden">
                {/* Klik na slobodnu kolonu — nudi PERIOD Grupe na poziciji klika,
                    sužen na slobodan deo sobe (ponudaZaKlik); vidljivo gde nema
                    belina/pojaseva. Tooltip se računa u letu (onMouseMove) ISTOM
                    logikom kao klik — uvek poklapanje sa popup-om. */}
                {kolone.map((k, i) => {
                  const zod = pDate(k.datum_od);
                  const zdo = pDate(k.datum_do);
                  const zauzeca = zauzecaPoSobi.get(rkey) ?? [];
                  const ponudaU = (klik: Date) => ponudaZaKlik(sec.periodi, zauzeca, zod, zdo, klik);
                  return (
                    <div
                      key={`k-${i}`}
                      className="absolute bottom-[2px] top-[2px] cursor-pointer hover:bg-muted/60"
                      style={{ left: `${k.leftPct}%`, width: `${k.widthPct}%` }}
                      onClick={(e) => onRez(sec, soba, ponudaU(klikDatum(e)))}
                      onMouseMove={(e) => ponudaMove(e, ponudaInfo(sec, soba, ponudaU(klikDatum(e))))}
                      onMouseLeave={ponudaKraj}
                    />
                  );
                })}
                {/* Unutrašnje granice kolona — odvojene ivice preklapajućih perioda */}
                {linije.map((lp, i) => (
                  <div key={`l-${i}`} className="pointer-events-none absolute top-0 bottom-0 w-px bg-gray-400" style={{ left: `${lp}%` }} />
                ))}
                {/* Slobodne beline — klik nudi PERIOD Grupe na poziciji klika,
                    sužen na slobodan deo sobe (belina može protezati kroz više smena) */}
                {(gaps.get(rkey) || []).map((g, gi) => {
                  const zauzeca = zauzecaPoSobi.get(rkey) ?? [];
                  const ponudaU = (klik: Date) => ponudaZaKlik(sec.periodi, zauzeca, pDate(g.od), pDate(g.doo), klik);
                  return (
                    <div
                      key={`g-${gi}`}
                      className="absolute bottom-[2px] top-[2px] z-20 cursor-pointer hover:bg-muted/50"
                      style={{ left: `${g.leftPct}%`, width: `${g.widthPct}%` }}
                      onClick={(e) => onRez(sec, soba, ponudaU(klikDatum(e)))}
                      onMouseMove={(e) => ponudaMove(e, ponudaInfo(sec, soba, ponudaU(klikDatum(e))))}
                      onMouseLeave={ponudaKraj}
                    />
                  );
                })}
                {/* Pojasevi ugovora — jedan pojas po ugovoru na celoj osi, proporcionalno datumima;
                    1px bela linija na svakom stvarnom početku i kraju boravka.
                    Kontejner NE SME hvataiti klikove (prostire se preko celog reda) —
                    pointer-events-none propušta klik do kolona/belina ispod */}
                <div className="pointer-events-none absolute inset-x-0 bottom-[2px] top-[2px]">
                  {bandovi.map((b) => (
                    <div
                      key={b.kljuc}
                      className={cn("grafik-band pointer-events-auto absolute top-1/2 -bottom-0.5 z-10 rounded-[2px] border-l border-l-white/90 border-r border-r-white/90", stilBoje(ugovorPoKljucu.get(b.kljuc)?.boja).pozadina)}
                      style={{ left: `${b.leftPct}%`, right: `${b.rightPct}%` }}
                    />
                  ))}
                </div>
                {/* Brojevi ugovora (bez godine) — jedan po ugovoru; tooltip samo na broju */}
                {bandovi.map((b) => {
                  const ui = ugovorPoKljucu.get(b.kljuc);
                  if (!ui) return null;
                  return (
                    <UgovorBroj
                      key={b.kljuc}
                      u={ui}
                      broj={b.kljuc.split("/")[0]}
                      className={cn("absolute top-1/2 -bottom-0.5 z-30 flex cursor-pointer items-center justify-start pl-1 hover:underline", stilBoje(ui.boja).tekst)}
                      style={{ left: `${b.leftPct}%`, right: `${b.rightPct}%` }}
                      onClick={() => onUgovor(b.kljuc)}
                    />
                  );
                })}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
    {tip ? <PonudaTooltip info={tip} tipRef={tipRef} pos={tipPos.current} /> : null}
    </>
  );
}

export default function GrafikPage() {
  const navigate = useNavigate();
  const [mesta, setMesta] = useState<Mesto[]>([]);
  const [grupe, setGrupe] = useState<PeriodGrupa[]>([]);
  const [smestaji, setSmestaji] = useState<Smestaj[]>([]);
  const [mestoId, setMestoId] = useState("");
  const [grupaId, setGrupaId] = useState("");
  const [smestajId, setSmestajId] = useState("");
  const [data, setData] = useState<GrafikData | null>(null);
  const [sekcije, setSekcije] = useState<GrafikData[]>([]);
  const [loading, setLoading] = useState(false);
  const [initialLoading, setInitialLoading] = useState(true);
  const [ugovorOpen, setUgovorOpen] = useState(false);
  const [ugovorKljuc, setUgovorKljuc] = useState("");
  const [ugovorDetail, setUgovorDetail] = useState<UgovorDetail | null>(null);
  const [ugovorLoading, setUgovorLoading] = useState(false);
  const [promenaOpen, setPromenaOpen] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const ugovorReqRef = useRef(0);
  // Slot popup (slobodan termin → Klasična/Brza) + forma brze rezervacije
  const [slotOtvoren, setSlotOtvoren] = useState(false);
  const [slotCena, setSlotCena] = useState<CenaOpcija | null>(null); // izabrana cena (soba ili virtuelna)
  const [slotSec, setSlotSec] = useState<GrafikData | null>(null);
  const [slotSoba, setSlotSoba] = useState<GrafikSoba | null>(null);
  const [slotPeriod, setSlotPeriod] = useState<GrafikPeriod | null>(null);
  const [slotSubagent, setSlotSubagent] = useState(""); // naziv subagenta (kao aranzman.subagent)
  const [slotPlacanje, setSlotPlacanje] = useState(""); // "" | delimicno | u_celosti → bira popust sobe
  const [slotPrevoz, setSlotPrevoz] = useState("autobuski"); // autobuski | sopstveni → umanjenje cene
  const [subagentiIzbor, setSubagentiIzbor] = useState<{ naziv: string }[]>([]);
  const [subagentiPretraga, setSubagentiPretraga] = useState("");
  const [brzaOtvoren, setBrzaOtvoren] = useState(false);
  const [brzaTip, setBrzaTip] = useState("Predrezervacija"); // "Predrezervacija" | "BLOK"
  const [brzaOd, setBrzaOd] = useState("");  // ISO yyyy-mm-dd
  const [brzaDo, setBrzaDo] = useState("");  // ISO yyyy-mm-dd
  const [brzaNapomena, setBrzaNapomena] = useState("");
  const [brzaIme, setBrzaIme] = useState("");
  const [brzaTelefon, setBrzaTelefon] = useState("");
  const [brzaTlOtvoren, setBrzaTlOtvoren] = useState(false);
  const [brzaTlDatum, setBrzaTlDatum] = useState<Date>();
  const [brzaTlSat, setBrzaTlSat] = useState("12");
  const [brzaSeCuva, setBrzaSeCuva] = useState(false);

  useEffect(() => {
    Promise.all([
      apiFetch<Mesto[]>("/mesto"),
      apiFetch<PeriodGrupa[]>("/period-grupa"),
      apiFetch<Smestaj[]>("/smestaj"),
    ])
      .then(([m, g, s]) => { setMesta(m); setGrupe(g); setSmestaji(s.filter((x) => x.status === 1)); })
      .catch(() => toast.error("Greška pri učitavanju podataka"))
      .finally(() => setInitialLoading(false));
  }, []);

  // Subagenti za popup slobodnog termina — pretraga na serveru (debounce 250ms)
  useEffect(() => {
    let aktivan = true;
    const t = setTimeout(() => {
      const params = new URLSearchParams({ search: subagentiPretraga.trim(), page_size: "50", sort: "naziv", dir: "asc" });
      apiFetch<{ rows: { naziv: string }[] }>(`/subagenti?${params}`)
        .then((d) => { if (aktivan) setSubagentiIzbor(d.rows.filter((r) => r.naziv && r.naziv.trim())); })
        .catch(() => { if (aktivan) setSubagentiIzbor([]); });
    }, 250);
    return () => { aktivan = false; clearTimeout(t); };
  }, [subagentiPretraga]);

  // Obračun za izabrani termin: maks. ADL izabrane strukture (kao u Rezervacijama) →
  // /slobodne-sobe (osnovna već umanjena za sopstveni prevoz) → popust čiji je tip plaćanja izabran.
  const slotStruktura = (slotCena?.tip || slotSoba?.tip || "").trim();
  const [slotObracun, setSlotObracun] = useState<SlotObracun | null>(null);
  const [slotObracunUcitava, setSlotObracunUcitava] = useState(false);
  useEffect(() => {
    if (!slotOtvoren || !slotSec || !slotSoba || !brzaOd || !brzaDo || brzaDo <= brzaOd) { setSlotObracun(null); setSlotObracunUcitava(false); return; }
    let aktivan = true;
    setSlotObracunUcitava(true);
    const ddmm = (iso: string) => `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}`;
    const smestajId = slotSec.smestaj.id;
    const sobaId = slotSoba.id;
    (async () => {
      try {
        const k = await apiFetch<{ redovi: { adl: number; chd: number; inf: number }[] }>(
          `/koeficijenti/struktura?${new URLSearchParams({ struktura: slotStruktura })}`
        );
        const adl = k.redovi.filter((r) => r.chd === 0 && r.inf === 0).reduce((m, r) => Math.max(m, r.adl), 0);
        if (adl < 1) {
          if (aktivan) setSlotObracun({ adl: 0, struktura: slotStruktura, osnovna: null, snizena: null, popust: 0, napomena: `Nema koeficijenta za strukturu ${slotStruktura || "—"}` });
          return;
        }
        const params = new URLSearchParams({ datum_od: ddmm(brzaOd), datum_do: ddmm(brzaDo), odrasli: String(adl), prevoz: slotPrevoz, smestaj_id: String(smestajId) });
        if (mestoId) params.set("mesto_id", mestoId);
        const grupe = await apiFetch<SlobodnaGrupa[]>(`/slobodne-sobe?${params}`);
        if (!aktivan) return;
        const s = grupe.find((g) => g.smestaj_id === smestajId)?.sobe.find((x) => x.id === sobaId);
        if (!s || s.nema_cene || s.cena_osnovna == null) {
          setSlotObracun({ adl, struktura: slotStruktura, osnovna: null, snizena: null, popust: 0, napomena: s?.obracun?.[0] ?? "Soba nije dostupna za izabrani termin" });
          return;
        }
        const osnovna = s.cena_osnovna;
        const v = slotPlacanje
          ? s.varijante?.find((x) => x.vazi && x.cena_snizena != null && x.tip_placanja === slotPlacanje)
          : undefined;
        const snizena = v?.cena_snizena ?? null;
        setSlotObracun({
          adl,
          struktura: s.struktura || slotStruktura,
          osnovna,
          snizena,
          popust: snizena != null ? Math.round((osnovna - snizena) * 100) / 100 : 0,
          napomena: slotPlacanje && snizena == null ? "Nema važećeg popusta za izabrani način plaćanja" : null,
        });
      } catch {
        if (aktivan) setSlotObracun({ adl: 0, struktura: slotStruktura, osnovna: null, snizena: null, popust: 0, napomena: "Obračun cene nije dostupan" });
      } finally {
        if (aktivan) setSlotObracunUcitava(false);
      }
    })();
    return () => { aktivan = false; };
  }, [slotOtvoren, slotSec, slotSoba, brzaOd, brzaDo, slotPrevoz, slotPlacanje, slotStruktura, mestoId]);

  // Prefill iz linka (?mesto=&grupa=&smestaj=) — dugme „Grafik“ na Rezervacijama otvara
  // grafik za mesto, grupu datuma i vilu izabranog ugovora; primenjuje se JEDNOM.
  const [searchParams] = useSearchParams();
  const prefillPrimenjen = useRef(false);
  useEffect(() => {
    if (initialLoading || prefillPrimenjen.current) return;
    prefillPrimenjen.current = true;
    const m = (searchParams.get("mesto") ?? "").trim();
    const mNaziv = (searchParams.get("mestoNaziv") ?? "").trim().toLocaleLowerCase();
    const mm = m
      ? mesta.find((x) => String(x.id) === m)
      : mNaziv
        ? mesta.find((x) => (x.naziv ?? "").trim().toLocaleLowerCase() === mNaziv)
        : undefined;
    const s = (searchParams.get("smestaj") ?? "").trim();
    const sNaziv = (searchParams.get("smestajNaziv") ?? "").trim().toLocaleLowerCase();
    const ss = s
      ? smestaji.find((x) => String(x.id) === s)
      : sNaziv
        ? smestaji.find((x) => (x.naziv ?? "").trim().toLocaleLowerCase() === sNaziv)
        : undefined;
    if (ss?.mesto) setMestoId(String(ss.mesto));
    else if (mm) setMestoId(String(mm.id));
    const g = (ss?.grupa_datuma ? String(ss.grupa_datuma) : "")
      || (searchParams.get("grupa") ?? "").trim()
      || (mm?.grupa_datuma ? String(mm.grupa_datuma) : "");
    if (g) setGrupaId(g);
    if (ss) setSmestajId(String(ss.id));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialLoading]);

  // Mesto → podrazumevana (primarna) grupa perioda + odmah "Prikaži sve" smeštaje
  function onMestoChange(v: string) {
    setMestoId(v);
    setSmestajId("sve");
    setData(null);
    setSekcije([]);
    const m = mesta.find((x) => String(x.id) === v);
    setGrupaId(m?.grupa_datuma ? String(m.grupa_datuma) : "");
  }

  function onGrupaChange(v: string) {
    setGrupaId(v);
    setSmestajId("sve"); // promena grupe takođe otvara sve smeštaje te grupe
    setData(null);
    setSekcije([]);
  }

  function openUgovor(kljuc: string) {
    const reqId = ++ugovorReqRef.current; // guard za zastarele odgovore
    setUgovorKljuc(kljuc);
    setUgovorDetail(null);
    setUgovorOpen(true);
    setUgovorLoading(true);
    apiFetch<UgovorDetail>(`/ugovori/${kljuc}`)
      .then((d) => { if (ugovorReqRef.current === reqId) setUgovorDetail(d); })
      .catch(() => { if (ugovorReqRef.current === reqId) toast.error("Greška pri učitavanju ugovora"); })
      .finally(() => { if (ugovorReqRef.current === reqId) setUgovorLoading(false); });
  }

  // klik na slobodan prostor → popup izbora Klasična/Brza rezervacija
  function otvoriSlot(sec: GrafikData, soba: GrafikSoba, p: GrafikPeriod) {
    setSlotSec(sec);
    setSlotSoba(soba);
    setSlotPeriod(p);
    // prva dostupna cena po redu je unapred izabrana (korisnik može da promeni klikom)
    setSlotCena(cenaOpcije(sec, soba, p).opcije.find((o) => !o.blokirano && o.cena != null) ?? null);

    setSlotPlacanje("delimicno");
    // predefinisani datumi slobodnog termina (mogu se ispraviti u formi)
    setBrzaOd(isoOdPrikaza(p.datum_od));
    setBrzaDo(isoOdPrikaza(p.datum_do));
    setBrzaTip("Predrezervacija");
    setBrzaNapomena("");
    setBrzaIme("");
    setBrzaTelefon("");
    setBrzaTlDatum(undefined);
    setBrzaTlSat("12");
    setBrzaTlOtvoren(false);
    setBrzaOtvoren(false);
    setSlotOtvoren(true);
  }

  function zatvoriSlotove() {
    setSlotOtvoren(false);
    setBrzaOtvoren(false);
    setBrzaTlOtvoren(false);
  }

  // Provera raspoloživosti ponuđenog termina pre Klasične/Brze rezervacije —
  // overlap ugovora iste sobe (isti koren naziva) nad [datumod, datumdo).
  // Vraća opis ugovora ako je zauzet, inače null.
  function terminZauzet(): string | null {
    if (!slotSec || !slotSoba || !slotPeriod) return null;
    const od = new Date(`${brzaOd}T00:00:00`).getTime();
    const doo = new Date(`${brzaDo}T00:00:00`).getTime();
    const z = slotSec.ugovori.find((u) =>
      (u.soba || "").trim() === (slotSoba.broj_sobe || "").trim()
      && pDate(u.datum_od).getTime() < doo && pDate(u.datum_do).getTime() > od
    );
    return z ? `${z.kljuc} (${(z.putnik || "").trim() || "putnik"}) ${z.datum_od} – ${z.datum_do}` : null;
  }

  function obavestiZauzet() {
    if (!brzaOd || !brzaDo || brzaDo <= brzaOd) {
      toast.error("Datum do mora biti posle Datuma od");
      return true;
    }
    const zauzet = terminZauzet();
    if (zauzet) {
      toast.error(`Termin je zauzet — ugovor ${zauzet}. Izaberite slobodan termin.`, { duration: 12000 });
    }
    return !!zauzet;
  }

  // Klasična rezervacija → postojeća stranica Rezervacije (kao do sada)
  function klasicnaRez() {
    if (!slotSec || !slotSoba || !slotPeriod) return;
    if (obavestiZauzet()) return;
    const params = new URLSearchParams({
      novi: "1",
      datumod: fmtDatum(new Date(`${brzaOd}T12:00:00`)),
      datumdo: fmtDatum(new Date(`${brzaDo}T12:00:00`)),
      soba: String(slotSoba.id),
      smestaj: String(slotSec.smestaj.id),
      mesto: mestoId,
    });
    if (slotSubagent) params.set("subagent", slotSubagent);
    // način plaćanja (bira koji popust sobe važi) i prevoz (sopstveni → umanjenje cene)
    if (slotPlacanje) params.set("placanje", slotPlacanje);
    params.set("prevoz", slotPrevoz);
    // izabrana cena iz popupa: cena cele sobe (EUR) + struktura virtuelne sobe u „Promena strukture“
    // struktura (uvek) → broj saputnika i količina smeštaja na Rezervacijama (adl koeficijenta)
    // obračun za izabrani termin (maks. ADL, osnovna već umanjena za sopstveni prevoz) → odrasli, cena, popust
    if (slotObracun?.osnovna != null && slotObracun.adl > 0) {
      params.set("odrasli", String(slotObracun.adl));
      params.set("cena", String(slotObracun.osnovna));
      if (slotObracun.popust > 0) params.set("popustPct", String(Math.round((slotObracun.popust / slotObracun.osnovna) * 10000) / 100));
    }
    if (slotCena?.tip) params.set("struktura", slotCena.tip);
    navigate(`/prodaja/rezervacije?${params.toString()}`);
  }

  // Brza rezervacija → upis u aranzman (Blok ili Predrezervacija) sa proverom zauzeća
  async function potvrdiBrzu() {
    if (!slotSec || !slotSoba || brzaSeCuva) return;
    if (!brzaOd || !brzaDo) { toast.error("Unesite datum od i datum do"); return; }
    if (brzaDo <= brzaOd) { toast.error("Datum do mora biti posle Datuma od"); return; }
    const jeBlok = brzaTip === "BLOK";
    if (!jeBlok && !brzaIme.trim()) { toast.error("Unesite ime putnika"); return; }
    setBrzaSeCuva(true);
    try {
      const r = await apiFetch<{ kljuc: string; message: string }>("/rezervacije", {
        method: "POST",
        body: JSON.stringify({
          tiprezervacije: jeBlok ? "BLOK" : "Predrezervacija",
          timelimit: !jeBlok && brzaTlDatum ? `${isoOdDatuma(brzaTlDatum)}T${brzaTlSat}:00:00` : null,
          nosilac: {
            ime: jeBlok ? "BLOK" : brzaIme.trim(),
            datumRodjenja: null, uzrast: "ADL", pasos: "", ow: false, rt: false, sp: false, smer: "",
            adresa: "", telefon: brzaTelefon.trim(), email: "",
          },
          saputnici: [],
          subagent: slotSubagent,
          boravak: {
            datumOd: brzaOd, datumDo: brzaDo,
            smestajId: slotSec.smestaj.id, sobaId: slotSoba.id,
            mestoId: mestoId ? Number(mestoId) : null,
            smestajNaziv: null, sobaBroj: null, mestoNaziv: null,
            struktura: slotSoba.tip || "", napomena: brzaNapomena.trim(), napomenaInterna: "",
          },
          destinacijaId: null, destinacijaNaziv: null, ulazak: "",
          cene: {
            cenaSmestajEUR: 0, kolSmestajEUR: 1, cenaSmestajRSD: 0, kolSmestajRSD: 1,
            popustSmestaj: {}, cenaPrevozEUR: 0, kolPrevozEUR: 1,
            cenaPrevozRSD: 0, kolPrevozRSD: 1, popustPrevoz: {},
            osiguranjeEUR: 0, osiguranjeRSD: 0, provizijaSmestaj: {}, provizijaPrevoz: {},
          },
        }),
      });
      toast.success("Brza rezervacija je upisana", {
        description: `${r.kljuc} — ${slotSec.smestaj.naziv}, soba ${slotSoba.broj_sobe}`,
      });
      zatvoriSlotove();
      setRefreshKey((k) => k + 1); // grafik se osvežava — novi pojas je vidljiv
    } catch (error) {
      const msg = error instanceof Error ? error.message : "Upis brze rezervacije nije uspeo";
      if (msg.includes("zauzet")) {
        toast.error("Rezervacija nije upisana — termin je zauzet", { description: msg, duration: 12000 });
      } else {
        toast.error(msg);
      }
    } finally {
      setBrzaSeCuva(false);
    }
  }

  // Smeštaji vezani za izabrano MESTO i grupu perioda (ista vila u drugom mestu ne ulazi)
  const smestajiGrupe = useMemo(
    () => smestaji.filter((s) => grupaId && s.grupa_datuma === Number(grupaId)
      && (!mestoId || String(s.mesto) === mestoId)),
    [smestaji, grupaId, mestoId]
  );

  // Auto-učitavanje grafika na izbor smeštaja ("sve" → sekcije po svim smeštajima grupe;
  // refreshKey → osvežavanje posle promene smeštaja)
  useEffect(() => {
    if (!grupaId || !smestajId) { setData(null); setSekcije([]); return; }
    let cancelled = false;
    setLoading(true);
    apiFetch<GrafikData | { sve: boolean; sekcije: GrafikData[] }>(
      `/grafik?smestaj_id=${smestajId}&grupa_id=${grupaId}&mesto_id=${mestoId}`
    )
      .then((d) => {
        if (cancelled) return;
        if ("sekcije" in d) { setSekcije(d.sekcije || []); setData(null); }
        else { setData(d); setSekcije([]); }
      })
      .catch(() => { if (!cancelled) { toast.error("Greška pri učitavanju grafika"); setData(null); setSekcije([]); } })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [grupaId, smestajId, mestoId, refreshKey]);

  function handlePromenaSuccess() {
    setRefreshKey((k) => k + 1); // osveži trenutni grafik
  }

  // "Prikaži sve" → sekcije po svim smeštajima grupe; inače jedna sekcija (izabrani smeštaj)
  const jeSve = smestajId === "sve";
  const allSekcije = useMemo(
    () => (jeSve ? sekcije : data ? [data] : []),
    [jeSve, sekcije, data]
  );
  const vidljiveSekcije = useMemo(
    () => allSekcije.filter((s) => s.sobe.length > 0),
    [allSekcije]
  );

  // soba/tip ugovora iz trenutnog grafika (za popup; traži po svim sekcijama kod "Prikaži sve")
  const detailSobaTip = useMemo(() => {
    if (!ugovorDetail) return null;
    const s = (ugovorDetail.soba || "").trim();
    const sec = allSekcije.find((x) => x.smestaj.naziv === ugovorDetail.naziv) ?? allSekcije[0];
    const room = s && sec
      ? sec.sobe.find((x) => (x.broj_sobe || "").trim() === s)
      : undefined;
    return { soba: s || (ugovorDetail.apartman || "").trim(), tip: room?.tip || "" };
  }, [ugovorDetail, allSekcije]);

  const hasSelection = !!(mestoId && grupaId && smestajId);

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <ChartGantt className="w-6 h-6" />Grafik
          </h1>
          <p className="text-muted-foreground text-sm">Raspored ugovora po sobama i periodima</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={() => window.print()} disabled={!hasSelection || allSekcije.length === 0}>
            <Printer className="w-4 h-4 mr-2" />Štampaj
          </Button>
          <Button variant="outline" onClick={() => navigate(-1)}>
            <ArrowLeft className="w-4 h-4 mr-2" />Nazad
          </Button>
        </div>
      </div>

      {/* Kaskadna selekcija */}
      <div className="rounded-md border bg-card p-4 flex flex-wrap items-end gap-4">
        <div>
          <PretraznaSelect
            className="w-56" ariaLabel="Izaberi mesto" label="Izaberi mesto" placeholder="Izaberi mesto"
            value={mestoId} onChange={onMestoChange} disabled={initialLoading}
            opcije={mesta.map((m) => ({ value: String(m.id), label: m.naziv }))}
          />
        </div>
        <div>
          <PretraznaSelect
            className="w-64" ariaLabel="Izaberi grupu perioda" label="Izaberi grupu perioda"
            placeholder={mestoId ? "Izaberi grupu perioda" : "Prvo izaberi mesto"}
            value={grupaId} onChange={onGrupaChange}
            disabled={!mestoId || initialLoading}
            opcije={grupe
              .filter((g) => mesta.find((m) => String(m.id) === mestoId)?.grupe?.includes(g.id))
              .slice()
              .sort((a, b) => a.id - b.id)
              .map((g) => ({ value: String(g.id), label: g.naziv }))}
          />
        </div>
        <div>
          <PretraznaSelect
            className="w-64" ariaLabel="Izaberi smeštaj" label="Izaberi smeštaj"
            placeholder={grupaId ? "Izaberi smeštaj" : "Prvo izaberi grupu"}
            value={smestajId} onChange={setSmestajId}
            disabled={!grupaId || initialLoading}
            opcije={[
              { value: "sve", label: "Prikaži sve" },
              ...smestajiGrupe.map((s) => ({ value: String(s.id), label: s.naziv })),
            ]}
          />
        </div>
        {loading && <Loader2 className="w-5 h-5 animate-spin text-muted-foreground mb-2" />}
      </div>

      {/* Grafik — jedan smeštaj ili "Prikaži sve" (po jedna sekcija za svaki smeštaj grupe) */}
      {!hasSelection ? (
        <div className="rounded-md border py-16 text-center text-muted-foreground text-sm">
          Izaberite mesto, grupu perioda i smeštaj za prikaz grafika
        </div>
      ) : loading && allSekcije.length === 0 ? (
        <div className="rounded-md border"><PageLoader className="min-h-[40vh] gap-6" /></div>
      ) : allSekcije.length > 0 && allSekcije.every((s) => s.periodi.length === 0) ? (
        <div className="rounded-md border py-16 text-center text-muted-foreground text-sm">
          Izabrana grupa perioda nema definisane periode
        </div>
      ) : (
        <div className="rounded-md border grafik-scroll max-h-[70vh] overflow-auto">
          <TooltipProvider delayDuration={200}>
            {vidljiveSekcije.length === 0 && (
              <div className="py-16 text-center text-muted-foreground text-sm">
                Izabrani smeštaj nema definisane sobe
              </div>
            )}
            {vidljiveSekcije.map((sec, si) => (
              <Fragment key={`s-${sec.smestaj.id}`}>
                {si > 0 && <div className="border-t-2 border-t-border" />}
                {jeSve && (
                  <div className="flex items-baseline justify-between border-b bg-muted/50 px-3 py-2">
                    <h3 className="text-sm font-semibold tracking-wide">{sec.smestaj.naziv}</h3>
                    <span className="text-xs text-muted-foreground">
                      {sec.sobe.length} {sec.sobe.length === 1 ? "soba" : "sobe"}
                    </span>
                  </div>
                )}
                <GrafikTabela
                  sec={sec}
                  onRez={(s, soba, p) => otvoriSlot(s, soba, p)}
                  onUgovor={openUgovor}
                />
              </Fragment>
            ))}
          </TooltipProvider>
        </div>
      )}

      {/* Popup: podaci o ugovoru */}
      <Dialog open={ugovorOpen} onOpenChange={setUgovorOpen}>
        <DialogContent className="max-w-md bg-card">
          <DialogHeader>
            <DialogTitle>Ugovor {ugovorKljuc}</DialogTitle>
            <DialogDescription>Podaci o ugovoru</DialogDescription>
          </DialogHeader>
          {ugovorLoading ? (
            <div className="py-8 text-center">
              <Loader2 className="w-6 h-6 animate-spin mx-auto text-muted-foreground" />
            </div>
          ) : ugovorDetail ? (
            <div className="space-y-4">
              <div>
                <PfRow label="Broj ugovora" value={ugovorDetail.kljuc} mono />
                <PfRow label="Datum ugovora" value={ugovorDetail.danas || "—"} />
                <PfRow label="Nosilac" value={ugovorDetail.putnik || "—"} />
                <PfRow
                  label="Putnici"
                  value={
                    [
                      ugovorDetail.putnik || "",
                      ...(ugovorDetail.putnici_detalji
                        ? fmtPutnici(ugovorDetail.putnici_detalji)
                        : (ugovorDetail.putnici || []).slice(1)),
                    ].filter(Boolean).join(", ") || "—"
                  }
                />
                <PfRow label="Mesto" value={ugovorDetail.mesto || "—"} />
                <PfRow label="Smeštaj" value={ugovorDetail.naziv || "—"} />
                <PfRow label="Soba" value={detailSobaTip?.soba || "—"} />
                {detailSobaTip?.tip ? <PfRow label="Tip" value={detailSobaTip.tip} /> : null}
                <PfRow label="Period" value={`${ugovorDetail.datumod || "?"} – ${ugovorDetail.datumdo || "?"}`} />
              </div>
              <div>
                <PfRow
                  label="Subagent"
                  value={
                    ugovorDetail.subagent_info
                      ? `${ugovorDetail.subagent_info.naziv || "—"}${ugovorDetail.subagent_info.tel ? ` · ${ugovorDetail.subagent_info.tel}` : ""}`
                      : "Nema subagenta"
                  }
                />
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                <Button
                  className="h-10 rounded-lg bg-green-600 font-semibold text-white shadow-sm hover:bg-green-700 hover:text-white"
                  onClick={() => {
                    setUgovorOpen(false);
                    navigate(`/prodaja/rezervacije?u=${encodeURIComponent(ugovorDetail.kljuc || ugovorKljuc)}`);
                  }}
                >
                  <ExternalLink className="w-4 h-4 mr-2" />Otvori rezervaciju
                </Button>
                <Button
                  className="h-10 rounded-lg bg-yellow-400 font-semibold text-black shadow-sm hover:bg-yellow-500 hover:text-black"
                  onClick={() => {
                    setUgovorOpen(false);
                    setPromenaOpen(true);
                  }}
                >
                  <ArrowRightLeft className="w-4 h-4 mr-2" />Promena smeštaja
                </Button>
              </div>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">Podaci o ugovoru nisu dostupni.</p>
          )}
        </DialogContent>
      </Dialog>

      {/* Popup: promena smeštaja */}
      <PromenaSmestajaDialog
        open={promenaOpen}
        onOpenChange={setPromenaOpen}
        ugovorKljuc={ugovorKljuc}
        detail={ugovorDetail}
        onSuccess={handlePromenaSuccess}
        onBack={() => { setPromenaOpen(false); setUgovorOpen(true); }}
      />

      {/* Popup: slobodan termin → Klasična / Brza rezervacija */}
      <Dialog open={slotOtvoren} onOpenChange={(o) => { if (!o) zatvoriSlotove(); }}>
        <DialogContent className="gap-2 rounded-2xl bg-card p-3 shadow-xl sm:max-w-lg sm:rounded-2xl sm:p-4">
          <DialogHeader className="text-left">
            <div className="flex items-center gap-2">
              <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-green-600/10 text-green-600">
                <CalendarCheck2 className="h-4 w-4" aria-hidden="true" />
              </div>
              <DialogTitle className="text-base tracking-tight">Slobodan termin</DialogTitle>
              <DialogDescription className="sr-only">Izaberite način rezervacije za odabrani boravak.</DialogDescription>
            </div>
          </DialogHeader>
          <div className="space-y-1.5 rounded-xl border border-border/60 bg-muted/40 p-2.5">
            <div className="flex items-center gap-2">
              <BedDouble className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold">{slotSec?.smestaj.naziv || "—"} · Soba {slotSoba?.broj_sobe || "—"}</p>
              </div>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-green-600/10 px-2 py-0.5 text-xs font-medium text-green-600">
                <span className="h-1.5 w-1.5 rounded-full bg-green-600" />
                Slobodno
              </span>
            </div>
            <div className="grid grid-cols-2 gap-2 border-t border-border/60 pt-1.5">
              <DatumBoravka label="Datum od" value={brzaOd} onChange={setBrzaOd} smene={slotSec?.periodi} />
              <DatumBoravka label="Datum do" value={brzaDo} onChange={setBrzaDo} smene={slotSec?.periodi} />
            </div>
          </div>
          <div>
            <PretraznaSelect
              ariaLabel="Izaberi subagenta" placeholder="Bez subagenta" label="Izaberi subagenta"
              value={slotSubagent} onChange={setSlotSubagent} prazno
              onPretraga={setSubagentiPretraga}
              opcije={subagentiIzbor.map((s) => ({ value: s.naziv, label: s.naziv }))}
            />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">Način plaćanja</Label>
              <Select value={slotPlacanje || "nista"} onValueChange={(v) => setSlotPlacanje(v === "nista" ? "" : v)}>
                <SelectTrigger aria-label="Način plaćanja" className="h-8"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="nista">Bez izbora</SelectItem>
                  <SelectItem value="delimicno">Delimično</SelectItem>
                  <SelectItem value="u_celosti">U celosti</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">Prevoz</Label>
              <Select value={slotPrevoz} onValueChange={setSlotPrevoz}>
                <SelectTrigger aria-label="Prevoz" className="h-8"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="autobuski">Autobuski</SelectItem>
                  <SelectItem value="sopstveni">Sopstveni</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          {slotSec && slotSoba && slotPeriod ? (
            <SlotCene
              sec={slotSec}
              soba={slotSoba}
              p={slotPeriod}
              izabrana={slotCena}
              onIzbor={(o) => setSlotCena((prev) => (prev?.sobaId === o.sobaId ? null : o))}
            />
          ) : null}
          {slotObracunUcitava ? (
            <div role="status" aria-live="polite" className="flex items-center gap-2 rounded-xl border border-border/60 bg-muted/40 p-3 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 shrink-0 animate-spin" aria-hidden="true" />
              Računanje cene…
            </div>
          ) : slotObracun ? (
            <div className="space-y-1 rounded-xl border border-border/60 bg-muted/40 p-3">
              <p className="text-xs font-medium text-muted-foreground">
                Obračun · {slotObracun.adl} {slotObracun.adl === 1 ? "osoba" : "osobe"}{slotObracun.struktura ? ` · ${slotObracun.struktura}` : ""}
              </p>
              {slotObracun.osnovna != null ? (
                <div className="space-y-0.5 text-sm">
                  <div className="flex justify-between gap-3">
                    <span>Osnovna cena{slotPrevoz === "sopstveni" ? " (umanjenje za sopstveni prevoz uračunato)" : ""}</span>
                    <span className="font-mono tabular-nums">{fmtEur(slotObracun.osnovna)}</span>
                  </div>
                  {slotObracun.popust > 0 ? (
                    <div className="flex justify-between gap-3 text-emerald-700">
                      <span>Popust · {slotPlacanje === "u_celosti" ? "u celosti" : "delimično"}</span>
                      <span className="font-mono tabular-nums">−{fmtEur(slotObracun.popust)}</span>
                    </div>
                  ) : null}
                  <div className="flex justify-between gap-3 border-t border-border/60 pt-0.5 font-semibold">
                    <span>Cena za rezervaciju</span>
                    <span className="font-mono tabular-nums">{fmtEur(slotObracun.snizena ?? slotObracun.osnovna)}</span>
                  </div>
                </div>
              ) : null}
              {slotObracun.napomena ? <p className="text-xs text-muted-foreground">{slotObracun.napomena}</p> : null}
            </div>
          ) : null}
          <div className="grid grid-cols-2 gap-2">
            <Button
              className="h-9 w-full gap-2 rounded-xl bg-green-600 px-2 text-white shadow-sm transition-colors hover:bg-green-700 sm:px-3"
              onClick={klasicnaRez}
            >
              <ClipboardList className="h-4 w-4 shrink-0" aria-hidden="true" />
              <span className="whitespace-normal text-xs leading-snug sm:text-sm">Klasična rezervacija</span>
            </Button>
            <Button
              className="h-9 w-full gap-2 rounded-xl bg-blue-600 px-2 text-white shadow-sm transition-colors hover:bg-blue-700 sm:px-3"
              onClick={() => { if (!obavestiZauzet()) { setSlotOtvoren(false); setBrzaOtvoren(true); } }}
            >
              <Zap className="h-4 w-4 shrink-0" aria-hidden="true" />
              <span className="whitespace-normal text-xs leading-snug sm:text-sm">Brza rezervacija</span>
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Popup: brza rezervacija (Blok / Predrezervacija) */}
      <Dialog open={brzaOtvoren} onOpenChange={(o) => { if (!o) zatvoriSlotove(); }}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Brza rezervacija</DialogTitle>
            <DialogDescription>
              {slotSoba ? `Soba ${slotSoba.broj_sobe || "—"}` : "—"}
              {slotSec ? ` · ${slotSec.smestaj.naziv}` : ""}
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-3 py-1">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">Tip rezervacije</Label>
                <Select
                  value={brzaTip}
                  onValueChange={(v) => {
                    setBrzaTip(v);
                    if (v !== "Predrezervacija") { setBrzaTlDatum(undefined); setBrzaTlOtvoren(false); }
                  }}
                >
                  <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="Predrezervacija">Predrezervacija</SelectItem>
                    <SelectItem value="BLOK">Blok</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              {brzaTip === "Predrezervacija" && (
                <div className="space-y-1.5">
                  <Label className="text-xs text-muted-foreground">Time limit</Label>
                  <Popover open={brzaTlOtvoren} onOpenChange={setBrzaTlOtvoren}>
                    <PopoverTrigger asChild>
                      <Button
                        variant="outline"
                        className={cn("w-full justify-start gap-2 font-normal", !brzaTlDatum && "text-muted-foreground")}
                      >
                        <CalendarDays className="size-4 shrink-0" />
                        {brzaTlDatum
                          ? `${String(brzaTlDatum.getDate()).padStart(2, "0")}.${String(brzaTlDatum.getMonth() + 1).padStart(2, "0")}.${brzaTlDatum.getFullYear()} ${brzaTlSat}:00`
                          : "Izaberite datum i sat"}
                      </Button>
                    </PopoverTrigger>
                    <PopoverContent align="start" className="w-auto p-0">
                      <Calendar
                        mode="single"
                        selected={brzaTlDatum}
                        onSelect={setBrzaTlDatum}
                        weekStartsOn={1}
                        formatters={formattersKalendara}
                        initialFocus
                      />
                      <div className="flex items-center gap-3 border-t px-4 py-3">
                        <Label className="text-sm">Sat</Label>
                        <Select value={brzaTlSat} onValueChange={setBrzaTlSat}>
                          <SelectTrigger className="ml-auto w-28"><SelectValue /></SelectTrigger>
                          <SelectContent className="max-h-52">
                            {SATI.map((sat) => <SelectItem key={sat} value={sat}>{sat}:00</SelectItem>)}
                          </SelectContent>
                        </Select>
                      </div>
                    </PopoverContent>
                  </Popover>
                </div>
              )}
            </div>
            <div className="grid grid-cols-2 gap-3">
              <DatumBoravka label="Datum od" value={brzaOd} onChange={setBrzaOd} />
              <DatumBoravka label="Datum do" value={brzaDo} onChange={setBrzaDo} />
            </div>
            {brzaTip === "Predrezervacija" && (
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label className="text-xs text-muted-foreground">Ime putnika</Label>
                  <Input value={brzaIme} onChange={(e) => setBrzaIme(e.target.value)} placeholder="Ime i prezime" />
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs text-muted-foreground">Telefon</Label>
                  <Input value={brzaTelefon} onChange={(e) => setBrzaTelefon(e.target.value)} placeholder="06x…" />
                </div>
              </div>
            )}
            <div className="space-y-1.5">
              <PretraznaSelect
                ariaLabel="Izaberi subagenta — brza" placeholder="Bez subagenta" label="Izaberi subagenta"
                value={slotSubagent} onChange={setSlotSubagent} prazno
                onPretraga={setSubagentiPretraga}
                opcije={subagentiIzbor.map((s) => ({ value: s.naziv, label: s.naziv }))}
              />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Napomena</Label>
              <Textarea rows={2} value={brzaNapomena} onChange={(e) => setBrzaNapomena(e.target.value)} />
            </div>
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={zatvoriSlotove} disabled={brzaSeCuva}>Odustani</Button>
            <Button onClick={() => void potvrdiBrzu()} disabled={brzaSeCuva}>
              {brzaSeCuva && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
              Potvrdi
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
