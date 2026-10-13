import { useState, useEffect } from "react";
import type { Drzava } from "../types";
import { apiFetch } from "../lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Plus, Pencil, Trash2, Loader2, Flag } from "lucide-react";
import { toast } from "sonner";

interface DrzavaForm {
  naziv: string;
  id_cis: string;
  naziv_cis: string;
}

const emptyForm: DrzavaForm = { naziv: "", id_cis: "", naziv_cis: "" };

export default function DrzavaPage() {
  const [items, setItems] = useState<Drzava[]>([]);
  const [loading, setLoading] = useState(true);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [deleteId, setDeleteId] = useState<number | null>(null);
  const [editing, setEditing] = useState<Drzava | null>(null);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState<DrzavaForm>(emptyForm);

  async function load() {
    try {
      const data = await apiFetch<Drzava[]>("/drzava");
      setItems(data);
    } catch {
      toast.error("Greška pri učitavanju država");
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

  function openEdit(item: Drzava) {
    setEditing(item);
    setForm({ naziv: item.naziv, id_cis: item.id_cis || "", naziv_cis: item.naziv_cis || "" });
    setSheetOpen(true);
  }

  function setField(key: keyof DrzavaForm, value: string) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function handleSave() {
    if (!form.naziv) { toast.error("Naziv je obavezan"); return; }
    setSaving(true);
    try {
      const payload = { naziv: form.naziv, id_cis: form.id_cis || undefined, naziv_cis: form.naziv_cis || undefined };
      if (editing) {
        await apiFetch(`/drzava/${editing.id}`, {
          method: "PUT",
          body: JSON.stringify(payload),
        });
        toast.success("Država ažurirana");
      } else {
        await apiFetch("/drzava", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        toast.success("Država kreirana");
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
      await apiFetch(`/drzava/${deleteId}`, { method: "DELETE" });
      toast.success("Država obrisana");
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
          <h1 className="text-2xl font-bold">Države</h1>
          <p className="text-muted-foreground text-sm">Upravljanje državama</p>
        </div>
        <Button onClick={openAdd}><Plus className="w-4 h-4 mr-2" />Dodaj</Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Flag className="w-5 h-5" />Države</CardTitle>
          <CardDescription>Lista svih država</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Naziv</TableHead>
                <TableHead>ID CIS</TableHead>
                <TableHead>Naziv CIS</TableHead>
                <TableHead className="w-24 text-right">Akcije</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.length === 0 ? (
                <TableRow><TableCell colSpan={4} className="text-center text-muted-foreground py-8">Nema podataka</TableCell></TableRow>
              ) : items.map((item) => (
                <TableRow key={item.id}>
                  <TableCell className="font-medium">{item.naziv}</TableCell>
                  <TableCell className="text-muted-foreground">{item.id_cis || "—"}</TableCell>
                  <TableCell className="text-muted-foreground">{item.naziv_cis || "—"}</TableCell>
                  <TableCell className="text-right">
                    <div className="flex items-center justify-end gap-1">
                      <Button variant="ghost" size="icon" onClick={() => openEdit(item)}><Pencil className="w-4 h-4" /></Button>
                      <Button variant="ghost" size="icon" className="text-destructive hover:text-destructive" onClick={() => setDeleteId(item.id)}><Trash2 className="w-4 h-4" /></Button>
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
            <SheetTitle>{editing ? "Izmeni državu" : "Dodaj državu"}</SheetTitle>
          </SheetHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label>Naziv *</Label>
              <Input value={form.naziv} onChange={(e) => setField("naziv", e.target.value)} placeholder="Unesite naziv" />
            </div>
            <div className="space-y-2">
              <Label>ID CIS</Label>
              <Input value={form.id_cis} onChange={(e) => setField("id_cis", e.target.value)} placeholder="CIS identifikator" />
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
              {editing ? "Sačuvaj izmene" : "Dodaj državu"}
            </Button>
          </SheetFooter>
        </SheetContent>
      </Sheet>

      {/* Delete Confirm */}
      <AlertDialog open={deleteId !== null} onOpenChange={() => setDeleteId(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Obriši državu?</AlertDialogTitle>
            <AlertDialogDescription>Ova akcija ne može biti poništena. Država će biti trajno obrisana.</AlertDialogDescription>
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
