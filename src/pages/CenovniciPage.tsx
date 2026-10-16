import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import type { Mesto, PeriodGrupa, Smestaj } from "../types";
import { apiFetch } from "../lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Switch } from "@/components/ui/switch";
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
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
import { ChevronLeft, ChevronRight, Loader2, Pencil, Receipt, Search, CalendarDays, Lock, Trash2, SlidersHorizontal } from "lucide-react";
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

/** Unos cene uz uključeno „Kopiraj cene“: vrednost se odmah upisuje i u sve ostale
 *  sobe šablona sa istom strukturom (tip), istim opisom i iste vrste
 *  (stvarna → stvarne, virtuelna → virtuelne). Primer: soba 12 (1/3 · STD) →
 *  18, 21, 22… ; v12 (1/2 · STD) → v18, v6… */
function ceneSaKopiranjem(
  prev: Record<string, string>,
  sobe: SablonSoba[],
  sobaId: number,
  periodId: number,
  vrednost: string,
): Record<string, string> {
  const izvor = sobe.find((s) => s.id === sobaId);
  if (!izvor) return { ...prev, [cellKey(sobaId, periodId)]: vrednost };
  const next = { ...prev, [cellKey(sobaId, periodId)]: vrednost };
  for (const s of sobe) {
    if (s.id === izvor.id) continue;
    if (s.tip !== izvor.tip || (s.opis ?? "") !== (izvor.opis ?? "")) continue;
    if (!!s.virtuelna !== !!izvor.virtuelna) continue;
    next[cellKey(s.id, periodId)] = vrednost;
  }
  return next;
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
  onOpcijeTermina?: (periodId: number, label: string) => void;
}

function MatricaCena({ sobe, periodi, cene, onCenaChange, disabled, onOpcijeTermina }: MatricaCenaProps) {
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
                {onOpcijeTermina ? (
                  <button
                    type="button"
                    title="Opcije · Popusti za termin"
                    aria-label={`Opcije i popusti termin ${fmtIso(p.datum_od)}–${fmtIso(p.datum_do)}`}
                    disabled={disabled}
                    onClick={() => onOpcijeTermina(
                      p.id, `${fmtIso(p.datum_od)} – ${fmtIso(p.datum_do)}`)}
                    className="mt-1 inline-flex h-5 items-center rounded border border-border bg-card px-1.5 text-[9px] font-semibold tracking-wide text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground disabled:pointer-events-none disabled:opacity-50"
                  >
                    O·P
                  </button>
                ) : null}
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
  kopiraj: boolean;
  onKopirajChange: (v: boolean) => void;
  onOtvoriOpcije?: () => void;
  onOpcijeTermina?: (periodId: number, label: string) => void;
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
          <>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <label
                htmlFor={`${p.idPrefix}-kopiraj`}
                className="flex w-fit cursor-pointer items-center gap-2 text-sm"
              >
                <Checkbox
                  id={`${p.idPrefix}-kopiraj`}
                  checked={p.kopiraj}
                  onCheckedChange={(c) => p.onKopirajChange(c === true)}
                  disabled={p.disabled}
                />
                <span className="font-medium">Kopiraj cene</span>
                <span className="text-xs text-muted-foreground">
                  — uneta cena se automatski upisuje u sve sobe iste strukture i opisa
                </span>
              </label>
              {p.onOtvoriOpcije ? (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={p.onOtvoriOpcije}
                  disabled={p.disabled}
                  title="Opcije · Popusti"
                >
                  <SlidersHorizontal className="mr-2 h-4 w-4" />
                  Opcije · Popusti
                </Button>
              ) : null}
            </div>
            <MatricaCena
              sobe={p.sobe}
              periodi={p.periodi}
              cene={p.cene}
              onCenaChange={p.onCenaChange}
              disabled={p.disabled}
              onOpcijeTermina={p.onOpcijeTermina}
            />
          </>
        )}
      </CardContent>
    </Card>
  );
}

// ── Opcije · Popusti (dijalog po sobi cenovnika) ────────────────────────────

const PREVOZ_LABELA: Record<string, string> = {
  opciono: "Opciono", obavezan: "Obavezan", nemoguc: "Nemoguć",
};
const ARANZMAN_LABELA: Record<string, string> = {
  sa_prevozom: "Aranžman sa prevozom", bez_prevoza: "Aranžman bez prevoza",
};
const CENA_LABELA: Record<string, string> = { po_osobi: "Po osobi", po_sobi: "Po sobi" };
const POPUST_TIP_LABELA: Record<string, string> = {
  last_minute: "Last minute", first_minute: "First minute",
  specijalna_ponuda: "Specijalna ponuda", ultra_last_minute: "Ultra last minute",
};
const PLACANJE_LABELA: Record<string, string> = { delimicno: "Delimično", u_celosti: "U celosti" };
const NEMA = "nema"; // sentinel u Select-u za „bez vrednosti“ (Radix ne dozvoljava value="")

interface OpcijeSobaApi {
  postoji: boolean;
  blokirano: boolean; istaknuto: boolean; blokirano_subagenci: boolean; blokirano_sajt: boolean;
  prevoz: string | null; tip_aranzmana: string | null; tip_cene: string | null;
  popust_sopstveni_prevoz: number | null;
}

