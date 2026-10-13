import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import type {
  BankaOption, KnjizenjeStavka, KnjizenjeStavkeResponse, IzvodRow,
  UgovorRow, UgovorDetail, UgovoriResponse,
} from "../types";
import { apiFetch } from "../lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow
} from "@/components/ui/table";
import {
  Loader2, Search, BookCheck, Pencil, RefreshCcwDot, ReceiptText, Plus,
  ChevronUp, ChevronDown, NotebookPen,
} from "lucide-react";
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle
} from "@/components/ui/dialog";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { toast } from "sonner";

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-");
  if (!y || !m || !d) return "—";
  return `${d}.${m}.${y}.`;
}

function fmtMoney(v: number): string {
  return new Intl.NumberFormat("sr-RS", {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  }).format(v);
}

function fmtEur(v: number | null | undefined): string {
  return v == null ? "—" : `${new Intl.NumberFormat("sr-RS", {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  }).format(v)} €`;
}

type SortKey = keyof Pick<KnjizenjeStavka,
  "poziv_na_broj" | "naziv_primaoca" | "mesto_primaoca" | "svrha_kod" | "svrha"
  | "iznos" | "datum_knjizenja" | "veza" | "predracun" | "broj_izvoda">;

const COLUMNS: { key: SortKey; label: string; numeric?: boolean }[] = [
  { key: "poziv_na_broj", label: "Poziv na broj" },
  { key: "naziv_primaoca", label: "Uplatioc" },
  { key: "mesto_primaoca", label: "Adresa" },
  { key: "svrha_kod", label: "Šifra" },
  { key: "svrha", label: "Opis" },
  { key: "iznos", label: "Iznos", numeric: true },
  { key: "datum_knjizenja", label: "Datum knjiženja" },
  { key: "veza", label: "Veza" },
  { key: "predracun", label: "Predračun" },
];

