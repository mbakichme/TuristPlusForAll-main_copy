import { useEffect, useState } from "react";
import { format, parseISO } from "date-fns";
import { srLatn } from "date-fns/locale";
import { CalendarDays, ChevronLeft, ChevronRight, Loader2, RotateCcw } from "lucide-react";
import { apiFetch } from "../lib/api";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

interface KursRow {
  id: number;
  iznos: number;
  datum: string;
  datum_kursa: string;
}

interface KursPregled {
  rows: KursRow[];
  total: number;
  page: number;
  page_size: number;
}

const PAGE_SIZE = 100;
const kursFormatter = new Intl.NumberFormat("sr-RS", {
  minimumFractionDigits: 4,
  maximumFractionDigits: 4,
});

function prikazDatuma(value: string) {
  return format(parseISO(value.slice(0, 10)), "dd.MM.yyyy");
}

export default function KursPage() {
  const [datum, setDatum] = useState("");
  const [calendarOpen, setCalendarOpen] = useState(false);
  const [page, setPage] = useState(1);
  const [data, setData] = useState<KursPregled | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError("");
    const params = new URLSearchParams({ datum, page: String(page), page_size: String(PAGE_SIZE) });
    apiFetch<KursPregled>(`/kurs/pregled?${params}`, { signal: controller.signal })
      .then((result) => { if (active) setData(result); })
      .catch((e: unknown) => {
        if (active) {
          setData(null);
          setError(e instanceof Error ? e.message : "Greška pri učitavanju kursa.");
        }
      })
      .finally(() => { if (active) setLoading(false); });
    return () => {
      active = false;
      controller.abort();
    };
  }, [datum, page, retry]);

  function promeniDatum(value: string) {
    if (value !== datum) {
      setLoading(true);
      setDatum(value);
      setPage(1);
    }
    setCalendarOpen(false);
  }

  function promeniStranicu(value: number) {
    setLoading(true);
    setPage(value);
  }

  const selectedDate = datum ? parseISO(datum) : undefined;
  const pageCount = Math.max(1, Math.ceil((data?.total ?? 0) / PAGE_SIZE));

  return (
    <div className="p-4 md:p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Kurs</h1>
        <p className="text-muted-foreground text-sm mt-1">Srednji kurs NBS · 1 EUR u RSD</p>
      </div>

      <Card>
        <CardHeader className="pb-4">
          <CardTitle className="text-base">Pregled kurseva</CardTitle>
          <CardDescription>Pregled sačuvanih kurseva po datumu.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-2">
              <Label htmlFor="kurs-datum">Datum</Label>
              <Popover open={calendarOpen} onOpenChange={setCalendarOpen}>
                <PopoverTrigger asChild>
                  <Button id="kurs-datum" variant="outline" className="w-48 justify-start gap-2 font-normal">
                    <CalendarDays className="size-4 shrink-0" />
                    <span className={datum ? undefined : "text-muted-foreground"}>
                      {datum ? prikazDatuma(datum) : "dd.mm.yyyy"}
                    </span>
                  </Button>
                </PopoverTrigger>
                <PopoverContent align="start" className="w-auto p-0">
                  <Calendar
                    mode="single"
                    selected={selectedDate}
                    defaultMonth={selectedDate}
                    onSelect={(date) => promeniDatum(date ? format(date, "yyyy-MM-dd") : "")}
                    locale={srLatn}
                    weekStartsOn={1}
                    captionLayout="dropdown"
                    startMonth={new Date(2000, 0)}
                    endMonth={new Date(new Date().getFullYear() + 5, 11)}
                  />
                </PopoverContent>
              </Popover>
            </div>
            <Button variant="outline" disabled={!datum} onClick={() => promeniDatum("")}>
              Prikaži sve
            </Button>
          </div>

          <div className="rounded-md border" aria-busy={loading}>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="whitespace-nowrap">Datum</TableHead>
                  <TableHead className="text-right whitespace-nowrap">Kurs (RSD)</TableHead>
                  <TableHead className="whitespace-nowrap">Datum kursne liste</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {loading ? (
                  <TableRow>
                    <TableCell colSpan={3} className="h-32 text-center">
                      <div role="status" className="flex items-center justify-center gap-2 text-muted-foreground">
                        <Loader2 className="size-4 animate-spin" aria-hidden="true" />
                        Učitavanje kurseva…
                      </div>
                    </TableCell>
                  </TableRow>
                ) : error ? (
                  <TableRow>
                    <TableCell colSpan={3} className="h-32 text-center">
                      <div className="space-y-3">
                        <p role="alert" className="text-sm text-destructive">{error}</p>
                        <Button variant="outline" size="sm" onClick={() => { setLoading(true); setRetry((v) => v + 1); }}>
                          <RotateCcw className="size-4 mr-2" />Pokušaj ponovo
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ) : !data?.rows.length ? (
                  <TableRow>
                    <TableCell colSpan={3} className="h-32 text-center text-muted-foreground">
                      <p role="status">
                        {datum ? `Nema sačuvanog kursa za ${prikazDatuma(datum)}.` : "Nema sačuvanih kurseva."}
                      </p>
                    </TableCell>
                  </TableRow>
                ) : data.rows.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell className="py-2 whitespace-nowrap tabular-nums">{prikazDatuma(row.datum)}</TableCell>
                    <TableCell className="py-2 text-right font-medium tabular-nums">{kursFormatter.format(row.iznos)}</TableCell>
                    <TableCell className="py-2 whitespace-nowrap tabular-nums">{prikazDatuma(row.datum_kursa)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          {!error && data && data.total > PAGE_SIZE && (
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-sm text-muted-foreground" aria-live="polite">
                Stranica {page} od {pageCount} · Ukupno: {data.total}
              </p>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" disabled={loading || page <= 1} onClick={() => promeniStranicu(page - 1)}>
                  <ChevronLeft className="size-4 mr-1" />Prethodna
                </Button>
                <Button variant="outline" size="sm" disabled={loading || page >= pageCount} onClick={() => promeniStranicu(page + 1)}>
                  Sledeća<ChevronRight className="size-4 ml-1" />
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
