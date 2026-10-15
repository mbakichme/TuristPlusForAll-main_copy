import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import type { Mesto, PeriodGrupa, Smestaj } from "../types";
import { apiFetch } from "../lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Loader2, Pencil, Receipt, Search, CalendarDays, Lock, Trash2 } from "lucide-react";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { srLatn } from "date-fns/locale";
import { toast } from "sonner";

// ── Tipovi (ugovor backend-a) ───────────────────────────────────────────────

interface SablonSoba {
  id: number; broj_sobe: string; tip: string; opis: string; opis_dodatno: string;
  izvor_soba_id?: number; virtuelna?: boolean; nova?: boolean;
}
interface SablonPeriod { id: number; datum_od: string; datum_do: string; nocenja: number; }
interface SablonCena { soba_id: number; period_id: number; cena: string; }

interface CenovnikDraft {
  naziv: string;
  mesto_id: number;
  grupa_id: number;
  smestaj_id: number;
  sobe: SablonSoba[];
  periodi: SablonPeriod[];
  cene: SablonCena[];
  datumod: string | null;
  datumdo: string | null;
  opis: string;
}

interface CenovnikDetail extends CenovnikDraft { id: number; uuid: string; }

interface CenovnikRow {
  id: number;
  uuid: string;
  naziv: string;
  opis: string;
  mesto_id: number;
  grupa_id: number;
  smestaj_id: number;
  datumod: string | null;
  datumdo: string | null;
}

type TabKey = "kreiranje" | "izmena";

// ── Pomoćne funkcije ────────────────────────────────────────────────────────

const cellKey = (sobaId: number, periodId: number) => `${sobaId}:${periodId}`;

/** Zarez je decimalni separator. Ne prepravljaj nevažeći iznos u drugu cenu. */
function normalizeCena(raw: string): string {
  return raw.replace(/,/g, ".");
}

/** Vrednost ćelije za slanje: prazno → null (izostavlja se iz payload-a), inače string. */
function cenaZaPayload(v: string | undefined): string | null {
  if (v === undefined) return null;
  const t = v.trim().replace(/\.$/, "");
  if (t === "") return null;
  if (!/^\d*(?:\.\d{1,2})?$/.test(t) || !Number.isFinite(Number(t)) || Number(t) >= 1e12) {
    throw new Error("Cena mora biti nenegativan broj sa najviše dve decimale (npr. 125,50)");
  }
  return t;
}

/** Niz cena iz odgovora → mapa ćelija (ključ soba:period → tekst cene). */
function ceneMap(cene: SablonCena[]): Record<string, string> {
  const m: Record<string, string> = {};
  for (const c of cene) m[cellKey(c.soba_id, c.period_id)] = normalizeCena(c.cena ?? "").replace(/\.0+$/, "");
  return m;
}

/** Matrica ćelija → payload za POST/PUT (prazna polja se izostavljaju, 0 ostaje). */
function ceneZaPayload(cene: Record<string, string>, sobe: SablonSoba[], periodi: SablonPeriod[]): SablonCena[] {
  const out: SablonCena[] = [];
  for (const s of sobe) {
    for (const p of periodi) {
      const cena = cenaZaPayload(cene[cellKey(s.id, p.id)]);
      if (cena !== null) out.push({ soba_id: s.id, period_id: p.id, cena });
    }
  }
  return out;
}

/** Otisak stanja matrice za poređenje „nesačuvano“. */
function snapshotStringa(cene: Record<string, string>, od: string, ddo: string, opis: string): string {
  return JSON.stringify({ c: cene, od, ddo, opis });
}

/** ISO yyyy-mm-dd → dd.mm.yyyy (prikaz); „—“ za prazno. */
function fmtIso(iso: string | null | undefined): string {
  if (!iso) return "—";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  return m ? `${m[3]}.${m[2]}.${m[1]}` : iso;
}

/** Srpska množina: 1 soba / 2 sobe / 5 soba. */
function pluralSr(n: number, jedan: string, nekoliko: string, vise: string): string {
  const m10 = n % 10;
  const m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return jedan;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return nekoliko;
  return vise;
}

// ── Matrica cena (zajednička za oba taba) ───────────────────────────────────

interface MatricaCenaProps {
  sobe: SablonSoba[];
  periodi: SablonPeriod[];
  cene: Record<string, string>;
  onCenaChange: (sobaId: number, periodId: number, vrednost: string) => void;
  disabled?: boolean;
}

