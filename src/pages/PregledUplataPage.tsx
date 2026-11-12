import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { PregledUplataResp, PregledUplataRow } from "../types";
import { apiFetch, getToken } from "../lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow
} from "@/components/ui/table";
import { CalendarDays, ChevronLeft, ChevronRight, Download, Loader2, Receipt, Search } from "lucide-react";
import { toast } from "sonner";
import {
  Kalendar, fmtDatum, isoToDate, keyOf, shiftIso, toIso, viewFromIso,
} from "@/components/DnevniKalendar";

// Kolone tabele (redosled = redosled prikaza)
const COLUMNS: { key: keyof PregledUplataRow | "vreme"; label: string; className?: string; right?: boolean }[] = [
  { key: "vreme", label: "Vreme", className: "w-16" },
  { key: "kljuc", label: "Uplata", className: "w-20" },
  { key: "ugovor", label: "Ugovor", className: "w-24" },
  { key: "ime", label: "Uplatilac", className: "min-w-44" },
  { key: "nacin", label: "Način", className: "min-w-28" },
  { key: "svrha", label: "Svrha", className: "min-w-32" },
  { key: "din", label: "Iznos (RSD)", className: "w-32", right: true },
  { key: "eur", label: "Iznos (EUR)", className: "w-28", right: true },
  { key: "obradio", label: "Operater", className: "min-w-28" },
  { key: "poslovnica", label: "Poslovnica", className: "min-w-28" },
];

