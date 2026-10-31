import { useState, useEffect } from "react";
import { apiFetch } from "../lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow
} from "@/components/ui/table";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle
} from "@/components/ui/dialog";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle
} from "@/components/ui/alert-dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue
} from "@/components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Plus, Pencil, Trash2, Loader2, Bus, Search } from "lucide-react";
import { toast } from "sonner";

interface PrevozLimit {
  id: number;
  naziv: string;
  destinacija_id: number | null;
  destinacija_naziv: string | null;
  mesto_id: number | null;
  mesto_naziv: string | null;
  grupa_datuma_id: number | null;
  grupa_datuma_naziv: string | null;
  smer: string;
  limit: number;
  dodatna_mesta: number;
  ukupno: number;
}

interface Opcija { id: number; naziv: string }

interface FormState {
  naziv: string;
  destinacija_id: string;
  mesto_id: string;
  grupa_datuma_id: string;
  smer: string;
  limit: string;
  dodatna_mesta: string;
}

const NISTA = "nista";
const SMEROVI = ["Polazak", "Povratak"];
const prazno: FormState = {
  naziv: "", destinacija_id: NISTA, mesto_id: NISTA, grupa_datuma_id: NISTA,
  smer: "Polazak", limit: "", dodatna_mesta: "0",
};

// Ceo broj (dozvoljen minus za dodatna mesta); vraća null ako nije validan
function celBroj(v: string, { negativan }: { negativan: boolean }): number | null {
  const t = v.trim();
  if (!/^-?\d+$/.test(t)) return null;
  const n = Number(t);
  if (!negativan && n < 0) return null;
  return n;
}

