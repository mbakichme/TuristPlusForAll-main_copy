import { useState, useEffect, useCallback, useRef } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import type { UgovorRow, UgovoriResponse } from "../types";
import { apiFetch } from "../lib/api";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
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
  { key: "datumod", label: "Polazak", sortable: true },
  { key: "datumdo", label: "Povratak", sortable: true },
  { key: "ukupna_vrednost", label: "Ukupna vrednost", sortable: false },
];

// Kolone sa filter-redom (ukupna_vrednost je računato polje — bez filtera)
const FILTER_COLS = COLUMNS.filter((c) => c.key !== "ukupna_vrednost").map((c) => c.key);
const emptyFilters = (): Record<string, string> => Object.fromEntries(FILTER_COLS.map((k) => [k, ""]));

const BATCH_SIZE = 100;

// Tabovi: grupa po aranzman.tiprezervacije (REZERVACIJE = sve osim PREDREZERVACIJA i STORNO)
type TipTab = "rezervacije" | "predrezervacija" | "storno";
const TABOVI: { key: TipTab; label: string; boja: string }[] = [
  { key: "rezervacije", label: "REZERVACIJE", boja: "data-[state=active]:bg-blue-600" },
  { key: "predrezervacija", label: "PREDREZERVACIJA", boja: "data-[state=active]:bg-amber-500" },
  { key: "storno", label: "STORNO", boja: "data-[state=active]:bg-red-600" },
];
const jeTipTab = (v: string | null): v is TipTab =>
  v === "rezervacije" || v === "predrezervacija" || v === "storno";

const fmtRSD = (v: number | null | undefined) =>
  v == null ? "—" : new Intl.NumberFormat("sr-RS", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(v) + " RSD";


export default function UgovoriPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const tabParam = searchParams.get("tab");
  const tip: TipTab = jeTipTab(tabParam) ? tabParam : "rezervacije";
  const [poTipu, setPoTipu] = useState<Record<TipTab, number> | null>(null);
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
  const replaceInFlight = useRef(false);
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
    p: number, replace: boolean, s: string, sk: string, d: string, f: Record<string, string>, t: TipTab
  ) => {
    // Dok traje učitavanje prve strane (npr. posle promene taba) ne dovlači sledeće —
    // inače bi novi requestId poništio odgovor prve strane.
    if (!replace && replaceInFlight.current) return;
    const rid = ++requestId.current;
    if (replace) { replaceInFlight.current = true; setLoading(true); } else setMore(true);
    try {
      const params = new URLSearchParams({
        page: String(p),
        page_size: String(BATCH_SIZE),
        sort: sk,
        dir: d,
        tip: t,
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
      if (data.po_tipu) setPoTipu(data.po_tipu);
      setPage(data.page);
      hasMoreRef.current = data.rows.length >= BATCH_SIZE;
    } catch {
      toast.error("Greška pri učitavanju ugovora");
    } finally {
      if (rid === requestId.current) {
        replaceInFlight.current = false;
        setLoading(false);
        setMore(false);
      }
    }
  }, []);

  // Prvo učitavanje i reload na promenu pretrage/sortiranja/filtera
  useEffect(() => {
    loadBatch(1, true, search, sort, dir, filters, tip);
  }, [search, sort, dir, filters, tip, loadBatch]);

  function promeniTab(v: string) {
    if (!jeTipTab(v) || v === tip) return;
    setRows([]);
    hasMoreRef.current = true;
    setSearchParams((prev) => {
      const n = new URLSearchParams(prev);
      n.set("tab", v);
      return n;
    }, { replace: true });
  }

  function toggleSort(key: string) {
    if (sort === key) {
      setDir(dir === "asc" ? "desc" : "asc");
    } else {
      setSort(key);
      setDir("asc");
    }
  }

  function refresh() {
    loadBatch(1, true, search, sort, dir, filters, tip);
  }

  // Infinite scroll — učitaj sledeću seriju kad se sentinel pojavi u viewportu
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && !loading && !more && hasMoreRef.current) {
          loadBatch(page + 1, false, search, sort, dir, filters, tip);
        }
      },
      { rootMargin: "600px" }
    );
    io.observe(el);
    return () => io.disconnect();
  }, [page, loading, more, search, sort, dir, filters, tip, loadBatch]);

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

      <Tabs value={tip} onValueChange={promeniTab}>
        <TabsList className="h-11 gap-1 p-1">
          {TABOVI.map((t) => (
            <TabsTrigger
              key={t.key}
              value={t.key}
              className={cn("h-9 px-5 text-sm font-semibold gap-2 data-[state=active]:text-white", t.boja)}
            >
              {t.label}
              <span className="rounded-full bg-black/10 px-2 py-0.5 text-xs font-medium tabular-nums">
                {poTipu ? poTipu[t.key].toLocaleString("sr-RS") : "…"}
              </span>
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      <Card>
        <CardHeader className="p-3 pb-2 space-y-1">
          <CardTitle className="flex items-center gap-2 text-sm">
            <FileText className="w-4 h-4" />{TABOVI.find((t) => t.key === tip)?.label}
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
                      {search ? "Nema rezultata za pretragu" : "Nema ugovora."}
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
                        <TableCell className="px-2 py-1 whitespace-nowrap">{r.datumod || "—"}</TableCell>
                        <TableCell className="px-2 py-1 whitespace-nowrap">{r.datumdo || "—"}</TableCell>
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
