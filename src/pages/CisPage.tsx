import { useState, useEffect } from "react";
import type { Mesto, PeriodGrupa } from "../types";
import { apiFetch } from "../lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow
} from "@/components/ui/table";
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle
} from "@/components/ui/dialog";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle
} from "@/components/ui/alert-dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue
} from "@/components/ui/select";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Plus, Pencil, Trash2, Loader2, Tag, Search } from "lucide-react";
import { toast } from "sonner";

interface CisOznaka {
  id: number;
  mesto_id: number;
  mesto_naziv: string;
  grupa_datuma: number;
  grupa_datuma_naziv: string;
  cis_oznaka: string;
}

interface CisForm {
  mesto_id: string;
  grupa_datuma: string;
  cis_oznaka: string;
}

const emptyForm: CisForm = { mesto_id: "", grupa_datuma: "", cis_oznaka: "" };

export default function CisPage() {
  const [items, setItems] = useState<CisOznaka[]>([]);
  const [mesta, setMesta] = useState<Mesto[]>([]);
  const [grupe, setGrupe] = useState<PeriodGrupa[]>([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<CisOznaka | null>(null);
  const [form, setForm] = useState<CisForm>(emptyForm);
  const [saving, setSaving] = useState(false);
  const [deleteId, setDeleteId] = useState<number | null>(null);
  const [pretraga, setPretraga] = useState("");

  const q = pretraga.trim().toLowerCase();
  // Grupe datuma samo za izabrano mesto (mesto_grupa preko /mesto → grupe)
  const izabranoMesto = mesta.find((m) => String(m.id) === form.mesto_id);
  const grupeZaMesto = (izabranoMesto?.grupe ?? [])
    .map((id) => grupe.find((g) => g.id === id))
    .filter((g): g is PeriodGrupa => !!g);
  const prikaz = q
    ? items.filter((r) =>
        [r.mesto_naziv, r.grupa_datuma_naziv, r.cis_oznaka].some((v) => (v || "").toLowerCase().includes(q)))
    : items;

  async function load() {
    try {
      const [cisData, mestoData, grupaData] = await Promise.all([
        apiFetch<CisOznaka[]>("/cis-oznake"),
        apiFetch<Mesto[]>("/mesto"),
        apiFetch<PeriodGrupa[]>("/period-grupa"),
      ]);
      setItems(cisData);
      setMesta(mestoData);
      setGrupe(grupaData);
    } catch {
      toast.error("Greška pri učitavanju CIS oznaka");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  function openAdd() {
    setEditing(null);
    setForm(emptyForm);
    setDialogOpen(true);
  }

  function openEdit(item: CisOznaka) {
    setEditing(item);
    setForm({
      mesto_id: String(item.mesto_id),
      grupa_datuma: String(item.grupa_datuma),
      cis_oznaka: item.cis_oznaka,
    });
    setDialogOpen(true);
  }

  async function handleSave() {
    if (!form.mesto_id) { toast.error("Izaberite mesto"); return; }
    if (!form.grupa_datuma) { toast.error("Izaberite grupu datuma"); return; }
    if (!form.cis_oznaka.trim()) { toast.error("CIS oznaka je obavezna"); return; }
    setSaving(true);
    try {
      const payload = {
        mesto_id: Number(form.mesto_id),
        grupa_datuma: Number(form.grupa_datuma),
        cis_oznaka: form.cis_oznaka.trim(),
      };
      if (editing) {
        await apiFetch(`/cis-oznake/${editing.id}`, { method: "PUT", body: JSON.stringify(payload) });
        toast.success("CIS oznaka ažurirana");
      } else {
        await apiFetch("/cis-oznake", { method: "POST", body: JSON.stringify(payload) });
        toast.success("CIS oznaka dodata");
      }
      setDialogOpen(false);
      load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Greška");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!deleteId) return;
    try {
      await apiFetch(`/cis-oznake/${deleteId}`, { method: "DELETE" });
      toast.success("CIS oznaka obrisana");
      setDeleteId(null);
      load();
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
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">CIS</h1>
          <p className="text-muted-foreground text-sm">CIS oznake po mestu i grupi datuma</p>
        </div>
        <Button onClick={openAdd}><Plus className="w-4 h-4 mr-2" />Dodaj</Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Tag className="w-5 h-5" />CIS oznake</CardTitle>
          <CardDescription>Lista svih CIS oznaka</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="relative max-w-sm">
            <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={pretraga}
              onChange={(e) => setPretraga(e.target.value)}
              placeholder="Pretraga po mestu, grupi datuma, CIS oznaci…"
              className="h-8 pl-8 text-xs"
            />
          </div>
          <Table className="text-xs">
            <TableHeader>
              <TableRow>
                <TableHead className="h-8 px-2 text-xs">Mesto</TableHead>
                <TableHead className="h-8 px-2 text-xs">Grupa datuma</TableHead>
                <TableHead className="h-8 px-2 text-xs">CIS oznaka</TableHead>
                <TableHead className="h-8 px-2 text-xs w-24 text-right">Akcije</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {prikaz.length === 0 && (
                <TableRow>
                  <TableCell colSpan={4} className="py-6 text-center text-muted-foreground">Nema CIS oznaka</TableCell>
                </TableRow>
              )}
              {prikaz.map((r) => (
                <TableRow key={r.id}>
                  <TableCell className="px-2 py-1 font-medium">{r.mesto_naziv}</TableCell>
                  <TableCell className="px-2 py-1">{r.grupa_datuma_naziv}</TableCell>
                  <TableCell className="px-2 py-1 font-mono">{r.cis_oznaka}</TableCell>
                  <TableCell className="px-2 py-1 text-right">
                    <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => openEdit(r)}>
                      <Pencil className="w-3.5 h-3.5" />
                    </Button>
                    <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive" onClick={() => setDeleteId(r.id)}>
                      <Trash2 className="w-3.5 h-3.5" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Dodaj / izmeni (popup) */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editing ? "Izmeni CIS oznaku" : "Nova CIS oznaka"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Mesto</Label>
              <Select
                value={form.mesto_id}
                onValueChange={(v) => setForm((f) => ({ ...f, mesto_id: v, grupa_datuma: "" }))}
              >
                <SelectTrigger><SelectValue placeholder="Izaberite mesto" /></SelectTrigger>
                <SelectContent className="max-h-72">
                  {mesta.map((m) => <SelectItem key={m.id} value={String(m.id)}>{m.naziv}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Grupa datuma</Label>
              <Select
                value={form.grupa_datuma}
                onValueChange={(v) => setForm((f) => ({ ...f, grupa_datuma: v }))}
                disabled={!form.mesto_id || grupeZaMesto.length === 0}
              >
                <SelectTrigger>
                  <SelectValue placeholder={!form.mesto_id ? "Prvo izaberite mesto" : grupeZaMesto.length === 0 ? "Mesto nema vezane grupe datuma" : "Izaberite grupu datuma"} />
                </SelectTrigger>
                <SelectContent className="max-h-72">
                  {grupeZaMesto.map((g) => <SelectItem key={g.id} value={String(g.id)}>{g.naziv}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>CIS oznaka</Label>
              <Input
                value={form.cis_oznaka}
                onChange={(e) => setForm((f) => ({ ...f, cis_oznaka: e.target.value }))}
                placeholder="CIS oznaka"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>Otkaži</Button>
            <Button onClick={handleSave} disabled={saving}>
              {saving ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : null}
              {editing ? "Sačuvaj izmene" : "Dodaj"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Brisanje */}
      <AlertDialog open={deleteId !== null} onOpenChange={() => setDeleteId(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Obriši CIS oznaku?</AlertDialogTitle>
            <AlertDialogDescription>Ova akcija ne može biti poništena.</AlertDialogDescription>
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
