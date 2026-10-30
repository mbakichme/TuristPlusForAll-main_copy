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
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue
} from "@/components/ui/select";
import {
  Plus, Pencil, Trash2, Loader2, Bus, Check, X, ArrowUp, ArrowDown, ChevronsUpDown, Search
} from "lucide-react";
import { toast } from "sonner";

interface Sifarnik { id: number; naziv: string; }

type PolazakKey = "destinacija" | "polazak" | "sat" | "valuta" | "mesto_naziv" | "grupa_naziv"
  | "adlrt" | "chdrt" | "adlow" | "chdow" | "cena_transfera";

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
  { key: "mesto_naziv", label: "Mesto", tip: "Mesto iz šifarnika", cls: "min-w-40" },
  { key: "grupa_naziv", label: "Grupa termina", tip: "Grupa termina", cls: "min-w-44" },
  { key: "adlrt", label: "ADL RT", tip: "Odrasli — povratna karta (RT)", num: true, cls: "w-24" },
  { key: "chdrt", label: "CHD RT", tip: "Dete — povratna karta (RT)", num: true, cls: "w-24" },
  { key: "adlow", label: "ADL OW", tip: "Odrasli — jedan pravac (OW)", num: true, cls: "w-24" },
  { key: "chdow", label: "CHD OW", tip: "Dete — jedan pravac (OW)", num: true, cls: "w-24" },
  { key: "cena_transfera", label: "Cena transfera (EUR)", tip: "Cena transfera u EUR", num: true, cls: "w-32" },
];

const NUM_KEYS: PolazakKey[] = ["adlrt", "chdrt", "adlow", "chdow", "cena_transfera"];

interface PolazakForm {
  destinacija_id: string; polazak: string; sat: string; valuta: string;
  mesto_id: string; grupa_id: string;
  adlrt: string; chdrt: string; infrt: string; adlow: string; chdow: string; infow: string;
  cena_transfera: string;
}

// INF RT/OW nisu u tabeli; podrazumevano 0 za nove zapise, a kod izmene ostaje sačuvana vrednost (toForm)
const emptyForm: PolazakForm = {
  destinacija_id: "", polazak: "", sat: "", valuta: "EUR", mesto_id: "", grupa_id: "",
  adlrt: "", chdrt: "", infrt: "0", adlow: "", chdow: "", infow: "0", cena_transfera: "",
};

const EMPTY_FILTERS: Record<PolazakKey, string> = {
  destinacija: "", polazak: "", sat: "", valuta: "", mesto_naziv: "", grupa_naziv: "",
  adlrt: "", chdrt: "", adlow: "", chdow: "", cena_transfera: "",
};

const fmtNum = new Intl.NumberFormat("sr-RS", { minimumFractionDigits: 0, maximumFractionDigits: 2 });

function toForm(p: Polazak): PolazakForm {
  return {
    destinacija_id: p.destinacija_id == null ? "" : String(p.destinacija_id),
    polazak: p.polazak ?? "",
    sat: p.sat ?? "",
    valuta: p.valuta ?? "",
    mesto_id: p.mesto_id == null ? "" : String(p.mesto_id),
    grupa_id: p.grupa_id == null ? "" : String(p.grupa_id),
    adlrt: p.adlrt == null ? "" : String(p.adlrt),
    chdrt: p.chdrt == null ? "" : String(p.chdrt),
    infrt: p.infrt == null ? "" : String(p.infrt),
    adlow: p.adlow == null ? "" : String(p.adlow),
    chdow: p.chdow == null ? "" : String(p.chdow),
    infow: p.infow == null ? "" : String(p.infow),
    cena_transfera: p.cena_transfera == null ? "" : String(p.cena_transfera),
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
  const [filters, setFilters] = useState<Record<PolazakKey, string>>(EMPTY_FILTERS);
  const [mesta, setMesta] = useState<Sifarnik[]>([]);
  const [grupe, setGrupe] = useState<Sifarnik[]>([]);
  const [destinacije, setDestinacije] = useState<Sifarnik[]>([]);
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

  useEffect(() => {
    Promise.all([
      apiFetch<Sifarnik[]>("/mesto"),
      apiFetch<Sifarnik[]>("/period-grupa"),
      apiFetch<Sifarnik[]>("/destinacija"),
    ])
      .then(([m, g, d]) => {
        setMesta([...m].sort((a, b) => a.naziv.localeCompare(b.naziv, "sr")));
        setGrupe([...g].sort((a, b) => a.naziv.localeCompare(b.naziv, "sr")));
        setDestinacije([...d].sort((a, b) => a.naziv.localeCompare(b.naziv, "sr")));
      })
      .catch(() => toast.error("Greška pri učitavanju šifarnika"));
  }, []);

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

  function setField(key: keyof PolazakForm, value: string) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function handleSave() {
    if (!form.destinacija_id) {
      toast.error("Destinacija je obavezna");
      return;
    }
    setSaving(true);
    try {
      const payload = {
        destinacija_id: form.destinacija_id ? Number(form.destinacija_id) : null,
        polazak: form.polazak.trim(),
        sat: form.sat.trim(),
        valuta: form.valuta.trim(),
        mesto_id: form.mesto_id ? Number(form.mesto_id) : null,
        grupa_id: form.grupa_id ? Number(form.grupa_id) : null,
        adlrt: parseNum(form.adlrt),
        chdrt: parseNum(form.chdrt),
        infrt: parseNum(form.infrt),
        adlow: parseNum(form.adlow),
        chdow: parseNum(form.chdow),
        infow: parseNum(form.infow),
        cena_transfera: parseNum(form.cena_transfera),
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
    setFilters(EMPTY_FILTERS);
  }

  function editCell(col: ColDef, autoFocus = false) {
    if (col.key === "destinacija" || col.key === "mesto_naziv" || col.key === "grupa_naziv") {
      const formKey = col.key === "destinacija" ? "destinacija_id"
        : col.key === "mesto_naziv" ? "mesto_id" : "grupa_id";
      const opcije = col.key === "destinacija" ? destinacije
        : col.key === "mesto_naziv" ? mesta : grupe;
      const placeholder = col.key === "destinacija" ? "Izaberi destinaciju"
        : col.key === "mesto_naziv" ? "Izaberi mesto" : "Izaberi grupu";
      return (
        <Select value={form[formKey] || undefined} onValueChange={(v) => setField(formKey, v)}>
          <SelectTrigger aria-label={col.label} className="h-8 text-sm">
            <SelectValue placeholder={placeholder} />
          </SelectTrigger>
          <SelectContent>
            {opcije.map((o) => (
              <SelectItem key={o.id} value={String(o.id)}>{o.naziv}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      );
    }
    const k = col.key as keyof PolazakForm;
    return (
      <Input
        autoFocus={autoFocus}
        inputMode={col.num ? "decimal" : undefined}
        className={cn("h-8 text-sm", col.num && "text-right")}
        value={form[k]}
        onChange={(e) => setField(k, e.target.value)}
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
                      <td className="px-2 py-1.5" title={item.mesto_naziv || undefined}>
                        {item.mesto_naziv || <span className="text-muted-foreground">—</span>}
                      </td>
                      <td className="px-2 py-1.5" title={item.grupa_naziv || undefined}>
                        {item.grupa_naziv || <span className="text-muted-foreground">—</span>}
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
