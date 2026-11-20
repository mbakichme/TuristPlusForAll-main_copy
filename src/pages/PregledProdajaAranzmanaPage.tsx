import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import type { ProdajaAranzmanaResp, ProdajaAranzmanaRow } from "../types";
import { apiFetch, getToken } from "../lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow
} from "@/components/ui/table";
import { CalendarDays, ChevronLeft, ChevronRight, Download, Loader2, FileBarChart2, Search } from "lucide-react";
import { toast } from "sonner";
import {
  Kalendar, fmtDatum, isoToDate, keyOf, shiftIso, toIso, viewFromIso,
} from "@/components/DnevniKalendar";

// Kolone tabele (redosled = redosled u izveštaju)
const COLUMNS: { key: string; label: string; className?: string }[] = [
  { key: "ugovor", label: "Ugovor", className: "w-24" },
  { key: "putnik", label: "Putnik", className: "min-w-40" },
  { key: "mesto", label: "Mesto", className: "min-w-32" },
  { key: "smestaj", label: "Smeštaj", className: "min-w-32" },
  { key: "soba", label: "Soba", className: "w-20" },
  { key: "period", label: "Period", className: "min-w-44" },
  { key: "tip", label: "Tip", className: "min-w-28" },
  { key: "struktura", label: "Struktura", className: "w-20" },
  { key: "operater", label: "Operater", className: "min-w-28" },
  { key: "subagent", label: "Subagent", className: "min-w-32" },
];
const FILTER_COLS = COLUMNS.map((c) => c.key);
const emptyFilters = (): Record<string, string> => Object.fromEntries(FILTER_COLS.map((k) => [k, ""]));

/** Tekst reda po ključu kolone — za globalnu pretragu i filter-red */
function rowField(r: ProdajaAranzmanaRow, key: string): string {
  switch (key) {
    case "ugovor": return r.kljuc ?? "";
    case "putnik": return r.putnik ?? "";
    case "mesto": return r.mesto ?? "";
    case "smestaj": return r.smestaj ?? "";
    case "soba": return r.soba ?? "";
    case "period": return `${r.datum_od ?? ""} ${r.datum_do ?? ""}`;
    case "tip": return r.tiprezervacije ?? "";
    case "struktura": return r.struktura ?? "";
    case "operater": return r.obradio ?? "";
    case "subagent": return r.subagent ?? "";
    default: return "";
  }
}

