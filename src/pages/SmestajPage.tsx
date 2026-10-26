import { useState, useEffect } from "react";
import type { Smestaj, Drzava, Destinacija, TipSmestaja, Mesto, PeriodGrupa } from "../types";
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
import { Plus, Pencil, Trash2, Loader2, BedDouble, Search } from "lucide-react";
import { toast } from "sonner";

interface SmestajForm {
  naziv: string;
  drzava: string;
  destinacija: string;
  mesto: string;
  tip_smestaja: string;
  grupa_datuma: string;
  status: string;
  organizator: string;
  predstavnik: string;
  grafik: string;
  granica_chd: string;
  prima_decu: string;
  ne_prima_ispod_godina: string;
}

const emptyForm: SmestajForm = { naziv: "", drzava: "", destinacija: "", mesto: "", tip_smestaja: "", grupa_datuma: "", status: "1", organizator: "", predstavnik: "", grafik: "0", granica_chd: "6.99", prima_decu: "1", ne_prima_ispod_godina: "" };

export default function SmestajPage() {
  const [items, setItems] = useState<Smestaj[]>([]);
  const [drzave, setDrzave] = useState<Drzava[]>([]);
  const [destinacije, setDestinacije] = useState<Destinacija[]>([]);
  const [mesta, setMesta] = useState<Mesto[]>([]);
  const [tipoviSmestaja, setTipoviSmestaja] = useState<TipSmestaja[]>([]);
  const [grupeDatuma, setGrupeDatuma] = useState<PeriodGrupa[]>([]);
  const [loading, setLoading] = useState(true);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [deleteId, setDeleteId] = useState<number | null>(null);
  const [editing, setEditing] = useState<Smestaj | null>(null);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState<SmestajForm>(emptyForm);
  const [pretraga, setPretraga] = useState("");
  const q = pretraga.trim().toLowerCase();
  const prikaz = q
    ? items.filter((s) =>
        [s.naziv, s.drzava_naziv, s.destinacija_naziv, s.tip_smestaja_naziv, s.grupa_datuma_naziv]
          .some((v) => (v || "").toLowerCase().includes(q)))
    : items;

  async function load() {
    try {
      const [smestajData, drzData, destData, mestoData, tipData, grupeData] = await Promise.all([
        apiFetch<Smestaj[]>("/smestaj"),
        apiFetch<Drzava[]>("/drzava"),
        apiFetch<Destinacija[]>("/destinacija"),
        apiFetch<Mesto[]>("/mesto"),
        apiFetch<TipSmestaja[]>("/tip-smestaja"),
        apiFetch<PeriodGrupa[]>("/period-grupa"),
      ]);
      setItems(smestajData);
      setDrzave(drzData);
      setDestinacije(destData);
      setMesta(mestoData);
      setTipoviSmestaja(tipData);
      setGrupeDatuma(grupeData);
    } catch {
      toast.error("Greška pri učitavanju smeštaja");
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

  function openEdit(item: Smestaj) {
    setEditing(item);
    setForm({
      naziv: item.naziv,
      drzava: item.drzava ? String(item.drzava) : "",
      destinacija: item.destinacija ? String(item.destinacija) : "",
      mesto: item.mesto ? String(item.mesto) : "",
      tip_smestaja: item.tip_smestaja ? String(item.tip_smestaja) : "",
      grupa_datuma: item.grupa_datuma ? String(item.grupa_datuma) : "",
      status: String(item.status),
      organizator: item.organizator ? String(item.organizator) : "",
      predstavnik: item.predstavnik ? String(item.predstavnik) : "",
      grafik: String(item.grafik),
      granica_chd: String(item.granica_chd ?? 6.99),
      prima_decu: item.prima_decu === false ? "0" : "1",
      ne_prima_ispod_godina: item.ne_prima_ispod_godina != null ? String(item.ne_prima_ispod_godina) : "",
    });
    setSheetOpen(true);
  }

  function setField(key: keyof SmestajForm, value: string) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function handleSave() {
    if (!form.naziv) { toast.error("Naziv je obavezan"); return; }
    const granica = Number(form.granica_chd.replace(",", "."));
    if (!Number.isFinite(granica) || granica <= 0 || granica >= 18) { toast.error("Granica CHD mora biti broj između 0 i 18"); return; }
    const primaDecu = form.prima_decu === "1";
    const godineDeteta = form.ne_prima_ispod_godina.trim();
    let ispod: number | null = null;
    if (!primaDecu) {
      if (godineDeteta === "") { toast.error("Unesite godine ispod kojih smeštaj ne prima decu"); return; }
      ispod = Number(godineDeteta);
      if (!Number.isInteger(ispod) || ispod < 0 || ispod > 18) { toast.error("Godine moraju biti ceo broj između 0 i 18"); return; }
    }
    setSaving(true);
    try {
      const payload = {
        naziv: form.naziv,
        drzava: form.drzava ? Number(form.drzava) : undefined,
        destinacija: form.destinacija ? Number(form.destinacija) : undefined,
        mesto: form.mesto ? Number(form.mesto) : undefined,
        tip_smestaja: form.tip_smestaja ? Number(form.tip_smestaja) : undefined,
        grupa_datuma: form.grupa_datuma ? Number(form.grupa_datuma) : undefined,
        status: Number(form.status),
        organizator: form.organizator ? Number(form.organizator) : undefined,
        predstavnik: form.predstavnik ? Number(form.predstavnik) : undefined,
        grafik: Number(form.grafik),
        granica_chd: granica,
        prima_decu: primaDecu,
        ne_prima_ispod_godina: ispod,
      };
      if (editing) {
        await apiFetch(`/smestaj/${editing.id}`, {
          method: "PUT",
          body: JSON.stringify(payload),
        });
        toast.success("Smeštaj ažuriran");
      } else {
        await apiFetch("/smestaj", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        toast.success("Smeštaj kreiran");
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
      await apiFetch(`/smestaj/${deleteId}`, { method: "DELETE" });
      toast.success("Smeštaj obrisan");
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
          <h1 className="text-2xl font-bold">Smeštaj</h1>
          <p className="text-muted-foreground text-sm">Upravljanje smeštajem</p>
        </div>
        <Button onClick={openAdd}><Plus className="w-4 h-4 mr-2" />Dodaj</Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><BedDouble className="w-5 h-5" />Smeštaj</CardTitle>
          <CardDescription>Lista svih smeštaja</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="relative max-w-sm">
            <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={pretraga}
              onChange={(e) => setPretraga(e.target.value)}
              placeholder="Pretraga po nazivu, državi, destinaciji, tipu, grupi…"
              className="h-8 pl-8 text-xs"
            />
          </div>
          <Table className="text-xs">
            <TableHeader>
              <TableRow>
                <TableHead className="h-8 px-2 text-xs">Naziv</TableHead>
                <TableHead className="h-8 px-2 text-xs">Država</TableHead>
                <TableHead className="h-8 px-2 text-xs">Destinacija</TableHead>
                <TableHead className="h-8 px-2 text-xs">Tip smeštaja</TableHead>
                <TableHead className="h-8 px-2 text-xs">Grupa perioda</TableHead>
                <TableHead className="h-8 px-2 text-xs">Status</TableHead>
                <TableHead className="h-8 px-2 text-xs">Grafik</TableHead>
                <TableHead className="h-8 px-2 text-xs">Granica CHD</TableHead>
                <TableHead className="h-8 px-2 text-xs">Prima decu</TableHead>
                <TableHead className="h-8 w-20 px-2 text-right text-xs">Akcije</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {prikaz.length === 0 ? (
                <TableRow><TableCell colSpan={10} className="py-6 text-center text-xs text-muted-foreground">{items.length === 0 ? "Nema podataka" : "Nema rezultata pretrage"}</TableCell></TableRow>
              ) : prikaz.map((item) => (
                <TableRow key={item.id}>
                  <TableCell className="px-2 py-1.5 font-medium">{item.naziv}</TableCell>
                  <TableCell className="px-2 py-1.5">{item.drzava_naziv || "—"}</TableCell>
                  <TableCell className="px-2 py-1.5">{item.destinacija_naziv || "—"}</TableCell>
                  <TableCell className="px-2 py-1.5">{item.tip_smestaja_naziv || "—"}</TableCell>
                  <TableCell className="px-2 py-1.5">{item.grupa_datuma_naziv || "—"}</TableCell>
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
                  <TableCell className="px-2 py-1.5">{item.granica_chd ?? 6.99}</TableCell>
                  <TableCell className="px-2 py-1.5">
                    {item.prima_decu === false ? `NE (ispod ${item.ne_prima_ispod_godina} god.)` : "DA"}
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
            <SheetTitle>{editing ? "Izmeni smeštaj" : "Dodaj smeštaj"}</SheetTitle>
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
              <Label>Destinacija</Label>
              <Select value={form.destinacija} onValueChange={(v) => setField("destinacija", v)}>
                <SelectTrigger><SelectValue placeholder="Izaberite destinaciju" /></SelectTrigger>
                <SelectContent>
                  {destinacije.map((d) => (
                    <SelectItem key={d.id} value={String(d.id)}>{d.naziv}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Mesto</Label>
              <Select value={form.mesto} onValueChange={(v) => setField("mesto", v)}>
                <SelectTrigger><SelectValue placeholder="Izaberite mesto" /></SelectTrigger>
                <SelectContent>
                  {mesta.map((m) => (
                    <SelectItem key={m.id} value={String(m.id)}>{m.naziv}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Tip smeštaja</Label>
              <Select value={form.tip_smestaja} onValueChange={(v) => setField("tip_smestaja", v)}>
                <SelectTrigger><SelectValue placeholder="Izaberite tip" /></SelectTrigger>
                <SelectContent>
                  {tipoviSmestaja.map((t) => (
                    <SelectItem key={t.id} value={String(t.id)}>{t.naziv}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Grupa perioda</Label>
              <Select value={form.grupa_datuma} onValueChange={(v) => setField("grupa_datuma", v)}>
                <SelectTrigger><SelectValue placeholder="Izaberite grupu perioda" /></SelectTrigger>
                <SelectContent>
                  {grupeDatuma.map((g) => (
                    <SelectItem key={g.id} value={String(g.id)}>{g.naziv}</SelectItem>
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
              <Label>Granica godina za CHD</Label>
              <Input inputMode="decimal" value={form.granica_chd} onChange={(e) => setField("granica_chd", e.target.value)} placeholder="6.99" />
            </div>
            <div className="space-y-2">
              <Label>Prima decu</Label>
              <Select value={form.prima_decu} onValueChange={(v) => setField("prima_decu", v)}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="1">DA</SelectItem>
                  <SelectItem value="0">NE</SelectItem>
                </SelectContent>
              </Select>
            </div>
            {form.prima_decu === "0" && (
              <div className="space-y-2">
                <Label>Ne prima decu mlađu od (godina)</Label>
                <Input inputMode="numeric" value={form.ne_prima_ispod_godina} onChange={(e) => setField("ne_prima_ispod_godina", e.target.value)} placeholder="npr. 5" />
              </div>
            )}
          </div>
          <SheetFooter>
            <Button variant="outline" onClick={() => setSheetOpen(false)}>Otkaži</Button>
            <Button onClick={handleSave} disabled={saving}>
              {saving ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : null}
              {editing ? "Sačuvaj izmene" : "Dodaj smeštaj"}
            </Button>
          </SheetFooter>
        </SheetContent>
      </Sheet>

      {/* Delete Confirm */}
      <AlertDialog open={deleteId !== null} onOpenChange={() => setDeleteId(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Obriši smeštaj?</AlertDialogTitle>
            <AlertDialogDescription>Ova akcija ne može biti poništena. Smeštaj će biti trajno obrisan.</AlertDialogDescription>
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
