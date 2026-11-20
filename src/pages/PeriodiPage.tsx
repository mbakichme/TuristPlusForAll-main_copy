import { useState, useEffect, useRef, useMemo } from "react";
import type { PeriodGrupa, PeriodDatum } from "../types";
import { apiFetch } from "../lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow
} from "@/components/ui/table";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle
} from "@/components/ui/alert-dialog";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Plus, Trash2, Loader2, CalendarDays, Pencil, Check, X, Search, ChevronRight } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

// ── Date helpers ───────────────────────────────────────────────────────────

/** Auto-format: user types digits, dots inserted at dd. mm. yyyy */
function formatMaskedDate(raw: string): string {
  const d = raw.replace(/\D/g, "").slice(0, 8);
  if (d.length <= 2) return d;
  if (d.length <= 4) return d.slice(0, 2) + "." + d.slice(2);
  return d.slice(0, 2) + "." + d.slice(2, 4) + "." + d.slice(4);
}

/** Validate dd.mm.yyyy — checks real calendar date */
function isValidDateDisplay(s: string): boolean {
  const m = s.match(/^(\d{2})\.(\d{2})\.(\d{4})$/);
  if (!m) return false;
  const [dd, mm, yyyy] = [parseInt(m[1]), parseInt(m[2]), parseInt(m[3])];
  if (mm < 1 || mm > 12) return false;
  if (dd < 1 || dd > 31) return false;
  const dt = new Date(yyyy, mm - 1, dd);
  return dt.getFullYear() === yyyy && dt.getMonth() === mm - 1 && dt.getDate() === dd;
}

/** dd.mm.yyyy → yyyy-mm-dd (ISO for DB) */
function toISO(display: string): string {
  const m = display.match(/^(\d{2})\.(\d{2})\.(\d{4})$/);
  if (!m) return "";
  return `${m[3]}-${m[2]}-${m[1]}`;
}

// ── Masked date input ──────────────────────────────────────────────────────

interface DateInputProps {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  className?: string;
  onEnter?: () => void;
}

function DateInput({ value, onChange, placeholder = "__.__.____", className, onEnter }: DateInputProps) {
  return (
    <Input
      value={value}
      onChange={(e) => onChange(formatMaskedDate(e.target.value))}
      onKeyDown={(e) => {
        if (e.key === "Enter" && onEnter) onEnter();
      }}
      placeholder={placeholder}
      className={cn(className)}
      inputMode="numeric"
    />
  );
}

// ── Inline editable date cell ──────────────────────────────────────────────

function EditableDateCell({
  value,
  onSave,
  compact,
}: {
  value: string;
  onSave: (newVal: string) => Promise<void>;
  compact?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState(value);
  const [saving, setSaving] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [editing]);

  async function commit() {
    if (val === value) {
      setEditing(false);
      return;
    }
    if (!isValidDateDisplay(val)) {
      toast.error("Format mora biti dd.mm.yyyy");
      setVal(value);
      setEditing(false);
      return;
    }
    setSaving(true);
    try {
      await onSave(val);
      setEditing(false);
    } catch {
      setVal(value);
      setEditing(false);
    } finally {
      setSaving(false);
    }
  }

  if (editing) {
    return (
      <div className="flex items-center gap-1">
        <Input
          ref={inputRef}
          value={val}
          onChange={(e) => setVal(formatMaskedDate(e.target.value))}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter") commit();
            if (e.key === "Escape") { setVal(value); setEditing(false); }
          }}
          placeholder="__.__.____"
          className={compact ? "h-7 w-24 text-[11px]" : "h-8 w-32"}
          inputMode="numeric"
        />
        {saving && <Loader2 className="w-3 h-3 animate-spin text-muted-foreground" />}
      </div>
    );
  }

  return (
    <button
      onClick={() => { setVal(value); setEditing(true); }}
      className={cn(
        "inline-flex items-center gap-1.5 hover:text-primary transition-colors group",
        compact ? "text-[11px]" : "text-sm"
      )}
    >
      <span>{value}</span>
      <Pencil className="w-3 h-3 opacity-0 group-hover:opacity-50 transition-opacity" />
    </button>
  );
}

