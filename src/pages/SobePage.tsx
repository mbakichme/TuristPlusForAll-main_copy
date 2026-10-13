import { useState, useEffect, useMemo } from "react";
import type { Soba, Smestaj } from "../types";
import { apiFetch } from "../lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
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
import { Plus, Pencil, Trash2, Loader2, DoorOpen, Search } from "lucide-react";
import { toast } from "sonner";

interface SobaForm {
  veza_id_smestaj: string;
  broj_sobe: string;
  tip: string;
  status: string;
  opis: string;
  opis_dodatno: string;
  veliki_opis: string;
}

const emptyForm: SobaForm = { veza_id_smestaj: "", broj_sobe: "", tip: "", status: "1", opis: "", opis_dodatno: "", veliki_opis: "" };

export default function SobePage() {
  const [items, setItems] = useState<Soba[]>([]);
  const [smestaji, setSmestaji] = useState<Smestaj[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [deleteId, setDeleteId] = useState<number | null>(null);
  const [editing, setEditing] = useState<Soba | null>(null);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState<SobaForm>(emptyForm);

  async function load() {
    try {
      const [sobeData, smestajData] = await Promise.all([
        apiFetch<Soba[]>("/sobe"),
        apiFetch<Smestaj[]>("/smestaj"),
      ]);
      setItems(sobeData);
      setSmestaji(smestajData);
    } catch {
      toast.error("Greška pri učitavanju soba");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return items;
    return items.filter((b) =>
      [b.broj_sobe, b.tip, b.opis, b.opis_dodatno, b.veliki_opis, b.smestaj_naziv]
        .some((v) => (v || "").toLowerCase().includes(q))
    );
  }, [items, search]);

  function openAdd() {
    setEditing(null);
    setForm(emptyForm);
    setSheetOpen(true);
  }

  function openEdit(item: Soba) {
    setEditing(item);
    setForm({
      veza_id_smestaj: item.veza_id_smestaj ? String(item.veza_id_smestaj) : "",
      broj_sobe: item.broj_sobe || "",
      tip: item.tip || "",
      status: String(item.status),
      opis: item.opis || "",
      opis_dodatno: item.opis_dodatno || "",
      veliki_opis: item.veliki_opis || "",
    });
    setSheetOpen(true);
  }

  function setField(key: keyof SobaForm, value: string) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function handleSave() {
    if (!form.veza_id_smestaj) { toast.error("Smeštaj je obavezan"); return; }
    setSaving(true);
    try {
      const payload = {
        veza_id_smestaj: Number(form.veza_id_smestaj),
        broj_sobe: form.broj_sobe,
        tip: form.tip,
        status: Number(form.status),
        opis: form.opis,
        opis_dodatno: form.opis_dodatno,
        veliki_opis: form.veliki_opis,
      };
      if (editing) {
        await apiFetch(`/sobe/${editing.id}`, { method: "PUT", body: JSON.stringify(payload) });
        toast.success("Soba ažurirana");
      } else {
        await apiFetch("/sobe", { method: "POST", body: JSON.stringify(payload) });
        toast.success("Soba kreirana");
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
      await apiFetch(`/sobe/${deleteId}`, { method: "DELETE" });
      toast.success("Soba obrisana");
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
          <h1 className="text-2xl font-bold">Sobe</h1>
          <p className="text-muted-foreground text-sm">Sobe po smeštajima</p>
        </div>
        <Button onClick={openAdd}><Plus className="w-4 h-4 mr-2" />Dodaj</Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><DoorOpen className="w-5 h-5" />Sobe</CardTitle>
          <CardDescription>
            Ukupno: <span className="font-semibold text-foreground">{items.length}</span>
            {search.trim() && <> · prikazano: <span className="font-semibold text-foreground">{filtered.length}</span></>}
          </CardDescription>
          <div className="relative max-w-md mt-2">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Pretraga: smeštaj, broj sobe, tip, opis..."
              className="pl-9"
            />
          </div>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Smeštaj</TableHead>
                <TableHead>Broj sobe</TableHead>
                <TableHead>Tip</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Opis</TableHead>
                <TableHead className="w-24 text-right">Akcije</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.length === 0 ? (
                <TableRow><TableCell colSpan={6} className="text-center text-muted-foreground py-8">
                  {search.trim() ? "Nema rezultata za pretragu" : "Nema soba. Kliknite Dodaj da kreirate prvu."}
                </TableCell></TableRow>
              ) : filtered.map((item) => (
                <TableRow key={item.id}>
                  <TableCell className="font-medium">{item.smestaj_naziv || `#${item.veza_id_smestaj}`}</TableCell>
                  <TableCell className="font-mono">{item.broj_sobe || "—"}</TableCell>
                  <TableCell>{item.tip || "—"}</TableCell>
                  <TableCell>
                    <Badge variant={item.status === 1 ? "default" : "secondary"}>
                      {item.status === 1 ? "Aktivan" : "Neaktivan"}
                    </Badge>
                  </TableCell>
                  <TableCell className="max-w-xs truncate text-muted-foreground" title={item.opis || undefined}>
                    {item.opis || "—"}
                  </TableCell>
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
            <SheetTitle>{editing ? "Izmeni sobu" : "Dodaj sobu"}</SheetTitle>
          </SheetHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label>Smeštaj *</Label>
              <Select value={form.veza_id_smestaj} onValueChange={(v) => setField("veza_id_smestaj", v)}>
                <SelectTrigger><SelectValue placeholder="Izaberite smeštaj" /></SelectTrigger>
                <SelectContent>
                  {smestaji.map((s) => (
                    <SelectItem key={s.id} value={String(s.id)}>{s.naziv}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Broj sobe</Label>
              <Input value={form.broj_sobe} onChange={(e) => setField("broj_sobe", e.target.value)} placeholder="npr. 101" />
            </div>
            <div className="space-y-2">
              <Label>Tip</Label>
              <Input value={form.tip} onChange={(e) => setField("tip", e.target.value)} placeholder="npr. 1/2+2" />
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
              <Label>Opis</Label>
              <Textarea value={form.opis} onChange={(e) => setField("opis", e.target.value)} placeholder="Kratak opis sobe" rows={2} />
            </div>
            <div className="space-y-2">
              <Label>Opis dodatno</Label>
              <Textarea value={form.opis_dodatno} onChange={(e) => setField("opis_dodatno", e.target.value)} placeholder="Dodatni opis" rows={2} />
            </div>
            <div className="space-y-2">
              <Label>Veliki opis</Label>
              <Textarea value={form.veliki_opis} onChange={(e) => setField("veliki_opis", e.target.value)} placeholder="Detaljan opis sobe" rows={4} />
            </div>
          </div>
          <SheetFooter>
            <Button variant="outline" onClick={() => setSheetOpen(false)}>Otkaži</Button>
            <Button onClick={handleSave} disabled={saving}>
              {saving ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : null}
              {editing ? "Sačuvaj izmene" : "Dodaj sobu"}
            </Button>
          </SheetFooter>
        </SheetContent>
      </Sheet>

      {/* Delete Confirm */}
      <AlertDialog open={deleteId !== null} onOpenChange={() => setDeleteId(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Obriši sobu?</AlertDialogTitle>
            <AlertDialogDescription>Ova akcija ne može biti poništena. Soba će biti trajno obrisana.</AlertDialogDescription>
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
