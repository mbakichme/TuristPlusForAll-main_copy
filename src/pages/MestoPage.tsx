import { useState, useEffect } from "react";
import type { Mesto, Drzava, Destinacija, PeriodGrupa } from "../types";
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
import {
  Popover, PopoverContent, PopoverTrigger
} from "@/components/ui/popover";
import { Checkbox } from "@/components/ui/checkbox";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Plus, Pencil, Trash2, Loader2, Map, ChevronsUpDown, Search } from "lucide-react";
import { toast } from "sonner";

interface MestoForm {
  naziv: string;
  drzava: string;
  destinacija: string;
  grupe: string[];
  status: string;
  organizator: string;
  predstavnik: string;
  grafik: string;
  cis: string;
}

const emptyForm: MestoForm = { naziv: "", drzava: "", destinacija: "", grupe: [], status: "1", organizator: "", predstavnik: "", grafik: "0", cis: "" };

export default function MestoPage() {
  const [items, setItems] = useState<Mesto[]>([]);
  const [drzave, setDrzave] = useState<Drzava[]>([]);
  const [destinacije, setDestinacije] = useState<Destinacija[]>([]);
  const [grupeDatuma, setGrupeDatuma] = useState<PeriodGrupa[]>([]);
  const [loading, setLoading] = useState(true);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [deleteId, setDeleteId] = useState<number | null>(null);
  const [editing, setEditing] = useState<Mesto | null>(null);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState<MestoForm>(emptyForm);
  const [pretraga, setPretraga] = useState("");
  const q = pretraga.trim().toLowerCase();
  const prikaz = q
    ? items.filter((m) =>
        [m.naziv, m.drzava_naziv, m.destinacija_naziv, m.grupe_nazivi?.join(" "), m.grupa_datuma_naziv]
          .some((v) => (v || "").toLowerCase().includes(q)))
    : items;

  async function load() {
    try {
      const [mestoData, drzData, destData, grupaData] = await Promise.all([
        apiFetch<Mesto[]>("/mesto"),
        apiFetch<Drzava[]>("/drzava"),
        apiFetch<Destinacija[]>("/destinacija"),
        apiFetch<PeriodGrupa[]>("/period-grupa"),
      ]);
      setItems(mestoData);
      setDrzave(drzData);
      setDestinacije(destData);
      setGrupeDatuma(grupaData);
    } catch {
      toast.error("Greška pri učitavanju mesta");
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

  function openEdit(item: Mesto) {
    setEditing(item);
    setForm({
      naziv: item.naziv,
      drzava: item.drzava ? String(item.drzava) : "",
      destinacija: item.destinacija ? String(item.destinacija) : "",
      grupe: item.grupe?.length ? item.grupe.map(String) : item.grupa_datuma ? [String(item.grupa_datuma)] : [],
      status: String(item.status),
      organizator: item.organizator ? String(item.organizator) : "",
      predstavnik: item.predstavnik ? String(item.predstavnik) : "",
      grafik: String(item.grafik),
      cis: item.cis || "",
    });
    setSheetOpen(true);
  }

  function setField(key: keyof MestoForm, value: string) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function handleSave() {
    if (!form.naziv) { toast.error("Naziv je obavezan"); return; }
    setSaving(true);
    try {
      const payload = {
        naziv: form.naziv,
        drzava: form.drzava ? Number(form.drzava) : undefined,
        destinacija: form.destinacija ? Number(form.destinacija) : undefined,
        grupa_datuma: form.grupe.length ? Number(form.grupe[0]) : undefined,
        grupe: form.grupe.map(Number),
        status: Number(form.status),
        organizator: form.organizator ? Number(form.organizator) : undefined,
        predstavnik: form.predstavnik ? Number(form.predstavnik) : undefined,
        grafik: Number(form.grafik),
        cis: form.cis || undefined,
      };
      if (editing) {
        await apiFetch(`/mesto/${editing.id}`, {
          method: "PUT",
          body: JSON.stringify(payload),
        });
        toast.success("Mesto ažurirano");
      } else {
        await apiFetch("/mesto", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        toast.success("Mesto kreirano");
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
      await apiFetch(`/mesto/${deleteId}`, { method: "DELETE" });
      toast.success("Mesto obrisano");
      setDeleteId(null);
      load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Greška");
    }
  }

  // Filter destinacije by selected drzava
  const filteredDestinacije = form.drzava
    ? destinacije.filter((d) => String(d.drzava) === form.drzava)
    : destinacije;

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
          <h1 className="text-2xl font-bold">Mesta</h1>
          <p className="text-muted-foreground text-sm">Upravljanje mestima</p>
        </div>
        <Button onClick={openAdd}><Plus className="w-4 h-4 mr-2" />Dodaj</Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Map className="w-5 h-5" />Mesta</CardTitle>
          <CardDescription>Lista svih mesta</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="relative max-w-sm">
            <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={pretraga}
              onChange={(e) => setPretraga(e.target.value)}
              placeholder="Pretraga po nazivu, državi, destinaciji, grupi…"
              className="h-8 pl-8 text-xs"
            />
          </div>
          <Table className="text-xs">
            <TableHeader>
              <TableRow>
                <TableHead className="h-8 px-2 text-xs">Naziv</TableHead>
                <TableHead className="h-8 px-2 text-xs">Država</TableHead>
                <TableHead className="h-8 px-2 text-xs">Destinacija</TableHead>
                <TableHead className="h-8 px-2 text-xs">Grupe perioda</TableHead>
                <TableHead className="h-8 px-2 text-xs">Status</TableHead>
                <TableHead className="h-8 px-2 text-xs">Grafik</TableHead>
                <TableHead className="h-8 w-20 px-2 text-right text-xs">Akcije</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {prikaz.length === 0 ? (
                <TableRow><TableCell colSpan={7} className="py-6 text-center text-xs text-muted-foreground">{items.length === 0 ? "Nema podataka" : "Nema rezultata pretrage"}</TableCell></TableRow>
              ) : prikaz.map((item) => (
                <TableRow key={item.id}>
                  <TableCell className="px-2 py-1.5 font-medium">{item.naziv}</TableCell>
                  <TableCell className="px-2 py-1.5">{item.drzava_naziv || "—"}</TableCell>
                  <TableCell className="px-2 py-1.5">{item.destinacija_naziv || "—"}</TableCell>
                  <TableCell className="px-2 py-1.5">{item.grupe_nazivi?.length ? item.grupe_nazivi.join(", ") : (item.grupa_datuma_naziv || "—")}</TableCell>
                  <TableCell className="px-2 py-1.5">
                    <Badge variant={item.status === 1 ? "default" : "secondary"} className="text-[10px] px-1.5 py-0">
                      {item.status === 1 ? "Aktivan" : "Neaktivan"}
                    </Badge>
                  </TableCell>
                  <TableCell className="px-2 py-1.5">
                    <Badge variant={item.grafik === 1 ? "default" : "outline"} className="text-[10px] px-1.5 py-0">
                      {item.grafik === 1 ? "Da" : "Ne"}
                    </Badge>
                  </TableCell>
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
            <SheetTitle>{editing ? "Izmeni mesto" : "Dodaj mesto"}</SheetTitle>
          </SheetHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label>Naziv *</Label>
              <Input value={form.naziv} onChange={(e) => setField("naziv", e.target.value)} placeholder="Unesite naziv" />
            </div>
            <div className="space-y-2">
              <Label>Država</Label>
              <Select value={form.drzava} onValueChange={(v) => { setField("drzava", v); setField("destinacija", ""); }}>
                <SelectTrigger><SelectValue placeholder="Izaberite državu" /></SelectTrigger>
                <SelectContent>
                  {drzave.map((d) => (
                    <SelectItem key={d.id} value={String(d.id)}>{d.naziv}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Destinacija</Label>
              <Select value={form.destinacija} onValueChange={(v) => setField("destinacija", v)}>
                <SelectTrigger><SelectValue placeholder="Izaberite destinaciju" /></SelectTrigger>
                <SelectContent>
                  {filteredDestinacije.map((d) => (
                    <SelectItem key={d.id} value={String(d.id)}>{d.naziv}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Grupe perioda</Label>
              <Popover>
                <PopoverTrigger asChild>
                  <Button variant="outline" className="w-full justify-between font-normal">
                    <span className="truncate">
                      {form.grupe.length === 0
                        ? "Izaberite grupe perioda"
                        : form.grupe.length === 1
                          ? (grupeDatuma.find((g) => String(g.id) === form.grupe[0])?.naziv ?? "1 grupa")
                          : `${form.grupe.length} grupe`}
                    </span>
                    <ChevronsUpDown className="w-4 h-4 opacity-50 shrink-0" />
                  </Button>
                </PopoverTrigger>
                <PopoverContent className="w-72 p-2" align="start">
                  <div className="max-h-64 overflow-y-auto">
                    {grupeDatuma.map((g) => {
                      const sel = form.grupe.includes(String(g.id));
                      return (
                        <label
                          key={g.id}
                          className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm cursor-pointer hover:bg-muted"
                        >
                          <Checkbox
                            checked={sel}
                            onCheckedChange={() =>
                              setForm((f) => ({
                                ...f,
                                grupe: sel
                                  ? f.grupe.filter((x) => x !== String(g.id))
                                  : [...f.grupe, String(g.id)],
                              }))
                            }
                          />
                          {g.naziv}
                        </label>
                      );
                    })}
                    {grupeDatuma.length === 0 && (
                      <p className="px-2 py-1.5 text-sm text-muted-foreground">Nema definisanih grupa</p>
                    )}
                  </div>
                </PopoverContent>
              </Popover>
              {form.grupe.length > 0 && (
                <p className="text-xs text-muted-foreground leading-snug">
                  {form.grupe
                    .map((id) => grupeDatuma.find((g) => String(g.id) === id)?.naziv)
                    .filter(Boolean)
                    .join(", ")}
                </p>
              )}
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
              <Label>Grafik</Label>
              <Select value={form.grafik} onValueChange={(v) => setField("grafik", v)}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="1">Da</SelectItem>
                  <SelectItem value="0">Ne</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>CIS</Label>
              <Input value={form.cis} onChange={(e) => setField("cis", e.target.value)} placeholder="CIS oznaka" />
            </div>
          </div>
          <SheetFooter>
            <Button variant="outline" onClick={() => setSheetOpen(false)}>Otkaži</Button>
            <Button onClick={handleSave} disabled={saving}>
              {saving ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : null}
              {editing ? "Sačuvaj izmene" : "Dodaj mesto"}
            </Button>
          </SheetFooter>
        </SheetContent>
      </Sheet>

      {/* Delete Confirm */}
      <AlertDialog open={deleteId !== null} onOpenChange={() => setDeleteId(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Obriši mesto?</AlertDialogTitle>
            <AlertDialogDescription>Ova akcija ne može biti poništena. Mesto će biti trajno obrisano.</AlertDialogDescription>
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