const fmtNum = new Intl.NumberFormat("sr-RS", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function fmtEur(v: number | null | undefined): string {
  return v == null ? "—" : fmtNum.format(v) + " €";
}
function fmtRsd(v: number | null | undefined): string {
  return v == null ? "—" : fmtNum.format(v) + " RSD";
}
function fmtInt(v: number | null | undefined): string {
  return v == null ? "—" : new Intl.NumberFormat("sr-RS").format(v);
}


export default function PregledProdajaAranzmanaPage() {
  const [iso, setIso] = useState<string>(() => toIso(new Date()));
  const [kalOpen, setKalOpen] = useState(false);
  const [kalView, setKalView] = useState(() => viewFromIso(toIso(new Date())));
  const [data, setData] = useState<ProdajaAranzmanaResp | null>(null);
  const [loading, setLoading] = useState(true);
  const requestId = useRef(0);

  // globalna pretraga + filter-red (kao kod ugovora)
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [filterInput, setFilterInput] = useState<Record<string, string>>(emptyFilters);
  const [filters, setFilters] = useState<Record<string, string>>(emptyFilters);

  // mesec kalendara prati izabrani datum
  useEffect(() => { setKalView(viewFromIso(iso)); }, [iso]);

  useEffect(() => {
    const t = setTimeout(() => setSearch(searchInput.trim()), 400);
    return () => clearTimeout(t);
  }, [searchInput]);

  useEffect(() => {
    const t = setTimeout(() => setFilters({ ...filterInput }), 400);
    return () => clearTimeout(t);
  }, [filterInput]);

  const load = useCallback(async (d: string) => {
    const rid = ++requestId.current;
    setLoading(true);
    try {
      const resp = await apiFetch<ProdajaAranzmanaResp>(
        `/pregledi/prodaja-aranzmana?datum=${encodeURIComponent(d)}`
      );
      if (rid !== requestId.current) return;
      setData(resp);
    } catch (e) {
      if (rid !== requestId.current) return;
      toast.error(e instanceof Error ? e.message : "Greška pri učitavanju izveštaja");
    } finally {
      if (rid === requestId.current) setLoading(false);
    }
  }, []);

  useEffect(() => { load(iso); }, [load, iso]);

  const rows = data?.rows ?? [];
  const t = data?.totals;

  // globalna pretraga (sva polja, OR) + filter-red po koloni (AND) — klijentski
  const visibleRows = useMemo(() => {
    const s = search.trim().toLowerCase();
    const flt = Object.entries(filters)
      .map(([k, v]) => [k, v.trim().toLowerCase()] as const)
      .filter(([, v]) => v !== "");
    return rows.filter((r) => {
      if (s) {
        const hay = COLUMNS.map((c) => rowField(r, c.key)).join(" ").toLowerCase();
        if (!hay.includes(s)) return false;
      }
      for (const [k, v] of flt) {
        if (!rowField(r, k).toLowerCase().includes(v)) return false;
      }
      return true;
    });
  }, [rows, search, filters]);

  const sumPutnika = visibleRows.reduce((a, r) => a + (r.broj_putnika || 0), 0);

  // ─── PDF: Preuzmi dokument ────────────────────────────────────────────────
  const [downloading, setDownloading] = useState(false);

  async function downloadDnevniPdf() {
    if (downloading) return;
    setDownloading(true);
    try {
      const token = getToken();
      const res = await fetch(`/api/pregledi/prodaja-aranzmana/pdf?datum=${encodeURIComponent(iso)}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `Dnevna_prodaja_${iso.split("-").reverse().join("-")}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.error(
        err instanceof TypeError
          ? "Server nije dostupan — osveži stranicu i pokušaj ponovo"
          : "Greška pri preuzimanju dokumenta"
      );
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader className="space-y-4">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="space-y-1">
            <CardTitle className="flex items-center gap-2 text-xl">
              <FileBarChart2 className="w-5 h-5 text-muted-foreground" />
              Prodaja aranžmana
            </CardTitle>
            <CardDescription>
              Dnevni izveštaji{data?.datum ? ` · ${data.datum}` : ""}
            </CardDescription>
          </div>
          <div className="flex flex-col items-stretch gap-2 sm:items-end">
            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="outline"
                size="icon"
                aria-label="Prethodni dan"
                onClick={() => setIso((v) => shiftIso(v, -1))}
              >
                <ChevronLeft className="w-4 h-4" />
              </Button>
              <Popover open={kalOpen} onOpenChange={setKalOpen}>
                <PopoverTrigger asChild>
                  <Button
                    variant="outline"
                    className="w-[11.5rem] justify-start gap-2 font-normal"
                    aria-label="Izaberite datum"
                  >
                    <CalendarDays className="w-4 h-4 text-muted-foreground" />
                    {fmtDatum(iso)}
                  </Button>
                </PopoverTrigger>
                <PopoverContent align="end" className="w-80 p-4">
                  <Kalendar
                    view={kalView}
                    onView={setKalView}
                    selectedKey={keyOf(isoToDate(iso))}
                    onPick={(d) => { setIso(toIso(d)); setKalOpen(false); }}
                  />
                  <div className="border-t mt-3 pt-3">
                    <Button
                      variant="outline"
                      size="sm"
                      className="w-full"
                      onClick={() => { setIso(toIso(new Date())); setKalOpen(false); }}
                    >
                      <CalendarDays className="w-4 h-4" />
                      Idi na današnji dan
                    </Button>
                  </div>
                </PopoverContent>
              </Popover>
              <Button
                variant="outline"
                size="icon"
                aria-label="Sledeći dan"
                onClick={() => setIso((v) => shiftIso(v, 1))}
              >
                <ChevronRight className="w-4 h-4" />
              </Button>
            </div>
            <Button variant="outline" onClick={downloadDnevniPdf} disabled={downloading}>
              {downloading
                ? <Loader2 className="w-4 h-4 animate-spin" />
                : <Download className="w-4 h-4" />}
              Preuzmi dokument
            </Button>
          </div>
          </div>
          <div className="flex items-center gap-2">
            <div className="relative flex-1 max-w-md">
              <Search className="absolute left-2.5 top-2.5 w-4 h-4 text-muted-foreground" />
              <Input
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                placeholder="Pretraga po svim poljima..."
                className="pl-9"
              />
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* Summary cards */}
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <Card className="py-0">
              <CardContent className="px-4 py-4">
                <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">Broj ugovora</p>
                {loading ? (
                  <div className="mt-2 h-8 w-16 rounded bg-muted animate-pulse" />
                ) : (
                  <p className="mt-1 text-2xl font-bold tabular-nums">{fmtInt(t?.broj)}</p>
                )}
                <p className="mt-1 text-xs text-muted-foreground">{fmtInt(t?.putnika)} putnika</p>
              </CardContent>
            </Card>
            <Card className="py-0">
              <CardContent className="px-4 py-4">
                <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">ZA NAPLATU</p>
                {loading ? (
                  <div className="mt-2 h-8 w-24 rounded bg-muted animate-pulse" />
                ) : (
                  <p className="mt-1 text-2xl font-bold tabular-nums">{fmtEur(t?.naplata)}</p>
                )}
                <p className="mt-1 text-xs text-muted-foreground">ukupno za naplatu</p>
              </CardContent>
            </Card>
            <Card className="py-0">
              <CardContent className="px-4 py-4">
                <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">Provizija</p>
                {loading ? (
                  <div className="mt-2 h-8 w-24 rounded bg-muted animate-pulse" />
                ) : (
                  <p className="mt-1 text-2xl font-bold tabular-nums">{fmtEur(t?.provizija)}</p>
                )}
                <p className="mt-1 text-xs text-muted-foreground">agencijska provizija</p>
              </CardContent>
            </Card>
            <Card className="py-0">
              <CardContent className="px-4 py-4">
                <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">Vrednost (RSD)</p>
                {loading ? (
                  <div className="mt-2 h-8 w-28 rounded bg-muted animate-pulse" />
                ) : (
                  <p className="mt-1 text-2xl font-bold tabular-nums">{fmtRsd(t?.ukupno_din)}</p>
                )}
                <p className="mt-1 text-xs text-muted-foreground">
                  {data?.kurs ? `kurs ${fmtNum.format(data.kurs)} RSD/€` : "kurs nije dostupan"}
                </p>
              </CardContent>
            </Card>
          </div>

          {/* Table */}
          <div className="rounded-lg border overflow-x-auto">
            <Table className="text-xs">
              <TableHeader>
                <TableRow>
                  {COLUMNS.map((c) => (
                    <TableHead key={c.key} className={cn("h-8 whitespace-nowrap px-2", c.className)}>
                      {c.label}
                    </TableHead>
                  ))}
                </TableRow>
                <TableRow>
                  {COLUMNS.map((c) => (
                    <TableHead key={`${c.key}-filter`} className="h-auto px-2 py-1 align-middle">
                      <Input
                        value={filterInput[c.key] || ""}
                        onChange={(e) => setFilterInput((prev) => ({ ...prev, [c.key]: e.target.value }))}
                        placeholder="Filter..."
                        className="h-6 text-xs"
                      />
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {loading ? (
                  <TableRow>
                    <TableCell colSpan={COLUMNS.length} className="py-12 text-center">
                      <Loader2 className="w-5 h-5 mx-auto animate-spin text-muted-foreground" />
                    </TableCell>
                  </TableRow>
                ) : rows.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={COLUMNS.length} className="py-12 text-center text-muted-foreground">
                      Nema prodaje aranžmana za {data?.datum ?? "izabrani datum"}.
                    </TableCell>
                  </TableRow>
                ) : visibleRows.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={COLUMNS.length} className="py-12 text-center text-muted-foreground">
                      Nema rezultata za zadate filtere.
                    </TableCell>
                  </TableRow>
                ) : (
                  visibleRows.map((r) => (
                    <TableRow key={r.kljuc}>
                      <TableCell className="px-2 py-1 font-medium">
                        <Link
                          to={`/knjigovodstvo/ugovor?u=${encodeURIComponent(r.kljuc)}`}
                          className="hover:underline"
                        >
                          {r.kljuc}
                        </Link>
                      </TableCell>
                      <TableCell className="px-2 py-1 font-medium">{r.putnik || "—"}</TableCell>
                      <TableCell className="px-2 py-1">{r.mesto || "—"}</TableCell>
                      <TableCell className="px-2 py-1">{r.smestaj || "—"}</TableCell>
                      <TableCell className="px-2 py-1">{r.soba || "—"}</TableCell>
                      <TableCell className="whitespace-nowrap px-2 py-1">
                        {r.datum_od || r.datum_do ? `${r.datum_od ?? "—"} – ${r.datum_do ?? "—"}` : "—"}
                      </TableCell>
                      <TableCell className="px-2 py-1">{r.tiprezervacije || "—"}</TableCell>
                      <TableCell className="px-2 py-1">{r.struktura || "—"}</TableCell>
                      <TableCell className="px-2 py-1">{r.obradio || "—"}</TableCell>
                      <TableCell className="px-2 py-1">{r.subagent || "—"}</TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
              {!loading && visibleRows.length > 0 && (
                <TableFooter>
                  <TableRow>
                    <TableCell colSpan={COLUMNS.length} className="px-2 py-1 font-semibold">
                      Ukupno: {fmtInt(visibleRows.length)} ugovora · {fmtInt(sumPutnika)} putnika
                    </TableCell>
                  </TableRow>
                </TableFooter>
              )}
            </Table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
