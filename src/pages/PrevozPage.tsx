import { useState, useEffect, useMemo, useDeferredValue } from "react";
import type { Polazak } from "../types";
import { apiFetch } from "../lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle
} from "@/components/ui/alert-dialog";
import {
  Plus, Pencil, Trash2, Loader2, Bus, Check, X, ArrowUp, ArrowDown, ChevronsUpDown, Search
} from "lucide-react";
import { toast } from "sonner";

type PolazakKey = "destinacija" | "polazak" | "sat" | "valuta"
  | "adlrt" | "chdrt" | "infrt" | "adlow" | "chdow" | "infow";

interface ColDef {
  key: PolazakKey;
  label: string;
  tip?: string;
  num?: boolean;
  cls?: string;
}

const COLUMNS: ColDef[] = [
  { key: "destinacija", label: "Destinacija", cls: "min-w-32" },
  { key: "polazak", label: "Mesto polaska", cls: "min-w-56" },
  { key: "sat", label: "Sat", cls: "w-20" },
  { key: "valuta", label: "Valuta", cls: "w-20" },
  { key: "adlrt", label: "ADL RT", tip: "Odrasli — povratna karta (RT)", num: true, cls: "w-24" },
  { key: "chdrt", label: "CHD RT", tip: "Dete — povratna karta (RT)", num: true, cls: "w-24" },
  { key: "infrt", label: "INF RT", tip: "Beba — povratna karta (RT)", num: true, cls: "w-24" },
  { key: "adlow", label: "ADL OW", tip: "Odrasli — jedan pravac (OW)", num: true, cls: "w-24" },
  { key: "chdow", label: "CHD OW", tip: "Dete — jedan pravac (OW)", num: true, cls: "w-24" },
  { key: "infow", label: "INF OW", tip: "Beba — jedan pravac (OW)", num: true, cls: "w-24" },
];

const NUM_KEYS: PolazakKey[] = ["adlrt", "chdrt", "infrt", "adlow", "chdow", "infow"];

interface PolazakForm {
  destinacija: string; polazak: string; sat: string; valuta: string;
  adlrt: string; chdrt: string; infrt: string; adlow: string; chdow: string; infow: string;
}

const emptyForm: PolazakForm = {
  destinacija: "", polazak: "", sat: "", valuta: "EUR",
  adlrt: "", chdrt: "", infrt: "", adlow: "", chdow: "", infow: "",
};

const fmtNum = new Intl.NumberFormat("sr-RS", { minimumFractionDigits: 0, maximumFractionDigits: 2 });

function toForm(p: Polazak): PolazakForm {
  return {
    destinacija: p.destinacija ?? "",
    polazak: p.polazak ?? "",
    sat: p.sat ?? "",
    valuta: p.valuta ?? "",
    adlrt: p.adlrt == null ? "" : String(p.adlrt),
    chdrt: p.chdrt == null ? "" : String(p.chdrt),
    infrt: p.infrt == null ? "" : String(p.infrt),
    adlow: p.adlow == null ? "" : String(p.adlow),
    chdow: p.chdow == null ? "" : String(p.chdow),
    infow: p.infow == null ? "" : String(p.infow),
  };
}

function parseNum(v: string): number | null {
  const t = v.trim().replace(",", ".");
  if (!t) return null;
  const n = Number(t);
  return Number.isNaN(n) ? null : n;
}

const thBase = "sticky z-10 h-9 border-b bg-card px-2 align-middle font-medium text-muted-foreground";

