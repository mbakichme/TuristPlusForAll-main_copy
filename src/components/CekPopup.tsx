import { useEffect, useState } from "react";
import { format } from "date-fns";
import { srLatn } from "date-fns/locale";
import { CalendarDays, Check, ChevronDown, Landmark, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { apiFetch } from "@/lib/api";
import { generisiDatume, podeliIznos, zbirCenti } from "@/lib/cekovi";
import { cn } from "@/lib/utils";
import type { BankaRow, CekStavka } from "@/types";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** iznos uplate u RSD */
  iznos: number;
  /** već sačuvani čekovi uplate (prazno = forma za generisanje) */
  pocetni: CekStavka[];
  cuva: boolean;
  onSacuvaj: (stavke: CekStavka[]) => void;
}

interface Red {
  s: CekStavka;
  /** tekst iznosa u inputu — parsira se pri snimanju */
  txt: string;
}

const nf2 = new Intl.NumberFormat("sr-RS", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const IZNOS_RE = /^\d+(?:[.,]\d{1,2})?$/;
const MAX_CEKOVA = 60;

function parseIznos(t: string): number {
  const s = t.trim();
  return IZNOS_RE.test(s) ? Number(s.replace(",", ".")) : NaN;
}

function prikazDatuma(iso: string): string {
  return format(new Date(`${iso}T00:00:00`), "dd.MM.yyyy.");
}

/** Popup za čekove uplate. Validacija zbira ogleda server (routes.py _cekovi_cisto). */
export function CekPopup({ open, onOpenChange, iznos, pocetni, cuva, onSacuvaj }: Props) {
  const [datum1, setDatum1] = useState<Date | undefined>(undefined);
  const [brojRata, setBrojRata] = useState("");
  const [iznosCeka, setIznosCeka] = useState("");
  const [banka, setBanka] = useState<BankaRow | null>(null);
  const [racunKlijenta, setRacunKlijenta] = useState("");
  const [kalendarOtvoren, setKalendarOtvoren] = useState(false);
  const [bankaOtvorena, setBankaOtvorena] = useState(false);
  const [bankaQ, setBankaQ] = useState("");
  const [bankaRez, setBankaRez] = useState<BankaRow[]>([]);
  const [bankaUcitava, setBankaUcitava] = useState(false);
  const [tabela, setTabela] = useState<Red[] | null>(null);
  const [greska, setGreska] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setGreska(null);
    setKalendarOtvoren(false);
    setBankaOtvorena(false);
    setBankaQ("");
    if (pocetni.length > 0) {
      setTabela(pocetni.map((s) => ({ s, txt: s.iznos.toFixed(2) })));
    } else {
      setTabela(null);
      setDatum1(undefined);
      setBrojRata("");
      setIznosCeka("");
      setBanka(null);
      setRacunKlijenta("");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // pretraga banaka — tek od 3 karaktera
  useEffect(() => {
    const q = bankaQ.trim();
    if (!bankaOtvorena || q.length < 3) {
      setBankaRez([]);
      setBankaUcitava(false);
      return;
    }
    const t = setTimeout(async () => {
      setBankaUcitava(true);
      try {
        const r = await apiFetch<{ rows: BankaRow[] }>(`/banke?q=${encodeURIComponent(q)}`);
        setBankaRez(r.rows);
      } catch {
        setBankaRez([]);
      } finally {
        setBankaUcitava(false);
      }
    }, 250);
    return () => clearTimeout(t);
  }, [bankaQ, bankaOtvorena]);

  const iznosValidan = Number.isFinite(iznos) && iznos > 0;
  const iznosCenti = Math.round(iznos * 100);
  // iznos čeka (opciono): ako je unet, broj čekova = ceil(ukupno / iznos čeka)
  const cekaUnet = iznosCeka.trim() !== "";
  const cekaVrednost = parseIznos(iznosCeka);
  const cekaValidna = Number.isFinite(cekaVrednost) && cekaVrednost > 0;
  const pregledBroja = cekaValidna && iznosValidan
    ? Math.ceil(iznosCenti / Math.round(cekaVrednost * 100))
    : null;

  const imaTabelu = !!tabela && tabela.length > 0;
  const parsirano = (tabela ?? []).map((r) => parseIznos(r.txt));
  const zbirCentiTabele = zbirCenti(parsirano.map((v) => (Number.isFinite(v) ? v : 0)));
  const tabelaValidna =
    imaTabelu &&
    parsirano.every((v) => Number.isFinite(v) && v > 0) &&
    zbirCentiTabele === iznosCenti;

  function potvrdiFormu() {
    setGreska(null);
    if (!datum1) return setGreska("Izaberite datum prve rate.");
    if (!banka) return setGreska("Izaberite banku.");
    if (!iznosValidan) return setGreska("Iznos uplate mora biti veći od nule.");
    if (cekaUnet && !cekaValidna) return setGreska("Iznos čeka mora biti broj veći od nule.");

    let iznosi: number[];
    if (cekaValidna) {
      const c = Math.round(cekaVrednost * 100);
      const n = Math.ceil(iznosCenti / c);
      if (n > MAX_CEKOVA) return setGreska(`Najviše ${MAX_CEKOVA} čekova. Povećajte iznos čeka.`);
      // svi čekovi po zadatom iznosu, poslednji = ostatak
      iznosi = [...Array(n - 1).fill(cekaVrednost), (iznosCenti - c * (n - 1)) / 100];
    } else {
      const n = Number(brojRata);
      if (!Number.isInteger(n) || n < 1 || n > MAX_CEKOVA) return setGreska(`Broj čekova mora biti od 1 do ${MAX_CEKOVA}.`);
      iznosi = podeliIznos(iznos, n);
      if (iznosi.length !== n) return setGreska("Iznos se ne može podeliti na zadati broj čekova.");
    }

    const datumi = generisiDatume(datum1, iznosi.length);
    setTabela(iznosi.map((v, i) => ({
      s: {
        redni: i + 1,
        datum: datumi[i],
        iznos: v,
        banka: banka.naziv,
        brojRacunaBanke: banka.racun,
        brojRacunaKlijenta: racunKlijenta.trim(),
        serijskiBroj: "",
      },
      txt: v.toFixed(2),
    })));
  }

  function sacuvaj() {
    if (!tabela || !tabelaValidna) return;
    onSacuvaj(tabela.map((r, i) => ({
      ...r.s,
      redni: i + 1,
      iznos: Math.round(parseIznos(r.txt) * 100) / 100,
      serijskiBroj: (r.s.serijskiBroj ?? "").trim(),
    })));
  }

  function postaviRed(i: number, patch: Partial<Red["s"]> & { txt?: string }) {
    setTabela((t) => (t ? t.map((r, j) => {
      if (j !== i) return r;
      const { txt, ...s } = patch;
      return { s: { ...r.s, ...s }, txt: txt ?? r.txt };
    }) : t));
  }

  function obrisiRed(i: number) {
    // redni se preračunava posle brisanja da ostane 1..N
    setTabela((t) => (t ? t.filter((_, j) => j !== i).map((r, j) => ({ ...r, s: { ...r.s, redni: j + 1 } })) : t));
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl bg-card max-h-[90vh] overflow-y-auto gap-3 p-4">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-sm">
            <Landmark className="size-4 text-primary" />
            Čekovi uplate
          </DialogTitle>
          <DialogDescription className="text-xs">
            {imaTabelu
              ? "Unesite serijske brojeve, po potrebi korigujte iznos ili obrišite red. Zbir mora biti jednak iznosu uplate."
              : "Unesite iznos čeka i banku, pa potvrdite za generisanje čekova."}
          </DialogDescription>
        </DialogHeader>

        <div className="flex items-center justify-between rounded-md border bg-muted/40 px-3 py-1.5">
          <span className="text-xs text-muted-foreground">Iznos uplate</span>
          <span className="text-sm font-semibold">{iznosValidan ? `${nf2.format(iznos)} din` : "—"}</span>
        </div>

        {!imaTabelu && (
          <div className="space-y-2">
            <div className="grid gap-x-3 gap-y-2 sm:grid-cols-2">
              <div className="space-y-0.5">
                <label className="text-[11px] font-medium text-muted-foreground">Datum 1. rate</label>
                <Popover open={kalendarOtvoren} onOpenChange={setKalendarOtvoren}>
                  <PopoverTrigger asChild>
                    <Button variant="outline" size="sm" className="h-8 w-full justify-start font-normal text-xs" aria-label="Datum 1. rate">
                      <CalendarDays className="size-3.5 mr-2 text-muted-foreground" />
                      {datum1 ? format(datum1, "dd.MM.yyyy.") : "Izaberite datum"}
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent className="w-auto p-0 bg-card" align="start">
                    <Calendar
                      mode="single"
                      selected={datum1}
                      onSelect={(d) => { setDatum1(d); setKalendarOtvoren(false); }}
                      locale={srLatn}
                      weekStartsOn={1}
                    />
                  </PopoverContent>
                </Popover>
              </div>

              <div className="space-y-0.5">
                <label className="text-[11px] font-medium text-muted-foreground" htmlFor="cek-iznos">Iznos čeka (din)</label>
                <Input
                  id="cek-iznos"
                  className="h-8 text-xs"
                  inputMode="decimal"
                  value={iznosCeka}
                  onChange={(e) => setIznosCeka(e.target.value)}
                  placeholder="npr. 5000"
                />
              </div>

              <div className="space-y-0.5">
                <label className="text-[11px] font-medium text-muted-foreground" htmlFor="cek-broj-rata">
                  Broj čekova{cekaValidna && pregledBroja !== null ? " (izračunato)" : ""}
                </label>
                <Input
                  id="cek-broj-rata"
                  className="h-8 text-xs"
                  type="number"
                  min={1}
                  max={MAX_CEKOVA}
                  inputMode="numeric"
                  value={cekaValidna && pregledBroja !== null ? String(pregledBroja) : brojRata}
                  disabled={cekaValidna}
                  onChange={(e) => setBrojRata(e.target.value)}
                  placeholder={cekaUnet ? "" : "npr. 9"}
                />
              </div>

              <div className="space-y-0.5">
                <label className="text-[11px] font-medium text-muted-foreground">Banka</label>
                <Popover open={bankaOtvorena} onOpenChange={setBankaOtvorena}>
                  <PopoverTrigger asChild>
                    <Button variant="outline" size="sm" className="h-8 w-full justify-between font-normal text-xs" aria-label="Banka">
                      <span className="truncate">{banka ? `${banka.naziv} (${banka.sifra})` : "Izaberite banku"}</span>
                      <ChevronDown className="size-3.5 opacity-50 shrink-0" />
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent className="w-[--radix-popover-trigger-width] p-0 bg-card" align="start">
                    <Command shouldFilter={false}>
                      <CommandInput placeholder="Pretraga (min. 3 karaktera)…" value={bankaQ} onValueChange={setBankaQ} />
                      <CommandList>
                        {bankaQ.trim().length < 3 ? (
                          <div className="py-4 text-center text-xs text-muted-foreground">Unesite najmanje 3 karaktera</div>
                        ) : bankaUcitava ? (
                          <div className="py-4 text-center text-xs text-muted-foreground">Pretraga…</div>
                        ) : (
                          <CommandEmpty>Nema banke za zadatu pretragu.</CommandEmpty>
                        )}
                        <CommandGroup>
                          {bankaRez.map((b) => (
                            <CommandItem
                              key={b.id}
                              value={String(b.id)}
                              onSelect={() => { setBanka(b); setBankaOtvorena(false); }}
                            >
                              <span className="font-medium">{b.naziv}</span>
                              <span className="ml-2 text-xs text-muted-foreground">{b.sifra} · {b.mesto}</span>
                            </CommandItem>
                          ))}
                        </CommandGroup>
                      </CommandList>
                    </Command>
                  </PopoverContent>
                </Popover>
              </div>

              <div className="space-y-0.5">
                <label className="text-[11px] font-medium text-muted-foreground" htmlFor="cek-racun-klijenta">Broj računa klijenta</label>
                <Input
                  id="cek-racun-klijenta"
                  className="h-8 text-xs"
                  maxLength={50}
                  value={racunKlijenta}
                  onChange={(e) => setRacunKlijenta(e.target.value)}
                />
              </div>
            </div>

            <div className="flex justify-end">
              <Button size="sm" variant="secondary" onClick={potvrdiFormu} disabled={!iznosValidan}>
                <Check className="size-3.5 mr-1.5" />Potvrdi
              </Button>
            </div>
            {greska && <p className="text-xs text-destructive">{greska}</p>}
          </div>
        )}

        {imaTabelu && (
          <div className="overflow-hidden rounded-md border">
            <div className="overflow-x-auto">
              <Table className="text-xs">
                <TableHeader>
                  <TableRow>
                    <TableHead className="h-8 px-2">Banka</TableHead>
                    <TableHead className="h-8 px-2">Račun banke</TableHead>
                    <TableHead className="h-8 px-2">Račun klijenta</TableHead>
                    <TableHead className="h-8 px-2">Serijski broj</TableHead>
                    <TableHead className="h-8 px-2">Datum</TableHead>
                    <TableHead className="h-8 px-2 text-right">Iznos (din)</TableHead>
                    <TableHead className="h-8 w-8 px-1" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {tabela!.map((r, i) => {
                    const v = parseIznos(r.txt);
                    const neispravan = !(Number.isFinite(v) && v > 0);
                    return (
                      <TableRow key={r.s.redni}>
                        <TableCell className="whitespace-nowrap px-2 py-1">{r.s.banka}</TableCell>
                        <TableCell className="px-2 py-1 font-mono">{r.s.brojRacunaBanke || "—"}</TableCell>
                        <TableCell className="px-2 py-1 font-mono">{r.s.brojRacunaKlijenta || "—"}</TableCell>
                        <TableCell className="px-2 py-1">
                          <Input
                            className="h-7 w-32 font-mono text-xs"
                            maxLength={50}
                            value={r.s.serijskiBroj}
                            placeholder="—"
                            aria-label={`Serijski broj čeka ${r.s.redni}`}
                            onChange={(e) => postaviRed(i, { serijskiBroj: e.target.value })}
                          />
                        </TableCell>
                        <TableCell className="whitespace-nowrap px-2 py-1">{prikazDatuma(r.s.datum)}</TableCell>
                        <TableCell className="px-2 py-1 text-right">
                          <Input
                            className={cn("ml-auto h-7 w-24 text-right text-xs tabular-nums", neispravan && "border-destructive")}
                            inputMode="decimal"
                            value={r.txt}
                            aria-label={`Iznos čeka ${r.s.redni}`}
                            aria-invalid={neispravan}
                            onChange={(e) => postaviRed(i, { txt: e.target.value })}
                          />
                        </TableCell>
                        <TableCell className="px-1 py-1 text-center">
                          <Button
                            variant="ghost"
                            size="icon"
                            className="size-6 text-destructive"
                            aria-label={`Obriši ček ${r.s.redni}`}
                            onClick={() => obrisiRed(i)}
                          >
                            <Trash2 className="size-3.5" />
                          </Button>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
                <TableFooter>
                  <TableRow>
                    <TableCell colSpan={5} className="px-2 py-1">
                      Ukupno ({tabela!.length} {tabela!.length === 1 ? "ček" : "čekova"})
                    </TableCell>
                    <TableCell className={cn("px-2 py-1 text-right font-semibold tabular-nums", !tabelaValidna && "text-destructive")}>
                      {nf2.format(zbirCentiTabele / 100)}
                    </TableCell>
                    <TableCell />
                  </TableRow>
                </TableFooter>
              </Table>
            </div>
          </div>
        )}
        {imaTabelu && !tabelaValidna && (
          <p className="text-xs text-destructive">
            Zbir čekova ({nf2.format(zbirCentiTabele / 100)}) se ne slaže sa iznosom uplate ({nf2.format(iznos)}), ili je neki iznos neispravan.
          </p>
        )}

        <DialogFooter>
          <Button size="sm" variant="outline" onClick={() => onOpenChange(false)} disabled={cuva}>Otkaži</Button>
          {imaTabelu && (
            <Button size="sm" onClick={sacuvaj} disabled={cuva || !tabelaValidna}>
              {cuva ? "Čuvanje…" : "Sačuvaj čekove"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