interface PopustSobaApi {
  postoji: boolean;
  umanjenje_vrsta: string; umanjenje: number | null; tip_popusta: string | null;
  tip_placanja: string | null; vazi_od: string | null; vazi_do: string | null;
  tip_aranzmana: string | null; tip_cene: string | null;
  popust_sopstveni_prevoz: number | null;
}

interface OpcijeForma {
  blokirano: boolean; istaknuto: boolean; blokirano_subagenci: boolean; blokirano_sajt: boolean;
  prevoz: string; tip_aranzmana: string; tip_cene: string; popust_sopstveni_prevoz: string;
}
const OPCIJE_PRAZNE: OpcijeForma = {
  blokirano: false, istaknuto: false, blokirano_subagenci: false, blokirano_sajt: false,
  prevoz: "opciono", tip_aranzmana: "sa_prevozom", tip_cene: "po_osobi", popust_sopstveni_prevoz: "",
};

interface PopustForma {
  umanjenje_vrsta: "iznos" | "procenat"; umanjenje: string; tip_popusta: string;
  tip_placanja: string; vazi_od: string; vazi_do: string; tip_aranzmana: string;
  tip_cene: string; popust_sopstveni_prevoz: string;
}
const POPUST_PRAZAN: PopustForma = {
  umanjenje_vrsta: "iznos", umanjenje: "", tip_popusta: "last_minute", tip_placanja: "delimicno",
  vazi_od: "", vazi_do: "", tip_aranzmana: "sa_prevozom", tip_cene: "po_osobi", popust_sopstveni_prevoz: "",
};

function formaIzOpcije(o: OpcijeSobaApi): OpcijeForma {
  return {
    blokirano: o.blokirano, istaknuto: o.istaknuto,
    blokirano_subagenci: o.blokirano_subagenci, blokirano_sajt: o.blokirano_sajt,
    prevoz: o.prevoz ?? NEMA, tip_aranzmana: o.tip_aranzmana ?? NEMA, tip_cene: o.tip_cene ?? NEMA,
    popust_sopstveni_prevoz: o.popust_sopstveni_prevoz == null ? "" : String(o.popust_sopstveni_prevoz),
  };
}

function formaIzPopusta(p: PopustSobaApi): PopustForma {
  return {
    umanjenje_vrsta: p.umanjenje_vrsta === "procenat" ? "procenat" : "iznos",
    umanjenje: p.umanjenje == null ? "" : String(p.umanjenje),
    tip_popusta: p.tip_popusta ?? NEMA, tip_placanja: p.tip_placanja ?? NEMA,
    vazi_od: p.vazi_od ?? "", vazi_do: p.vazi_do ?? "",
    tip_aranzmana: p.tip_aranzmana ?? NEMA, tip_cene: p.tip_cene ?? NEMA,
    popust_sopstveni_prevoz: p.popust_sopstveni_prevoz == null ? "" : String(p.popust_sopstveni_prevoz),
  };
}

/** Prazno → null (bez vrednosti); inače broj na 2 decimale ili ok=false. */
function parsirajIznos(raw: string): { ok: boolean; vrednost: number | null } {
  const t = raw.trim().replace(",", ".");
  if (t === "") return { ok: true, vrednost: null };
  const n = Number(t);
  if (!Number.isFinite(n) || n < 0) return { ok: false, vrednost: null };
  return { ok: true, vrednost: Math.round(n * 100) / 100 };
}

interface SveOpcijeOdgovor { postoji: boolean; zapisi: OpcijeSobaApi[] }
interface SvePopustiOdgovor { postoji: boolean; zapisi: PopustSobaApi[] }

/** Masovni mod: spoji zapise svih soba — vrednost ostaje samo ako je ISTA za sve sobe, inače neutralna. */
function spojiOpcije(zapisi: OpcijeSobaApi[]): OpcijeForma {
  if (zapisi.length === 0) return OPCIJE_PRAZNE;
  const prvi = zapisi[0];
  const isti = <K extends keyof OpcijeSobaApi>(k: K) => zapisi.every((o) => o[k] === prvi[k]);
  return {
    blokirano: isti("blokirano") ? prvi.blokirano : false,
    istaknuto: isti("istaknuto") ? prvi.istaknuto : false,
    blokirano_subagenci: isti("blokirano_subagenci") ? prvi.blokirano_subagenci : false,
    blokirano_sajt: isti("blokirano_sajt") ? prvi.blokirano_sajt : false,
    prevoz: isti("prevoz") ? (prvi.prevoz ?? NEMA) : NEMA,
    tip_aranzmana: isti("tip_aranzmana") ? (prvi.tip_aranzmana ?? NEMA) : NEMA,
    tip_cene: isti("tip_cene") ? (prvi.tip_cene ?? NEMA) : NEMA,
    popust_sopstveni_prevoz: isti("popust_sopstveni_prevoz")
      ? (prvi.popust_sopstveni_prevoz == null ? "" : String(prvi.popust_sopstveni_prevoz))
      : "",
  };
}

