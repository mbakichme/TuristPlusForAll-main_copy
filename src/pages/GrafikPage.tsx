import { useState, useEffect, useMemo, useRef, Fragment } from "react";
import type { ReactNode } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import type { Mesto, Smestaj, PeriodGrupa, UgovorDetail } from "../types";
import { apiFetch } from "../lib/api";
import { cn } from "@/lib/utils";
import { fmtPutnici } from "@/lib/putnici";
import PromenaSmestajaDialog from "@/components/PromenaSmestajaDialog";
import { Button } from "@/components/ui/button";
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
interface GrafikData {
  smestaj: { id: number; naziv: string };
  periodi: GrafikPeriod[];
  sobe: GrafikSoba[];
  ugovori: GrafikUgovor[];
}

/** DD.MM.YYYY → Date */
function pDate(s: string): Date {
  const [d, m, y] = s.split(".").map(Number);
  return new Date(y, m - 1, d);
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

/** Geometrija grafika za jedan smeštaj — JEDINSTVENA vremenska osa.
 *  Kolone se gradi od SVIH unikatnih granica perioda (počeci + krajevi), pa se
 *  preklapajući periodi (npr. 20.05–27.05 i 20.05–30.05) crtaju na zajedničkoj osi:
 *  20.05 je zajednička granica, a 27.05 i 30.05 odvojene. Širine kolona su
 *  proporcionalne trajanju, a pojasevi/beline su procenti te iste ose. */
function grafikGeometrija(data: GrafikData) {
  const fmt = (d: Date) =>
    `${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")}.${d.getFullYear()}`;
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
    datum_od: fmt(od),
    datum_do: fmt(granice[i + 1]),
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
        arr2.push({ leftPct: pct(cursor), widthPct: pct(s.od) - pct(cursor), od: fmt(cursor), doo: fmt(s.od) });
      }
      if (s.doo.getTime() > cursor.getTime()) cursor = s.doo;
    }
    if (t1 > cursor.getTime() + 1000) {
      arr2.push({ leftPct: pct(cursor), widthPct: 100 - pct(cursor), od: fmt(cursor), doo: fmt(new Date(t1)) });
    }
    if (arr2.length > 0) gaps.set(key, arr2);
  }
  return { kolone, linije, spans, gaps };
}

/** Period Grupe koji odgovara kliknutom intervalu: tačno poklapanje pobeđuje,
 *  inače najuži period koji POTPUNO sadrži klik (npr. klik na zonu 27.05–30.05
 *  unutar preklapajućih perioda 20.05–27.05 i 20.05–30.05 nudi baš 20.05–30.05).
 *  Klik van svih perioda vraća kliknute datume neizmenjene. */