export default function PrevozLimitiPage() {
  const [items, setItems] = useState<PrevozLimit[]>([]);
  const [destinacije, setDestinacije] = useState<Opcija[]>([]);
  const [mesta, setMesta] = useState<Opcija[]>([]);
  const [grupe, setGrupe] = useState<Opcija[]>([]);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<PrevozLimit | null>(null);
  const [form, setForm] = useState<FormState>(prazno);
  const [saving, setSaving] = useState(false);
  const [deleteItem, setDeleteItem] = useState<PrevozLimit | null>(null);
  const [deleting, setDeleting] = useState(false);

  async function ucitaj(upit: string) {
    try {
      const data = await apiFetch<PrevozLimit[]>(
        `/prevoz-limit${upit ? `?q=${encodeURIComponent(upit)}` : ""}`,
      );
      setItems(data);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Greška pri učitavanju");
    } finally {
      setLoading(false);
    }
  }

  // Pretraga po svim poljima (uključujući mesto) — debounce 300ms
  useEffect(() => {
    const t = setTimeout(() => { void ucitaj(q.trim()); }, 300);
    return () => clearTimeout(t);
  }, [q]);

  useEffect(() => {
    apiFetch<Opcija[]>("/destinacija").then(setDestinacije).catch(() => {});
    apiFetch<Opcija[]>("/mesto").then(setMesta).catch(() => {});
    apiFetch<Opcija[]>("/period-grupa").then(setGrupe).catch(() => {});
  }, []);

  function otvoriNovi() {
    setEditing(null);
    setForm(prazno);
    setDialogOpen(true);
  }

  function otvoriIzmenu(r: PrevozLimit) {
    setEditing(r);
    setForm({
      naziv: r.naziv,
      destinacija_id: r.destinacija_id != null ? String(r.destinacija_id) : NISTA,
      mesto_id: r.mesto_id != null ? String(r.mesto_id) : NISTA,
      grupa_datuma_id: r.grupa_datuma_id != null ? String(r.grupa_datuma_id) : NISTA,
      smer: r.smer,
      limit: String(r.limit),
      dodatna_mesta: String(r.dodatna_mesta),
    });
    setDialogOpen(true);
  }

  async function snimi() {
    if (saving) return;
    const naziv = form.naziv.trim();
    if (!naziv) { toast.error("Naziv je obavezan"); return; }
    const limit = celBroj(form.limit, { negativan: false });
    if (limit == null) { toast.error("Limit mora biti ceo broj 0 ili veći"); return; }
    const dodatna = celBroj(form.dodatna_mesta, { negativan: true });
    if (dodatna == null) { toast.error("Dodatna mesta moraju biti ceo broj (može i negativan)"); return; }

    const body = {
      naziv,
      destinacija_id: form.destinacija_id === NISTA ? null : Number(form.destinacija_id),
      mesto_id: form.mesto_id === NISTA ? null : Number(form.mesto_id),
      grupa_datuma_id: form.grupa_datuma_id === NISTA ? null : Number(form.grupa_datuma_id),
      smer: form.smer,
      limit,
      dodatna_mesta: dodatna,
    };
    setSaving(true);
    try {
      if (editing) {
        await apiFetch(`/prevoz-limit/${editing.id}`, { method: "PUT", body: JSON.stringify(body) });
        toast.success("Limit je sačuvan");
      } else {
        await apiFetch("/prevoz-limit", { method: "POST", body: JSON.stringify(body) });
        toast.success("Limit je dodat");
      }
      setDialogOpen(false);
      await ucitaj(q.trim());
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Greška pri čuvanju");
    } finally {
      setSaving(false);
    }
  }

  async function obrisi() {
    if (!deleteItem || deleting) return;
    setDeleting(true);
    try {
      await apiFetch(`/prevoz-limit/${deleteItem.id}`, { method: "DELETE" });
      toast.success("Limit je obrisan");
      setDeleteItem(null);
      await ucitaj(q.trim());
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Greška pri brisanju");
    } finally {
      setDeleting(false);
    }
  }

  function Izbor({ label, value, onChange, opcije, placeholder }: {
    label: string; value: string; onChange: (v: string) => void;
    opcije: Opcija[]; placeholder: string;
  }) {
    return (
      <div className="space-y-1">
        <Label className="text-xs">{label}</Label>
        <Select value={value} onValueChange={onChange}>
          <SelectTrigger aria-label={label} className="h-9"><SelectValue placeholder={placeholder} /></SelectTrigger>
          <SelectContent>
            <SelectItem value={NISTA}>— nije izabrano —</SelectItem>
            {opcije.map((o) => (
              <SelectItem key={o.id} value={String(o.id)}>{o.naziv}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    );
  }

  return (
    <div className="p-4 md:p-6 space-y-4">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-4 space-y-0">
          <CardTitle className="text-base flex items-center gap-2">
            <Bus className="w-4 h-4" />Limiti prevoz
          </CardTitle>
          <Button size="sm" onClick={otvoriNovi}>
            <Plus className="w-4 h-4 mr-1" />Dodaj limit
          </Button>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="relative max-w-md">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              aria-label="Pretraga limita"
              placeholder="Pretraga: naziv, destinacija, mesto, grupa, smer…"
              className="pl-8 h-9"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>

          {loading ? (
            <div className="flex justify-center py-10"><Loader2 className="w-5 h-5 animate-spin" /></div>
          ) : items.length === 0 ? (
            <p className="text-sm text-muted-foreground py-8 text-center">
              {q.trim() ? "Nema limita za zadatu pretragu." : "Još nema unetih limita."}
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Naziv</TableHead>
                  <TableHead>Destinacija</TableHead>
                  <TableHead>Mesto</TableHead>
                  <TableHead>Grupa termina</TableHead>
                  <TableHead>Smer</TableHead>
                  <TableHead className="text-right">Limit</TableHead>
                  <TableHead className="text-right">Dodatna</TableHead>
                  <TableHead className="text-right">Ukupno</TableHead>
                  <TableHead className="text-right">Akcije</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell className="font-medium">{r.naziv}</TableCell>
                    <TableCell>{r.destinacija_naziv ?? "—"}</TableCell>
                    <TableCell>{r.mesto_naziv ?? "—"}</TableCell>
                    <TableCell>{r.grupa_datuma_naziv ?? "—"}</TableCell>
                    <TableCell><Badge variant="outline">{r.smer}</Badge></TableCell>
                    <TableCell className="text-right tabular-nums">{r.limit}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {r.dodatna_mesta > 0 ? `+${r.dodatna_mesta}` : r.dodatna_mesta}
                    </TableCell>
                    <TableCell className="text-right tabular-nums font-semibold">{r.ukupno}</TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-1">
                        <Button variant="ghost" size="icon" className="h-8 w-8" aria-label={`Izmeni limit ${r.naziv}`} onClick={() => otvoriIzmenu(r)}>
                          <Pencil className="w-4 h-4" />
                        </Button>
                        <Button variant="ghost" size="icon" className="h-8 w-8 text-destructive" aria-label={`Obriši limit ${r.naziv}`} onClick={() => setDeleteItem(r)}>
                          <Trash2 className="w-4 h-4" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Dialog open={dialogOpen} onOpenChange={(o) => { if (!saving) setDialogOpen(o); }}>
        <DialogContent className="sm:max-w-xl bg-card">
          <DialogHeader>
            <DialogTitle>{editing ? "Izmena limita prevoza" : "Novi limit prevoza"}</DialogTitle>
            <DialogDescription>Broj mesta u autobusu za izabrani smer i termin.</DialogDescription>
          </DialogHeader>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="space-y-1 sm:col-span-2">
              <Label className="text-xs" htmlFor="pl-naziv">Naziv</Label>
              <Input id="pl-naziv" className="h-9" maxLength={200} value={form.naziv}
                onChange={(e) => setForm({ ...form, naziv: e.target.value })} />
            </div>
            <Izbor label="Destinacija" placeholder="Izaberite destinaciju" value={form.destinacija_id}
              onChange={(v) => setForm({ ...form, destinacija_id: v })} opcije={destinacije} />
            <Izbor label="Mesto" placeholder="Izaberite mesto" value={form.mesto_id}
              onChange={(v) => setForm({ ...form, mesto_id: v })} opcije={mesta} />
            <Izbor label="Grupa termina" placeholder="Izaberite grupu" value={form.grupa_datuma_id}
              onChange={(v) => setForm({ ...form, grupa_datuma_id: v })} opcije={grupe} />
            <div className="space-y-1">
              <Label className="text-xs">Smer</Label>
              <Select value={form.smer} onValueChange={(v) => setForm({ ...form, smer: v })}>
                <SelectTrigger aria-label="Smer" className="h-9"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {SMEROVI.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label className="text-xs" htmlFor="pl-limit">Limit (mesta)</Label>
              <Input id="pl-limit" inputMode="numeric" className="h-9" value={form.limit}
                onChange={(e) => setForm({ ...form, limit: e.target.value })} />
            </div>
            <div className="space-y-1">
              <Label className="text-xs" htmlFor="pl-dodatna">Dodatna mesta (+ ili −)</Label>
              <Input id="pl-dodatna" inputMode="numeric" className="h-9" value={form.dodatna_mesta}
                onChange={(e) => setForm({ ...form, dodatna_mesta: e.target.value })} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)} disabled={saving}>Odustani</Button>
            <Button onClick={snimi} disabled={saving}>
              {saving && <Loader2 className="w-4 h-4 mr-1 animate-spin" />}Sačuvaj
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog open={deleteItem !== null} onOpenChange={(o) => { if (!o && !deleting) setDeleteItem(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Obrisati limit?</AlertDialogTitle>
            <AlertDialogDescription>
              „{deleteItem?.naziv}“ ({deleteItem?.smer}) biće trajno obrisan.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>Odustani</AlertDialogCancel>
            <AlertDialogAction onClick={(e) => { e.preventDefault(); void obrisi(); }} disabled={deleting}>
              Obriši
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