function spojiPopust(zapisi: PopustSobaApi[]): PopustForma {
  if (zapisi.length === 0) return POPUST_PRAZAN;
  const prvi = zapisi[0];
  const isti = <K extends keyof PopustSobaApi>(k: K) => zapisi.every((p) => p[k] === prvi[k]);
  return {
    umanjenje_vrsta: isti("umanjenje_vrsta") && prvi.umanjenje_vrsta === "procenat" ? "procenat" : "iznos",
    umanjenje: isti("umanjenje") ? (prvi.umanjenje == null ? "" : String(prvi.umanjenje)) : "",
    tip_popusta: isti("tip_popusta") ? (prvi.tip_popusta ?? NEMA) : NEMA,
    tip_placanja: isti("tip_placanja") ? (prvi.tip_placanja ?? NEMA) : NEMA,
    vazi_od: isti("vazi_od") ? (prvi.vazi_od ?? "") : "",
    vazi_do: isti("vazi_do") ? (prvi.vazi_do ?? "") : "",
    tip_aranzmana: isti("tip_aranzmana") ? (prvi.tip_aranzmana ?? NEMA) : NEMA,
    tip_cene: isti("tip_cene") ? (prvi.tip_cene ?? NEMA) : NEMA,
    popust_sopstveni_prevoz: isti("popust_sopstveni_prevoz")
      ? (prvi.popust_sopstveni_prevoz == null ? "" : String(prvi.popust_sopstveni_prevoz))
      : "",
  };
}

function Polje({ id, label, children }: { id: string; label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id} className="text-xs text-muted-foreground">{label}</Label>
      {children}
    </div>
  );
}

function Prekidac({ id, label, hint, checked, onChange }: {
  id: string; label: string; hint?: string; checked: boolean; onChange: (v: boolean) => void;
}) {
  return (
    <div
      className={cn(
        "flex items-start justify-between gap-3 rounded-lg border px-3 py-2.5 transition-colors",
        checked ? "border-primary/40 bg-primary/5" : "bg-card",
      )}
    >
      <label htmlFor={id} className="cursor-pointer">
        <span className="block text-sm font-medium leading-tight">{label}</span>
        {hint ? (
          <span className="mt-0.5 block text-[11px] leading-tight text-muted-foreground">{hint}</span>
        ) : null}
      </label>
      <Switch id={id} checked={checked} onCheckedChange={onChange} />
    </div>
  );
}