function periodZaKlik(periodi: GrafikPeriod[], od: string, doo: string): GrafikPeriod {
  const tacan = periodi.find((p) => p.datum_od === od && p.datum_do === doo);
  if (tacan) return tacan;
  const tOd = pDate(od).getTime();
  const tDo = pDate(doo).getTime();
  let najbolji: GrafikPeriod | null = null;
  let najuzi = Number.POSITIVE_INFINITY;
  for (const p of periodi) {
    const a = pDate(p.datum_od).getTime();
    const b = pDate(p.datum_do).getTime();
    if (a <= tOd && tDo <= b && b - a < najuzi) {
      najbolji = p;
      najuzi = b - a;
    }
  }
  return najbolji ?? { datum_od: od, datum_do: doo };
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

/** Tabela grafika za JEDAN smeštaj — redovi su sobe, zeleni pojasevi su ugovori. */
function GrafikTabela({ sec, onRez, onUgovor }: {
  sec: GrafikData;
  onRez: (sec: GrafikData, soba: GrafikSoba, p: GrafikPeriod) => void;
  onUgovor: (kljuc: string) => void;
}) {
  const { kolone, linije, spans, gaps } = useMemo(() => grafikGeometrija(sec), [sec]);
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
  return (
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
                {/* Klik na slobodnu kolonu — nudi PERIOD Grupe koji sadrži kolonu
                    (tačno poklapanje pobeđuje; preklapajući periodi se razrešavaju
                    preko periodZaKlik), vidljivo gde nema belina/pojaseva */}
                {kolone.map((k, i) => {
                  const pz = periodZaKlik(sec.periodi, k.datum_od, k.datum_do);
                  return (
                    <div
                      key={`k-${i}`}
                      className="absolute bottom-[2px] top-[2px] cursor-pointer hover:bg-muted/60"
                      style={{ left: `${k.leftPct}%`, width: `${k.widthPct}%` }}
                      onClick={() => onRez(sec, soba, pz)}
                      title={`Soba ${soba.broj_sobe || "—"} — ${pz.datum_od.slice(0, 5)} – ${pz.datum_do.slice(0, 5)}`}
                    />
                  );
                })}
                {/* Unutrašnje granice kolona — odvojene ivice preklapajućih perioda */}
                {linije.map((lp, i) => (
                  <div key={`l-${i}`} className="pointer-events-none absolute top-0 bottom-0 w-px bg-gray-400" style={{ left: `${lp}%` }} />
                ))}
                {/* Slobodne beline — klik nudi PERIOD Grupe koji sadrži belinu */}
                {(gaps.get(rkey) || []).map((g, gi) => {
                  const pz = periodZaKlik(sec.periodi, g.od, g.doo);
                  return (
                    <div
                      key={`g-${gi}`}
                      className="absolute bottom-[2px] top-[2px] z-20 cursor-pointer hover:bg-muted/50"
                      style={{ left: `${g.leftPct}%`, width: `${g.widthPct}%` }}
                      onClick={() => onRez(sec, soba, pz)}
                      title={`Slobodno ${g.od.slice(0, 5)} – ${g.doo.slice(0, 5)} — klik za rezervaciju`}
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
                    <Tooltip key={b.kljuc}>
                      <TooltipTrigger asChild>
                        <span
                          className={cn("absolute top-1/2 -bottom-0.5 z-30 flex cursor-pointer items-center justify-start pl-1 hover:underline", stilBoje(ui.boja).tekst)}
                          style={{ left: `${b.leftPct}%`, right: `${b.rightPct}%` }}
                          onClick={() => onUgovor(b.kljuc)}
                        >
                          {b.kljuc.split("/")[0]}
                        </span>
                      </TooltipTrigger>
                      <TooltipContent side="top" className="bg-slate-900/95 text-white border-slate-700 shadow-lg">
                        <UgovorTooltip u={ui} />
                      </TooltipContent>
                    </Tooltip>
                  );
                })}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
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
  const [slotSec, setSlotSec] = useState<GrafikData | null>(null);
  const [slotSoba, setSlotSoba] = useState<GrafikSoba | null>(null);
  const [slotPeriod, setSlotPeriod] = useState<GrafikPeriod | null>(null);
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
      .then(([m, g, s]) => { setMesta(m); setGrupe(g); setSmestaji(s); })
      .catch(() => toast.error("Greška pri učitavanju podataka"))
      .finally(() => setInitialLoading(false));
  }, []);

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

  // Klasična rezervacija → postojeća stranica Rezervacije (kao do sada)
  function klasicnaRez() {
    if (!slotSec || !slotSoba || !slotPeriod) return;
    const params = new URLSearchParams({
      novi: "1",
      datumod: slotPeriod.datum_od,
      datumdo: slotPeriod.datum_do,
      soba: String(slotSoba.id),
      smestaj: String(slotSec.smestaj.id),
      mesto: mestoId,
    });
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
            datumRodjenja: null, pasos: "", ow: false, rt: false, sp: false, smer: "",
            adresa: "", telefon: brzaTelefon.trim(), email: "",
          },
          saputnici: [],
          boravak: {
            datumOd: brzaOd, datumDo: brzaDo,
            smestajId: slotSec.smestaj.id, sobaId: slotSoba.id,
            mestoId: mestoId ? Number(mestoId) : null,
            smestajNaziv: null, sobaBroj: null, mestoNaziv: null,
            struktura: "", napomena: brzaNapomena.trim(), napomenaInterna: "",
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

  // Smeštaji povezani sa izabranom grupom perioda
  const smestajiGrupe = useMemo(
    () => smestaji.filter((s) => grupaId && s.grupa_datuma === Number(grupaId)),
    [smestaji, grupaId]
  );

  // Auto-učitavanje grafika na izbor smeštaja ("sve" → sekcije po svim smeštajima grupe;
  // refreshKey → osvežavanje posle promene smeštaja)
  useEffect(() => {
    if (!grupaId || !smestajId) { setData(null); setSekcije([]); return; }
    let cancelled = false;
    setLoading(true);
    apiFetch<GrafikData | { sve: boolean; sekcije: GrafikData[] }>(
      `/grafik?smestaj_id=${smestajId}&grupa_id=${grupaId}`
    )
      .then((d) => {
        if (cancelled) return;
        if ("sekcije" in d) { setSekcije(d.sekcije || []); setData(null); }
        else { setData(d); setSekcije([]); }
      })
      .catch(() => { if (!cancelled) { toast.error("Greška pri učitavanju grafika"); setData(null); setSekcije([]); } })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [grupaId, smestajId, refreshKey]);

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
        <div className="space-y-1.5">
          <Label className="text-xs text-muted-foreground">Izaberi mesto</Label>
          <Select value={mestoId} onValueChange={onMestoChange} disabled={initialLoading}>
            <SelectTrigger className="w-56"><SelectValue placeholder="Izaberi mesto" /></SelectTrigger>
            <SelectContent>
              {mesta.map((m) => (
                <SelectItem key={m.id} value={String(m.id)}>{m.naziv}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs text-muted-foreground">Izaberi grupu perioda</Label>
          <Select
            value={grupaId}
            onValueChange={onGrupaChange}
            disabled={!mestoId || initialLoading}
          >
            <SelectTrigger className="w-64">
              <SelectValue placeholder={mestoId ? "Izaberi grupu perioda" : "Prvo izaberi mesto"} />
            </SelectTrigger>
            <SelectContent>
              {grupe
                .filter((g) => mesta.find((m) => String(m.id) === mestoId)?.grupe?.includes(g.id))
                .map((g) => (
                  <SelectItem key={g.id} value={String(g.id)}>{g.naziv}</SelectItem>
                ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs text-muted-foreground">Izaberi smeštaj</Label>
          <Select
            value={smestajId}
            onValueChange={setSmestajId}
            disabled={!grupaId || initialLoading}
          >
            <SelectTrigger className="w-64">
              <SelectValue placeholder={grupaId ? "Izaberi smeštaj" : "Prvo izaberi grupu"} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="sve">Prikaži sve</SelectItem>
              {smestajiGrupe.map((s) => (
                <SelectItem key={s.id} value={String(s.id)}>{s.naziv}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        {loading && <Loader2 className="w-5 h-5 animate-spin text-muted-foreground mb-2" />}
      </div>

      {/* Grafik — jedan smeštaj ili "Prikaži sve" (po jedna sekcija za svaki smeštaj grupe) */}
      {!hasSelection ? (
        <div className="rounded-md border py-16 text-center text-muted-foreground text-sm">
          Izaberite mesto, grupu perioda i smeštaj za prikaz grafika
        </div>
      ) : loading && allSekcije.length === 0 ? (
        <div className="py-16 text-center"><Loader2 className="w-6 h-6 animate-spin mx-auto text-muted-foreground" /></div>
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
        <DialogContent className="max-w-md">
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
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setUgovorOpen(false);
                    navigate(`/prodaja/rezervacije?u=${encodeURIComponent(ugovorDetail.kljuc || ugovorKljuc)}`);
                  }}
                >
                  <ExternalLink className="w-4 h-4 mr-2" />Otvori rezervaciju
                </Button>
                <Button
                  variant="outline"
                  size="sm"
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
        <DialogContent className="gap-5 rounded-2xl p-5 shadow-xl sm:max-w-lg sm:rounded-2xl sm:p-6">
          <DialogHeader className="text-left">
            <div className="mb-2 flex h-11 w-11 items-center justify-center rounded-xl bg-green-600/10 text-green-600">
              <CalendarCheck2 className="h-6 w-6" aria-hidden="true" />
            </div>
            <DialogTitle className="text-xl tracking-tight">Slobodan termin</DialogTitle>
            <DialogDescription>Izaberite način rezervacije za odabrani boravak.</DialogDescription>
          </DialogHeader>
          <div className="space-y-3 rounded-xl border border-border/60 bg-muted/40 p-4">
            <div className="flex items-center gap-3">
              <BedDouble className="h-5 w-5 shrink-0 text-muted-foreground" aria-hidden="true" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold">{slotSec?.smestaj.naziv || "—"}</p>
                <p className="text-xs text-muted-foreground">Soba {slotSoba?.broj_sobe || "—"}</p>
              </div>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-green-600/10 px-2.5 py-1 text-xs font-medium text-green-600">
                <span className="h-1.5 w-1.5 rounded-full bg-green-600" />
                Slobodno
              </span>
            </div>
            <div className="flex items-center gap-2 border-t border-border/60 pt-3 text-sm">
              <CalendarDays className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
              <span className="font-medium tabular-nums">
                {slotPeriod ? `${slotPeriod.datum_od} – ${slotPeriod.datum_do}` : "—"}
              </span>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Button
              className="h-auto min-h-14 w-full gap-2 rounded-xl bg-green-600 px-2 py-3 text-white shadow-sm transition-colors hover:bg-green-700 sm:px-3"
              onClick={klasicnaRez}
            >
              <ClipboardList className="h-5 w-5 shrink-0" aria-hidden="true" />
              <span className="whitespace-normal text-xs leading-snug sm:text-sm">Klasična rezervacija</span>
            </Button>
            <Button
              className="h-auto min-h-14 w-full gap-2 rounded-xl bg-blue-600 px-2 py-3 text-white shadow-sm transition-colors hover:bg-blue-700 sm:px-3"
              onClick={() => { setSlotOtvoren(false); setBrzaOtvoren(true); }}
            >
              <Zap className="h-5 w-5 shrink-0" aria-hidden="true" />
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
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">Datum od</Label>
                <Input type="date" value={brzaOd} onChange={(e) => setBrzaOd(e.target.value)} />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">Datum do</Label>
                <Input type="date" value={brzaDo} onChange={(e) => setBrzaDo(e.target.value)} />
              </div>
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
