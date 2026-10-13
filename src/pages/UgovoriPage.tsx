import { useState, useEffect, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import type { UgovorRow, UgovoriResponse, UgovorDetail, UplataRow } from "../types";
import { apiFetch } from "../lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow
} from "@/components/ui/table";
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle
} from "@/components/ui/dialog";
import {
  Loader2, FileText, Search, ChevronUp, ChevronDown, RefreshCw, Receipt, Eye, FilePlus
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { fmtPutnici } from "@/lib/putnici";

const COLUMNS: { key: string; label: string; sortable: boolean }[] = [
  { key: "kljuc", label: "Broj ugovora", sortable: true },
  { key: "danas", label: "Datum", sortable: true },
  { key: "putnik", label: "Nosilac", sortable: true },
  { key: "mesto", label: "Mesto", sortable: true },
  { key: "naziv", label: "Smeštaj", sortable: true },
  { key: "subagent", label: "Subagent", sortable: true },
  { key: "datumod", label: "Datum od", sortable: true },
  { key: "datumdo", label: "Datum do", sortable: true },
  { key: "ukupna_vrednost", label: "Ukupna vrednost", sortable: false },
];

// Kolone sa filter-redom (ukupna_vrednost je računato polje — bez filtera)
const FILTER_COLS = COLUMNS.filter((c) => c.key !== "ukupna_vrednost").map((c) => c.key);
const emptyFilters = (): Record<string, string> => Object.fromEntries(FILTER_COLS.map((k) => [k, ""]));

const BATCH_SIZE = 100;

const fmtRSD = (v: number | null | undefined) =>
  v == null ? "—" : new Intl.NumberFormat("sr-RS", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(v) + " RSD";
const fmtEUR = (v: number | null | undefined) =>
  v == null ? "—" : new Intl.NumberFormat("sr-RS", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(v) + " €";

export default function UgovoriPage() {
  const navigate = useNavigate();
  const [rows, setRows] = useState<UgovorRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState("kljuc");
  const [dir, setDir] = useState<"asc" | "desc">("asc");
  const [filterInput, setFilterInput] = useState<Record<string, string>>(emptyFilters);
  const [filters, setFilters] = useState<Record<string, string>>(emptyFilters);
  const [loading, setLoading] = useState(true);
  const [more, setMore] = useState(false);
  const requestId = useRef(0);
  const hasMoreRef = useRef(true);
  const sentinelRef = useRef<HTMLDivElement | null>(null);

  // dialog
  const [openKljuc, setOpenKljuc] = useState<string | null>(null);
  const [detail, setDetail] = useState<UgovorDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [uplate, setUplate] = useState<UplataRow[] | null>(null);
  const [uplateLoading, setUplateLoading] = useState(false);
  const [showUplate, setShowUplate] = useState(false);

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

  function openDetail(kljuc: string) {
    setOpenKljuc(kljuc);
    setDetail(null);
    setUplate(null);
    setShowUplate(false);
    setDetailLoading(true);
    apiFetch<UgovorDetail>(`/ugovori/${kljuc}`)
      .then(setDetail)
      .catch(() => toast.error("Greška pri učitavanju ugovora"))
      .finally(() => setDetailLoading(false));
  }

  function loadUplate(kljuc: string) {
    setUplateLoading(true);
    apiFetch<{ rows: UplataRow[] }>(`/ugovori/${kljuc}/uplate`)
      .then((d) => setUplate(d.rows))
      .catch(() => toast.error("Greška pri učitavanju uplata"))
      .finally(() => setUplateLoading(false));
  }

  const shown = rows.length;

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Ugovori</h1>
          <p className="text-muted-foreground text-sm">Preuzeti ugovori</p>
        </div>
        <Button variant="outline" onClick={refresh}>
          <RefreshCw className="w-4 h-4 mr-2" />Osveži
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileText className="w-5 h-5" />Ugovori
          </CardTitle>
          <CardDescription>
            Ukupno: <span className="font-semibold text-foreground">{total.toLocaleString("sr-RS")}</span> zapisa
            {" · "}prikazano: <span className="font-semibold text-foreground">{shown.toLocaleString("sr-RS")}</span>
          </CardDescription>
          <div className="flex items-center gap-2 pt-2">
            <div className="relative flex-1 max-w-md">
              <Search className="absolute left-2.5 top-2.5 w-4 h-4 text-muted-foreground" />
              <Input
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                placeholder="Pretraga po svim poljima..."
                className="pl-9"
              />
              {loading && <Loader2 className="absolute right-2.5 top-2.5 w-4 h-4 animate-spin text-muted-foreground" />}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  {COLUMNS.map((c) => (
                    <TableHead key={c.key} className="whitespace-nowrap">
                      {c.sortable ? (
                        <button
                          onClick={() => toggleSort(c.key)}
                          className="inline-flex items-center gap-1 hover:text-foreground transition-colors"
                        >
                          {c.label}
                          {sort === c.key ? (
                            dir === "asc"
                              ? <ChevronUp className="w-3.5 h-3.5" />
                              : <ChevronDown className="w-3.5 h-3.5" />
                          ) : (
                            <ChevronUp className="w-3.5 h-3.5 opacity-0" />
                          )}
                        </button>
                      ) : (
                        c.label
                      )}
                    </TableHead>
                  ))}
                </TableRow>
                <TableRow>
                  {COLUMNS.map((c) => (
                    <TableHead key={`${c.key}-filter`} className="h-auto px-2 py-1 align-middle">
                      {FILTER_COLS.includes(c.key) ? (
                        <div className="relative">
                          <Input
                            value={filterInput[c.key] || ""}
                            onChange={(e) => setFilterInput((prev) => ({ ...prev, [c.key]: e.target.value }))}
                            placeholder="Filter..."
                            className="h-7 text-xs"
                          />
                          {loading && (filterInput[c.key] || "").trim().length >= 3 && (
                            <Loader2 className="absolute right-2 top-1.5 w-3.5 h-3.5 animate-spin text-muted-foreground" />
                          )}
                        </div>
                      ) : null}
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {loading && rows.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={COLUMNS.length} className="text-center py-10">
                      <Loader2 className="w-6 h-6 animate-spin mx-auto text-muted-foreground" />
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
                          "cursor-pointer hover:bg-muted/50",
                          hasSubagent && "bg-indigo-50/70 hover:bg-indigo-100/80 dark:bg-indigo-950/40 dark:hover:bg-indigo-900/50"
                        )}
                        title={hasSubagent ? `Subagent: ${r.subagent}` : undefined}
                        onClick={() => openDetail(r.kljuc)}
                      >
                        <TableCell className="font-mono font-medium">{r.kljuc}</TableCell>
                        <TableCell className="whitespace-nowrap">{r.danas || "—"}</TableCell>
                        <TableCell className="font-medium">{r.putnik || "—"}</TableCell>
                        <TableCell>{r.mesto || "—"}</TableCell>
                        <TableCell>{r.naziv || "—"}</TableCell>
                        <TableCell>{r.subagent || "—"}</TableCell>
                        <TableCell className="whitespace-nowrap">{r.datumod || "—"}</TableCell>
                        <TableCell className="whitespace-nowrap">{r.datumdo || "—"}</TableCell>
                        <TableCell className="whitespace-nowrap font-medium">
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

      {/* Detalj ugovora */}
      <Dialog open={openKljuc != null} onOpenChange={(o) => { if (!o) setOpenKljuc(null); }}>
        <DialogContent className="max-w-3xl text-xs max-h-[85vh] overflow-y-auto">
          <DialogHeader className="space-y-1">
            <DialogTitle className="flex items-center gap-2 text-base">
              <FileText className="w-4 h-4" />
              Ugovor {openKljuc}
            </DialogTitle>
            <DialogDescription className="text-xs">Detalji ugovora i obračun vrednosti</DialogDescription>
          </DialogHeader>

          {detailLoading ? (
            <div className="py-10 text-center">
              <Loader2 className="w-6 h-6 animate-spin mx-auto text-muted-foreground" />
            </div>
          ) : detail ? (
            <div className="space-y-3">
              <div className="grid grid-cols-3 gap-x-4 gap-y-1.5 text-xs">
                <div>
                  <div className="text-muted-foreground text-[11px]">Broj ugovora</div>
                  <div className="font-mono font-medium">{detail.kljuc}</div>
                </div>
                <div>
                  <div className="text-muted-foreground text-[11px]">Datum</div>
                  <div>{detail.danas || "—"}</div>
                </div>
                <div>
                  <div className="text-muted-foreground text-[11px]">Destinacija</div>
                  <div className="truncate" title={detail.destinacija || ""}>{detail.destinacija || "—"}</div>
                </div>
                <div>
                  <div className="text-muted-foreground text-[11px]">Nosilac</div>
                  <div className="font-medium">{detail.putnik || "—"}</div>
                </div>
                <div>
                  <div className="text-muted-foreground text-[11px]">Mesto</div>
                  <div className="truncate" title={detail.mesto || ""}>{detail.mesto || "—"}</div>
                </div>
                <div>
                  <div className="text-muted-foreground text-[11px]">Smeštaj</div>
                  <div className="truncate" title={detail.naziv || ""}>{detail.naziv || "—"}</div>
                </div>
                <div className="col-span-3">
                  <div className="text-muted-foreground text-[11px]">Putnici</div>
                  <div>
                    {(detail.putnici_detalji
                      ? fmtPutnici(detail.putnici_detalji)
                      : (detail.putnici || []).slice(1)
                    ).join(", ") || "—"}
                  </div>
                </div>
                <div>
                  <div className="text-muted-foreground text-[11px]">Datum od</div>
                  <div>{detail.datumod || "—"}</div>
                </div>
                <div>
                  <div className="text-muted-foreground text-[11px]">Datum do</div>
                  <div>{detail.datumdo || "—"}</div>
                </div>
                <div>
                  <div className="text-muted-foreground text-[11px]">Smer</div>
                  <div>{detail.smer || "—"}</div>
                </div>
                <div className="col-span-3">
                  <div className="text-muted-foreground text-[11px]">Subagent</div>
                  <div>
                    {detail.subagent_info ? (
                      <span>
                        <span className="font-medium">{detail.subagent_info.naziv}</span>
                        {detail.subagent_info.provizija != null && (
                          <span className="text-muted-foreground"> · provizija {detail.subagent_info.provizija}%</span>
                        )}
                        {detail.subagent_info.kontakt && (
                          <span className="text-muted-foreground"> · {detail.subagent_info.kontakt}</span>
                        )}
                      </span>
                    ) : detail.subagent ? (
                      <span>{detail.subagent} <span className="text-muted-foreground">(nije u spisku subagenata)</span></span>
                    ) : (
                      "—"
                    )}
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-md border bg-muted/30 p-3 space-y-1 text-xs">
                  <div className="font-semibold mb-1.5">Obračun (EUR)</div>
                  <div className="flex justify-between"><span className="text-muted-foreground">Smeštaj</span><span>{fmtEUR(detail.smestaj)}</span></div>
                  <div className="flex justify-between"><span className="text-muted-foreground">Prevoz</span><span>{fmtEUR(detail.prevoz)}</span></div>
                  <div className="flex justify-between"><span className="text-muted-foreground">Viza</span><span>{fmtEUR(detail.viza)}</span></div>
                  <div className="flex justify-between"><span className="text-muted-foreground">Popust</span><span>{detail.popust ? "-" + fmtEUR(detail.popust) : fmtEUR(0)}</span></div>
                  <div className="flex justify-between"><span className="text-muted-foreground">Provizija</span><span>{fmtEUR(detail.provizija)}</span></div>
                  <div className="flex justify-between"><span className="text-muted-foreground">Naplata</span><span>{fmtEUR(detail.naplata)}</span></div>
                  <div className="flex justify-between"><span className="text-muted-foreground">Uplaćeno</span><span>{fmtEUR(detail.uplaceno)}</span></div>
                  <div className="flex justify-between"><span className="text-muted-foreground">Saldo</span><span className={cn(detail.saldo > 0.001 && "text-destructive")}>{fmtEUR(detail.saldo)}</span></div>
                </div>
                <div className="rounded-md border bg-muted/30 p-3 flex flex-col justify-between">
                  <div className="space-y-1 text-xs">
                    <div className="flex justify-between"><span className="text-muted-foreground">Kurs (srednji NBS)</span><span>{detail.kurs ? new Intl.NumberFormat("sr-RS", { maximumFractionDigits: 4 }).format(detail.kurs) : "—"}</span></div>
                  </div>
                  <div className="border-t pt-2">
                    <div className="text-muted-foreground text-[11px] mb-0.5">Ukupna vrednost</div>
                    <div className="text-base font-bold">{fmtRSD(detail.ukupna_vrednost)}</div>
                  </div>
                </div>
              </div>

              <div className="flex flex-wrap gap-2">
                <Button size="sm" onClick={() => {
                  setOpenKljuc(null);
                  navigate(`/knjigovodstvo/predracuni/novi/${openKljuc}`);
                }}>
                  <FilePlus className="w-3.5 h-3.5 mr-1.5" />Kreiraj predracun
                </Button>
                <Button
                  size="sm" variant="outline"
                  onClick={() => {
                    const next = !showUplate;
                    setShowUplate(next);
                    if (next && uplate == null && openKljuc) loadUplate(openKljuc);
                  }}
                >
                  <Eye className="w-3.5 h-3.5 mr-1.5" />Pregled uplata
                </Button>
                <Button size="sm" variant="outline" onClick={() => toast.info("Izdati računi su u pripremi")}>
                  <Receipt className="w-3.5 h-3.5 mr-1.5" />Izdati računi
                </Button>
              </div>

              {showUplate && (
                <div className="rounded-md border p-3">
                  <div className="font-semibold text-xs mb-2">Uplate za ugovor {openKljuc}</div>
                  {uplateLoading ? (
                    <div className="py-6 text-center">
                      <Loader2 className="w-5 h-5 animate-spin mx-auto text-muted-foreground" />
                    </div>
                  ) : uplate && uplate.length > 0 ? (
                    <div className="space-y-1.5 text-xs">
                      {uplate.map((u) => (
                        <div key={u.id} className="flex flex-wrap justify-between gap-2 border-b pb-1.5 last:border-0 last:pb-0">
                          <div>
                            <div className="font-medium">{u.ime || "—"}</div>
                            <div className="text-muted-foreground text-[11px]">
                              {u.danas || "—"} · {u.vrsta || "—"} · {u.nacin || "—"}
                            </div>
                          </div>
                          <div className="text-right">
                            <div className="font-medium">{u.uevro != null ? fmtEUR(u.uevro) : "—"}</div>
                            <div className="text-muted-foreground text-[11px]">{u.din != null ? fmtRSD(u.din) : ""}</div>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="text-muted-foreground text-xs py-3 text-center">Nema uplata za ovaj ugovor</div>
                  )}
                </div>
              )}
            </div>
          ) : (
            <div className="py-8 text-center text-muted-foreground text-xs">Ugovor nije pronađen</div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
