import { useState, useEffect } from "react";
import type { Destinacija, Drzava } from "../types";
import { apiFetch } from "../lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow
} from "@/components/ui/table";
import {
  Sheet, SheetContent, SheetHeader, SheetTitle, SheetFooter
} from "@/components/ui/sheet";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle
} from "@/components/ui/alert-dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue
} from "@/components/ui/select";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Plus, Pencil, Trash2, Loader2, MapPin, Search } from "lucide-react";
import { toast } from "sonner";

interface DestinacijaForm {
  naziv: string;
  drzava: string;
  status: string;
  organizator: string;
  predstavnik: string;
  naziv_cis: string;
}

const emptyForm: DestinacijaForm = { naziv: "", drzava: "", status: "1", organizator: "", predstavnik: "", naziv_cis: "" };

export default function DestinacijaPage() {
  const [items, setItems] = useState<Destinacija[]>([]);
  const [drzave, setDrzave] = useState<Drzava[]>([]);
  const [loading, setLoading] = useState(true);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [deleteId, setDeleteId] = useState<number | null>(null);
  const [editing, setEditing] = useState<Destinacija | null>(null);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState<DestinacijaForm>(emptyForm);
  const [pretraga, setPretraga] = useState("");
  const q = pretraga.trim().toLowerCase();
  const prikaz = q
    ? items.filter((d) =>
        [d.naziv, d.drzava_naziv, d.naziv_cis].some((v) => (v || "").toLowerCase().includes(q)))
    : items;

  async function load() {
    try {
      const [destData, drzData] = await Promise.all([
        apiFetch<Destinacija[]>("/destinacija"),
        apiFetch<Drzava[]>("/drzava"),
      ]);
      setItems(destData);
      setDrzave(drzData);
    } catch {
      toast.error("Greška pri učitavanju destinacija");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  function openAdd() {
    setEditing(null);
    setForm(emptyForm);
    setSheetOpen(true);
  }

  function openEdit(item: Destinacija) {
    setEditing(item);
    setForm({
      naziv: item.naziv,
      drzava: item.drzava ? String(item.drzava) : "",
      status: String(item.status),
      organizator: item.organizator ? String(item.organizator) : "",
      predstavnik: item.predstavnik ? String(item.predstavnik) : "",
      naziv_cis: item.naziv_cis || "",
    });
    setSheetOpen(true);
  }

  function setField(key: keyof DestinacijaForm, value: string) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function handleSave() {
    if (!form.naziv) { toast.error("Naziv je obavezan"); return; }
    setSaving(true);
    try {
      const payload = {
        naziv: form.naziv,
        drzava: form.drzava ? Number(form.drzava) : undefined,
        status: Number(form.status),
        organizator: form.organizator ? Number(form.organizator) : undefined,
        predstavnik: form.predstavnik ? Number(form.predstavnik) : undefined,
        naziv_cis: form.naziv_cis || undefined,
      };
      if (editing) {
        await apiFetch(`/destinacija/${editing.id}`, {
          method: "PUT",
          body: JSON.stringify(payload),
        });
        toast.success("Destinacija ažurirana");
      } else {
        await apiFetch("/destinacija", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        toast.success("Destinacija kreirana");
      }
      setSheetOpen(false);
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
      await apiFetch(`/destinacija/${deleteId}`, { method: "DELETE" });
      toast.success("Destinacija obrisana");
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
          <h1 className="text-2xl font-bold">Destinacije</h1>
          <p className="text-muted-foreground text-sm">Upravljanje destinacijama</p>
        </div>
        <Button onClick={openAdd}><Plus className="w-4 h-4 mr-2" />Dodaj</Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><MapPin className="w-5 h-5" />Destinacije</CardTitle>
          <CardDescription>Lista svih destinacija</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="relative max-w-sm">
            <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={pretraga}
              onChange={(e) => setPretraga(e.target.value)}
              placeholder="Pretraga po nazivu, državi, nazivu CIS…"
              className="h-8 pl-8 text-xs"
            />
          </div>
          <Table className="text-xs">
            <TableHeader>
              <TableRow>
                <TableHead className="h-8 px-2 text-xs">Naziv</TableHead>
                <TableHead className="h-8 px-2 text-xs">Država</TableHead>
                <TableHead className="h-8 px-2 text-xs">Status</TableHead>
                <TableHead className="h-8 px-2 text-xs">Naziv CIS</TableHead>
                <TableHead className="h-8 w-20 px-2 text-right text-xs">Akcije</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {prikaz.length === 0 ? (
                <TableRow><TableCell colSpan={5} className="py-6 text-center text-xs text-muted-foreground">{items.length === 0 ? "Nema podataka" : "Nema rezultata pretrage"}</TableCell></TableRow>
              ) : prikaz.map((item) => (
                <TableRow key={item.id}>
                  <TableCell className="px-2 py-1.5 font-medium">{item.naziv}</TableCell>
                  <TableCell className="px-2 py-1.5">{item.drzava_naziv || "—"}</TableCell>
                  <TableCell className="px-2 py-1.5">
                    <Badge variant={item.status === 1 ? "default" : "secondary"} className="px-1.5 py-0 text-[10px]">
                      {item.status === 1 ? "Aktivan" : "Neaktivan"}
                    </Badge>
                  </TableCell>
                  <TableCell className="px-2 py-1.5 text-muted-foreground">{item.naziv_cis || "—"}</TableCell>
                  <TableCell className="px-2 py-1 text-right">
                    <div className="flex items-center justify-end gap-0.5">
                      <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => openEdit(item)}><Pencil className="w-3.5 h-3.5" /></Button>
                      <Button variant="ghost" size="icon" className="h-6 w-6 text-destructive hover:text-destructive" onClick={() => setDeleteId(item.id)}><Trash2 className="w-3.5 h-3.5" /></Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Add/Edit Sheet */}
      <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
        <SheetContent className="sm:max-w-lg overflow-y-auto">
          <SheetHeader>
            <SheetTitle>{editing ? "Izmeni destinaciju" : "Dodaj destinaciju"}</SheetTitle>
          </SheetHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label>Naziv *</Label>
              <Input value={form.naziv} onChange={(e) => setField("naziv", e.target.value)} placeholder="Unesite naziv" />
            </div>
            <div className="space-y-2">
              <Label>Država</Label>
              <Select value={form.drzava} onValueChange={(v) => setField("drzava", v)}>
                <SelectTrigger><SelectValue placeholder="Izaberite državu" /></SelectTrigger>
                <SelectContent>
                  {drzave.map((d) => (
                    <SelectItem key={d.id} value={String(d.id)}>{d.naziv}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Status</Label>
              <Select value={form.status} onValueChange={(v) => setField("status", v)}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="1">Aktivan</SelectItem>
                  <SelectItem value="0">Neaktivan</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Organizator</Label>
              <Input type="number" value={form.organizator} onChange={(e) => setField("organizator", e.target.value)} placeholder="ID organizatora" />
            </div>
            <div className="space-y-2">
              <Label>Predstavnik</Label>
              <Input type="number" value={form.predstavnik} onChange={(e) => setField("predstavnik", e.target.value)} placeholder="ID predstavnika" />
            </div>
            <div className="space-y-2">
              <Label>Naziv CIS</Label>
              <Input value={form.naziv_cis} onChange={(e) => setField("naziv_cis", e.target.value)} placeholder="CIS naziv" />
            </div>
          </div>
          <SheetFooter>
            <Button variant="outline" onClick={() => setSheetOpen(false)}>Otkaži</Button>
            <Button onClick={handleSave} disabled={saving}>
              {saving ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : null}
              {editing ? "Sačuvaj izmene" : "Dodaj destinaciju"}
            </Button>
          </SheetFooter>
        </SheetContent>
      </Sheet>

      {/* Delete Confirm */}
      <AlertDialog open={deleteId !== null} onOpenChange={() => setDeleteId(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Obriši destinaciju?</AlertDialogTitle>
            <AlertDialogDescription>Ova akcija ne može biti poništena. Destinacija će biti trajno obrisana.</AlertDialogDescription>
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