export default function KnjizenjePage() {
  // forma
  const [banke, setBanke] = useState<BankaOption[]>([]);
  const [racun, setRacun] = useState("");
  const [brojIzvoda, setBrojIzvoda] = useState("");
  const [izvodiSvi, setIzvodiSvi] = useState<IzvodRow[]>([]);

  // rezultat
  const [meta, setMeta] = useState<KnjizenjeStavkeResponse["izvodi"]>([]);
  const [stavke, setStavke] = useState<KnjizenjeStavka[]>([]);
  const [loading, setLoading] = useState(false);
  const requestId = useRef(0);

  // tabela
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [selected, setSelected] = useState<boolean[]>([]);

  // Izmena popup
  const [editRow, setEditRow] = useState<KnjizenjeStavka | null>(null);
  const [editUgovor, setEditUgovor] = useState<UgovorDetail | null>(null);
  const [editUgovorLoading, setEditUgovorLoading] = useState(false);
  const [ugInput, setUgInput] = useState("");
  const [ugSearch, setUgSearch] = useState("");
  const [ugResults, setUgResults] = useState<UgovorRow[]>([]);
  const [ugSearching, setUgSearching] = useState(false);
  const [ugSelectedKljuc, setUgSelectedKljuc] = useState<string | null>(null);
  const ugReqId = useRef(0);

  const loadedRef = useRef(false);
  useEffect(() => {
    if (loadedRef.current) return;
    loadedRef.current = true;
    apiFetch<BankaOption[]>("/izvodi/banke")
      .then(setBanke)
      .catch((e) => toast.error(e instanceof Error ? e.message : "Greška pri učitavanju banaka"));
    apiFetch<IzvodRow[]>("/izvodi")
      .then(setIzvodiSvi)
      .catch(() => { /* opcionalno */ });
  }, []);

  useEffect(() => {
    const t = setTimeout(() => setSearch(searchInput.trim()), 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  const brojOpcije = useMemo(
    () => izvodiSvi.filter((i) => i.racun === racun),
    [izvodiSvi, racun]
  );

  const prikazi = useCallback(async () => {
    if (!racun || !brojIzvoda) return;
    const rid = ++requestId.current;
    setLoading(true);
    try {
      const params = new URLSearchParams({ racun });
      params.set("broj_izvoda", brojIzvoda);
      const data = await apiFetch<KnjizenjeStavkeResponse>(`/izvodi/stavke?${params}`);
      if (rid !== requestId.current) return;
      setMeta(data.izvodi);
      setStavke(data.stavke);
      setSelected(data.stavke.map((s) => !!s.veza));
      setSortKey(null); setSortDir("asc"); setSearchInput(""); setSearch("");
      if (data.stavke.length === 0) toast.info("Nema transakcija za zadate kriterijume");
    } catch (e) {
      if (rid === requestId.current) {
        toast.error(e instanceof Error ? e.message : "Greška pri učitavanju stavki");
      }
    } finally {
      if (rid === requestId.current) setLoading(false);
    }
  }, [racun, brojIzvoda]);

  // Automatska akcija: izbor broja izvoda odmah prikazuje stavke
  useEffect(() => {
    if (racun && brojIzvoda) prikazi();
  }, [racun, brojIzvoda, prikazi]);

  const idxMap = useMemo(() => new Map(stavke.map((s, i) => [s, i] as const)), [stavke]);

  const filtrirane = useMemo(() => {
    let rows = stavke;
    if (search) {
      const q = search.toLowerCase();
      rows = stavke.filter((s) =>
        [s.poziv_na_broj, s.naziv_primaoca, s.mesto_primaoca, s.svrha_kod,
         s.svrha, s.iznos, s.datum_knjizenja, s.veza, s.predracun]
          .some((v) => String(v ?? "").toLowerCase().includes(q))
      );
    }
    if (sortKey) {
      const dir = sortDir === "asc" ? 1 : -1;
      rows = [...rows].sort((a, b) => {
        const va = a[sortKey], vb = b[sortKey];
        if (typeof va === "number" && typeof vb === "number") return (va - vb) * dir;
        return String(va ?? "").localeCompare(String(vb ?? ""), "sr", { numeric: true }) * dir;
      });
    }
    return rows;
  }, [stavke, search, sortKey, sortDir]);

  function toggleSort(k: SortKey) {
    if (sortKey === k) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(k); setSortDir("asc");
    }
  }

  function toggleRow(origIdx: number) {
    setSelected((prev) => prev.map((v, i) => (i === origIdx ? !v : v)));
  }

  // ── Izmena popup ────────────────────────────────────────────────────────
  async function loadUgovorDetail(kljuc: string) {
    setEditUgovorLoading(true);
    try {
      const d = await apiFetch<UgovorDetail>(`/ugovori/${kljuc}`);
      setEditUgovor(d);
      setUgSelectedKljuc(d.kljuc);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Greška pri učitavanju ugovora");
      setEditUgovor(null);
    } finally {
      setEditUgovorLoading(false);
    }
  }

  function openEdit(row: KnjizenjeStavka) {
    setEditRow(row);
    setEditUgovor(null);
    setUgSelectedKljuc(null);
    setUgInput(""); setUgSearch(""); setUgResults([]);
    if (row.veza) loadUgovorDetail(row.veza);
  }

  useEffect(() => {
    const v = ugInput.trim();
    const t = setTimeout(() => setUgSearch(v.length >= 3 ? v : ""), 400);
    return () => clearTimeout(t);
  }, [ugInput]);

  useEffect(() => {
    if (!editRow) return;
    if (!ugSearch) { setUgResults([]); setUgSearching(false); return; }
    const rid = ++ugReqId.current;
    setUgSearching(true);
    apiFetch<UgovoriResponse>(
      `/ugovori?search=${encodeURIComponent(ugSearch)}&page_size=10&sort=kljuc&dir=asc`
    )
      .then((d) => { if (rid === ugReqId.current) setUgResults(d.rows); })
      .catch(() => { if (rid === ugReqId.current) setUgResults([]); })
      .finally(() => { if (rid === ugReqId.current) setUgSearching(false); });
  }, [ugSearch, editRow]);

  const selektovano = selected.filter(Boolean).length;

  return (
    <div className="p-6 md:p-8 space-y-6 max-w-[110rem] mx-auto">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <NotebookPen className="w-6 h-6" />Knjiženje
        </h1>
        <p className="text-muted-foreground text-sm mt-1">
          Pregled transakcija iz bankovnih izvoda i povezivanje sa ugovorima
        </p>
      </div>

      {/* Forma */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Izbor izvoda</CardTitle>
          <CardDescription>
            Izaberi banku i broj izvoda — pregled se prikazuje automatski
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col md:flex-row md:items-end gap-4">
            <div className="space-y-1.5 md:w-72">
              <Label>Banka (račun)</Label>
              <Select
                value={racun}
                onValueChange={(v) => { setRacun(v); setBrojIzvoda(""); }}
              >
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="Izaberi račun…" />
                </SelectTrigger>
                <SelectContent>
                  {banke.length === 0 && (
                    <div className="px-3 py-2 text-sm text-muted-foreground">Nema unešenih izvoda</div>
                  )}
                  {banke.map((b) => (
                    <SelectItem key={b.racun} value={b.racun}>
                      {b.racun} ({b.izvoda} {b.izvoda === 1 ? "izvod" : "izvoda"})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5 md:w-56">
              <Label>Broj izvoda</Label>
              <Select
                value={brojIzvoda}
                onValueChange={setBrojIzvoda}
                disabled={!racun}
              >
                <SelectTrigger className="w-full">
                  <SelectValue placeholder={racun ? "Izaberi…" : "Prvo račun"} />
                </SelectTrigger>
                <SelectContent>
                  {brojOpcije.map((i) => (
                    <SelectItem key={i.id} value={i.broj_izvoda}>
                      {i.broj_izvoda}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {loading && (
              <div className="flex items-center gap-2 pb-1.5 text-sm text-muted-foreground">
                <Loader2 className="w-4 h-4 animate-spin" />
                Učitavam…
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Tabela */}
      {stavke.length > 0 && (
        <Card>
          <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3 space-y-0">
            <div>
              <CardTitle className="text-base flex items-center gap-2">
                <BookCheck className="w-4 h-4" />
                Transakcije
              </CardTitle>
              <CardDescription className="mt-1">
                {meta.map((m) => `Izvod ${m.broj_izvoda} • ${m.racun}`).join(" | ")}
              </CardDescription>
            </div>
            <div className="flex items-center gap-2">
              <div className="relative">
                <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input
                  placeholder="Pretraga svih kolona…"
                  value={searchInput}
                  onChange={(e) => setSearchInput(e.target.value)}
                  className="pl-8 w-52 sm:w-72"
                />
              </div>
              <Button variant="outline" onClick={() => { toast.info("Rasknjižavanje je u pripremi"); }}>
                <RefreshCcwDot className="w-4 h-4" />
                Rasknjiži selektovano{selektovano > 0 ? ` (${selektovano})` : ""}
              </Button>
              <Button variant="outline" onClick={() => { toast.info("Dodavanje uplate je u pripremi"); }}>
                <Plus className="w-4 h-4" />
                Dodaj uplatu
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            {loading ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
              </div>
            ) : filtrirane.length === 0 ? (
              <div className="text-center py-12 text-muted-foreground text-sm">
                Nema stavki koje odgovaraju pretrazi.
              </div>
            ) : (
              <div className="rounded-md border overflow-x-auto">
                <Table className="text-xs [&_th]:h-8 [&_th]:px-2 [&_td]:px-2 [&_td]:py-1">
                  <TableHeader>
                    <TableRow>
                      {COLUMNS.map((c) => (
                        <TableHead
                          key={c.key}
                          className={cnSortable(c.numeric)}
                          onClick={() => toggleSort(c.key)}
                          title="Sortiraj"
                        >
                          <span className="inline-flex items-center gap-1 cursor-pointer select-none">
                            {c.label}
                            {sortKey === c.key && (sortDir === "asc"
                              ? <ChevronUp className="w-3.5 h-3.5" />
                              : <ChevronDown className="w-3.5 h-3.5" />)}
                          </span>
                        </TableHead>
                      ))}
                      <TableHead className="w-20 text-right">Akcija</TableHead>
                      <TableHead className="text-center">Selektovanje</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filtrirane.map((s) => {
                      const origIdx = idxMap.get(s) ?? 0;
                      return (
                        <TableRow key={`${s.broj_izvoda}-${s.fitid}-${origIdx}`}
                          className={s.veza ? "bg-emerald-50/50 dark:bg-emerald-950/20" : ""}>
                          <TableCell className="whitespace-nowrap font-medium">{s.poziv_na_broj || "—"}</TableCell>
                          <TableCell className="whitespace-nowrap max-w-72 truncate" title={s.naziv_primaoca}>{s.naziv_primaoca || "—"}</TableCell>
                          <TableCell className="whitespace-nowrap">{s.mesto_primaoca || "—"}</TableCell>
                          <TableCell>{s.svrha_kod || "—"}</TableCell>
                          <TableCell className="max-w-96 truncate" title={s.svrha}>{s.svrha || "—"}</TableCell>
                          <TableCell className="text-right whitespace-nowrap font-mono text-xs">
                            {fmtMoney(s.iznos)}
                          </TableCell>
                          <TableCell className="whitespace-nowrap">{fmtDate(s.datum_knjizenja)}</TableCell>
                          <TableCell className="whitespace-nowrap font-medium">{s.veza || "—"}</TableCell>
                          <TableCell className="whitespace-nowrap">{s.predracun || "—"}</TableCell>
                          <TableCell className="text-right whitespace-nowrap">
                            <TooltipProvider delayDuration={300}>
                              <div className="inline-flex gap-0.5">
                                <Tooltip>
                                  <TooltipTrigger asChild>
                                    <Button variant="ghost" size="icon" className="h-7 w-7"
                                      onClick={() => toast.info("Proknjižavanje je u pripremi")}>
                                      <BookCheck className="w-4 h-4" />
                                    </Button>
                                  </TooltipTrigger>
                                  <TooltipContent>Proknjiži</TooltipContent>
                                </Tooltip>
                                <Tooltip>
                                  <TooltipTrigger asChild>
                                    <Button variant="ghost" size="icon" className="h-7 w-7"
                                      onClick={() => openEdit(s)}>
                                      <Pencil className="w-4 h-4" />
                                    </Button>
                                  </TooltipTrigger>
                                  <TooltipContent>Izmena</TooltipContent>
                                </Tooltip>
                              </div>
                            </TooltipProvider>
                          </TableCell>
                          <TableCell className="text-center">
                            <input
                              type="checkbox"
                              checked={selected[origIdx] ?? false}
                              onChange={() => toggleRow(origIdx)}
                              className="h-4 w-4 accent-primary cursor-pointer"
                            />
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {stavke.length === 0 && !loading && (
        <Card>
          <CardContent className="py-10 text-center text-muted-foreground text-sm flex flex-col items-center gap-2">
            <ReceiptText className="w-8 h-8 opacity-50" />
            Izaberi banku i broj izvoda — transakcije se prikazuju automatski
          </CardContent>
        </Card>
      )}

      {/* Izmena popup */}
      <Dialog open={!!editRow} onOpenChange={(o) => !o && setEditRow(null)}>
        <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Izmena stavke</DialogTitle>
            <DialogDescription>
              Izvod {editRow?.broj_izvoda} • {editRow?.racun}
            </DialogDescription>
          </DialogHeader>

          {/* Podaci transakcije */}
          <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
            <Pf label="Poziv na broj" value={editRow?.poziv_na_broj || "—"} />
            <Pf label="Uplatioc" value={editRow?.naziv_primaoca || "—"} />
            <Pf label="Adresa" value={editRow?.mesto_primaoca || "—"} />
            <Pf label="Šifra" value={editRow?.svrha_kod || "—"} />
            <Pf label="Iznos" value={editRow ? fmtMoney(editRow.iznos) : "—"} />
            <Pf label="Datum knjiženja" value={fmtDate(editRow?.datum_knjizenja ?? null)} />
            <div className="col-span-2">
              <p className="text-xs text-muted-foreground">Opis</p>
              <p className="text-sm">{editRow?.svrha || "—"}</p>
            </div>
          </div>

          <div className="border-t" />

          {/* Ugovor — jedna celina */}
          <div className="rounded-lg border bg-muted/30 p-4">
            <div className="flex items-center justify-between mb-2">
              <h4 className="text-sm font-semibold">
                Ugovor: {editUgovor?.kljuc ?? (editRow?.veza || "nije povezano")}
              </h4>
              {editUgovorLoading && <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />}
            </div>
            {editUgovor ? (
              <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
                <Pf label="Putnik" value={editUgovor.putnik || "—"} />
                <Pf label="Mesto" value={editUgovor.mesto || "—"} />
                <Pf label="Destinacija" value={editUgovor.destinacija || "—"} />
                <Pf label="Naziv smeštaja" value={editUgovor.naziv || "—"} />
                <Pf label="Period" value={
                  editUgovor.datumod || editUgovor.datumdo
                    ? `${editUgovor.datumod ?? "—"} - ${editUgovor.datumdo ?? "—"}`
                    : "—"
                } />
                <Pf label="Vrednost aranžmana" value={fmtEur(editUgovor.ukupna_vrednost)} />
                {editUgovor.subagent && (
                  <div className="col-span-2">
                    <p className="text-xs text-muted-foreground">Subagent</p>
                    <p className="text-sm">{editUgovor.subagent}</p>
                  </div>
                )}
              </div>
            ) : (
              !editUgovorLoading && (
                <p className="text-sm text-muted-foreground">
                  Stavka nije povezana sa ugovorom — pretraži i izaberi ugovor ispod.
                </p>
              )
            )}
          </div>

          {/* Pretraga ugovora */}
          <div className="space-y-2">
            <Label>Pretraga ugovora (broj ugovora ili putnik)</Label>
            <div className="relative">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="npr. 33986 ili ime putnika…"
                value={ugInput}
                onChange={(e) => setUgInput(e.target.value)}
                className="pl-8"
              />
            </div>
            {ugSearching && (
              <div className="flex items-center justify-center py-2">
                <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
              </div>
            )}
            {!ugSearching && ugResults.length > 0 && (
              <div className="rounded-md border max-h-44 overflow-y-auto">
                {ugResults.map((r) => (
                  <button
                    key={r.kljuc}
                    type="button"
                    onClick={() => loadUgovorDetail(r.kljuc)}
                    className={cnResultRow(ugSelectedKljuc === r.kljuc)}
                  >
                    <span className="font-medium whitespace-nowrap">{r.kljuc}</span>
                    <span className="truncate flex-1 text-left">{r.putnik || "—"}</span>
                    <span className="text-muted-foreground whitespace-nowrap">
                      {r.datumod && r.datumdo ? `${r.datumod} - ${r.datumdo}` : ""}
                    </span>
                  </button>
                ))}
              </div>
            )}
            {!ugSearching && ugSearch && ugResults.length === 0 && (
              <p className="text-sm text-muted-foreground">Nema ugovora za datu pretragu.</p>
            )}
          </div>

          <p className="text-xs text-muted-foreground">
            Izbor ugovora popunjava podatke o ugovoru — čuvanje veze će biti deo Proknjiži funkcionalnosti.
          </p>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Pf({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-sm">{value}</p>
    </div>
  );
}

function cnResultRow(selected: boolean) {
  return [
    "w-full flex items-center gap-3 px-3 py-2 text-sm border-b last:border-b-0 transition-colors",
    selected
      ? "bg-primary/10 hover:bg-primary/15"
      : "hover:bg-muted/50",
  ].join(" ");
}

function cnSortable(numeric?: boolean) {
  return numeric ? "text-right" : "";
}
