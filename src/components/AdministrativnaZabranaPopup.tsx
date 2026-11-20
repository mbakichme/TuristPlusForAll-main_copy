import { useEffect, useState } from "react";
import { addMonths, format, getDaysInMonth, startOfMonth } from "date-fns";
import { Ban, ChevronDown, Loader2, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { DatumPicker } from "@/components/CekPopup";
import { apiFetch } from "@/lib/api";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** ključ sačuvanog ugovora (aranzman.kljuc) */
  kljuc: string;
}

interface Predlog {
  broj_zabrane: string;
  iznos_eur: number;
  kurs: number | null;
}

interface SubagentOpcija {
  id: number;
  naziv: string;
}

const IZNOS_RE = /^\d+(?:[.,]\d{1,2})?$/;
const danas = () => format(new Date(), "yyyy-MM-dd");
const prviUSledecemMesecu = () => format(startOfMonth(addMonths(new Date(), 1)), "yyyy-MM-dd");

/** Izbor subagenta: pretraga po nazivu (lista je cela, filtrira se lokalno). */
function SubagentPicker({ izabrani, opcije, onIzbor }: {
  izabrani: SubagentOpcija | null;
  opcije: SubagentOpcija[];
  onIzbor: (s: SubagentOpcija) => void;
}) {
  const [otvoreno, setOtvoreno] = useState(false);
  return (
    <Popover open={otvoreno} onOpenChange={setOtvoreno}>
      <PopoverTrigger asChild>
        <Button variant="outline" className="h-9 w-full justify-between font-normal" aria-label="Firma">
          <span className="truncate">{izabrani?.naziv ?? "Izaberite firmu"}</span>
          <ChevronDown className="size-4 opacity-50 shrink-0" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[--radix-popover-trigger-width] p-0 bg-card" align="start">
        <Command>
          <CommandInput placeholder="Pretraga firme…" />
          <CommandList>
            <CommandEmpty>Nema firme za zadatu pretragu.</CommandEmpty>
            <CommandGroup>
              {opcije.map((s) => (
                <CommandItem
                  key={s.id}
                  value={`${s.naziv} ${s.id}`}
                  onSelect={() => { onIzbor(s); setOtvoreno(false); }}
                >
                  {s.naziv}
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

/** Popup za kreiranje administrativne zabrane (tabele zabrana + ratazab). */
export function AdministrativnaZabranaPopup({ open, onOpenChange, kljuc }: Props) {
  const [ucitava, setUcitava] = useState(false);
  const [cuva, setCuva] = useState(false);
  const [subagenti, setSubagenti] = useState<SubagentOpcija[]>([]);
  const [subagent, setSubagent] = useState<SubagentOpcija | null>(null);
  const [mesto, setMesto] = useState("");
  const [datum, setDatum] = useState(danas());
  const [broj, setBroj] = useState("");
  const [prvaRata, setPrvaRata] = useState(prviUSledecemMesecu());
  const [prvaPolurata, setPrvaPolurata] = useState<string>("");
  const [iznosTxt, setIznosTxt] = useState("");
  const [brojRataTxt, setBrojRataTxt] = useState("12");
  const [kurs, setKurs] = useState<number | null>(null);
  const [preuzeta, setPreuzeta] = useState(false);
  const [preuzetaDatum, setPreuzetaDatum] = useState(danas());

  // Pri svakom otvaranju: novi predlog broja (posle kreiranja broj se pomera na /N+1) i iznos iz obračuna.
  useEffect(() => {
    if (!open) return;
    let aktivan = true;
    setUcitava(true);
    setSubagent(null);
    setMesto("");
    setDatum(danas());
    setPrvaRata(prviUSledecemMesecu());
    setPrvaPolurata("");
    setBrojRataTxt("12");
    setPreuzeta(false);
    setPreuzetaDatum(danas());
    Promise.all([
      apiFetch<Predlog>(`/zabrane/predlog?kljuc=${encodeURIComponent(kljuc)}`),
      apiFetch<SubagentOpcija[]>("/subagenti-izbor?ta=false"),
    ])
      .then(([p, s]) => {
        if (!aktivan) return;
        setBroj(p.broj_zabrane);
        setIznosTxt(p.iznos_eur.toFixed(2));
        setKurs(p.kurs ?? null);
        setSubagenti(s);
      })
      .catch((error) => {
        if (aktivan) toast.error(error instanceof Error ? error.message : "Podaci za zabranu nisu učitani");
      })
      .finally(() => { if (aktivan) setUcitava(false); });
    return () => { aktivan = false; };
  }, [open, kljuc]);

  const iznos = IZNOS_RE.test(iznosTxt.trim()) ? Number(iznosTxt.trim().replace(",", ".")) : NaN;
  const brojRata = /^\d+$/.test(brojRataTxt.trim()) ? Number(brojRataTxt.trim()) : NaN;
  const brojRataOk = Number.isInteger(brojRata) && brojRata >= 1 && brojRata <= 120;
  const validno = !!subagent && broj.trim() !== "" && /^\d{4}-\d{2}-\d{2}$/.test(prvaRata)
    && Number.isFinite(iznos) && iznos > 0 && brojRataOk;

  // pregled rata u RSD: iznos EUR × kurs, podeljeno na N rata (ostatak centi na prvim ratama)
  const pregled = (() => {
    if (!Number.isFinite(iznos) || iznos <= 0 || !brojRataOk || kurs == null
        || !/^\d{4}-\d{2}-\d{2}$/.test(prvaRata)) return null;
    const cents = Math.round(iznos * kurs * 100);
    const base = Math.floor(cents / brojRata);
    const ostatak = cents % brojRata;
    const start = new Date(`${prvaRata}T00:00:00`);
    const mesec = addMonths(startOfMonth(start), brojRata - 1);
    const dan = prvaPolurata ? new Date(`${prvaPolurata}T00:00:00`).getDate() : start.getDate();
    const poslednja = new Date(mesec.getFullYear(), mesec.getMonth(), Math.min(dan, getDaysInMonth(mesec)));
    return {
      ukupno: (cents / 100).toFixed(2),
      osnovna: (base / 100).toFixed(2),
      uvecana: ((base + 1) / 100).toFixed(2),
      ostatak,
      poslednja: format(poslednja, "dd.MM.yyyy."),
    };
  })();

  async function kreiraj() {
    if (!subagent) { toast.error("Izaberite firmu"); return; }
    if (broj.trim() === "") { toast.error("Unesite broj zabrane"); return; }
    if (!Number.isFinite(iznos) || iznos <= 0) { toast.error("Iznos mora biti pozitivan broj sa najviše dve decimale"); return; }
    if (!brojRataOk) { toast.error("Broj rata mora biti ceo broj od 1 do 120"); return; }
    setCuva(true);
    try {
      const r = await apiFetch<{ broj_zabrane: string }>("/zabrane", {
        method: "POST",
        body: JSON.stringify({
          kljuc,
          subagent_id: subagent.id,
          mesto_obracuna: mesto,
          datum,
          broj_zabrane: broj.trim(),
          prva_rata: prvaRata,
          prva_polurata: prvaPolurata || null,
          iznos_eur: iznos,
          broj_rata: brojRata,
          preuzeta_datum: preuzeta ? preuzetaDatum : null,
        }),
      });
      toast.success("Administrativna zabrana je kreirana", { description: r.broj_zabrane });
      onOpenChange(false);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Zabrana nije kreirana");
    } finally {
      setCuva(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!cuva) onOpenChange(o); }}>
      <DialogContent className="sm:max-w-lg bg-card">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><Ban className="size-5 text-red-600" />Administrativna zabrana</DialogTitle>
          <DialogDescription>
            Ugovor {kljuc}. Rate su mesečne od prve rate; prva polurata pomera sve rate na njen dan u mesecu.
          </DialogDescription>
        </DialogHeader>

        {ucitava ? (
          <div className="flex items-center justify-center py-10 text-muted-foreground">
            <Loader2 className="size-5 animate-spin" />
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-x-4 gap-y-3 [&_label]:block">
            <div className="col-span-2 space-y-1.5">
              <label className="text-sm font-medium">Firma</label>
              <SubagentPicker izabrani={subagent} opcije={subagenti} onIzbor={setSubagent} />
            </div>

            <div className="col-span-2 space-y-1.5">
              <label htmlFor="zab-mesto" className="text-sm font-medium">Mesto obračuna</label>
              <Input id="zab-mesto" value={mesto} maxLength={512} onChange={(e) => setMesto(e.target.value)} />
            </div>

            <div className="space-y-1.5">
              <label className="text-sm font-medium">Datum</label>
              <DatumPicker iso={datum} label="Datum zabrane" onIzbor={setDatum} />
            </div>

            <div className="space-y-1.5">
              <label htmlFor="zab-broj" className="text-sm font-medium">Broj zabrane</label>
              <Input id="zab-broj" value={broj} maxLength={512} className="tabular-nums" onChange={(e) => setBroj(e.target.value)} />
            </div>

            <div className="space-y-1.5">
              <label className="text-sm font-medium">Prva rata</label>
              <DatumPicker iso={prvaRata} label="Prva rata" onIzbor={setPrvaRata} />
            </div>

            <div className="space-y-1.5">
              <label className="text-sm font-medium">Prva polurata</label>
              <div className="flex items-center gap-1">
                <DatumPicker
                  iso={prvaPolurata || ""}
                  label="Prva polurata"
                  onIzbor={setPrvaPolurata}
                />
                {prvaPolurata && (
                  <Button
                    variant="ghost"
                    size="icon"
                    className="size-7"
                    aria-label="Ukloni prvu polurata"
                    onClick={() => setPrvaPolurata("")}
                  >
                    <X className="size-4" />
                  </Button>
                )}
              </div>
            </div>

            <div className="space-y-1.5">
              <label htmlFor="zab-broj-rata" className="text-sm font-medium">Broj rata</label>
              <Input
                id="zab-broj-rata"
                inputMode="numeric"
                value={brojRataTxt}
                className="tabular-nums"
                onChange={(e) => setBrojRataTxt(e.target.value)}
              />
              {pregled && (
                <div className="text-xs text-muted-foreground tabular-nums" data-testid="zab-rata-info">
                  Iznos rate: {pregled.osnovna} RSD
                  {pregled.ostatak > 0 && <> (prvih {pregled.ostatak} po {pregled.uvecana} RSD)</>}
                  <div>Poslednja rata: {pregled.poslednja}</div>
                </div>
              )}
            </div>

            <div className="space-y-1.5">
              <label htmlFor="zab-iznos" className="text-sm font-medium">Iznos iz obračuna (EUR)</label>
              <Input
                id="zab-iznos"
                inputMode="decimal"
                value={iznosTxt}
                className="tabular-nums"
                onChange={(e) => setIznosTxt(e.target.value)}
              />
              {pregled && (
                <div className="text-xs text-muted-foreground tabular-nums" data-testid="zab-pregled">
                  Ukupno: {pregled.ukupno} RSD · kurs EUR {kurs}
                </div>
              )}
            </div>

            <div className="col-span-2 flex flex-wrap items-end gap-3 rounded-md border p-3">
              <label htmlFor="zab-preuzeta" className="flex items-center gap-2 text-sm font-medium">
                <Checkbox
                  id="zab-preuzeta"
                  checked={preuzeta}
                  onCheckedChange={(v) => setPreuzeta(v === true)}
                />
                Zabrana preuzeta
              </label>
              {preuzeta && (
                <DatumPicker iso={preuzetaDatum} label="Datum preuzimanja" onIzbor={setPreuzetaDatum} />
              )}
            </div>
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" disabled={cuva} onClick={() => onOpenChange(false)}>Otkaži</Button>
          <Button
            className="bg-red-600 text-white hover:bg-red-700"
            disabled={!validno || ucitava || cuva}
            onClick={() => void kreiraj()}
          >
            {cuva && <Loader2 className="mr-1.5 size-4 animate-spin" />}
            Kreiraj zabranu
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