// ── Inline editable text cell (naziv grupe) ────────────────────────────────

function EditableTextCell({
  value,
  onSave,
}: {
  value: string;
  onSave: (newVal: string) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState(value);
  const [saving, setSaving] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [editing]);

  async function commit() {
    if (val === value) {
      setEditing(false);
      return;
    }
    if (!val.trim()) {
      toast.error("Naziv ne može biti prazan");
      setVal(value);
      setEditing(false);
      return;
    }
    setSaving(true);
    try {
      await onSave(val.trim());
      setEditing(false);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Izmena naziva nije uspela");
      setVal(value);
      setEditing(false);
    } finally {
      setSaving(false);
    }
  }

  if (editing) {
    return (
      <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
        <Input
          ref={inputRef}
          value={val}
          onChange={(e) => setVal(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter") commit();
            if (e.key === "Escape") { setVal(value); setEditing(false); }
          }}
          className="h-8 w-56"
        />
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 text-primary hover:text-primary"
          onMouseDown={(e) => e.preventDefault()}
          onClick={commit}
        >
          <Check className="w-4 h-4" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7"
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => { setVal(value); setEditing(false); }}
        >
          <X className="w-4 h-4" />
        </Button>
        {saving && <Loader2 className="w-3 h-3 animate-spin text-muted-foreground" />}
      </div>
    );
  }

  return (
    <button
      onClick={(e) => { e.stopPropagation(); setVal(value); setEditing(true); }}
      className="inline-flex items-center gap-1.5 text-sm font-medium transition-colors hover:text-primary"
      title="Kliknite da izmenite naziv grupe"
    >
      <span>{value}</span>
      <Pencil className="w-3.5 h-3.5 shrink-0 text-muted-foreground" />
    </button>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────

export default function PeriodiPage() {
  const [grupe, setGrupe] = useState<PeriodGrupa[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);

  // New group
  const [newGroup, setNewGroup] = useState("");

  // New date range
  const [newOd, setNewOd] = useState("");
  const [newDo, setNewDo] = useState("");
  const [addingDate, setAddingDate] = useState(false);

  // Pretraga datuma izabrane grupe
  const [datumPretraga, setDatumPretraga] = useState("");

  // Delete state
  const [deleteGrupaId, setDeleteGrupaId] = useState<number | null>(null);
  const [deleteDatumId, setDeleteDatumId] = useState<number | null>(null);

  async function load() {
    try {
      const data = await apiFetch<PeriodGrupa[]>("/period-grupa");
      setGrupe(data);
      if (selectedId && !data.find((g) => g.id === selectedId)) {
        setSelectedId(null);
      }
    } catch {
      toast.error("Greška pri učitavanju perioda");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  const selected = grupe.find((g) => g.id === selectedId) || null;

  // Datumi izabrane grupe filtrirani pretragom (substring na dd.mm.yyyy)
  const filtriraniDatumi = useMemo(() => {
    if (!selected) return [];
    const q = datumPretraga.trim();
    if (!q) return selected.datumi;
    return selected.datumi.filter((d) => d.datum_od.includes(q) || d.datum_do.includes(q));
  }, [selected, datumPretraga]);

  async function addGroup() {
    if (!newGroup.trim()) { toast.error("Unesite naziv grupe"); return; }
    try {
      const created = await apiFetch<PeriodGrupa>("/period-grupa", {
        method: "POST",
        body: JSON.stringify({ naziv: newGroup.trim() }),
      });
      setGrupe((prev) => [created, ...prev]);
      setSelectedId(created.id);
      setNewGroup("");
      toast.success("Grupa kreirana");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Greška");
    }
  }

  async function addDateRange() {
    if (!selectedId) return;
    if (!isValidDateDisplay(newOd) || !isValidDateDisplay(newDo)) {
      toast.error("Datumi moraju biti u formatu dd.mm.yyyy");
      return;
    }
    setAddingDate(true);
    try {
      const created = await apiFetch<PeriodDatum>("/period-datum", {
        method: "POST",
        body: JSON.stringify({
          grupa_id: selectedId,
          datum_od: toISO(newOd),
          datum_do: toISO(newDo),
        }),
      });
      setGrupe((prev) => prev.map((g) =>
        g.id === selectedId
          ? { ...g, datumi: [...g.datumi, created].sort((a, b) => a.datum_od.localeCompare(b.datum_od)) }
          : g
      ));
      setNewOd("");
      setNewDo("");
      toast.success("Datum dodat");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Greška");
    } finally {
      setAddingDate(false);
    }
  }

  async function updateDatum(datumId: number, field: "datum_od" | "datum_do", newVal: string) {
    if (!selectedId) return;
    const payload: Record<string, string> = { [field]: toISO(newVal) };
    await apiFetch(`/period-datum/${datumId}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    setGrupe((prev) => prev.map((g) =>
      g.id === selectedId
        ? {
            ...g,
            datumi: g.datumi
              .map((d) => (d.id === datumId ? { ...d, [field]: newVal } : d))
              .sort((a, b) => a.datum_od.localeCompare(b.datum_od)),
          }
        : g
    ));
    toast.success("Datum ažuriran");
  }

  async function renameGrupa(grupaId: number, noviNaziv: string) {
    const updated = await apiFetch<{ id: number; naziv: string }>(`/period-grupa/${grupaId}`, {
      method: "PUT",
      body: JSON.stringify({ naziv: noviNaziv }),
    });
    setGrupe((prev) => prev.map((g) => (g.id === grupaId ? { ...g, naziv: updated.naziv } : g)));
    toast.success("Naziv grupe je ažuriran");
  }

  async function deleteDatum() {
    if (!deleteDatumId || !selectedId) return;
    try {
      await apiFetch(`/period-datum/${deleteDatumId}`, { method: "DELETE" });
      setGrupe((prev) => prev.map((g) =>
        g.id === selectedId
          ? { ...g, datumi: g.datumi.filter((d) => d.id !== deleteDatumId) }
          : g
      ));
      setDeleteDatumId(null);
      toast.success("Datum obrisan");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Greška");
    }
  }

  async function deleteGrupa() {
    if (!deleteGrupaId) return;
    try {
      await apiFetch(`/period-grupa/${deleteGrupaId}`, { method: "DELETE" });
      if (selectedId === deleteGrupaId) setSelectedId(null);
      setGrupe((prev) => prev.filter((g) => g.id !== deleteGrupaId));
      setDeleteGrupaId(null);
      toast.success("Grupa obrisana");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Greška");
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Periodi</h1>
        <p className="text-muted-foreground text-sm">Grupe datuma putovanja</p>
      </div>

      {/* New group */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <CalendarDays className="w-5 h-5" /> Nova grupa
          </CardTitle>
          <CardDescription>Unesite naziv grupe datuma (npr. "Kasandra prva rotacija")</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-3">
            <Input
              value={newGroup}
              onChange={(e) => setNewGroup(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") addGroup(); }}
              placeholder="Naziv grupe"
              className="flex-1"
            />
            <Button onClick={addGroup}>
              <Plus className="w-4 h-4 mr-2" />Dodaj grupu
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Group list — tabelarni prikaz */}
      <Card>
        <CardHeader>
          <CardTitle>Grupe perioda</CardTitle>
          <CardDescription>Kliknite na red da otvorite datume ispod tabele; ime grupe menjate klikom na olovku</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Naziv grupe</TableHead>
                <TableHead className="w-32">Broj datuma</TableHead>
                <TableHead className="w-10" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {grupe.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={3} className="py-6 text-center text-sm text-muted-foreground">
                    Nema kreiranih grupa. Dodajte prvu grupu iznad.
                  </TableCell>
                </TableRow>
              ) : (
                grupe.map((g) => (
                  <TableRow
                    key={g.id}
                    onClick={() => { setSelectedId(g.id); setDatumPretraga(""); }}
                    className={cn("cursor-pointer", selectedId === g.id && "bg-primary/10 hover:bg-primary/10")}
                  >
                    <TableCell>
                      <EditableTextCell value={g.naziv} onSave={(v) => renameGrupa(g.id, v)} />
                    </TableCell>
                    <TableCell>
                      <Badge variant={selectedId === g.id ? "default" : "outline"}>{g.datumi.length}</Badge>
                    </TableCell>
                    <TableCell>
                      <ChevronRight className="w-4 h-4 text-muted-foreground" />
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Selected group — date management */}
      {selected && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div>
                <CardTitle className="flex items-center gap-2">
                  <CalendarDays className="w-5 h-5" />
                  Datumi — {selected.naziv}
                </CardTitle>
                <CardDescription>Datumski periodi za ovu grupu (format: dd.mm.yyyy)</CardDescription>
              </div>
              <Button
                variant="ghost"
                size="sm"
                className="text-destructive hover:text-destructive hover:bg-destructive/10"
                onClick={() => setDeleteGrupaId(selected.id)}
              >
                <Trash2 className="w-4 h-4 mr-1" />Obriši grupu
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-6">
            {/* Add date range */}
            <div className="flex flex-wrap items-end gap-3">
              <div className="space-y-2">
                <Label>Datum od</Label>
                <DateInput
                  value={newOd}
                  onChange={setNewOd}
                  onEnter={addDateRange}
                  className="w-36"
                />
              </div>
              <div className="space-y-2">
                <Label>Datum do</Label>
                <DateInput
                  value={newDo}
                  onChange={setNewDo}
                  onEnter={addDateRange}
                  className="w-36"
                />
              </div>
              <Button onClick={addDateRange} disabled={addingDate}>
                {addingDate ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Plus className="w-4 h-4 mr-2" />}
                Dodaj period
              </Button>
            </div>

            {/* Pretraga + zapisa datuma — 10 u redu */}
            {selected.datumi.length > 0 ? (
              <div className="space-y-3">
                <div className="relative">
                  <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    value={datumPretraga}
                    onChange={(e) => setDatumPretraga(e.target.value)}
                    placeholder="Pretraži datume (npr. 05.2026)"
                    className="pl-8"
                  />
                </div>
                {filtriraniDatumi.length === 0 ? (
                  <p className="text-sm text-muted-foreground text-center py-6">
                    Nema rezultata za „{datumPretraga.trim()}“.
                  </p>
                ) : (
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 md:grid-cols-5 xl:grid-cols-10">
                    {filtriraniDatumi.map((d) => (
                      <div
                        key={d.id}
                        className="group/chip relative flex flex-col gap-0.5 rounded-md border bg-card px-2 py-1.5 transition-colors hover:border-primary/50"
                      >
                        <span className="text-[9px] uppercase tracking-wide text-muted-foreground">od</span>
                        <EditableDateCell
                          compact
                          value={d.datum_od}
                          onSave={(v) => updateDatum(d.id, "datum_od", v)}
                        />
                        <span className="mt-1 text-[9px] uppercase tracking-wide text-muted-foreground">do</span>
                        <EditableDateCell
                          compact
                          value={d.datum_do}
                          onSave={(v) => updateDatum(d.id, "datum_do", v)}
                        />
                        <Button
                          variant="ghost"
                          size="icon"
                          className="absolute -right-1.5 -top-1.5 hidden h-5 w-5 rounded-full border bg-background text-destructive shadow-sm group-hover/chip:flex hover:text-destructive"
                          onClick={() => setDeleteDatumId(d.id)}
                        >
                          <Trash2 className="w-3 h-3" />
                        </Button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground text-center py-6">
                Nema unetih datuma. Dodajte prvi period iznad.
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {/* Delete grupa confirm */}
      <AlertDialog open={deleteGrupaId !== null} onOpenChange={() => setDeleteGrupaId(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Obriši grupu?</AlertDialogTitle>
            <AlertDialogDescription>
              Ova akcija briše grupu i sve njene datume. Ne može biti poništeno.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Otkaži</AlertDialogCancel>
            <AlertDialogAction
              onClick={deleteGrupa}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Obriši
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Delete datum confirm */}
      <AlertDialog open={deleteDatumId !== null} onOpenChange={() => setDeleteDatumId(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Obriši datum?</AlertDialogTitle>
            <AlertDialogDescription>Ovaj datumski period će biti trajno obrisan.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Otkaži</AlertDialogCancel>
            <AlertDialogAction
              onClick={deleteDatum}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Obriši
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