export default function PrevozPage() {
  const [items, setItems] = useState<Polazak[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState<Record<PolazakKey, string>>({
    destinacija: "", polazak: "", sat: "", valuta: "",
    adlrt: "", chdrt: "", infrt: "", adlow: "", chdow: "", infow: "",
  });
  const [sort, setSort] = useState<{ key: PolazakKey; dir: "asc" | "desc" }>({ key: "destinacija", dir: "asc" });
  const [editId, setEditId] = useState<number | "new" | null>(null);
  const [form, setForm] = useState<PolazakForm>(emptyForm);
  const [saving, setSaving] = useState(false);
  const [deleteId, setDeleteId] = useState<number | null>(null);

  async function load() {
    try {
      setItems(await apiFetch<Polazak[]>("/polazak"));
    } catch {
      toast.error("Greška pri učitavanju polazaka");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  const deferredSearch = useDeferredValue(search);
  const deferredFilters = useDeferredValue(filters);

  const filtered = useMemo(() => {
    const q = deferredSearch.trim().toLowerCase();
    const active = (Object.entries(deferredFilters) as [PolazakKey, string][])
      .filter(([, v]) => v.trim() !== "");
    let rows = items;
    if (q) {
      rows = rows.filter((it) =>
        COLUMNS.some((c) => {
          const v = it[c.key];
          return v != null && String(v).toLowerCase().includes(q);
        })
      );
    }
    if (active.length) {
      rows = rows.filter((it) =>
        active.every(([k, v]) => {
          const val = it[k];
          const s = val == null ? "" : String(val).toLowerCase();
          return s.includes(v.trim().toLowerCase());
        })
      );
    }
    const { key, dir } = sort;
    const mul = dir === "asc" ? 1 : -1;
    const num = NUM_KEYS.includes(key);
    return [...rows].sort((a, b) => {
      const av = a[key];
      const bv = b[key];
      if (num) {
        const an = av == null ? null : Number(av);
        const bn = bv == null ? null : Number(bv);
        if (an == null && bn == null) return a.id - b.id;
        if (an == null) return 1;
        if (bn == null) return -1;
        if (an !== bn) return (an - bn) * mul;
        return a.id - b.id;
      }
      const as = (av ?? "").toString().toLowerCase();
      const bs = (bv ?? "").toString().toLowerCase();
      if (as !== bs) return as < bs ? -1 * mul : 1 * mul;
      return a.id - b.id;
    });
  }, [items, deferredSearch, deferredFilters, sort]);

  const filteriAktivni = deferredSearch.trim() !== "" ||
    Object.values(filters).some((v) => v.trim() !== "");

  function toggleSort(key: PolazakKey) {
    setSort((s) => s.key === key
      ? { key, dir: s.dir === "asc" ? "desc" : "asc" }
      : { key, dir: "asc" });
  }

  function openAdd() {
    setForm(emptyForm);
    setEditId("new");
  }

  function openEdit(p: Polazak) {
    setForm(toForm(p));
    setEditId(p.id);
  }

  function cancelEdit() {
    setEditId(null);
    setForm(emptyForm);
  }

  function setField(key: PolazakKey, value: string) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function handleSave() {
    setSaving(true);
    try {
      const payload = {
        destinacija: form.destinacija.trim(),
        polazak: form.polazak.trim(),
        sat: form.sat.trim(),
        valuta: form.valuta.trim(),
        adlrt: parseNum(form.adlrt),
        chdrt: parseNum(form.chdrt),
        infrt: parseNum(form.infrt),
        adlow: parseNum(form.adlow),
        chdow: parseNum(form.chdow),
        infow: parseNum(form.infow),
      };
      if (editId === "new") {
        await apiFetch("/polazak", { method: "POST", body: JSON.stringify(payload) });
        toast.success("Polazak dodat");
      } else if (editId != null) {
        await apiFetch(`/polazak/${editId}`, { method: "PUT", body: JSON.stringify(payload) });
        toast.success("Polazak sačuvan");
      }
      cancelEdit();
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Greška");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!deleteId) return;
    try {
      await apiFetch(`/polazak/${deleteId}`, { method: "DELETE" });
      toast.success("Polazak obrisan");
      setDeleteId(null);
      load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Greška");
    }
  }

  function clearFilters() {
    setSearch("");
    setFilters({ destinacija: "", polazak: "", sat: "", valuta: "", adlrt: "", chdrt: "", infrt: "", adlow: "", chdow: "", infow: "" });
  }

  function editCell(col: ColDef, autoFocus = false) {
    return (
      <Input
        autoFocus={autoFocus}
        inputMode={col.num ? "decimal" : undefined}
        className={cn("h-8 text-sm", col.num && "text-right")}
        value={form[col.key]}
        onChange={(e) => setField(col.key, e.target.value)}
      />
    );
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
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Detalji o prevozu</h1>
          <p className="text-muted-foreground text-sm">Cene i mesta polaska agencijskog prevoza</p>
        </div>
        <Button onClick={openAdd} disabled={editId === "new"}>
          <Plus className="w-4 h-4 mr-2" />Dodaj
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Bus className="w-5 h-5" />Prevoz</CardTitle>
          <CardDescription>
            Ukupno: <span className="font-semibold text-foreground">{items.length}</span>
            {filteriAktivni && <> · prikazano: <span className="font-semibold text-foreground">{filtered.length}</span></>}
            {filteriAktivni && (
              <Button variant="ghost" size="sm" className="ml-2 h-6 px-2 text-xs" onClick={clearFilters}>
                <X className="w-3 h-3 mr-1" />Očisti filtere
              </Button>
            )}
          </CardDescription>
          <div className="relative max-w-md mt-2">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Pretraga po svim poljima..."
              className="pl-9"
            />
          </div>
        </CardHeader>
        <CardContent className="px-4 pb-4">
          <div className="max-h-[70vh] overflow-auto rounded-lg border">
            <table className="w-full border-separate border-spacing-0 text-sm">
              <thead>
                <tr>
                  {COLUMNS.map((col) => (
                    <th
                      key={col.key}
                      title={col.tip}
                      className={cn(thBase, "top-0 text-left", col.num && "text-right", col.cls)}
                    >
                      <button
                        onClick={() => toggleSort(col.key)}
                        className={cn(
                          "flex items-center gap-1 hover:text-foreground",
                          col.num && "flex-row-reverse",
                          sort.key === col.key && "text-foreground font-semibold"
                        )}
                      >
                        {col.label}
                        {sort.key === col.key
                          ? sort.dir === "asc"
                            ? <ArrowUp className="w-3 h-3" />
                            : <ArrowDown className="w-3 h-3" />
                          : <ChevronsUpDown className="w-3 h-3 opacity-40" />}
                      </button>
                    </th>
                  ))}
                  <th className={cn(thBase, "top-0 text-right w-24")}>Akcije</th>
                </tr>
                <tr>
                  {COLUMNS.map((col) => (
                    <th key={col.key} className={cn(thBase, "top-9 border-b-2 px-1 py-1", col.cls)}>
                      <Input
                        value={filters[col.key]}
                        onChange={(e) => setFilters((f) => ({ ...f, [col.key]: e.target.value }))}
                        placeholder="filter"
                        className="h-8 text-xs"
                      />
                    </th>
                  ))}
                  <th className={cn(thBase, "top-9 border-b-2 w-24")} />
                </tr>
              </thead>
              <tbody>
                {editId === "new" && (
                  <tr className="bg-muted/40">
                    {COLUMNS.map((col, i) => (
                      <td key={col.key} className={cn("px-1 py-1", col.cls)}>
                        {editCell(col, i === 0)}
                      </td>
                    ))}
                    <td className="px-1 py-1 text-right whitespace-nowrap">
                      <Button variant="ghost" size="icon" onClick={handleSave} disabled={saving} title="Sačuvaj">
                        {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4 text-green-600" />}
                      </Button>
                      <Button variant="ghost" size="icon" onClick={cancelEdit} title="Otkaži">
                        <X className="w-4 h-4" />
                      </Button>
                    </td>
                  </tr>
                )}
                {filtered.length === 0 && editId !== "new" ? (
                  <tr>
                    <td colSpan={COLUMNS.length + 1} className="text-center text-muted-foreground py-8">
                      {filteriAktivni ? "Nema rezultata za zadate filtere" : "Nema podataka. Kliknite Dodaj da unesete prvi polazak."}
                    </td>
                  </tr>
                ) : filtered.map((item) =>
                  item.id === editId ? (
                    <tr key={item.id} className="bg-muted/40">
                      {COLUMNS.map((col, i) => (
                        <td key={col.key} className={cn("px-1 py-1", col.cls)}>
                          {editCell(col, i === 0)}
                        </td>
                      ))}
                      <td className="px-1 py-1 text-right whitespace-nowrap">
                        <Button variant="ghost" size="icon" onClick={handleSave} disabled={saving} title="Sačuvaj">
                          {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4 text-green-600" />}
                        </Button>
                        <Button variant="ghost" size="icon" onClick={cancelEdit} title="Otkaži">
                          <X className="w-4 h-4" />
                        </Button>
                      </td>
                    </tr>
                  ) : (
                    <tr key={item.id}>
                      <td className="px-2 py-1.5 font-medium max-w-40 truncate" title={item.destinacija || undefined}>
                        {item.destinacija || <span className="text-muted-foreground">—</span>}
                      </td>
                      <td className="px-2 py-1.5 max-w-60 truncate" title={item.polazak || undefined}>
                        {item.polazak || <span className="text-muted-foreground">—</span>}
                      </td>
                      <td className="px-2 py-1.5 font-mono text-xs">
                        {item.sat || <span className="text-muted-foreground">—</span>}
                      </td>
                      <td className="px-2 py-1.5">
                        {item.valuta || <span className="text-muted-foreground">—</span>}
                      </td>
                      {NUM_KEYS.map((k) => (
                        <td key={k} className={cn("px-2 py-1.5 text-right", item[k] == null && "text-muted-foreground")}>
                          {item[k] == null ? "—" : fmtNum.format(item[k] as number)}
                        </td>
                      ))}
                      <td className="px-2 py-1.5 text-right whitespace-nowrap">
                        <Button variant="ghost" size="icon" onClick={() => openEdit(item)} title="Izmeni">
                          <Pencil className="w-4 h-4" />
                        </Button>
                        <Button
                          variant="ghost" size="icon"
                          className="text-destructive hover:text-destructive"
                          onClick={() => setDeleteId(item.id)}
                          title="Obriši"
                        >
                          <Trash2 className="w-4 h-4" />
                        </Button>
                      </td>
                    </tr>
                  )
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      {/* Delete Confirm */}
      <AlertDialog open={deleteId !== null} onOpenChange={() => setDeleteId(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Obriši polazak?</AlertDialogTitle>
            <AlertDialogDescription>Ova akcija ne može biti poništena. Red će biti trajno obrisan.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Otkaži</AlertDialogCancel>
            <AlertDialogAction onClick={handleDelete} className="bg-destructive text-destructive-foreground hover:bg-destructive/90">Obriši</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
