import { useEffect, useState } from "react";
import { apiFetch } from "../lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { srLatn } from "date-fns/locale";
import { Loader2, Plus, Trash2, Save, Handshake, Receipt, Search, X, CalendarDays } from "lucide-react";
import { toast } from "sonner";

interface Subagent { id: number; naziv: string }

interface ZaduzenjeResp {
  postoji: boolean;
  subagent_id: number | null;
  subagent_naziv: string | null;
  hotel_eur: number; hotel_rsd: number;
  hf_eur: number; hf_rsd: number;
  transfer_eur: number; transfer_rsd: number;
  prevoz_eur: number; prevoz_rsd: number;
}

interface UsloviRedResp {
  id: number;
  naziv: string;
  iznos_eur: number | null;
  iznos_rsd: number | null;
  iznos_procenat: number | null;
  datum_placanja: string | null;
  placeno: boolean;
}

interface UsloviRed {
  key: number;
  naziv: string;
  eur: string;
  rsd: string;
  pct: string;
  datum: string;
  placeno: boolean;
}

type Stavka = "hotel" | "hf" | "transfer" | "prevoz";
const STAVKE: { k: Stavka; label: string }[] = [
  { k: "hotel", label: "Hotel" },
  { k: "hf", label: "HF" },
  { k: "transfer", label: "Transfer" },
  { k: "prevoz", label: "Prevoz" },
];

const NEMA = "nema";

// Broj iz unosa: zarez ili tačka; prazno = null
function broj(s: string): number | null {
  const t = s.trim().replace(",", ".");
  if (t === "") return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : NaN;
}

function brojUnos(v: number | null | undefined): string {
  if (v === null || v === undefined || v === 0) return "";
  return String(v).replace(".", ",");
}

const KOMPAKT = "h-8 text-xs";

function fmtDatum(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  return m ? `${m[3]}.${m[2]}.${m[1]}` : "dd.mm.yyyy";
}