function MatricaCena({ sobe, periodi, cene, onCenaChange, disabled }: MatricaCenaProps) {
  return (
    <div className="overflow-x-auto rounded-lg border bg-card">
      <table
        className="table-fixed border-collapse text-sm"
        style={{ width: `${256 + Math.max(periodi.length, 1) * 76}px` }}
      >
        <thead>
          <tr>
            <th className="sticky left-0 z-20 w-20 min-w-[5rem] border-b bg-muted px-2 py-2 text-left text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              Broj sobe
            </th>
            <th className="sticky left-20 z-20 w-44 min-w-[11rem] border-b border-r bg-muted px-2 py-2 text-left text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              Struktura
            </th>
            {periodi.map((p) => (
              <th key={p.id} className="w-[76px] border-b bg-muted px-1 py-1.5 text-center">
                <div className="whitespace-nowrap text-xs font-semibold text-foreground">
                  <div>{fmtIso(p.datum_od).slice(0, 5)}</div>
                  <div>{fmtIso(p.datum_do).slice(0, 5)}</div>
                </div>
                <div className="mt-0.5 text-[10px] font-normal text-muted-foreground">
                  {p.nocenja} {pluralSr(p.nocenja, "noćenje", "noćenja", "noćenja")}
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sobe.map((soba) => {
            const struktura = [soba.tip, soba.opis].filter(Boolean).join(" · ");
            const virtTitle = soba.virtuelna && soba.izvor_soba_id !== undefined
              ? `Virtuelna soba — nastala iz sobe ${soba.izvor_soba_id}`
              : undefined;
            return (
              <tr
                key={soba.id}
                title={virtTitle}
                className={cn("hover:bg-muted/40", soba.virtuelna && "bg-violet-500/5 hover:bg-violet-500/10")}
              >
                <td
                  className={cn(
                    "sticky left-0 z-10 w-20 min-w-[5rem] border-b bg-card px-2 py-1.5 text-[13px] font-semibold tabular-nums",
                    soba.virtuelna && "border-l-2 border-l-violet-500/60",
                  )}
                >
                  {soba.virtuelna && (
                    <span aria-hidden className="pointer-events-none absolute inset-0 -z-10 bg-violet-500/5" />
                  )}
                  {soba.virtuelna ? (
                    <span className="inline-flex max-w-full items-center truncate rounded-full border border-violet-500/40 bg-violet-500/10 px-1.5 py-px text-[11px] italic text-violet-600 dark:text-violet-400">
                      {soba.broj_sobe || "—"}
                    </span>
                  ) : (
                    <span>{soba.broj_sobe || "—"}</span>
                  )}
                </td>
                <td className="sticky left-20 z-10 w-44 min-w-[11rem] border-b border-r bg-card px-2 py-1.5">
                  {soba.virtuelna && (
                    <span aria-hidden className="pointer-events-none absolute inset-0 -z-10 bg-violet-500/5" />
                  )}
                  <div className="truncate text-[13px] font-medium" title={struktura}>
                    {struktura || "—"}
                  </div>
                  {soba.nova ? (
                    <div className="text-[9px] font-medium italic leading-tight text-violet-600 dark:text-violet-400">
                      nova
                    </div>
                  ) : null}
                  {soba.opis_dodatno ? (
                    <div className="truncate text-[9px] leading-tight text-muted-foreground" title={soba.opis_dodatno}>
                      {soba.opis_dodatno}
                    </div>
                  ) : null}
                </td>
                {periodi.map((p) => {
                  const k = cellKey(soba.id, p.id);
                  return (
                    <td key={p.id} className="w-[76px] border-b px-1 py-1.5">
                      <Input
                        value={cene[k] ?? ""}
                        onChange={(e) => onCenaChange(soba.id, p.id, normalizeCena(e.target.value))}
                        disabled={disabled}
                        inputMode="decimal"
                        autoComplete="off"
                        aria-label={`Cena — soba ${soba.broj_sobe}, period ${fmtIso(p.datum_od)}–${fmtIso(p.datum_do)}`}
                        className="h-8 min-w-0 border-input/60 bg-background px-1.5 text-center text-xs tabular-nums"
                      />
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ── Opcije iznad tabele: Aktivan od / Aktivan do / Sačuvaj ──────────────────

interface OpcijeDatumaProps {
  idPrefix: string;
  od: string;
  ddo: string;
  onOd: (v: string) => void;
  onDdo: (v: string) => void;
  opis: string;
  onOpis: (v: string) => void;
  onSave: () => void;
  saving: boolean;
  disabled?: boolean;
  label: string;
  onIzmeni?: () => void;
  izmeniDisabled?: boolean;
}

function DatumCenovnika({ id, value, onChange, disabled }: {
  id: string; value: string; onChange: (value: string) => void; disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const selected = value ? new Date(`${value}T00:00:00`) : undefined;
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          id={id}
          variant="outline"
          disabled={disabled}
          className={cn("h-9 w-44 justify-between bg-background font-normal tabular-nums", !value && "text-muted-foreground")}
        >
          <span>{value ? fmtIso(value) : "dd.mm.yyyy"}</span>
          <CalendarDays className="h-4 w-4 text-muted-foreground" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-auto rounded-xl p-0 shadow-lg">
        <Calendar
          mode="single"
          locale={srLatn}
          weekStartsOn={1}
          captionLayout="dropdown"
          selected={selected}
          defaultMonth={selected}
          startMonth={new Date(2000, 0, 1)}
          endMonth={new Date(2100, 11, 31)}
          onSelect={(day) => {
            if (!day) return;
            onChange(`${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, "0")}-${String(day.getDate()).padStart(2, "0")}`);
            setOpen(false);
          }}
        />
      </PopoverContent>
    </Popover>
  );
}

function OpcijeDatuma({ idPrefix, od, ddo, onOd, onDdo, opis, onOpis, onSave, saving, disabled, label, onIzmeni, izmeniDisabled }: OpcijeDatumaProps) {
  return (
    <div className="flex flex-wrap items-end gap-3 rounded-lg border bg-muted/40 px-3 py-2.5">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${idPrefix}-od`} className="text-xs text-muted-foreground">Aktivan od</Label>
        <DatumCenovnika id={`${idPrefix}-od`} value={od} onChange={onOd} disabled={disabled} />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${idPrefix}-do`} className="text-xs text-muted-foreground">Aktivan do</Label>
        <DatumCenovnika id={`${idPrefix}-do`} value={ddo} onChange={onDdo} disabled={disabled} />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${idPrefix}-opis`} className="text-xs text-muted-foreground">Opis cenovnika</Label>
        <Input
          id={`${idPrefix}-opis`}
          value={opis}
          onChange={(e) => onOpis(e.target.value)}
          disabled={disabled}
          maxLength={500}
          placeholder="npr. Termin 22.06–29.06, polazak iz Novog Sada"
          className="h-9 w-72 min-w-56 bg-background font-normal"
        />
      </div>
      <Button onClick={onSave} disabled={saving || disabled}>
        {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
        {label}
      </Button>
      {onIzmeni && (
        <Button variant="outline" onClick={onIzmeni} disabled={izmeniDisabled}>
          <Pencil className="mr-2 h-4 w-4" />
          Izmeni cenovnik
        </Button>
      )}
    </div>
  );
}

// ── Zajednička sadržina urednika (naslov + opcije + matrica) ────────────────

interface UrednikCenovnikaProps {
  idPrefix: string;
  naziv: string;
  badge?: ReactNode;
  prljavo?: boolean;
  opis: string;
  sobe: SablonSoba[];
  periodi: SablonPeriod[];
  cene: Record<string, string>;
  onCenaChange: (sobaId: number, periodId: number, vrednost: string) => void;
  od: string;
  ddo: string;
  onOd: (v: string) => void;
  onDdo: (v: string) => void;
  opisCenovnika: string;
  onOpisCenovnika: (v: string) => void;
  onSave: () => void;
  saving: boolean;
  disabled?: boolean;
  saveLabel: string;
  onIzmeni?: () => void;
  izmeniDisabled?: boolean;
  zakljucano?: boolean;
}

function UrednikCenovnika(p: UrednikCenovnikaProps) {
  return (
    <Card>
      <CardHeader className="pb-4">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <CardTitle className="truncate text-base" title={p.naziv}>{p.naziv || "Cenovnik"}</CardTitle>
            <CardDescription>
              {p.opis} · {p.sobe.length} {pluralSr(p.sobe.length, "soba", "sobe", "soba")} ·{" "}
              {p.periodi.length} {pluralSr(p.periodi.length, "period", "perioda", "perioda")}
            </CardDescription>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {p.zakljucano ? (
              <span className="inline-flex items-center gap-1.5 rounded-full border border-sky-500/40 bg-sky-500/10 px-2.5 py-0.5 text-xs font-medium text-sky-600 dark:text-sky-500">
                <Lock className="h-3 w-3" />
                Zaključano
              </span>
            ) : null}
            {p.prljavo ? (
              <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-500/40 bg-amber-500/10 px-2.5 py-0.5 text-xs font-medium text-amber-600 dark:text-amber-500">
                Nesačuvane izmene
              </span>
            ) : null}
            {p.badge}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <OpcijeDatuma
          idPrefix={p.idPrefix}
          od={p.od}
          ddo={p.ddo}
          onOd={p.onOd}
          onDdo={p.onDdo}
          opis={p.opisCenovnika}
          onOpis={p.onOpisCenovnika}
          onSave={p.onSave}
          saving={p.saving}
          disabled={p.disabled}
          label={p.saveLabel}
          onIzmeni={p.onIzmeni}
          izmeniDisabled={p.izmeniDisabled}
        />
        {p.sobe.length === 0 || p.periodi.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            Šablon ne sadrži {p.sobe.length === 0 ? "sobe" : "periode"} za izabrani smeštaj.
          </p>
        ) : (
          <MatricaCena
            sobe={p.sobe}
            periodi={p.periodi}
            cene={p.cene}
            onCenaChange={p.onCenaChange}
            disabled={p.disabled}
          />
        )}
      </CardContent>
    </Card>
  );
}

// ── Glavna stranica ─────────────────────────────────────────────────────────

export default function CenovniciPage() {
  const navigate = useNavigate();
  // Referentni podaci
  const [mesta, setMesta] = useState<Mesto[]>([]);
  const [grupe, setGrupe] = useState<PeriodGrupa[]>([]);
  const [smestaji, setSmestaji] = useState<Smestaj[]>([]);
  const [loading, setLoading] = useState(true);

  const [tab, setTab] = useState<TabKey>("kreiranje");

  // Tab „Kreiranje cenovnika“
  const [mestoId, setMestoId] = useState("");
  const [grupaId, setGrupaId] = useState("");
  const [smestajId, setSmestajId] = useState("");
  const [createDraft, setCreateDraft] = useState<CenovnikDraft | null>(null);
  const [createCene, setCreateCene] = useState<Record<string, string>>({});
  const [createOd, setCreateOd] = useState("");
  const [createDo, setCreateDo] = useState("");
  const [createOpis, setCreateOpis] = useState("");
  const [createSnapshot, setCreateSnapshot] = useState<string | null>(null);
  const [createSaved, setCreateSaved] = useState<{ id: number; uuid: string } | null>(null);
  const [createZakljucano, setCreateZakljucano] = useState(false);
  const [loadingSablon, setLoadingSablon] = useState(false);
  const [savingCreate, setSavingCreate] = useState(false);
  const sablonReq = useRef(0);

  // Tab „Izmena kreiranih cenovnika“
  const [q, setQ] = useState("");
  const [lista, setLista] = useState<CenovnikRow[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [editDetail, setEditDetail] = useState<CenovnikDetail | null>(null);
  const [editCene, setEditCene] = useState<Record<string, string>>({});
  const [editOd, setEditOd] = useState("");
  const [editDo, setEditDo] = useState("");
  const [editOpis, setEditOpis] = useState("");
  const [editSnapshot, setEditSnapshot] = useState<string | null>(null);
  const [loadingEdit, setLoadingEdit] = useState(false);
  const [savingEdit, setSavingEdit] = useState(false);
  const listReq = useRef(0);
  const editReq = useRef(0);
  const editorRef = useRef<HTMLDivElement | null>(null);

  // Potvrda odbacivanja nesačuvanih izmena
  const [confirmOpen, setConfirmOpen] = useState(false);
  const pendingConfirm = useRef<(() => void) | null>(null);

  // Brisanje kompletnog cenovnika (tab Izmena)
  const [obrisiRed, setObrisiRed] = useState<CenovnikRow | null>(null);
  const [deleting, setDeleting] = useState(false);

  // Referentni podaci: /mesto, /period-grupa, /smestaj
  useEffect(() => {
    let otkazano = false;
    Promise.all([
      apiFetch<Mesto[]>("/mesto"),
      apiFetch<PeriodGrupa[]>("/period-grupa"),
      apiFetch<Smestaj[]>("/smestaj"),
    ])
      .then(([m, g, s]) => {
        if (otkazano) return;
        setMesta(m);
        setGrupe(g);
        setSmestaji(s);
      })
      .catch(() => {
        if (!otkazano) toast.error("Učitavanje referentnih podataka nije uspelo");
      })
      .finally(() => {
        if (!otkazano) setLoading(false);
      });
    return () => { otkazano = true; };
  }, []);

  // Pretraga cenovnika — 400 ms debounce, zaštita od zastarelih odgovora
  useEffect(() => {
    const req = ++listReq.current;
    const t = setTimeout(() => {
      setListLoading(true);
      const qs = q.trim() ? `?q=${encodeURIComponent(q.trim())}` : "";
      apiFetch<CenovnikRow[]>(`/cenovnici${qs}`)
        .then((rows) => { if (req === listReq.current) setLista(rows); })
        .catch(() => { if (req === listReq.current) toast.error("Učitavanje cenovnika nije uspelo"); })
        .finally(() => { if (req === listReq.current) setListLoading(false); });
    }, 400);
    return () => clearTimeout(t);
  }, [q]);

  // Grupe perioda izabranog mesta: mesto.grupe, fallback na staro grupa_datuma
  const grupeMesta = useMemo(() => {
    const m = mesta.find((x) => String(x.id) === mestoId);
    if (!m) return [] as { id: number; naziv: string }[];
    const ids = m.grupe && m.grupe.length > 0 ? m.grupe : m.grupa_datuma ? [m.grupa_datuma] : [];
    const nazivi = new Map<number, string>();
    (m.grupe_nazivi ?? []).forEach((n, i) => {
      if (m.grupe && m.grupe[i] != null) nazivi.set(m.grupe[i], n);
    });
    for (const g of grupe) if (!nazivi.has(g.id)) nazivi.set(g.id, g.naziv);
    return ids.map((id) => ({ id, naziv: nazivi.get(id) ?? `Grupa ${id}` }));
  }, [mesta, mestoId, grupe]);

  // Smeštaji filtrirani po mestu i grupi datuma
  const smestajiFiltrirani = useMemo(() => {
    const m = Number(mestoId);
    const g = Number(grupaId);
    if (!m || !g) return [];
    return smestaji.filter((s) => s.mesto === m && s.grupa_datuma === g);
  }, [smestaji, mestoId, grupaId]);

  const createDirty = createSnapshot !== null
    && snapshotStringa(createCene, createOd, createDo, createOpis) !== createSnapshot;
  const editDirty = editSnapshot !== null
    && snapshotStringa(editCene, editOd, editDo, editOpis) !== editSnapshot;

  useEffect(() => {
    if (!createDirty && !editDirty) return;
    const preZatvaranja = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    const preNavigacije = (event: MouseEvent) => {
      const anchor = event.target instanceof Element ? event.target.closest("a[href]") : null;
      if (!(anchor instanceof HTMLAnchorElement) || anchor.target === "_blank" || anchor.hasAttribute("download")) return;
      if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      if (anchor.origin === window.location.origin && anchor.pathname === window.location.pathname) return;
      event.preventDefault();
      event.stopPropagation();
      const destination = anchor.href;
      pendingConfirm.current = () => {
        if (anchor.origin === window.location.origin) {
          navigate(new URL(destination).pathname + new URL(destination).search + new URL(destination).hash);
        } else {
          window.location.assign(destination);
        }
      };
      setConfirmOpen(true);
    };
    window.addEventListener("beforeunload", preZatvaranja);
    document.addEventListener("click", preNavigacije, true);
    return () => {
      window.removeEventListener("beforeunload", preZatvaranja);
      document.removeEventListener("click", preNavigacije, true);
    };
  }, [createDirty, editDirty, navigate]);

  function uzPotvrdu(prljavo: boolean, action: () => void) {
    if (prljavo) {
      pendingConfirm.current = action;
      setConfirmOpen(true);
      return;
    }
    action();
  }

  function izvrsiPotvrdu() {
    const fn = pendingConfirm.current;
    pendingConfirm.current = null;
    setConfirmOpen(false);
    fn?.();
  }

  function resetujCreateDraft() {
    sablonReq.current += 1; // poništi odgovore šablona u letu
    setCreateDraft(null);
    setCreateCene({});
    setCreateOd("");
    setCreateDo("");
    setCreateOpis("");
    setCreateSnapshot(null);
    setCreateSaved(null);
    setCreateZakljucano(false);
  }

  function izborMesta(v: string) {
    if (v === mestoId) return;
    uzPotvrdu(createDirty, () => {
      setMestoId(v);
      setGrupaId("");
      setSmestajId("");
      resetujCreateDraft();
    });
  }

  function izborGrupe(v: string) {
    if (v === grupaId) return;
    uzPotvrdu(createDirty, () => {
      setGrupaId(v);
      setSmestajId("");
      resetujCreateDraft();
    });
  }

  function izborSmestaja(v: string) {
    if (v === smestajId) return;
    uzPotvrdu(createDirty, () => {
      setSmestajId(v);
      resetujCreateDraft();
    });
  }

  function primeniCreateDraft(d: CenovnikDraft, saved: { id: number; uuid: string } | null) {
    const cene = ceneMap(d.cene ?? []);
    setCreateDraft(d);
    setCreateCene(cene);
    setCreateOd(d.datumod ?? "");
    setCreateDo(d.datumdo ?? "");
    setCreateOpis(d.opis ?? "");
    setCreateSnapshot(snapshotStringa(cene, d.datumod ?? "", d.datumdo ?? "", d.opis ?? ""));
    setCreateSaved(saved);
  }

  function klikKreiraj() {
    if (!mestoId || !grupaId || !smestajId || loadingSablon || savingCreate) return;
    uzPotvrdu(createDirty, () => { void ucitajSablon(); });
  }

  async function ucitajSablon() {
    const req = ++sablonReq.current;
    setLoadingSablon(true);
    try {
      const params = new URLSearchParams({
        mesto_id: mestoId,
        grupa_id: grupaId,
        smestaj_id: smestajId,
      });
      const d = await apiFetch<CenovnikDraft>(`/cenovnici/sablon?${params}`);
      if (req !== sablonReq.current) return;
      setCreateZakljucano(false); // novi šablon je uvek otključan
      primeniCreateDraft(d, null);
    } catch (e) {
      if (req !== sablonReq.current) return;
      toast.error(e instanceof Error ? e.message : "Učitavanje šablona nije uspelo");
    } finally {
      if (req === sablonReq.current) setLoadingSablon(false);
    }
  }

  async function sacuvajCreate() {
    if (!createDraft || savingCreate) return;
    if (!createOd || !createDo) {
      toast.error("Aktivan od i aktivan do su obavezni");
      return;
    }
    if (createDo < createOd) {
      toast.error("Datum 'Aktivan do' ne može biti pre datuma 'Aktivan od'");
      return;
    }
    setSavingCreate(true);
    try {
      const cene = ceneZaPayload(createCene, createDraft.sobe, createDraft.periodi);
      const detail = createSaved
        ? await apiFetch<CenovnikDetail>(`/cenovnici/${createSaved.id}`, {
            method: "PUT",
            body: JSON.stringify({ datumod: createOd, datumdo: createDo, cene, opis: createOpis }),
          })
        : await apiFetch<CenovnikDetail>("/cenovnici", {
            method: "POST",
            body: JSON.stringify({
              mesto_id: createDraft.mesto_id,
              grupa_id: createDraft.grupa_id,
              smestaj_id: createDraft.smestaj_id,
              datumod: createOd,
              datumdo: createDo,
              cene,
              opis: createOpis,
            }),
          });
      const biloKreiranje = !createSaved;
      primeniCreateDraft(detail, { id: detail.id, uuid: detail.uuid });
      setCreateZakljucano(true); // posle čuvanja polja cenovnika su zaključana
      if (editDetail?.id === detail.id) {
        const c = ceneMap(detail.cene ?? []);
        setEditDetail(detail);
        setEditCene(c);
        setEditOd(detail.datumod ?? "");
        setEditDo(detail.datumdo ?? "");
        setEditOpis(detail.opis ?? "");
        setEditSnapshot(snapshotStringa(c, detail.datumod ?? "", detail.datumdo ?? "", detail.opis ?? ""));
      }
      osveziListu();
      toast.success(biloKreiranje ? "Cenovnik je kreiran" : "Izmene cenovnika su sačuvane");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Čuvanje cenovnika nije uspelo");
    } finally {
      setSavingCreate(false);
    }
  }

  function osveziListu() {
    const req = ++listReq.current;
    setListLoading(true);
    const qs = q.trim() ? `?q=${encodeURIComponent(q.trim())}` : "";
    apiFetch<CenovnikRow[]>(`/cenovnici${qs}`)
      .then((rows) => { if (req === listReq.current) setLista(rows); })
      .catch(() => { if (req === listReq.current) toast.error("Učitavanje cenovnika nije uspelo"); })
      .finally(() => { if (req === listReq.current) setListLoading(false); });
  }

  async function obrisiCenovnik() {
    if (!obrisiRed || deleting) return;
    const red = obrisiRed;
    setDeleting(true);
    try {
      await apiFetch(`/cenovnici/${red.id}`, { method: "DELETE" });
      if (editDetail?.id === red.id) {
        setEditDetail(null);
        setEditCene({});
        setEditOd("");
        setEditDo("");
        setEditOpis("");
        setEditSnapshot(null);
      }
      toast.success(`Cenovnik „${red.naziv}“ je obrisan`);
      setObrisiRed(null);
      osveziListu();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Brisanje cenovnika nije uspelo");
    } finally {
      setDeleting(false);
    }
  }

  function otvoriEdit(row: CenovnikRow) {
    if (savingEdit) return; // ne menjaj metricu dok traje čuvanje
    uzPotvrdu(editDirty, () => { void ucitajEdit(row.id); });
  }

  async function ucitajEdit(id: number) {
    const req = ++editReq.current;
    setLoadingEdit(true);
    try {
      const d = await apiFetch<CenovnikDetail>(`/cenovnici/${id}`);
      if (req !== editReq.current) return;
      const cene = ceneMap(d.cene ?? []);
      setEditDetail(d);
      setEditCene(cene);
      setEditOd(d.datumod ?? "");
      setEditDo(d.datumdo ?? "");
      setEditOpis(d.opis ?? "");
      setEditSnapshot(snapshotStringa(cene, d.datumod ?? "", d.datumdo ?? "", d.opis ?? ""));
      requestAnimationFrame(() => editorRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
    } catch (e) {
      if (req !== editReq.current) return;
      toast.error(e instanceof Error ? e.message : "Učitavanje cenovnika nije uspelo");
    } finally {
      if (req === editReq.current) setLoadingEdit(false);
    }
  }

  async function sacuvajEdit() {
    if (!editDetail || savingEdit) return;
    if (!editOd || !editDo) {
      toast.error("Aktivan od i aktivan do su obavezni");
      return;
    }
    if (editDo < editOd) {
      toast.error("Datum 'Aktivan do' ne može biti pre datuma 'Aktivan od'");
      return;
    }
    setSavingEdit(true);
    try {
      const cene = ceneZaPayload(editCene, editDetail.sobe, editDetail.periodi);
      const d = await apiFetch<CenovnikDetail>(`/cenovnici/${editDetail.id}`, {
        method: "PUT",
        body: JSON.stringify({ datumod: editOd, datumdo: editDo, cene, opis: editOpis }),
      });
      const c = ceneMap(d.cene ?? []);
      setEditDetail(d);
      setEditCene(c);
      setEditOd(d.datumod ?? "");
      setEditDo(d.datumdo ?? "");
      setEditOpis(d.opis ?? "");
      setEditSnapshot(snapshotStringa(c, d.datumod ?? "", d.datumdo ?? "", d.opis ?? ""));
      if (createSaved?.id === d.id) primeniCreateDraft(d, { id: d.id, uuid: d.uuid });
      toast.success("Izmene cenovnika su sačuvane");
      osveziListu();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Čuvanje cenovnika nije uspelo");
    } finally {
      setSavingEdit(false);
    }
  }

  const postaviCreateCenu = (sobaId: number, periodId: number, vrednost: string) =>
    setCreateCene((prev) => ({ ...prev, [cellKey(sobaId, periodId)]: vrednost }));
  const postaviEditCenu = (sobaId: number, periodId: number, vrednost: string) =>
    setEditCene((prev) => ({ ...prev, [cellKey(sobaId, periodId)]: vrednost }));

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold">Cenovnici</h1>
        <p className="text-sm text-muted-foreground">Matrica cena smeštaja po grupama perioda</p>
      </div>

      <Tabs value={tab} onValueChange={(v) => setTab(v as TabKey)}>
        <TabsList className="h-auto p-2 gap-3">
          <TabsTrigger
            value="kreiranje"
            className="h-12 rounded-lg px-9 text-base font-semibold data-[state=active]:shadow-md"
          >
            Kreiranje cenovnika
          </TabsTrigger>
          <TabsTrigger
            value="izmena"
            className="h-12 rounded-lg px-9 text-base font-semibold data-[state=active]:shadow-md"
          >
            Izmena kreiranih cenovnika
          </TabsTrigger>
        </TabsList>

        {/* ── Tab 1: Kreiranje cenovnika ── */}
        <TabsContent value="kreiranje" className="mt-4 space-y-4">
          <Card>
            <CardHeader className="pb-4">
              <CardTitle className="text-base">Izbor aranžmana</CardTitle>
              <CardDescription>
                Kaskadno: mesto → njegova grupa perioda → smeštaj u toj grupi. Šablon učitava sve sobe i periode.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-wrap items-end gap-3">
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">Mesto</Label>
                <Select value={mestoId} onValueChange={izborMesta} disabled={loadingSablon || savingCreate}>
                  <SelectTrigger className="h-9 w-52 bg-background">
                    <SelectValue placeholder="Izaberite mesto" />
                  </SelectTrigger>
                  <SelectContent>
                    {mesta.length === 0 ? (
                      <SelectItem value="_nema" disabled>Nema mesta</SelectItem>
                    ) : (
                      mesta.map((m) => (
                        <SelectItem key={m.id} value={String(m.id)}>{m.naziv}</SelectItem>
                      ))
                    )}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">Grupa perioda</Label>
                <Select
                  value={grupaId}
                  onValueChange={izborGrupe}
                  disabled={!mestoId || loadingSablon || savingCreate}
                >
                  <SelectTrigger className="h-9 w-56 bg-background">
                    <SelectValue placeholder={mestoId ? "Izaberite grupu" : "Prvo izaberite mesto"} />
                  </SelectTrigger>
                  <SelectContent>
                    {grupeMesta.length === 0 ? (
                      <SelectItem value="_nema" disabled>Mesto nema grupa perioda</SelectItem>
                    ) : (
                      grupeMesta.map((g) => (
                        <SelectItem key={g.id} value={String(g.id)}>{g.naziv}</SelectItem>
                      ))
                    )}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">Smeštaj</Label>
                <Select
                  value={smestajId}
                  onValueChange={izborSmestaja}
                  disabled={!grupaId || loadingSablon || savingCreate}
                >
                  <SelectTrigger className="h-9 w-56 bg-background">
                    <SelectValue placeholder={grupaId ? "Izaberite smeštaj" : "Prvo izaberite grupu"} />
                  </SelectTrigger>
                  <SelectContent>
                    {smestajiFiltrirani.length === 0 ? (
                      <SelectItem value="_nema" disabled>Nema smeštaja za ovu grupu</SelectItem>
                    ) : (
                      smestajiFiltrirani.map((s) => (
                        <SelectItem key={s.id} value={String(s.id)}>{s.naziv}</SelectItem>
                      ))
                    )}
                  </SelectContent>
                </Select>
              </div>
              <Button
                onClick={klikKreiraj}
                disabled={!mestoId || !grupaId || !smestajId || loadingSablon || savingCreate}
              >
                {loadingSablon ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Receipt className="mr-2 h-4 w-4" />
                )}
                Kreiraj cenovnik
              </Button>
            </CardContent>
          </Card>

          {createDraft ? (
            <UrednikCenovnika
              idPrefix="create"
              naziv={createDraft.naziv}
              prljavo={createDirty}
              opis="Unesite cene po periodima"
              badge={createSaved ? (
                <Badge
                  variant="outline"
                  className="max-w-72 truncate font-mono text-[10px] font-normal"
                  title={createSaved.uuid}
                >
                  #{createSaved.id} · {createSaved.uuid}
                </Badge>
              ) : undefined}
              sobe={createDraft.sobe}
              periodi={createDraft.periodi}
              cene={createCene}
              onCenaChange={postaviCreateCenu}
              od={createOd}
              ddo={createDo}
              onOd={setCreateOd}
              onDdo={setCreateDo}
              opisCenovnika={createOpis}
              onOpisCenovnika={setCreateOpis}
              onSave={sacuvajCreate}
              saving={savingCreate}
              disabled={loadingSablon || savingCreate || createZakljucano}
              saveLabel="Sačuvaj cenovnik"
              onIzmeni={createZakljucano && createSaved ? () => {
                setCreateZakljucano(false);
                toast.info("Polja za unos cena su otključana");
              } : undefined}
              izmeniDisabled={savingCreate}
              zakljucano={createZakljucano}
            />
          ) : (
            <Card>
              <CardContent className="flex flex-col items-center justify-center gap-2 py-12 text-center">
                <Receipt className="h-8 w-8 text-muted-foreground/50" />
                <p className="max-w-md text-sm text-muted-foreground">
                  Izaberite mesto, grupu perioda i smeštaj, pa kliknite „Kreiraj cenovnik“ da učitate
                  matricu cena za sve sobe i periode.
                </p>
              </CardContent>
            </Card>
          )}
        </TabsContent>

        {/* ── Tab 2: Izmena kreiranih cenovnika ── */}
        <TabsContent value="izmena" className="mt-4 space-y-4">
          <Card>
            <CardHeader className="pb-4">
              <CardTitle className="text-base">Kreirani cenovnici</CardTitle>
              <CardDescription>
                Pretražite i izaberite cenovnik za izmenu. Korpicom u redu se briše kompletan cenovnik (trajno).
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="relative max-w-sm">
                <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  placeholder="Pretraži cenovnike…"
                  aria-label="Pretraga cenovnika"
                  className="bg-background pl-8 pr-8"
                />
                {listLoading ? (
                  <Loader2 className="absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 animate-spin text-muted-foreground" />
                ) : null}
              </div>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-16">ID</TableHead>
                    <TableHead>Naziv</TableHead>
                    <TableHead className="w-56">UUID</TableHead>
                    <TableHead className="w-32">Aktivan od</TableHead>
                    <TableHead className="w-32">Aktivan do</TableHead>
                    <TableHead className="w-24 text-right">Akcije</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {lista.length === 0 && !listLoading ? (
                    <TableRow>
                      <TableCell colSpan={6} className="py-8 text-center text-sm text-muted-foreground">
                        {q.trim() ? "Nema rezultata za zadatu pretragu." : "Još nema kreiranih cenovnika."}
                      </TableCell>
                    </TableRow>
                  ) : (
                    lista.map((row) => (
                      <TableRow
                        key={row.id}
                        onClick={() => otvoriEdit(row)}
                        className={cn(
                          "cursor-pointer",
                          editDetail?.id === row.id && "bg-primary/10 hover:bg-primary/10"
                        )}
                      >
                        <TableCell className="font-mono text-xs tabular-nums">{row.id}</TableCell>
                        <TableCell className="max-w-64 font-medium" title={row.naziv}>
                          <span className="block truncate">{row.naziv}</span>
                          {row.opis ? (
                            <span className="block max-w-64 truncate text-[11px] font-normal text-muted-foreground" title={row.opis}>
                              {row.opis}
                            </span>
                          ) : null}
                        </TableCell>
                        <TableCell className="font-mono text-[11px] text-muted-foreground">
                          <span className="block max-w-52 truncate" title={row.uuid}>{row.uuid}</span>
                        </TableCell>
                        <TableCell className="text-sm tabular-nums">{fmtIso(row.datumod)}</TableCell>
                        <TableCell className="text-sm tabular-nums">{fmtIso(row.datumdo)}</TableCell>
                        <TableCell className="text-right">
                          <div className="flex items-center justify-end gap-0.5">
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-8 w-8 text-muted-foreground hover:text-foreground"
                              aria-label={`Izmeni cenovnik ${row.naziv}`}
                              disabled={savingEdit || loadingEdit}
                              onClick={(e) => { e.stopPropagation(); otvoriEdit(row); }}
                            >
                              <Pencil className="h-4 w-4" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-8 w-8 text-destructive hover:text-destructive"
                              aria-label={`Obriši cenovnik ${row.naziv}`}
                              disabled={deleting}
                              onClick={(e) => { e.stopPropagation(); setObrisiRed(row); }}
                            >
                              <Trash2 className="h-4 w-4" />
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          <div ref={editorRef}>
            {loadingEdit ? (
              <Card>
                <CardContent className="flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" /> Učitavanje cenovnika…
                </CardContent>
              </Card>
            ) : editDetail ? (
              <UrednikCenovnika
                idPrefix="edit"
                naziv={editDetail.naziv}
                prljavo={editDirty}
                opis="Izmene se čuvaju na postojeći cenovnik"
                badge={
                  <Badge
                    variant="outline"
                    className="max-w-72 truncate font-mono text-[10px] font-normal"
                    title={editDetail.uuid}
                  >
                    #{editDetail.id} · {editDetail.uuid}
                  </Badge>
                }
                sobe={editDetail.sobe}
                periodi={editDetail.periodi}
                cene={editCene}
                onCenaChange={postaviEditCenu}
                od={editOd}
                ddo={editDo}
                onOd={setEditOd}
                onDdo={setEditDo}
                opisCenovnika={editOpis}
                onOpisCenovnika={setEditOpis}
                onSave={sacuvajEdit}
                saving={savingEdit}
                disabled={loadingEdit || savingEdit}
                saveLabel="Sačuvaj izmene"
              />
            ) : null}
          </div>
        </TabsContent>
      </Tabs>

      {/* Potvrda brisanja kompletnog cenovnika */}
      <AlertDialog
        open={obrisiRed !== null}
        onOpenChange={(o) => { if (!o) setObrisiRed(null); }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Obrisati cenovnik?</AlertDialogTitle>
            <AlertDialogDescription>
              Cenovnik „{obrisiRed?.naziv}“ (#{obrisiRed?.id}) će biti trajno obrisan zajedno sa svim
              unetim cenama. <span className="font-semibold text-destructive">Brisanje je trajno i ne može se opozvati.</span>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>Otkaži</AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => { e.preventDefault(); void obrisiCenovnik(); }}
              disabled={deleting}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {deleting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Trash2 className="mr-2 h-4 w-4" />}
              Obriši trajno
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Potvrda odbacivanja nesačuvanih izmena matrice */}
      <AlertDialog
        open={confirmOpen}
        onOpenChange={(o) => {
          if (!o) pendingConfirm.current = null;
          setConfirmOpen(o);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Odbaciti nesačuvane izmene?</AlertDialogTitle>
            <AlertDialogDescription>
              Matrica cena sadrži nesačuvane izmene. Ako nastavite, one će biti izgubljene.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Otkaži</AlertDialogCancel>
            <AlertDialogAction
              onClick={izvrsiPotvrdu}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Nastavi
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
