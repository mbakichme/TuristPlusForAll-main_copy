import { useState, useEffect, useCallback, useRef } from "react";
import type { IzvodRow, IzvodUploadResult } from "../types";
import { apiFetch, getToken } from "../lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow
} from "@/components/ui/table";
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle
} from "@/components/ui/dialog";
import {
  Loader2, Search, Upload, Trash2, Landmark, RefreshCw, FileUp, FileCheck2
} from "lucide-react";
import { toast } from "sonner";

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-");
  if (!y || !m || !d) return "—";
  return `${d}.${m}.${y}.`;
}

function fmtDateTime(iso: string | null): string {
  if (!iso) return "—";
  const d = fmtDate(iso);
  const t = iso.slice(11, 16);
  return t ? `${d} ${t}` : d;
}

export default function IzvodiPage() {
  const [rows, setRows] = useState<IzvodRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const requestId = useRef(0);

  // upload
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // delete
  const [deleteRow, setDeleteRow] = useState<IzvodRow | null>(null);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setSearch(searchInput.trim()), 400);
    return () => clearTimeout(t);
  }, [searchInput]);

  const load = useCallback(async (s: string) => {
    const rid = ++requestId.current;
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (s) params.set("q", s);
      const data = await apiFetch<IzvodRow[]>(`/izvodi?${params}`);
      if (rid !== requestId.current) return;
      setRows(data);
    } catch (e) {
      if (rid !== requestId.current) return;
      toast.error(e instanceof Error ? e.message : "Greška pri učitavanju izvoda");
    } finally {
      if (rid === requestId.current) setLoading(false);
    }
  }, []);

  useEffect(() => { load(search); }, [load, search]);

  async function handleUpload() {
    if (!file || uploading) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const token = getToken();
      const res = await fetch("/api/izvodi/upload", {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        body: fd,
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) {
        throw new Error((data as { detail?: string } | null)?.detail || "Greška pri uploadu fajla");
      }
      const result = data as IzvodUploadResult;
      if (result.uneseno > 0) {
        for (const iz of result.izvodi) {
          toast.success(`Izvod br. ${iz.broj_izvoda} unešen`, {
            description: `Račun ${iz.racun} — ${iz.broj_transakcija} transakcija`,
          });
        }
      }
      if (result.preskoceno.length > 0) {
        toast.info(
          result.uneseno > 0
            ? `Preskočeno (već unešeno): ${result.preskoceno.join(", ")}`
            : `Izvod je već unešen: ${result.preskoceno.join(", ")}`
        );
      }
      setFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      load(search);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Greška pri uploadu fajla");
    } finally {
      setUploading(false);
    }
  }

  async function handleDelete() {
    if (!deleteRow || deleting) return;
    setDeleting(true);
    try {
      await apiFetch(`/izvodi/${deleteRow.izvod_id}`, { method: "DELETE" });
      toast.success(`Izvod br. ${deleteRow.broj_izvoda} obrisan`);
      setDeleteRow(null);
      load(search);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Greška pri brisanju izvoda");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className="p-6 md:p-8 space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Landmark className="w-6 h-6" />Izvodi
        </h1>
        <p className="text-muted-foreground text-sm mt-1">
          Bankovni izvodi — upload XML fajla i pregled unešenih izvoda
        </p>
      </div>

      {/* Upload */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <FileUp className="w-4 h-4" />Upload XML izvoda
          </CardTitle>
          <CardDescription>
            Izaberi XML fajl bankovnog izvoda. Podaci se čitaju i čuvaju u bazu —
            fajl se ne čuva na serveru.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col sm:flex-row sm:items-center gap-3">
            <label className="flex-1">
              <input
                ref={fileInputRef}
                type="file"
                accept=".xml,text/xml,application/xml"
                className="sr-only"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
              <div className="flex items-center gap-3 rounded-lg border border-dashed border-border bg-muted/30 px-4 py-3 cursor-pointer hover:bg-muted/50 transition-colors">
                <FileUp className="w-5 h-5 text-muted-foreground flex-shrink-0" />
                <span className="text-sm truncate">
                  {file ? (
                    <span className="flex items-center gap-2 font-medium text-foreground">
                      <FileCheck2 className="w-4 h-4 text-primary flex-shrink-0" />
                      {file.name}
                      <span className="text-muted-foreground font-normal">
                        ({(file.size / 1024).toFixed(1)} KB)
                      </span>
                    </span>
                  ) : (
                    <span className="text-muted-foreground">
                      Klikni da izabereš XML fajl…
                    </span>
                  )}
                </span>
              </div>
            </label>
            <Button
              onClick={handleUpload}
              disabled={!file || uploading}
              className="sm:w-40"
            >
              {uploading ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Upload className="w-4 h-4" />
              )}
              {uploading ? "Učitavam…" : "Učitaj izvod"}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Lista izvoda */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0">
          <div>
            <CardTitle className="text-base">Unešeni izvodi</CardTitle>
            <CardDescription className="mt-1">
              Ukupno: {rows.length} {rows.length === 1 ? "izvod" : "izvoda"}
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <div className="relative">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Pretraga…"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                className="pl-8 w-48 sm:w-64"
              />
            </div>
            <Button variant="outline" size="icon" onClick={() => load(search)} title="Osveži">
              <RefreshCw className="w-4 h-4" />
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
            </div>
          ) : rows.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground text-sm">
              {search
                ? "Nema izvoda koji odgovaraju pretrazi."
                : "Nema unešenih izvoda. Učitaj XML fajl izvoda da počneš."}
            </div>
          ) : (
            <div className="rounded-md border overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Datum unosa</TableHead>
                    <TableHead>Datum izvoda</TableHead>
                    <TableHead>Broj izvoda</TableHead>
                    <TableHead>Račun</TableHead>
                    <TableHead>Korisnik</TableHead>
                    <TableHead className="text-right">Transakcije</TableHead>
                    <TableHead className="w-16 text-right">Akcija</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((r) => (
                    <TableRow key={r.id}>
                      <TableCell className="whitespace-nowrap">
                        {fmtDateTime(r.datum_unosa)}
                      </TableCell>
                      <TableCell className="whitespace-nowrap">
                        {fmtDate(r.datum_izvoda)}
                      </TableCell>
                      <TableCell className="font-medium">{r.broj_izvoda}</TableCell>
                      <TableCell className="font-mono text-xs">{r.racun}</TableCell>
                      <TableCell>{r.korisnik || "—"}</TableCell>
                      <TableCell className="text-right">{r.broj_transakcija ?? "—"}</TableCell>
                      <TableCell className="text-right">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 text-muted-foreground hover:text-destructive"
                          onClick={() => setDeleteRow(r)}
                          title="Obriši izvod"
                        >
                          <Trash2 className="w-4 h-4" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Delete confirm */}
      <Dialog open={!!deleteRow} onOpenChange={(o) => !o && setDeleteRow(null)}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Obriši izvod?</DialogTitle>
            <DialogDescription>
              Izvod br. {deleteRow?.broj_izvoda} za račun {deleteRow?.racun}
              {deleteRow?.broj_transakcija
                ? ` (${deleteRow.broj_transakcija} transakcija)`
                : ""}{" "}
              će biti trajno obrisan. Ova akcija se ne može poništiti.
            </DialogDescription>
          </DialogHeader>
          <div className="flex justify-end gap-2 mt-2">
            <Button variant="outline" onClick={() => setDeleteRow(null)}>
              Otkaži
            </Button>
            <Button variant="destructive" onClick={handleDelete} disabled={deleting}>
              {deleting && <Loader2 className="w-4 h-4 animate-spin" />}
              Obriši
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
