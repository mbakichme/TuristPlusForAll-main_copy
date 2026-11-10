import { useState, useEffect, useCallback, useRef } from "react";
import type { Subagent, SubagentiResponse } from "../types";
import { apiFetch } from "../lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Checkbox } from "@/components/ui/checkbox";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { format } from "date-fns";
import { srLatn } from "date-fns/locale";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow
} from "@/components/ui/table";
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle
} from "@/components/ui/dialog";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle
} from "@/components/ui/alert-dialog";
import {
  Loader2, Search, ChevronUp, ChevronDown, RefreshCw, Plus, Pencil, Trash2, Handshake, CalendarDays, CloudUpload
} from "lucide-react";
import { toast } from "sonner";

/** Datum u formi: dugme sa kalendarom u popover-u (srpski, ponedeljak prvi), prazno = bez datuma. */
function DatumPolje({ value, onChange, label }: { value: string; onChange: (iso: string) => void; label: string }) {
  const [otvoreno, setOtvoreno] = useState(false);
  const d = /^\d{4}-\d{2}-\d{2}$/.test(value) ? new Date(`${value}T00:00:00`) : undefined;
  return (
    <Popover open={otvoreno} onOpenChange={setOtvoreno}>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" className="h-8 w-full justify-start font-normal text-xs tabular-nums" aria-label={label}>
          <CalendarDays className="size-3.5 mr-1.5 text-muted-foreground" />
          {d ? format(d, "dd.MM.yyyy.") : "Izaberite"}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-auto p-0 bg-card" align="start">
        <Calendar
          mode="single"
          selected={d}
          onSelect={(x) => { if (x) onChange(format(x, "yyyy-MM-dd")); setOtvoreno(false); }}
          locale={srLatn}
          weekStartsOn={1}
        />
        {value && (
          <div className="border-t p-2">
            <Button variant="ghost" size="sm" className="w-full text-xs" onClick={() => { onChange(""); setOtvoreno(false); }}>
              Obriši datum
            </Button>
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}

const COLUMNS: { key: string; label: string; sortable: boolean }[] = [
  { key: "naziv", label: "Naziv", sortable: true },
  { key: "mesto", label: "Mesto", sortable: true },
  { key: "pib", label: "PIB", sortable: true },
  { key: "matbroj", label: "MB", sortable: true },
  { key: "ta", label: "TA", sortable: false },
  { key: "ugovor_broj", label: "Broj ugovora", sortable: false },
  { key: "ugovor_datumod", label: "Datum od", sortable: false },
  { key: "ugovor_datumdo", label: "Datum do", sortable: false },
  { key: "tel", label: "Telefon", sortable: false },
  { key: "email", label: "Email", sortable: false },
  { key: "racun", label: "Račun", sortable: false },
  { key: "provizija", label: "Provizija %", sortable: true },
  { key: "broj_ugovora", label: "Ugovori", sortable: true },
];

const BATCH_SIZE = 100;

/** ASNS subagenti se prikazuju, ali ne mogu da se sinhronizuju kroz ovu listu. */
function jeAsns(s: Subagent): boolean {
  return (s.naziv || "").toUpperCase().includes("ASNS");
}

interface SinhronizacijaRezultat {
  id: number;
  naziv: string;
  api_sync: string;
  api_sync_error: string | null;
}

interface SinhronizacijaOdgovor {
  rezultati: SinhronizacijaRezultat[];
}

function fmtDatum(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}.${m}.${y}.`;
}

const EMPTY_FORM = {
  naziv: "", adresa: "", mesto: "", pib: "", matbroj: "", ta: "true", ugovor_broj: "", ugovor_datumod: "", ugovor_datumdo: "", tel: "", tel1: "", tel2: "", email: "",
  fax: "", racun: "", provizija: "0", provizija1: "0", provizija1a: "0",
  provizija2: "0", punnaziv: "", kontakt: "",
};

export default function SubagentiPage() {
  const [rows, setRows] = useState<Subagent[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState("naziv");
  const [dir, setDir] = useState<"asc" | "desc">("asc");
  const [loading, setLoading] = useState(true);
  const [more, setMore] = useState(false);
  const requestId = useRef(0);
  const hasMoreRef = useRef(true);
  const sentinelRef = useRef<HTMLDivElement | null>(null);

  // form dialog
  const [formOpen, setFormOpen] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [form, setForm] = useState({ ...EMPTY_FORM });
  const [saving, setSaving] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Subagent | null>(null);

  // selekcija za sinhronizaciju sa App2
  const [selektovani, setSelektovani] = useState<Set<number>>(new Set());
  const [sinhronizujem, setSinhronizujem] = useState(false);

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
      const data = await apiFetch<SubagentiResponse>(`/subagenti?${params}`);
      if (rid !== requestId.current) return;
      setRows((prev) => (replace ? data.rows : [...prev, ...data.rows]));
      setTotal(data.total);
      setPage(data.page);
      hasMoreRef.current = data.rows.length >= BATCH_SIZE;
    } catch {
      toast.error("Greška pri učitavanju subagenata");
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

  function openCreate() {
    setEditId(null);
    setForm({ ...EMPTY_FORM });
    setFormOpen(true);
  }

  function openEdit(s: Subagent) {
    setEditId(s.id);
    setForm({
      naziv: s.naziv || "", adresa: s.adresa || "", mesto: s.mesto || "",
      pib: s.pib || "", matbroj: s.matbroj || "", ta: s.ta === false ? "false" : "true", ugovor_broj: s.ugovor_broj || "",
      ugovor_datumod: s.ugovor_datumod || "", ugovor_datumdo: s.ugovor_datumdo || "",
      tel: s.tel || "", tel1: s.tel1 || "", tel2: s.tel2 || "", email: s.email || "",
      fax: s.fax || "", racun: s.racun || "",
      provizija: String(s.provizija ?? 0), provizija1: String(s.provizija1 ?? 0),
      provizija1a: String(s.provizija1a ?? 0), provizija2: String(s.provizija2 ?? 0),
      punnaziv: s.punnaziv || "", kontakt: s.kontakt || "",
    });
    setFormOpen(true);
  }

  async function save() {
    if (!form.naziv.trim()) {
      toast.error("Naziv je obavezan");
      return;
    }
    setSaving(true);
    const payload = {
      ...form,
      ugovor_datumod: form.ugovor_datumod || null,
      ugovor_datumdo: form.ugovor_datumdo || null,
      ta: form.ta === "true",
      provizija: parseFloat(form.provizija) || 0,
      provizija1: parseFloat(form.provizija1) || 0,
      provizija1a: parseFloat(form.provizija1a) || 0,
      provizija2: parseFloat(form.provizija2) || 0,
    };
    try {
      if (editId != null) {
        await apiFetch(`/subagenti/${editId}`, { method: "PUT", body: JSON.stringify(payload) });
        toast.success("Subagent je ažuriran");
      } else {
        await apiFetch("/subagenti", { method: "POST", body: JSON.stringify(payload) });
        toast.success("Subagent je dodat");
      }
      setFormOpen(false);
      loadBatch(1, true, search, sort, dir);
    } catch {
      toast.error("Greška pri čuvanju subagenta");
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!deleteTarget) return;
    const s = deleteTarget;
    setDeletingId(s.id);
    try {
      await apiFetch(`/subagenti/${s.id}`, { method: "DELETE" });
      toast.success("Subagent je obrisan");
      setRows((prev) => prev.filter((r) => r.id !== s.id));
      setTotal((t) => Math.max(t - 1, 0));
      setDeleteTarget(null);
    } catch {
      toast.error("Greška pri brisanju subagenta");
    } finally {
      setDeletingId(null);
    }
  }

  function setField(k: keyof typeof form, v: string) {
    setForm((f) => ({ ...f, [k]: v }));
  }

  const shown = rows.length;
  const selectableRows = rows.filter((s) => !jeAsns(s));
  const allVisibleSelected = selectableRows.length > 0 && selectableRows.every((s) => selektovani.has(s.id));
  const someVisibleSelected = selectableRows.some((s) => selektovani.has(s.id));

  function toggleSelection(id: number) {
    setSelektovani((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  function toggleAllVisible() {
    setSelektovani((prev) => {
      const next = new Set(prev);
      if (allVisibleSelected) selectableRows.forEach((s) => next.delete(s.id));
      else selectableRows.forEach((s) => next.add(s.id));
      return next;
    });
  }

  async function sinhronizujSelektovane() {
    if (selektovani.size === 0 || sinhronizujem) return;
    const ids = Array.from(selektovani);
    setSinhronizujem(true);
    try {
      const response = await apiFetch<SinhronizacijaOdgovor>("/subagenti/sinhronizuj-selektovane", {
        method: "POST",
        body: JSON.stringify({ ids }),
      });
      const rezultati = response.rezultati || [];
      const greske = rezultati.filter((r) => r.api_sync_error !== null || r.api_sync === "failed" || r.api_sync === "not_found" || r.api_sync === "deactivate_pending");
      const preskoceni = rezultati.filter((r) => r.api_sync === "skipped");
      const uspesni = rezultati.filter((r) => r.api_sync === "synced" || r.api_sync === "deactivated");
      if (greske.length) {
        const detalji = greske.map((r) => `${r.naziv || `#${r.id}`}: ${r.api_sync_error || r.api_sync}`).join("; ");
        toast.warning(`Sinhronizovano: ${uspesni.length}; preskočeno: ${preskoceni.length}; grešaka: ${greske.length}. ${detalji}`);
      } else {
        toast.success(`Sinhronizacija završena: ${uspesni.length} uspešno, ${preskoceni.length} preskočeno.`);
      }
      setSelektovani(new Set());
      await loadBatch(1, true, search, sort, dir);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Greška pri sinhronizaciji subagenata");
    } finally {
      setSinhronizujem(false);
    }
  }


  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Subagenti</h1>
          <p className="text-muted-foreground text-sm">Spisak subagenata (povezano sa ugovorima preko naziva)</p>
        </div>
        <div className="flex gap-2">
          <Button
            onClick={sinhronizujSelektovane}
            disabled={selektovani.size === 0 || sinhronizujem}
            className="bg-[#FFE299] text-gray-900 hover:bg-[#f5d477]"
          >
            {sinhronizujem ? <Loader2 className="w-4 h-4 animate-spin" /> : <CloudUpload className="w-4 h-4" />}
            Sinhronizuj sve selektovane subagente
          </Button>
          <Button variant="outline" onClick={() => loadBatch(1, true, search, sort, dir)}>
            <RefreshCw className="w-4 h-4 mr-2" />Osveži
          </Button>
          <Button onClick={openCreate}>
            <Plus className="w-4 h-4 mr-2" />Dodaj subagenta
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Handshake className="w-5 h-5" />Subagenti
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
            <Table className="text-xs [&_td]:px-1.5 [&_th]:px-1.5">
              <TableHeader>

                <TableRow>
                  <TableHead className="w-24 whitespace-nowrap">
                    <div className="flex items-center gap-2">
                      <Checkbox
                        checked={allVisibleSelected ? true : someVisibleSelected ? "indeterminate" : false}
                        onCheckedChange={toggleAllVisible}
                        disabled={selectableRows.length === 0}
                        aria-label="Izaberi sve vidljive subagente"
                      />
                      <span>Selekcija</span>
                    </div>
                  </TableHead>
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
                  <TableHead className="w-20 text-right">Akcije</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {loading && rows.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={15} className="text-center py-10">
                      <Loader2 className="w-6 h-6 animate-spin mx-auto text-muted-foreground" />
                    </TableCell>
                  </TableRow>
                ) : rows.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={15} className="text-center text-muted-foreground py-10">
                      {search ? "Nema rezultata za pretragu" : "Nema subagenata"}
                    </TableCell>
                  </TableRow>
                ) : (
                  rows.map((s) => (
                    <TableRow key={s.id}>
                      <TableCell className="text-center">
                        {!jeAsns(s) && (
                          <Checkbox
                            checked={selektovani.has(s.id)}
                            onCheckedChange={() => toggleSelection(s.id)}
                            aria-label={`Izaberi ${s.naziv || "subagenta"}`}
                          />
                        )}
                      </TableCell>
                      <TableCell className="font-medium">{s.naziv || "—"}</TableCell>
                      <TableCell>{s.mesto || "—"}</TableCell>
                      <TableCell className="font-mono text-xs whitespace-nowrap">{s.pib || "—"}</TableCell>
                      <TableCell className="font-mono text-xs whitespace-nowrap">{s.matbroj || "—"}</TableCell>
                      <TableCell>{s.ta === false ? <span className="text-muted-foreground">Ne</span> : <span className="font-medium">Da</span>}</TableCell>
                      <TableCell className="font-mono text-xs whitespace-nowrap">{s.ugovor_broj || "—"}</TableCell>
                      <TableCell className="whitespace-nowrap">{fmtDatum(s.ugovor_datumod)}</TableCell>
                      <TableCell className="whitespace-nowrap">{fmtDatum(s.ugovor_datumdo)}</TableCell>
                      <TableCell className="whitespace-nowrap">{s.tel || "—"}</TableCell>
                      <TableCell className="max-w-40 truncate" title={s.email || ""}>{s.email || "—"}</TableCell>
                      <TableCell className="font-mono text-xs">{s.racun || "—"}</TableCell>
                      <TableCell>{s.provizija ?? 0}</TableCell>
                      <TableCell className="text-center">
                        {s.broj_ugovora ? (
                          <span className="font-medium">{s.broj_ugovora}</span>
                        ) : (
                          <span className="text-muted-foreground">0</span>
                        )}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-1">
                          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => openEdit(s)}>
                            <Pencil className="w-3.5 h-3.5" />
                          </Button>
                          <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive" onClick={() => setDeleteTarget(s)} disabled={deletingId === s.id}>
                            <Trash2 className="w-3.5 h-3.5" />
                          </Button>
                        </div>
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

      {/* Forma za dodavanje/izmenu */}
      <Dialog open={formOpen} onOpenChange={setFormOpen}>
        <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-base">
              <Handshake className="w-4 h-4" />
              {editId != null ? "Izmeni subagenta" : "Dodaj subagenta"}
            </DialogTitle>
            <DialogDescription className="text-xs">
              Provizije se primenjuju na ugovore gde je aranzman.subagent = naziv subagenta
            </DialogDescription>
          </DialogHeader>
          <div className="grid grid-cols-2 gap-x-4 gap-y-2.5 text-xs">
            <div className="col-span-2">
              <Label className="text-[11px]">Naziv *</Label>
              <Input value={form.naziv} onChange={(e) => setField("naziv", e.target.value)} className="h-8 text-xs" placeholder="npr. RODA TOURS" />
            </div>
            <div>
              <Label className="text-[11px]">Adresa</Label>
              <Input value={form.adresa} onChange={(e) => setField("adresa", e.target.value)} className="h-8 text-xs" />
            </div>
            <div>
              <Label className="text-[11px]">Mesto</Label>
              <Input value={form.mesto} onChange={(e) => setField("mesto", e.target.value)} className="h-8 text-xs" />
            </div>
            <div>
              <Label className="text-[11px]">PIB</Label>
              <Input value={form.pib} onChange={(e) => setField("pib", e.target.value)} className="h-8 text-xs" />
            </div>
            <div>
              <Label className="text-[11px]">MB (matični broj)</Label>
              <Input value={form.matbroj} onChange={(e) => setField("matbroj", e.target.value)} className="h-8 text-xs" />
            </div>
            <div className="flex items-end pb-1.5">
              <div className="flex items-center gap-2">
                <Switch id="sub-ta" checked={form.ta === "true"} onCheckedChange={(v) => setField("ta", v ? "true" : "false")} />
                <Label htmlFor="sub-ta" className="text-[11px]">TA (true/false)</Label>
              </div>
            </div>
            <div>
              <Label className="text-[11px]">Broj ugovora</Label>
              <Input value={form.ugovor_broj} onChange={(e) => setField("ugovor_broj", e.target.value)} className="h-8 text-xs" />
            </div>
            <div>
              <Label className="text-[11px]">Datum od</Label>
              <DatumPolje label="Datum od" value={form.ugovor_datumod} onChange={(v) => setField("ugovor_datumod", v)} />
            </div>
            <div>
              <Label className="text-[11px]">Datum do</Label>
              <DatumPolje label="Datum do" value={form.ugovor_datumdo} onChange={(v) => setField("ugovor_datumdo", v)} />
            </div>
            <div>
              <Label className="text-[11px]">Kontakt osoba</Label>
              <Input value={form.kontakt} onChange={(e) => setField("kontakt", e.target.value)} className="h-8 text-xs" />
            </div>
            <div>
              <Label className="text-[11px]">Telefon</Label>
              <Input value={form.tel} onChange={(e) => setField("tel", e.target.value)} className="h-8 text-xs" />
            </div>
            <div>
              <Label className="text-[11px]">Telefon 1</Label>
              <Input value={form.tel1} onChange={(e) => setField("tel1", e.target.value)} className="h-8 text-xs" />
            </div>
            <div>
              <Label className="text-[11px]">Telefon 2</Label>
              <Input value={form.tel2} onChange={(e) => setField("tel2", e.target.value)} className="h-8 text-xs" />
            </div>
            <div>
              <Label className="text-[11px]">Email</Label>
              <Input type="email" value={form.email} onChange={(e) => setField("email", e.target.value)} className="h-8 text-xs" />
            </div>
            <div>
              <Label className="text-[11px]">Fax</Label>
              <Input value={form.fax} onChange={(e) => setField("fax", e.target.value)} className="h-8 text-xs" />
            </div>
            <div className="col-span-2">
              <Label className="text-[11px]">Broj računa</Label>
              <Input value={form.racun} onChange={(e) => setField("racun", e.target.value)} className="h-8 text-xs font-mono" />
            </div>
            <div>
              <Label className="text-[11px]">Provizija %</Label>
              <Input type="number" step="0.01" value={form.provizija} onChange={(e) => setField("provizija", e.target.value)} className="h-8 text-xs" />
            </div>
            <div>
              <Label className="text-[11px]">Provizija 1 %</Label>
              <Input type="number" step="0.01" value={form.provizija1} onChange={(e) => setField("provizija1", e.target.value)} className="h-8 text-xs" />
            </div>
            <div>
              <Label className="text-[11px]">Provizija 1a %</Label>
              <Input type="number" step="0.01" value={form.provizija1a} onChange={(e) => setField("provizija1a", e.target.value)} className="h-8 text-xs" />
            </div>
            <div>
              <Label className="text-[11px]">Provizija 2 %</Label>
              <Input type="number" step="0.01" value={form.provizija2} onChange={(e) => setField("provizija2", e.target.value)} className="h-8 text-xs" />
            </div>
            <div className="col-span-2">
              <Label className="text-[11px]">Pun naziv</Label>
              <Input value={form.punnaziv} onChange={(e) => setField("punnaziv", e.target.value)} className="h-8 text-xs" />
            </div>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" size="sm" onClick={() => setFormOpen(false)}>Otkaži</Button>
            <Button size="sm" onClick={save} disabled={saving}>
              {saving && <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" />}
              Sačuvaj
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Potvrda brisanja */}
      <AlertDialog open={deleteTarget !== null} onOpenChange={(o) => { if (!o) setDeleteTarget(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Obriši subagenta?</AlertDialogTitle>
            <AlertDialogDescription>
              Subagent &quot;{deleteTarget?.naziv}&quot; će biti trajno obrisan. Ova akcija se ne može poništiti.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Otkaži</AlertDialogCancel>
            <AlertDialogAction
              onClick={remove}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {deletingId != null && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
              Obriši
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
