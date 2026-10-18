import { useState, useEffect, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import type { UgovorRow, UgovoriResponse } from "../types";
import { apiFetch } from "../lib/api";
import { Button } from "@/components/ui/button";
import { PageLoader } from "@/components/PageLoader";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow
} from "@/components/ui/table";
import {
  Loader2, FileText, Search, ChevronUp, ChevronDown, RefreshCw
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

const COLUMNS: { key: string; label: string; sortable: boolean }[] = [
  { key: "kljuc", label: "Broj ugovora", sortable: true },
  { key: "danas", label: "Datum", sortable: true },
  { key: "putnik", label: "Nosilac", sortable: true },
  { key: "mesto", label: "Mesto", sortable: true },
  { key: "naziv", label: "Smeštaj", sortable: true },
  { key: "struktura", label: "Struktura / soba", sortable: false },
  { key: "subagent", label: "Subagent", sortable: true },
  { key: "datumod", label: "Termin", sortable: true },
  { key: "ukupna_vrednost", label: "Ukupna vrednost", sortable: false },
];

// Kolone sa filter-redom (ukupna_vrednost je računato polje — bez filtera)
const FILTER_COLS = COLUMNS.filter((c) => c.key !== "ukupna_vrednost").map((c) => c.key);
const emptyFilters = (): Record<string, string> => Object.fromEntries(FILTER_COLS.map((k) => [k, ""]));

const BATCH_SIZE = 100;

const fmtRSD = (v: number | null | undefined) =>
  v == null ? "—" : new Intl.NumberFormat("sr-RS", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(v) + " RSD";

/** "DD.MM.YYYY" + "DD.MM.YYYY" → "04.07-14.07.2026" (ista godina); različita godina → "28.12.2026-03.01.2027" */
const fmtTermin = (od: string | null | undefined, doDatum: string | null | undefined) => {
  const a = (od || "").split(".");
  const b = (doDatum || "").split(".");
  if (a.length !== 3 || b.length !== 3) return "—";
  if (a[2] === b[2]) return `${a[0]}.${a[1]}-${b[0]}.${b[1]}.${b[2]}`;
  return `${od}-${doDatum}`;
};

export default function UgovoriPage() {
  const navigate = useNavigate();
  const [rows, setRows] = useState<UgovorRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState("danas");
  const [dir, setDir] = useState<"asc" | "desc">("desc");
  const [filterInput, setFilterInput] = useState<Record<string, string>>(emptyFilters);
  const [filters, setFilters] = useState<Record<string, string>>(emptyFilters);
  const [loading, setLoading] = useState(true);
  const [more, setMore] = useState(false);
  const requestId = useRef(0);
  const hasMoreRef = useRef(true);
  const sentinelRef = useRef<HTMLDivElement | null>(null);

  // Debounce unosa pretrage
  useEffect(() => {
    const t = setTimeout(() => setSearch(searchInput.trim()), 400);
    return () => clearTimeout(t);
  }, [searchInput]);

  // Debounce filter-reda (min 3 karaktera po polju — proverava i server)
  useEffect(() => {
    const t = setTimeout(() => setFilters({ ...filterInput }), 400);
    return () => clearTimeout(t);
  }, [filterInput]);

  const loadBatch = useCallback(async (
    p: number, replace: boolean, s: string, sk: string, d: string, f: Record<string, string>
  ) => {
    const rid = ++requestId.current;
    if (replace) setLoading(true); else setMore(true);
    try {
      const params = new URLSearchParams({
        page: String(p),
        page_size: String(BATCH_SIZE),
        sort: sk,
        dir: d,
      });
      if (s) params.set("search", s);
      for (const [k, v] of Object.entries(f)) {
        const val = (v || "").trim();
        if (val.length >= 3) params.set(`f_${k}`, val);
      }
      const data = await apiFetch<UgovoriResponse>(`/ugovori?${params}`);
      if (rid !== requestId.current) return; // zastareo odgovor — preskoči
      setRows((prev) => (replace ? data.rows : [...prev, ...data.rows]));
      setTotal(data.total);
      setPage(data.page);
      hasMoreRef.current = data.rows.length >= BATCH_SIZE;
    } catch {
      toast.error("Greška pri učitavanju ugovora");
    } finally {
      if (rid === requestId.current) {
        setLoading(false);
        setMore(false);
      }
    }
  }, []);

  // Prvo učitavanje i reload na promenu pretrage/sortiranja/filtera
  useEffect(() => {
    loadBatch(1, true, search, sort, dir, filters);
  }, [search, sort, dir, filters, loadBatch]);

  function toggleSort(key: string) {
    if (sort === key) {
      setDir(dir === "asc" ? "desc" : "asc");
    } else {
      setSort(key);
      setDir("asc");
    }
  }

  function refresh() {
    loadBatch(1, true, search, sort, dir, filters);
  }

  // Infinite scroll — učitaj sledeću seriju kad se sentinel pojavi u viewportu
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && !loading && !more && hasMoreRef.current) {
          loadBatch(page + 1, false, search, sort, dir, filters);
        }
      },
      { rootMargin: "600px" }
    );
    io.observe(el);
    return () => io.disconnect();
  }, [page, loading, more, search, sort, dir, filters, loadBatch]);

  const shown = rows.length;

  return (
    <div className="p-4 space-y-3 text-xs">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">Ugovori</h1>
          <p className="text-muted-foreground text-xs">Preuzeti ugovori</p>
        </div>
        <Button variant="outline" size="sm" onClick={refresh}>
          <RefreshCw className="w-3.5 h-3.5 mr-1.5" />Osveži
        </Button>
      </div>

      <Card>
        <CardHeader className="p-3 pb-2 space-y-1">
          <CardTitle className="flex items-center gap-2 text-sm">
            <FileText className="w-4 h-4" />Ugovori
          </CardTitle>
          <CardDescription className="text-xs">
            Ukupno: <span className="font-semibold text-foreground">{total.toLocaleString("sr-RS")}</span> zapisa
            {" · "}prikazano: <span className="font-semibold text-foreground">{shown.toLocaleString("sr-RS")}</span>
          </CardDescription>
          <div className="flex items-center gap-2 pt-1">
            <div className="relative flex-1 max-w-md">
              <Search className="absolute left-2.5 top-2 w-3.5 h-3.5 text-muted-foreground" />
              <Input
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                placeholder="Pretraga po svim poljima..."
                className="pl-8 h-7 text-xs"
              />
              {loading && <Loader2 className="absolute right-2.5 top-2 w-3.5 h-3.5 animate-spin text-muted-foreground" />}
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-3 pt-0">
          <div className="rounded-md border">
            <Table className="text-xs">
              <TableHeader>
                <TableRow className="h-7">
                  {COLUMNS.map((c) => (
                    <TableHead key={c.key} className="h-7 px-2 py-1 whitespace-nowrap">
                      {c.sortable ? (
                        <button
                          onClick={() => toggleSort(c.key)}
                          className="inline-flex items-center gap-0.5 hover:text-foreground transition-colors"
                        >
                          {c.label}
                          {sort === c.key ? (
                            dir === "asc"
                              ? <ChevronUp className="w-3 h-3" />
                              : <ChevronDown className="w-3 h-3" />
                          ) : (
                            <ChevronUp className="w-3 h-3 opacity-0" />
                          )}
                        </button>
                      ) : (
                        c.label
                      )}
                    </TableHead>
                  ))}
                </TableRow>
                <TableRow className="h-7">
                  {COLUMNS.map((c) => (
                    <TableHead key={`${c.key}-filter`} className="h-auto px-2 py-0.5 align-middle">
                      {FILTER_COLS.includes(c.key) ? (
                        <div className="relative">
                          <Input
                            value={filterInput[c.key] || ""}
                            onChange={(e) => setFilterInput((prev) => ({ ...prev, [c.key]: e.target.value }))}
                            placeholder="Filter..."
                            className="h-6 text-xs px-1.5"
                          />
                          {loading && (filterInput[c.key] || "").trim().length >= 3 && (
                            <Loader2 className="absolute right-1.5 top-1 w-3 h-3 animate-spin text-muted-foreground" />
                          )}
                        </div>
                      ) : null}
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {loading && rows.length === 0 ? (
                  <TableRow className="hover:bg-transparent">
                    <TableCell colSpan={COLUMNS.length} className="p-0">
                      <PageLoader className="min-h-[40vh] gap-6" />
                    </TableCell>
                  </TableRow>
                ) : rows.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={COLUMNS.length} className="text-center text-muted-foreground py-10">
                      {search ? "Nema rezultata za pretragu" : "Nema ugovora. Koristite stranicu preuzimanje_podataka da uvezete ugovore."}
                    </TableCell>
                  </TableRow>
                ) : (
                  rows.map((r, idx) => {
                    const hasSubagent = !!(r.subagent || "").trim();
                    return (
                      <TableRow
                        key={`${r.kljuc}-${idx}`}
                        className={cn(
                          "cursor-pointer hover:bg-muted/50 h-7",
                          hasSubagent && "bg-indigo-50/70 hover:bg-indigo-100/80 dark:bg-indigo-950/40 dark:hover:bg-indigo-900/50"
                        )}
                        title={hasSubagent ? `Subagent: ${r.subagent}` : undefined}
                        onClick={() => navigate(`/prodaja/rezervacije?u=${encodeURIComponent(r.kljuc)}`)}
                      >
                        <TableCell className="px-2 py-1 font-mono font-medium">{r.kljuc}</TableCell>
                        <TableCell className="px-2 py-1 whitespace-nowrap">{r.danas || "—"}</TableCell>
                        <TableCell className="px-2 py-1 font-medium">{r.putnik || "—"}</TableCell>
                        <TableCell className="px-2 py-1">{r.mesto || "—"}</TableCell>
                        <TableCell className="px-2 py-1">{r.naziv || "—"}</TableCell>
                        <TableCell className="px-2 py-1 whitespace-nowrap">
                          {[r.struktura, r.soba].filter((x) => (x || "").trim()).join(" · ") || "—"}
                        </TableCell>
                        <TableCell className="px-2 py-1">{r.subagent || "—"}</TableCell>
                        <TableCell className="px-2 py-1 whitespace-nowrap">{fmtTermin(r.datumod, r.datumdo)}</TableCell>
                        <TableCell className="px-2 py-1 whitespace-nowrap font-medium">
                          {fmtRSD(r.ukupna_vrednost)}
                        </TableCell>
                      </TableRow>
                    );
                  })
                )}
              </TableBody>
            </Table>
          </div>

          {/* Infinite scroll sentinel */}
          <div ref={sentinelRef} className="flex items-center justify-center gap-2 py-4">
            {more && (
              <>
                <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
                <span className="text-sm text-muted-foreground">Učitavanje još zapisa...</span>
              </>
            )}
            {!more && !loading && !hasMoreRef.current && shown > 0 && (
              <span className="text-sm text-muted-foreground">
                Prikazano svih {shown.toLocaleString("sr-RS")} od {total.toLocaleString("sr-RS")} zapisa
              </span>
            )}
            {!more && !loading && hasMoreRef.current && shown > 0 && (
              <span className="text-sm text-muted-foreground">Skrolujte dole za još zapisa...</span>
            )}
          </div>
        </CardContent>
      </Card>

    </div>
  );
}