function Selekt({ id, value, onChange, opcije }: {
  id: string; value: string; onChange: (v: string) => void; opcije: Record<string, string>;
}) {
  return (
    <Select value={value || NEMA} onValueChange={onChange}>
      <SelectTrigger id={id} className="h-9 w-full bg-background">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={NEMA}>—</SelectItem>
        {Object.entries(opcije).map(([k, l]) => (
          <SelectItem key={k} value={k}>{l}</SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function OpcijePopustiDialog({ red, masovnoId, masovnoSobe, terminId, terminLabel, terminCid, onClose }: {
  red: CenovnikRow | null;
  /** Masovni mod (iz editora): primena na SVE sobe cenovnika i SVE termine. */
  masovnoId?: number | null;
  masovnoSobe?: SablonSoba[];
  /** Mod po terminu (O·P u koloni matrice): sve sobe, samo navedeni termin. */
  terminId?: number | null;
  terminLabel?: string | null;
  /** id cenovnika u termin modu (terminId je id PERIODA, ne cenovnika) */
  terminCid?: number | null;
  onClose: () => void;
}) {
  const [sobe, setSobe] = useState<SablonSoba[]>([]);
  const [sobaId, setSobaId] = useState<number | null>(null);
  const [ucitava, setUcitava] = useState(false);
  const [opcije, setOpcije] = useState<OpcijeForma>(OPCIJE_PRAZNE);
  const [popust, setPopust] = useState<PopustForma>(POPUST_PRAZAN);
  const [opcijePostoje, setOpcijePostoje] = useState(false);
  const [popustPostoji, setPopustPostoji] = useState(false);
  const [snimaOpcije, setSnimaOpcije] = useState(false);
  const [snimaPopust, setSnimaPopust] = useState(false);
  const [briseOpcije, setBriseOpcije] = useState(false);
  const [brisePopust, setBrisePopust] = useState(false);

  const masovno = masovnoId != null;
  const poTerminu = !masovno && terminId != null;
  const grupno = masovno || poTerminu;
  const cid = masovno ? masovnoId : (poTerminu ? terminCid ?? null : red?.id ?? null);

  // Otvaranje: masovno — sobe iz editora + spojeni zapisi svih soba; po terminu — zapisi
  // tog termina (fallback za prefill: zajednički zapisi); inače sobe iz detail-a
  useEffect(() => {
    if (cid === null) { setSobe([]); setSobaId(null); return; }
    let otkazano = false;
    setUcitava(true);
    setOpcije(OPCIJE_PRAZNE); setPopust(POPUST_PRAZAN);
    setOpcijePostoje(false); setPopustPostoji(false);
    if (masovno) {
      setSobe(masovnoSobe ?? []); setSobaId(null);
      Promise.all([
        apiFetch<SveOpcijeOdgovor>(`/cenovnici/${cid}/opcije-soba-sve`),
        apiFetch<SvePopustiOdgovor>(`/cenovnici/${cid}/popust-soba-sve`),
      ])
        .then(([o, p]) => {
          if (otkazano) return;
          setOpcije(spojiOpcije(o.zapisi)); setOpcijePostoje(o.postoji);
          setPopust(spojiPopust(p.zapisi)); setPopustPostoji(p.postoji);
        })
        .catch(() => { if (!otkazano) toast.error("Učitavanje opcija nije uspelo"); })
        .finally(() => { if (!otkazano) setUcitava(false); });
    } else if (poTerminu && terminId != null) {
      setSobe(masovnoSobe ?? []); setSobaId(null);
      void (async () => {
        try {
          const [oT, pT] = await Promise.all([
            apiFetch<SveOpcijeOdgovor>(`/cenovnici/${cid}/opcije-soba-termin/${terminId}`),
            apiFetch<SvePopustiOdgovor>(`/cenovnici/${cid}/popust-soba-termin/${terminId}`),
          ]);
          if (otkazano) return;
          let oZ = oT.zapisi;
          let pZ = pT.zapisi;
          // nema override-a za ovaj termin → kreni od zajedničkih (svi termini) vrednosti
          if (!oT.postoji) {
            oZ = (await apiFetch<SveOpcijeOdgovor>(`/cenovnici/${cid}/opcije-soba-sve`)).zapisi;
          }
          if (otkazano) return;
          if (!pT.postoji) {
            pZ = (await apiFetch<SvePopustiOdgovor>(`/cenovnici/${cid}/popust-soba-sve`)).zapisi;
          }
          if (otkazano) return;
          setOpcije(spojiOpcije(oZ)); setOpcijePostoje(oT.postoji);
          setPopust(spojiPopust(pZ)); setPopustPostoji(pT.postoji);
        } catch {
          if (!otkazano) toast.error("Učitavanje opcija nije uspelo");
        } finally {
          if (!otkazano) setUcitava(false);
        }
      })();
    } else {
      setSobe([]); setSobaId(null);
      apiFetch<CenovnikDetail>(`/cenovnici/${cid}`)
        .then((d) => {
          if (otkazano) return;
          setSobe(d.sobe);
          setSobaId(d.sobe.length > 0 ? d.sobe[0].id : null);
        })
        .catch(() => { if (!otkazano) toast.error("Učitavanje cenovnika nije uspelo"); })
        .finally(() => { if (!otkazano) setUcitava(false); });
    }
    return () => { otkazano = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cid, masovno, poTerminu, terminId]);

  // Promena sobe: opcije + popust te sobe
  useEffect(() => {
    if (cid === null || sobaId === null) return;
    let otkazano = false;
    setOpcije(OPCIJE_PRAZNE); setPopust(POPUST_PRAZAN);
    setOpcijePostoje(false); setPopustPostoji(false);
    Promise.all([
      apiFetch<OpcijeSobaApi>(`/cenovnici/${cid}/opcije-soba/${sobaId}`),
      apiFetch<PopustSobaApi>(`/cenovnici/${cid}/popust-soba/${sobaId}`),
    ])
      .then(([o, p]) => {
        if (otkazano) return;
        setOpcije(formaIzOpcije(o)); setOpcijePostoje(o.postoji);
        setPopust(formaIzPopusta(p)); setPopustPostoji(p.postoji);
      })
      .catch(() => { if (!otkazano) toast.error("Učitavanje opcija nije uspelo"); });
    return () => { otkazano = true; };
  }, [cid, sobaId]);

  async function snimiOpcije() {
    if (cid === null || (!grupno && sobaId === null)) return;
    const psp = parsirajIznos(opcije.popust_sopstveni_prevoz);
    if (!psp.ok) { toast.error("Popust za sopstveni prevoz mora biti nenegativan broj"); return; }
    setSnimaOpcije(true);
    try {
      const telo = JSON.stringify({
        blokirano: opcije.blokirano, istaknuto: opcije.istaknuto,
        blokirano_subagenci: opcije.blokirano_subagenci, blokirano_sajt: opcije.blokirano_sajt,
        prevoz: opcije.prevoz === NEMA ? null : opcije.prevoz,
        tip_aranzmana: opcije.tip_aranzmana === NEMA ? null : opcije.tip_aranzmana,
        tip_cene: opcije.tip_cene === NEMA ? null : opcije.tip_cene,
        popust_sopstveni_prevoz: psp.vrednost,
      });
      if (masovno) {
        const o = await apiFetch<{ status: string; broj_soba: number }>(
          `/cenovnici/${cid}/opcije-soba-sve`, { method: "PUT", body: telo });
        setOpcijePostoje(true);
        toast.success(`Opcije su sačuvane za sve sobe (${o.broj_soba})`);
      } else if (poTerminu) {
        await apiFetch<{ status: string; broj_soba: number }>(
          `/cenovnici/${cid}/opcije-soba-termin/${terminId}`, { method: "PUT", body: telo });
        setOpcijePostoje(true);
        toast.success(`Opcije su sačuvane za sve sobe i termin ${terminLabel}`);
      } else {
        const o = await apiFetch<OpcijeSobaApi>(`/cenovnici/${cid}/opcije-soba/${sobaId}`, {
          method: "PUT", body: telo,
        });
        setOpcije(formaIzOpcije(o));
        setOpcijePostoje(true);
        toast.success("Opcije su sačuvane");
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Čuvanje opcija nije uspelo");
    } finally {
      setSnimaOpcije(false);
    }
  }

  async function obrisiOpcije() {
    if (cid === null || (!grupno && sobaId === null)) return;
    setBriseOpcije(true);
    try {
      if (masovno) {
        await apiFetch(`/cenovnici/${cid}/opcije-soba-sve`, { method: "DELETE" });
        setOpcije(OPCIJE_PRAZNE);
        setOpcijePostoje(false);
        toast.success("Opcije su obrisane za sve sobe");
      } else if (poTerminu) {
        await apiFetch(`/cenovnici/${cid}/opcije-soba-termin/${terminId}`, { method: "DELETE" });
        setOpcije(OPCIJE_PRAZNE);
        setOpcijePostoje(false);
        toast.success(`Opcije su obrisane za sve sobe i termin ${terminLabel}`);
      } else {
        await apiFetch(`/cenovnici/${cid}/opcije-soba/${sobaId}`, { method: "DELETE" });
        setOpcije(OPCIJE_PRAZNE);
        setOpcijePostoje(false);
        toast.success("Opcije su obrisane");
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Brisanje opcija nije uspelo");
    } finally {
      setBriseOpcije(false);
    }
  }

  async function snimiPopust() {
    if (cid === null || (!grupno && sobaId === null)) return;
    const um = parsirajIznos(popust.umanjenje);
    if (!um.ok || um.vrednost === null || um.vrednost <= 0) {
      toast.error("Umanjenje mora biti broj veći od 0");
      return;
    }
    if (popust.umanjenje_vrsta === "procenat" && um.vrednost > 100) {
      toast.error("Procenat može biti najviše 100");
      return;
    }
    if (popust.tip_popusta === NEMA) {
      toast.error("Tip popusta je obavezan");
      return;
    }
    if (popust.vazi_od && popust.vazi_do && popust.vazi_od > popust.vazi_do) {
      toast.error("'Važi od' mora biti pre ili isti kao 'Važi do'");
      return;
    }
    const psp = parsirajIznos(popust.popust_sopstveni_prevoz);
    if (!psp.ok) { toast.error("Popust za sopstveni prevoz mora biti nenegativan broj"); return; }
    setSnimaPopust(true);
    try {
      const telo = JSON.stringify({
        umanjenje_vrsta: popust.umanjenje_vrsta,
        umanjenje: um.vrednost,
        tip_popusta: popust.tip_popusta,
        tip_placanja: popust.tip_placanja === NEMA ? null : popust.tip_placanja,
        vazi_od: popust.vazi_od || null,
        vazi_do: popust.vazi_do || null,
        tip_aranzmana: popust.tip_aranzmana === NEMA ? null : popust.tip_aranzmana,
        tip_cene: popust.tip_cene === NEMA ? null : popust.tip_cene,
        popust_sopstveni_prevoz: psp.vrednost,
      });
      if (masovno) {
        const p = await apiFetch<{ status: string; broj_soba: number }>(
          `/cenovnici/${cid}/popust-soba-sve`, { method: "PUT", body: telo });
        setPopustPostoji(true);
        toast.success(`Popust je sačuvan za sve sobe (${p.broj_soba})`);
      } else if (poTerminu) {
        await apiFetch<{ status: string; broj_soba: number }>(
          `/cenovnici/${cid}/popust-soba-termin/${terminId}`, { method: "PUT", body: telo });
        setPopustPostoji(true);
        toast.success(`Popust je sačuvan za sve sobe i termin ${terminLabel}`);
      } else {
        const p = await apiFetch<PopustSobaApi>(`/cenovnici/${cid}/popust-soba/${sobaId}`, {
          method: "PUT", body: telo,
        });
        setPopust(formaIzPopusta(p));
        setPopustPostoji(true);
        toast.success("Popust je sačuvan");
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Čuvanje popusta nije uspelo");
    } finally {
      setSnimaPopust(false);
    }
  }

  async function obrisiPopust() {
    if (cid === null || (!grupno && sobaId === null)) return;
    setBrisePopust(true);
    try {
      if (masovno) {
        await apiFetch(`/cenovnici/${cid}/popust-soba-sve`, { method: "DELETE" });
        setPopust(POPUST_PRAZAN);
        setPopustPostoji(false);
        toast.success("Popust je obrisan za sve sobe");
      } else if (poTerminu) {
        await apiFetch(`/cenovnici/${cid}/popust-soba-termin/${terminId}`, { method: "DELETE" });
        setPopust(POPUST_PRAZAN);
        setPopustPostoji(false);
        toast.success(`Popust je obrisan za sve sobe i termin ${terminLabel}`);
      } else {
        await apiFetch(`/cenovnici/${cid}/popust-soba/${sobaId}`, { method: "DELETE" });
        setPopust(POPUST_PRAZAN);
        setPopustPostoji(false);
        toast.success("Popust je obrisan");
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Brisanje popusta nije uspelo");
    } finally {
      setBrisePopust(false);
    }
  }

  return (
    <Dialog open={red !== null || masovno || poTerminu} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="max-h-[92vh] overflow-y-auto bg-card sm:max-w-xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-base">
            <SlidersHorizontal className="h-4 w-4 text-muted-foreground" />
            Opcije · Popusti
          </DialogTitle>
          <DialogDescription className="truncate">
            {masovno
              ? `Cenovnik #${cid} — podešavanja važe za sve sobe i sve termine`
              : poTerminu
                ? `Cenovnik #${cid} — sve sobe · termin ${terminLabel}`
                : `Cenovnik #${red?.id} — ${red?.naziv} · podešavanja važe za izabranu sobu`}
          </DialogDescription>
        </DialogHeader>

        {grupno ? (
          <div className="rounded-lg border border-primary/30 bg-primary/5 px-3 py-2 text-xs leading-relaxed text-muted-foreground">
            {masovno ? (
              <>
                Ovde definisane opcije i popusti primenjuju se na{" "}
                <span className="font-medium text-foreground">sve sobe</span> u cenovniku
                ({sobe.length}) — realne i virtuelne — i na{" "}
                <span className="font-medium text-foreground">sve termine</span>. Svaka soba u
                svakom terminu dobija ista podešavanja.
              </>
            ) : (
              <>
                Ovde definisane opcije i popusti primenjuju se na{" "}
                <span className="font-medium text-foreground">sve sobe</span> u cenovniku
                ({sobe.length}) — realne i virtuelne — samo za{" "}
                <span className="font-medium text-foreground">termin {terminLabel}</span>.
                Ostali termini zadržavaju svoja podešavanja.
              </>
            )}
          </div>
        ) : (
          <div className="flex flex-col gap-1.5">
            <Label className="text-xs text-muted-foreground">Soba</Label>
            <Select
              value={sobaId === null ? undefined : String(sobaId)}
              onValueChange={(v) => setSobaId(Number(v))}
              disabled={ucitava || sobe.length === 0}
            >
              <SelectTrigger className="w-full bg-background">
                <SelectValue placeholder={sobe.length === 0 ? "Nema soba u cenovniku" : "Izaberite sobu"} />
              </SelectTrigger>
              <SelectContent>
                {sobe.map((s) => (
                  <SelectItem key={s.id} value={String(s.id)}>
                    {s.broj_sobe} · {[s.tip, s.opis].filter(Boolean).join(" ")}
                    {s.virtuelna ? " · virtuelna" : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}

        {ucitava ? (
          <div className="flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Učitavanje…
          </div>
        ) : (grupno ? sobe.length === 0 : sobaId === null) ? (
          <p className="py-8 text-center text-sm text-muted-foreground">Cenovnik nema soba.</p>
        ) : (
          <Tabs defaultValue="opcije">
            <TabsList className="grid w-full grid-cols-2">
              <TabsTrigger value="opcije">Opcije</TabsTrigger>
              <TabsTrigger value="popusti">Popusti</TabsTrigger>
            </TabsList>

            <TabsContent value="opcije" className="mt-4 space-y-4">
              <div className="grid gap-2 sm:grid-cols-2">
                <Prekidac
                  id="opc-blokirano" label="Blokirano" hint="Soba nije dostupna za prodaju"
                  checked={opcije.blokirano}
                  onChange={(v) => setOpcije({ ...opcije, blokirano: v })}
                />
                <Prekidac
                  id="opc-istaknuto" label="Istaknuto" hint="Soba se ističe u ponudi"
                  checked={opcije.istaknuto}
                  onChange={(v) => setOpcije({ ...opcije, istaknuto: v })}
                />
                <Prekidac
                  id="opc-subagenci" label="Blokirati za subagente" hint="Ne prikazuje se subagentima"
                  checked={opcije.blokirano_subagenci}
                  onChange={(v) => setOpcije({ ...opcije, blokirano_subagenci: v })}
                />
                <Prekidac
                  id="opc-sajt" label="Blokirati za sajt" hint="Ne prikazuje se na sajtu"
                  checked={opcije.blokirano_sajt}
                  onChange={(v) => setOpcije({ ...opcije, blokirano_sajt: v })}
                />
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <Polje id="opc-prevoz" label="Prevoz">
                  <Selekt id="opc-prevoz" value={opcije.prevoz}
                    onChange={(v) => setOpcije({ ...opcije, prevoz: v })} opcije={PREVOZ_LABELA} />
                </Polje>
                <Polje id="opc-aranzman" label="Tip aranžmana">
                  <Selekt id="opc-aranzman" value={opcije.tip_aranzmana}
                    onChange={(v) => setOpcije({ ...opcije, tip_aranzmana: v })} opcije={ARANZMAN_LABELA} />
                </Polje>
                <Polje id="opc-cena" label="Tip cene">
                  <Selekt id="opc-cena" value={opcije.tip_cene}
                    onChange={(v) => setOpcije({ ...opcije, tip_cene: v })} opcije={CENA_LABELA} />
                </Polje>
                <Polje id="opc-psp" label="Popust za sopstveni prevoz">
                  <Input
                    id="opc-psp" inputMode="decimal" autoComplete="off" placeholder="0.00"
                    value={opcije.popust_sopstveni_prevoz}
                    onChange={(e) => setOpcije({ ...opcije, popust_sopstveni_prevoz: normalizeCena(e.target.value) })}
                    className="h-9 bg-background"
                  />
                </Polje>
              </div>

              <div className="flex items-center justify-between gap-2 border-t pt-3">
                <Button
                  variant="outline" size="sm"
                  className="text-destructive hover:text-destructive"
                  onClick={() => void obrisiOpcije()}
                  disabled={briseOpcije || snimaOpcije || !opcijePostoje}
                >
                  {briseOpcije ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Trash2 className="mr-2 h-4 w-4" />}
                  Obriši opcije
                </Button>
                <Button size="sm" onClick={() => void snimiOpcije()} disabled={snimaOpcije || briseOpcije}>
                  {snimaOpcije ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                  Snimi
                </Button>
              </div>
            </TabsContent>

            <TabsContent value="popusti" className="mt-4 space-y-4">
              <div className="rounded-lg border bg-muted/30 p-3">
                <div className="flex flex-wrap items-end gap-3">
                  <div className="flex flex-col gap-1.5">
                    <span className="text-xs text-muted-foreground">Vrsta umanjenja</span>
                    <div className="inline-flex items-center rounded-lg border bg-background p-0.5">
                      {(["iznos", "procenat"] as const).map((v) => (
                        <button
                          key={v} type="button"
                          onClick={() => setPopust({ ...popust, umanjenje_vrsta: v })}
                          className={cn(
                            "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                            popust.umanjenje_vrsta === v
                              ? "bg-primary text-primary-foreground shadow-sm"
                              : "text-muted-foreground hover:text-foreground",
                          )}
                        >
                          {v === "iznos" ? "Iznos" : "Procenat"}
                        </button>
                      ))}
                    </div>
                  </div>
                  <Polje id="pop-umanjenje" label={`Umanjenje${popust.umanjenje_vrsta === "procenat" ? " (%)" : ""}`}>
                    <Input
                      id="pop-umanjenje" inputMode="decimal" autoComplete="off"
                      placeholder={popust.umanjenje_vrsta === "procenat" ? "npr. 10" : "npr. 50"}
                      value={popust.umanjenje}
                      onChange={(e) => setPopust({ ...popust, umanjenje: normalizeCena(e.target.value) })}
                      className="h-9 w-32 bg-background"
                    />
                  </Polje>
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <Polje id="pop-tip" label="Tip popusta">
                  <Selekt id="pop-tip" value={popust.tip_popusta}
                    onChange={(v) => setPopust({ ...popust, tip_popusta: v })} opcije={POPUST_TIP_LABELA} />
                </Polje>
                <Polje id="pop-placanja" label="Tip plaćanja">
                  <Selekt id="pop-placanja" value={popust.tip_placanja}
                    onChange={(v) => setPopust({ ...popust, tip_placanja: v })} opcije={PLACANJE_LABELA} />
                </Polje>
                <Polje id="pop-od" label="Važi od">
                  <DatumCenovnika id="pop-od" value={popust.vazi_od}
                    onChange={(v) => setPopust({ ...popust, vazi_od: v })} />
                </Polje>
                <Polje id="pop-do" label="Važi do">
                  <DatumCenovnika id="pop-do" value={popust.vazi_do}
                    onChange={(v) => setPopust({ ...popust, vazi_do: v })} />
                </Polje>
                <Polje id="pop-aranzman" label="Tip aranžmana">
                  <Selekt id="pop-aranzman" value={popust.tip_aranzmana}
                    onChange={(v) => setPopust({ ...popust, tip_aranzmana: v })} opcije={ARANZMAN_LABELA} />
                </Polje>
                <Polje id="pop-cena" label="Tip cene">
                  <Selekt id="pop-cena" value={popust.tip_cene}
                    onChange={(v) => setPopust({ ...popust, tip_cene: v })} opcije={CENA_LABELA} />
                </Polje>
                <Polje id="pop-psp" label="Popust za sopstveni prevoz">
                  <Input
                    id="pop-psp" inputMode="decimal" autoComplete="off" placeholder="0.00"
                    value={popust.popust_sopstveni_prevoz}
                    onChange={(e) => setPopust({ ...popust, popust_sopstveni_prevoz: normalizeCena(e.target.value) })}
                    className="h-9 bg-background"
                  />
                </Polje>
              </div>

              <div className="flex items-center justify-between gap-2 border-t pt-3">
                <Button
                  variant="outline" size="sm"
                  className="text-destructive hover:text-destructive"
                  onClick={() => void obrisiPopust()}
                  disabled={brisePopust || snimaPopust || !popustPostoji}
                >
                  {brisePopust ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Trash2 className="mr-2 h-4 w-4" />}
                  Obriši popust
                </Button>
                <Button size="sm" onClick={() => void snimiPopust()} disabled={snimaPopust || brisePopust}>
                  {snimaPopust ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                  Snimi
                </Button>
              </div>
            </TabsContent>
          </Tabs>
        )}
      </DialogContent>
    </Dialog>
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
  const [kopirajCene, setKopirajCene] = useState(false); // opcija „Kopiraj cene“ (zajednička za oba editora)
  const sablonReq = useRef(0);

  // Tab „Izmena kreiranih cenovnika“
  const [q, setQ] = useState("");
  const [lista, setLista] = useState<CenovnikRow[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [strana, setStrana] = useState(1); // paginacija liste — 5 cenovnika po strani
  const [editDetail, setEditDetail] = useState<CenovnikDetail | null>(null);
  const [editCene, setEditCene] = useState<Record<string, string>>({});
  const [editOd, setEditOd] = useState("");
  const [editDo, setEditDo] = useState("");
  const [editOpis, setEditOpis] = useState("");
  const [editSnapshot, setEditSnapshot] = useState<string | null>(null);
  const [editZakljucano, setEditZakljucano] = useState(false);
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

  // Dijalog Opcije · Popusti (tab Izmena) — po sobi iz liste, masovno iz editora, O·P po terminu
  const [opcijeRed, setOpcijeRed] = useState<CenovnikRow | null>(null);
  const [opcijeMasovno, setOpcijeMasovno] = useState(false);
  const [opcijeTermin, setOpcijeTermin] = useState<{ id: number; label: string } | null>(null);

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
    setStrana(1); // nova pretraga uvek počinje od prve strane
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

  // Paginacija liste cenovnika: 5 poslednjih kreiranih na prvoj strani, ostatak na
  // sledećim — lista je već sortirana po id DESC (najnoviji prvi).
  const STRANICA = 5;
  const ukupnoStrana = Math.max(1, Math.ceil(lista.length / STRANICA));
  const aktivnaStrana = Math.min(strana, ukupnoStrana);
  const redoviStrane = lista.slice((aktivnaStrana - 1) * STRANICA, aktivnaStrana * STRANICA);

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
        setEditZakljucano(false);
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
      setEditZakljucano(true); // otvoren cenovnik je zaključan — „Izmeni cenovnik“ otključava
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
      setEditZakljucano(true); // posle čuvanja polja cenovnika su zaključana
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
    setCreateCene((prev) =>
      kopirajCene && createDraft
        ? ceneSaKopiranjem(prev, createDraft.sobe, sobaId, periodId, vrednost)
        : { ...prev, [cellKey(sobaId, periodId)]: vrednost },
    );
  const postaviEditCenu = (sobaId: number, periodId: number, vrednost: string) =>
    setEditCene((prev) =>
      kopirajCene && editDetail
        ? ceneSaKopiranjem(prev, editDetail.sobe, sobaId, periodId, vrednost)
        : { ...prev, [cellKey(sobaId, periodId)]: vrednost },
    );

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

      <Tabs value={tab} onValueChange={(v) => {
        // Prelazak na tab Izmena sklanja kreiranu tabelu iz taba Kreiranje — čak i
        // sa nesačuvanim izmenama — da cene dva editora ne dođu u preklapanje.
        if (v === "izmena" && tab !== "izmena") resetujCreateDraft();
        setTab(v as TabKey);
      }}>
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
              kopiraj={kopirajCene}
              onKopirajChange={setKopirajCene}
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
                    <TableHead className="w-28 text-right">Akcije</TableHead>
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
                    redoviStrane.map((row) => (
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
                              title="Opcije · Popusti"
                              aria-label={`Opcije i popusti cenovnika #${row.id}`}
                              onClick={(e) => { e.stopPropagation(); setOpcijeRed(row); }}
                            >
                              <SlidersHorizontal className="h-4 w-4" />
                            </Button>
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
              {ukupnoStrana > 1 ? (
                <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
                  <p className="text-xs text-muted-foreground">
                    Ukupno {lista.length} {pluralSr(lista.length, "cenovnik", "cenovnika", "cenovnika")} · strana{" "}
                    {aktivnaStrana} od {ukupnoStrana}
                  </p>
                  <div className="flex items-center gap-1">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={aktivnaStrana <= 1}
                      onClick={() => setStrana(aktivnaStrana - 1)}
                    >
                      <ChevronLeft className="mr-1 h-4 w-4" />
                      Prethodna
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={aktivnaStrana >= ukupnoStrana}
                      onClick={() => setStrana(aktivnaStrana + 1)}
                    >
                      Sledeća
                      <ChevronRight className="ml-1 h-4 w-4" />
                    </Button>
                  </div>
                </div>
              ) : null}
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
                disabled={loadingEdit || savingEdit || editZakljucano}
                saveLabel="Sačuvaj izmene"
                onIzmeni={editZakljucano ? () => {
                  setEditZakljucano(false);
                  toast.info("Polja za unos cena su otključana");
                } : undefined}
                izmeniDisabled={savingEdit}
                zakljucano={editZakljucano}
                kopiraj={kopirajCene}
                onKopirajChange={setKopirajCene}
                onOtvoriOpcije={() => setOpcijeMasovno(true)}
                onOpcijeTermina={(periodId, label) => setOpcijeTermin({ id: periodId, label })}
              />
            ) : null}
          </div>
        </TabsContent>
      </Tabs>

      {/* Dijalog Opcije · Popusti (tab Izmena) — po sobi iz liste, masovno iz editora, O·P po terminu */}
      <OpcijePopustiDialog
        red={opcijeRed}
        masovnoId={opcijeMasovno && editDetail ? editDetail.id : null}
        terminId={opcijeTermin && editDetail ? opcijeTermin.id : null}
        terminLabel={opcijeTermin?.label ?? null}
        terminCid={opcijeTermin && editDetail ? editDetail.id : null}
        masovnoSobe={editDetail?.sobe ?? []}
        onClose={() => { setOpcijeRed(null); setOpcijeMasovno(false); setOpcijeTermin(null); }}
      />

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