// Datepicker za datum plaćanja: Popover + Calendar (isti obrazac kao Cenovnici)
function DatumPlacanja({ id, value, onChange, disabled }: {
  id: string; value: string; onChange: (value: string) => void; disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const selected = value ? new Date(`${value}T00:00:00`) : undefined;
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          id={id}
          type="button"
          variant="outline"
          disabled={disabled}
          aria-label="Datum plaćanja"
          className={cn(KOMPAKT, "w-full justify-between bg-background font-normal tabular-nums", !value && "text-muted-foreground")}
        >
          <span>{fmtDatum(value)}</span>
          <CalendarDays className="h-3.5 w-3.5 text-muted-foreground" />
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
        {value && (
          <div className="border-t p-2">
            <Button type="button" variant="ghost" size="sm" className="h-7 w-full text-xs text-destructive hover:text-destructive"
              onClick={() => { onChange(""); setOpen(false); }}>
              <X className="size-3.5" /> Obriši datum
            </Button>
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}

export default function ZaduzenjePartnerTab({ kljuc, zakljucano }: { kljuc: string | null; zakljucano: boolean }) {
  const [subagenti, setSubagenti] = useState<Subagent[]>([]);
  const [ucitava, setUcitava] = useState(false);

  // Deo 1: zaduženje partner
  const [subagentId, setSubagentId] = useState<string>(NEMA);
  const [upit, setUpit] = useState("");
  const [otvoren, setOtvoren] = useState(false);
  const [iznosi, setIznosi] = useState<Record<string, string>>({});
  const [snimaZad, setSnimaZad] = useState(false);

  // Deo 2: uslovi plaćanja
  const [redovi, setRedovi] = useState<UsloviRed[]>([]);
  const [sledeciKey, setSledeciKey] = useState(1);
  const [snimaUsl, setSnimaUsl] = useState(false);

  const onemoguceno = zakljucano || !kljuc;

  const izabraniNaziv = subagentId === NEMA
    ? ""
    : (subagenti.find((s) => String(s.id) === subagentId)?.naziv ?? "");
  const upitNorm = upit.trim().toLowerCase();
  const rezultati = upitNorm.length >= 3
    ? subagenti.filter((s) => s.naziv.toLowerCase().includes(upitNorm)).slice(0, 50)
    : [];
  const prikaziRezultate = otvoren && upitNorm.length >= 3 && upit !== izabraniNaziv;

  useEffect(() => {
    apiFetch<Subagent[]>("/subagenti-izbor")
      .then(setSubagenti)
      .catch(() => toast.error("Lista subagenata nije učitana"));
  }, []);

  useEffect(() => {
    if (!kljuc) return;
    let aktivan = true;
    setUcitava(true);
    Promise.all([
      apiFetch<ZaduzenjeResp>(`/zaduzenje/${encodeURIComponent(kljuc)}`),
      apiFetch<{ redovi: UsloviRedResp[] }>(`/uslovi-placanja/${encodeURIComponent(kljuc)}`),
    ])
      .then(([z, u]) => {
        if (!aktivan) return;
        setSubagentId(z.subagent_id != null ? String(z.subagent_id) : NEMA);
        setUpit(z.subagent_naziv ?? "");
        setIznosi({
          hotel_eur: brojUnos(z.hotel_eur), hotel_rsd: brojUnos(z.hotel_rsd),
          hf_eur: brojUnos(z.hf_eur), hf_rsd: brojUnos(z.hf_rsd),
          transfer_eur: brojUnos(z.transfer_eur), transfer_rsd: brojUnos(z.transfer_rsd),
          prevoz_eur: brojUnos(z.prevoz_eur), prevoz_rsd: brojUnos(z.prevoz_rsd),
        });
        let k = 1;
        setRedovi(u.redovi.map((r) => ({
          key: k++,
          naziv: r.naziv,
          eur: brojUnos(r.iznos_eur),
          rsd: brojUnos(r.iznos_rsd),
          pct: brojUnos(r.iznos_procenat),
          datum: r.datum_placanja ?? "",
          placeno: r.placeno,
        })));
        setSledeciKey(k);
      })
      .catch(() => { if (aktivan) toast.error("Učitavanje zaduženja nije uspelo"); })
      .finally(() => { if (aktivan) setUcitava(false); });
    return () => { aktivan = false; };
  }, [kljuc]);

  function postaviIznos(polje: string, vrednost: string) {
    setIznosi((prev) => ({ ...prev, [polje]: vrednost }));
  }

  function izmeniRed(key: number, patch: Partial<UsloviRed>) {
    setRedovi((prev) => prev.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  }

  function dodajRed() {
    setRedovi((prev) => [...prev, { key: sledeciKey, naziv: "", eur: "", rsd: "", pct: "", datum: "", placeno: false }]);
    setSledeciKey((k) => k + 1);
  }

  function ukloniRed(key: number) {
    setRedovi((prev) => prev.filter((r) => r.key !== key));
  }

  async function snimiZaduzenje() {
    if (!kljuc) return;
    const body: Record<string, unknown> = {
      subagent_id: subagentId === NEMA ? null : Number(subagentId),
    };
    for (const { k } of STAVKE) {
      for (const valuta of ["eur", "rsd"] as const) {
        const polje = `${k}_${valuta}`;
        const n = broj(iznosi[polje] ?? "");
        if (n !== null && Number.isNaN(n)) { toast.error("Iznosi moraju biti brojevi"); return; }
        if (n !== null && n < 0) { toast.error("Iznosi ne smeju biti negativni"); return; }
        body[polje] = n ?? 0;
      }
    }
    setSnimaZad(true);
    try {
      await apiFetch(`/zaduzenje/${encodeURIComponent(kljuc)}`, { method: "PUT", body: JSON.stringify(body) });
      toast.success("Zaduženje partner sačuvano");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Snimanje nije uspelo");
    } finally {
      setSnimaZad(false);
    }
  }

  async function snimiUslove() {
    if (!kljuc) return;
    const payload: Record<string, unknown>[] = [];
    for (const r of redovi) {
      const e = broj(r.eur), rs = broj(r.rsd), p = broj(r.pct);
      if ([e, rs, p].some((n) => n !== null && Number.isNaN(n))) { toast.error("Iznosi moraju biti brojevi"); return; }
      if ([e, rs, p].some((n) => n !== null && (n as number) < 0)) { toast.error("Iznosi ne smeju biti negativni"); return; }
      if (p !== null && p > 100) { toast.error("Procenat ne može biti veći od 100"); return; }
      payload.push({
        naziv: r.naziv,
        iznos_eur: e,
        iznos_rsd: rs,
        iznos_procenat: p,
        datum_placanja: r.datum || null,
        placeno: r.placeno,
      });
    }
    setSnimaUsl(true);
    try {
      await apiFetch(`/uslovi-placanja/${encodeURIComponent(kljuc)}`, {
        method: "PUT",
        body: JSON.stringify({ redovi: payload }),
      });
      toast.success("Uslovi plaćanja sačuvani");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Snimanje nije uspelo");
    } finally {
      setSnimaUsl(false);
    }
  }

  if (!kljuc) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">
        Zaduženje partner se vezuje za rezervaciju. Sačuvajte rezervaciju pa otvorite ovaj tab.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      {ucitava && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="size-3.5 animate-spin" /> Učitavanje…
        </div>
      )}

      {/* Deo 1: Zaduženje partner */}
      <Card>
        <CardHeader className="px-4 pt-3 pb-2">
          <CardTitle className="flex items-center gap-2 text-sm"><Handshake className="size-4" />Zaduženje partner</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 px-4 pb-3">
          <div className="relative max-w-sm space-y-1">
            <Label className="text-xs" htmlFor="zad-partner">Partner (subagent)</Label>
            <div className="flex items-center gap-1">
              <div className="relative flex-1">
                <Search className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
                <Input
                  id="zad-partner"
                  autoComplete="off"
                  placeholder="Pretražite partnera (min 3 slova)"
                  className={cn(KOMPAKT, "pl-7")}
                  disabled={onemoguceno}
                  value={upit}
                  onFocus={() => setOtvoren(true)}
                  onBlur={() => { setOtvoren(false); setUpit(izabraniNaziv); }}
                  onChange={(e) => { setUpit(e.target.value); setOtvoren(true); }}
                  onKeyDown={(e) => { if (e.key === "Escape") setOtvoren(false); }}
                />
                {prikaziRezultate && (
                  <div className="absolute z-50 mt-1 max-h-60 w-full overflow-y-auto rounded-md border bg-popover text-popover-foreground shadow-md">
                    {rezultati.length === 0 ? (
                      <div className="px-3 py-2 text-xs text-muted-foreground">Nema rezultata</div>
                    ) : rezultati.map((s) => (
                      <button
                        type="button"
                        key={s.id}
                        className="block w-full px-3 py-1.5 text-left text-xs hover:bg-accent hover:text-accent-foreground"
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => { setSubagentId(String(s.id)); setUpit(s.naziv); setOtvoren(false); }}
                      >
                        {s.naziv}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-8"
                aria-label="Obriši partnera"
                disabled={onemoguceno || subagentId === NEMA}
                onClick={() => { setSubagentId(NEMA); setUpit(""); setOtvoren(false); }}
              >
                <X className="size-3.5" /> Obriši
              </Button>
            </div>
            {upit.trim().length > 0 && upit.trim().length < 3 && (
              <p className="text-[11px] text-muted-foreground">Unesite najmanje 3 karaktera za pretragu</p>
            )}
          </div>

          <div className="grid grid-cols-[5rem_1fr_1fr] items-center gap-x-3 gap-y-2">
            <span />
            <span className="text-xs font-semibold text-muted-foreground">EUR</span>
            <span className="text-xs font-semibold text-muted-foreground">RSD</span>
            {STAVKE.map(({ k, label }) => (
              <div key={k} className="contents">
                <span className="text-xs font-medium">{label}</span>
                <Input
                  inputMode="decimal"
                  aria-label={`${label} — EUR`}
                  className={KOMPAKT}
                  disabled={onemoguceno}
                  value={iznosi[`${k}_eur`] ?? ""}
                  onChange={(e) => postaviIznos(`${k}_eur`, e.target.value)}
                  placeholder="0"
                />
                <Input
                  inputMode="decimal"
                  aria-label={`${label} — RSD`}
                  className={KOMPAKT}
                  disabled={onemoguceno}
                  value={iznosi[`${k}_rsd`] ?? ""}
                  onChange={(e) => postaviIznos(`${k}_rsd`, e.target.value)}
                  placeholder="0"
                />
              </div>
            ))}
          </div>

          <div className="flex justify-end">
            <Button size="sm" className="h-8" onClick={snimiZaduzenje} disabled={onemoguceno || snimaZad}>
              {snimaZad ? <Loader2 className="size-3.5 animate-spin" /> : <Save className="size-3.5" />}
              Snimi
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Deo 2: Uslovi plaćanja */}
      <Card>
        <CardHeader className="px-4 pt-3 pb-2">
          <CardTitle className="flex items-center gap-2 text-sm"><Receipt className="size-4" />Uslovi plaćanja</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 px-4 pb-3">
          {redovi.length === 0 && (
            <p className="text-xs text-muted-foreground">Nema uslova plaćanja.</p>
          )}
          {redovi.length > 0 && (
            <div className="grid grid-cols-[minmax(0,2fr)_6rem_6rem_5rem_9rem_8rem_2rem] items-center gap-x-2 gap-y-1 text-xs">
              <span className="font-semibold text-muted-foreground">Naziv / Napomena</span>
              <span className="font-semibold text-muted-foreground">Iznos EUR</span>
              <span className="font-semibold text-muted-foreground">Iznos RSD</span>
              <span className="font-semibold text-muted-foreground">Iznos %</span>
              <span className="font-semibold text-muted-foreground">Datum plaćanja</span>
              <span className="font-semibold text-muted-foreground">Status</span>
              <span />
              {redovi.map((r) => (
                <div key={r.key} className="contents">
                  <Input aria-label="Naziv / Napomena" className={KOMPAKT} disabled={onemoguceno} value={r.naziv}
                    onChange={(e) => izmeniRed(r.key, { naziv: e.target.value })} />
                  <Input aria-label="Iznos EUR" inputMode="decimal" className={KOMPAKT} disabled={onemoguceno} value={r.eur}
                    onChange={(e) => izmeniRed(r.key, { eur: e.target.value })} />
                  <Input aria-label="Iznos RSD" inputMode="decimal" className={KOMPAKT} disabled={onemoguceno} value={r.rsd}
                    onChange={(e) => izmeniRed(r.key, { rsd: e.target.value })} />
                  <Input aria-label="Iznos %" inputMode="decimal" className={KOMPAKT} disabled={onemoguceno} value={r.pct}
                    onChange={(e) => izmeniRed(r.key, { pct: e.target.value })} />
                  <DatumPlacanja id={`uslov-datum-${r.key}`} value={r.datum} disabled={onemoguceno}
                    onChange={(v) => izmeniRed(r.key, { datum: v })} />
                  <label className="flex h-8 cursor-pointer items-center gap-1.5">
                    <Checkbox
                      aria-label="Plaćeno"
                      checked={r.placeno}
                      disabled={onemoguceno}
                      onCheckedChange={(v) => izmeniRed(r.key, { placeno: v === true })}
                    />
                    <span>{r.placeno ? "Plaćeno" : "Nije plaćeno"}</span>
                  </label>
                  <Button variant="ghost" size="icon" className="size-7 text-destructive hover:text-destructive"
                    aria-label="Ukloni red" disabled={onemoguceno} onClick={() => ukloniRed(r.key)}>
                    <Trash2 className="size-3.5" />
                  </Button>
                </div>
              ))}
            </div>
          )}

          <div className="flex items-center justify-between pt-1">
            <Button variant="outline" size="sm" className="h-8" onClick={dodajRed} disabled={onemoguceno}>
              <Plus className="size-3.5" /> Dodaj red
            </Button>
            <Button size="sm" className="h-8" onClick={snimiUslove} disabled={onemoguceno || snimaUsl}>
              {snimaUsl ? <Loader2 className="size-3.5 animate-spin" /> : <Save className="size-3.5" />}
              Snimi
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
