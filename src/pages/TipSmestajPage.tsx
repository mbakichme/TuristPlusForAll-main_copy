import { useState, useEffect } from "react";
import type { TipSmestaja } from "../types";
import { apiFetch } from "../lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow
} from "@/components/ui/table";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter
} from "@/components/ui/dialog";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle
} from "@/components/ui/alert-dialog";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Plus, Pencil, Trash2, Loader2, Hotel } from "lucide-react";
import { toast } from "sonner";

export default function TipSmestajPage() {
  const [items, setItems] = useState<TipSmestaja[]>([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [deleteId, setDeleteId] = useState<number | null>(null);
  const [editing, setEditing] = useState<TipSmestaja | null>(null);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ naziv: "" });

  async function load() {
    try {
      const data = await apiFetch<TipSmestaja[]>("/tip-smestaja");
      setItems(data);
    } catch {
      toast.error("Greška pri učitavanju tipova smeštaja");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  function openAdd() {
    setEditing(null);
    setForm({ naziv: "" });
    setDialogOpen(true);
  }

  function openEdit(item: TipSmestaja) {
    setEditing(item);
    setForm({ naziv: item.naziv });
    setDialogOpen(true);
  }

  async function handleSave() {
    if (!form.naziv) { toast.error("Naziv je obavezan"); return; }
    setSaving(true);
    try {
      if (editing) {
        await apiFetch(`/tip-smestaja/${editing.id}`, {
          method: "PUT",
          body: JSON.stringify(form),
        });
        toast.success("Tip smeštaja ažuriran");
      } else {
        await apiFetch("/tip-smestaja", {
          method: "POST",
          body: JSON.stringify(form),
        });
        toast.success("Tip smeštaja kreiran");
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
      await apiFetch(`/tip-smestaja/${deleteId}`, { method: "DELETE" });
      toast.success("Tip smeštaja obrisan");
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
          <h1 className="text-2xl font-bold">Tipovi smeštaja</h1>
          <p className="text-muted-foreground text-sm">Upravljanje tipovima smeštaja</p>
        </div>
        <Button onClick={openAdd}><Plus className="w-4 h-4 mr-2" />Dodaj</Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Hotel className="w-5 h-5" />Tipovi smeštaja</CardTitle>
          <CardDescription>Lista svih tipova smeštaja</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-16">ID</TableHead>
                <TableHead>Naziv</TableHead>
                <TableHead className="w-24 text-right">Akcije</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.length === 0 ? (
                <TableRow><TableCell colSpan={3} className="text-center text-muted-foreground py-8">Nema podataka</TableCell></TableRow>
              ) : items.map((item) => (
                <TableRow key={item.id}>
                  <TableCell className="font-mono text-sm">{item.id}</TableCell>
                  <TableCell className="font-medium">{item.naziv}</TableCell>
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

      {/* Add/Edit Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editing ? "Izmeni tip smeštaja" : "Dodaj tip smeštaja"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <Label>Naziv *</Label>
              <Input value={form.naziv} onChange={(e) => setForm({ naziv: e.target.value })} placeholder="Unesite naziv" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>Otkaži</Button>
            <Button onClick={handleSave} disabled={saving}>
              {saving ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : null}
              {editing ? "Sačuvaj" : "Dodaj"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirm */}
      <AlertDialog open={deleteId !== null} onOpenChange={() => setDeleteId(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Obriši tip smeštaja?</AlertDialogTitle>
            <AlertDialogDescription>Ova akcija ne može biti poništena. Tip smeštaja će biti trajno obrisan.</AlertDialogDescription>
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