/** Tekst reda po ključu kolone — za globalnu pretragu */
function rowText(r: PregledUplataRow): string {
  return [r.kljuc, r.vreme, r.ugovor, r.ime, r.nacin, r.svrha, r.din, r.eur, r.obradio, r.poslovnica]
    .map((v) => (v == null ? "" : String(v)))
    .join(" ")
    .toLowerCase();
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

export default function PregledUplataPage() {
  const [iso, setIso] = useState<string>(() => toIso(new Date()));
  const [kalOpen, setKalOpen] = useState(false);
  const [kalView, setKalView] = useState(() => viewFromIso(toIso(new Date())));
  const [data, setData] = useState<PregledUplataResp | null>(null);
  const [loading, setLoading] = useState(true);
  const requestId = useRef(0);

  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");

  // mesec kalendara prati izabrani datum
  useEffect(() => { setKalView(viewFromIso(iso)); }, [iso]);

  useEffect(() => {
    const t = setTimeout(() => setSearch(searchInput.trim().toLowerCase()), 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  const load = useCallback(async (d: string) => {
    const rid = ++requestId.current;
    setLoading(true);
    try {
      const resp = await apiFetch<PregledUplataResp>(
        `/pregledi/uplate?datum=${encodeURIComponent(d)}`
      );
      if (rid !== requestId.current) return;
      setData(resp);
    } catch (e) {
      if (rid !== requestId.current) return;
      toast.error(e instanceof Error ? e.message : "Greška pri učitavanju uplata");
    } finally {
      if (rid === requestId.current) setLoading(false);
    }
  }, []);

  useEffect(() => { load(iso); }, [load, iso]);

  const rows = data?.rows ?? [];
  const t = data?.totals;

  const visibleRows = useMemo(() => {
    if (!search) return rows;
    return rows.filter((r) => rowText(r).includes(search));
  }, [rows, search]);

  const sumVisibleDin = visibleRows.reduce((a, r) => a + (r.din || 0), 0);

  // ─── PDF: pregled po načinu plaćanja ──────────────────────────────────────
  const [downloadingNacin, setDownloadingNacin] = useState<string | null>(null);

  async function downloadPregledPdf(nacin: "Gotovina" | "Ček" | "Kartica") {
    if (downloadingNacin) return;
    setDownloadingNacin(nacin);
    try {
      const token = getToken();
      const res = await fetch(
        `/api/pregledi/uplate/pdf?datum=${encodeURIComponent(iso)}&nacin=${encodeURIComponent(nacin)}`,
        { headers: token ? { Authorization: `Bearer ${token}` } : undefined },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const ime = nacin === "Ček" ? "Cek" : nacin;
      a.download = `Pregled_uplata_${ime}_${iso.split("-").reverse().join("-")}.pdf`;
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
      setDownloadingNacin(null);
    }
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader className="space-y-4">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div className="space-y-1">
              <CardTitle className="flex items-center gap-2 text-xl">
                <Receipt className="w-5 h-5 text-muted-foreground" />
                Pregled uplata
              </CardTitle>
              <CardDescription>
                Dnevni izveštaj uplata{data?.datum ? ` · ${data.datum}` : ""}
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
            <div className="flex flex-wrap items-center gap-2">
              {(["Gotovina", "Ček", "Kartica"] as const).map((n) => (
                <Button
                  key={n}
                  variant="outline"
                  size="sm"
                  onClick={() => downloadPregledPdf(n)}
                  disabled={downloadingNacin !== null}
                >
                  {downloadingNacin === n
                    ? <Loader2 className="w-4 h-4 animate-spin" />
                    : <Download className="w-4 h-4" />}
                  PDF {n}
                </Button>
              ))}
            </div>
            </div>
          </div>
          <div className="relative max-w-md">
            <Search className="absolute left-2.5 top-2.5 w-4 h-4 text-muted-foreground" />
            <Input
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Pretraga po svim poljima..."
              className="pl-9"
            />
          </div>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* Summary cards */}
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <Card className="py-0">
              <CardContent className="px-4 py-4">
                <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">Broj uplata</p>
                {loading ? (
                  <div className="mt-2 h-8 w-16 rounded bg-muted animate-pulse" />
                ) : (
                  <p className="mt-1 text-2xl font-bold tabular-nums">{fmtInt(t?.broj)}</p>
                )}
                <p className="mt-1 text-xs text-muted-foreground">na izabrani dan</p>
              </CardContent>
            </Card>
            <Card className="py-0">
              <CardContent className="px-4 py-4">
                <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">Ukupno (RSD)</p>
                {loading ? (
                  <div className="mt-2 h-8 w-28 rounded bg-muted animate-pulse" />
                ) : (
                  <p className="mt-1 text-2xl font-bold tabular-nums">{fmtRsd(t?.din)}</p>
                )}
                <p className="mt-1 text-xs text-muted-foreground">zbir uplata</p>
              </CardContent>
            </Card>
            <Card className="py-0">
              <CardContent className="px-4 py-4">
                <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">Ukupno (EUR)</p>
                {loading ? (
                  <div className="mt-2 h-8 w-24 rounded bg-muted animate-pulse" />
                ) : (
                  <p className="mt-1 text-2xl font-bold tabular-nums">{fmtEur(t?.eur)}</p>
                )}
                <p className="mt-1 text-xs text-muted-foreground">
                  {data?.kurs ? `kurs ${fmtNum.format(data.kurs)} RSD/€` : "kurs nije dostupan"}
                </p>
              </CardContent>
            </Card>
            <Card className="py-0">
              <CardContent className="px-4 py-4">
                <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">Prikazano</p>
                {loading ? (
                  <div className="mt-2 h-8 w-24 rounded bg-muted animate-pulse" />
                ) : (
                  <p className="mt-1 text-2xl font-bold tabular-nums">{fmtRsd(sumVisibleDin)}</p>
                )}
                <p className="mt-1 text-xs text-muted-foreground">
                  {fmtInt(visibleRows.length)} od {fmtInt(rows.length)} po filteru
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
                    <TableHead
                      key={c.key}
                      className={`h-8 whitespace-nowrap px-2 ${c.right ? "text-right" : ""} ${c.className ?? ""}`}
                    >
                      {c.label}
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
                      Nema uplata za {data?.datum ?? "izabrani datum"}.
                    </TableCell>
                  </TableRow>
                ) : visibleRows.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={COLUMNS.length} className="py-12 text-center text-muted-foreground">
                      Nema rezultata za zadatu pretragu.
                    </TableCell>
                  </TableRow>
                ) : (
                  visibleRows.map((r) => (
                    <TableRow key={r.kljuc}>
                      <TableCell className="px-2 py-1">{r.vreme || "—"}</TableCell>
                      <TableCell className="px-2 py-1">{r.kljuc}</TableCell>
                      <TableCell className="px-2 py-1 font-medium">{r.ugovor || "—"}</TableCell>
                      <TableCell className="px-2 py-1 font-medium">{r.ime || "—"}</TableCell>
                      <TableCell className="px-2 py-1">{r.nacin || "—"}</TableCell>
                      <TableCell className="px-2 py-1">{r.svrha || "—"}</TableCell>
                      <TableCell className="px-2 py-1 text-right tabular-nums">{fmtNum.format(r.din)}</TableCell>
                      <TableCell className="px-2 py-1 text-right tabular-nums">
                        {r.eur == null ? "—" : fmtNum.format(r.eur)}
                      </TableCell>
                      <TableCell className="px-2 py-1">{r.obradio || "—"}</TableCell>
                      <TableCell className="px-2 py-1">{r.poslovnica || "—"}</TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
              {!loading && visibleRows.length > 0 && (
                <TableFooter>
                  <TableRow>
                    <TableCell colSpan={COLUMNS.length} className="px-2 py-1 font-semibold">
                      Ukupno: {fmtInt(visibleRows.length)} uplata · {fmtRsd(sumVisibleDin)}
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
