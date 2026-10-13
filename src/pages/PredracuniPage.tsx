import { useState, useEffect, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import type { Predracun, PredracuniResponse } from "../types";
import { apiFetch, getToken } from "../lib/api";
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
  Loader2, Search, ChevronUp, ChevronDown, RefreshCw, Trash2, ReceiptText, FileDown
} from "lucide-react";
import { toast } from "sonner";

const COLUMNS: { key: string; label: string; sortable: boolean }[] = [
  { key: "broj_predracuna", label: "Broj predracuna", sortable: true },
  { key: "datum", label: "Datum", sortable: true },
  { key: "nosilac", label: "Nosilac", sortable: true },
  { key: "ugovor", label: "Ugovor", sortable: true },
  { key: "destinacija", label: "Destinacija", sortable: false },
  { key: "zaduzenje", label: "Zaduženje", sortable: true },
  { key: "nacin", label: "Način", sortable: false },
  { key: "racun", label: "Račun", sortable: false },
];

const BATCH_SIZE = 100;

const fmtRSD = (v: number | null | undefined) =>
  v == null ? "—" : new Intl.NumberFormat("sr-RS", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(v) + " RSD";

export default function PredracuniPage() {
  const navigate = useNavigate();
  const [rows, setRows] = useState<Predracun[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState("broj_predracuna");
  const [dir, setDir] = useState<"asc" | "desc">("asc");
  const [loading, setLoading] = useState(true);
  const [more, setMore] = useState(false);
  const requestId = useRef(0);
  const hasMoreRef = useRef(true);
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [deleteRow, setDeleteRow] = useState<Predracun | null>(null);
  const [downloadingId, setDownloadingId] = useState<number | null>(null);

  async function downloadPdf(p: Predracun) {
    setDownloadingId(p.id);
    try {
      const token = getToken();
      const res = await fetch(`/api/predracuni/${p.id}/pdf`, {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `Predracun_${p.broj_predracuna.replace(/[^0-9A-Za-z-]/g, "-")}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.error(
        err instanceof TypeError
          ? "Server nije dostupan — osveži stranicu i pokušaj ponovo"
          : "Greška pri preuzimanju PDF-a"
      );
    } finally {
      setDownloadingId(null);
    }
  }

  useEffect(() => {
    const t = setTimeout(() => setSearch(searchInput.trim()), 400);
    return () => clearTimeout(t);
  }, [searchInput]);

  const loadBatch = useCallback(async (
    p: number, replace: boolean, s: string, sk: string, d: string
  ) => {
    const rid = ++requestId.current;
    if (replace) setLoading(true); else setMore(true);
    try {
      const params = new URLSearchParams({
        page: String(p), page_size: String(BATCH_SIZE), sort: sk, dir: d,
      });
      if (s) params.set("search", s);
      const data = await apiFetch<PredracuniResponse>(`/predracuni?${params}`);
      if (rid !== requestId.current) return;
      setRows((prev) => (replace ? data.rows : [...prev, ...data.rows]));
      setTotal(data.total);
      setPage(data.page);
      hasMoreRef.current = data.rows.length >= BATCH_SIZE;
    } catch {
      toast.error("Greška pri učitavanju predracuna");
    } finally {
      if (rid === requestId.current) {
        setLoading(false);
        setMore(false);
      }
    }
  }, []);

  useEffect(() => {
    loadBatch(1, true, search, sort, dir);
  }, [search, sort, dir, loadBatch]);

  function toggleSort(key: string) {
    if (sort === key) {
      setDir(dir === "asc" ? "desc" : "asc");
    } else {
      setSort(key);
      setDir("asc");
    }
  }

  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && !loading && !more && hasMoreRef.current) {
          loadBatch(page + 1, false, search, sort, dir);
        }
      },
      { rootMargin: "600px" }
    );
    io.observe(el);
    return () => io.disconnect();
  }, [page, loading, more, search, sort, dir, loadBatch]);

  async function confirmDelete() {
    if (!deleteRow || deletingId !== null) return;
    const p = deleteRow;
    setDeletingId(p.id);
    try {
      await apiFetch(`/predracuni/${p.id}`, { method: "DELETE" });
      toast.success("Predračun je obrisan");
      setRows((prev) => prev.filter((r) => r.id !== p.id));
      setTotal((t) => Math.max(t - 1, 0));
      setDeleteRow(null);
    } catch {
      toast.error("Greška pri brisanju predračuna");
    } finally {
      setDeletingId(null);
    }
  }

  const shown = rows.length;

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Predračuni</h1>
          <p className="text-muted-foreground text-sm">
            Kreiraju se iz ugovora (dugme Kreiraj predracun) — klik na red otvara izmenu
          </p>
        </div>
        <Button variant="outline" onClick={() => loadBatch(1, true, search, sort, dir)}>
          <RefreshCw className="w-4 h-4 mr-2" />Osveži
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ReceiptText className="w-5 h-5" />Predračuni
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
                  <TableHead className="w-20 text-right">Akcija</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {loading && rows.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={9} className="text-center py-10">
                      <Loader2 className="w-6 h-6 animate-spin mx-auto text-muted-foreground" />
                    </TableCell>
                  </TableRow>
                ) : rows.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={9} className="text-center text-muted-foreground py-10">
                      {search ? "Nema rezultata za pretragu" : "Nema predracuna. Kreirajte ih iz ugovora."}
                    </TableCell>
                  </TableRow>
                ) : (
                  rows.map((p) => (
                    <TableRow
                      key={p.id}
                      className="cursor-pointer hover:bg-muted/50"
                      onClick={() => navigate(`/knjigovodstvo/predracuni/${p.id}/edit`)}
                    >
                      <TableCell className="font-mono font-medium">{p.broj_predracuna}</TableCell>
                      <TableCell className="whitespace-nowrap">{p.datum_fmt || "—"}</TableCell>
                      <TableCell className="font-medium">{p.nosilac || "—"}</TableCell>
                      <TableCell className="font-mono">{p.ugovor || "—"}</TableCell>
                      <TableCell className="max-w-40 truncate" title={p.destinacija || ""}>{p.destinacija || "—"}</TableCell>
                      <TableCell className="whitespace-nowrap">{fmtRSD(p.zaduzenje)}</TableCell>
                      <TableCell>{p.nacin || "—"}</TableCell>
                      <TableCell className="font-mono text-xs max-w-32 truncate" title={p.racun || ""}>{p.racun || "—"}</TableCell>
                      <TableCell className="text-right whitespace-nowrap">
                        <Button
                          variant="ghost" size="icon" className="h-7 w-7 text-primary"
                          title="Preuzmi PDF"
                          onClick={(e) => { e.stopPropagation(); downloadPdf(p); }}
                          disabled={downloadingId === p.id}
                        >
                          {downloadingId === p.id
                            ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                            : <FileDown className="w-3.5 h-3.5" />}
                        </Button>
                        <Button
                          variant="ghost" size="icon" className="h-7 w-7 text-destructive"
                          title="Obriši"
                          onClick={(e) => { e.stopPropagation(); setDeleteRow(p); }}
                          disabled={deletingId === p.id}
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>

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
          </div>
        </CardContent>
      </Card>

      {/* Delete confirm */}
      <Dialog open={!!deleteRow} onOpenChange={(o) => !o && setDeleteRow(null)}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Obriši predracun?</DialogTitle>
            <DialogDescription>
              Predračun br. {deleteRow?.broj_predracuna}
              {deleteRow?.ugovor ? ` (ugovor ${deleteRow.ugovor})` : ""} će biti trajno
              obrisan. Ova akcija se ne može poništiti.
            </DialogDescription>
          </DialogHeader>
          <div className="flex justify-end gap-2 mt-2">
            <Button variant="outline" onClick={() => setDeleteRow(null)}>
              Otkaži
            </Button>
            <Button variant="destructive" onClick={confirmDelete} disabled={deletingId !== null}>
              {deletingId !== null && <Loader2 className="w-4 h-4 animate-spin" />}
              Obriši
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
