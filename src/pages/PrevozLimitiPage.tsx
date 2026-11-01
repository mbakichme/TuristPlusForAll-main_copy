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
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle
} from "@/components/ui/dialog";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle
} from "@/components/ui/alert-dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue
} from "@/components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Plus, Pencil, Trash2, Loader2, Armchair, Search, Wand2 } from "lucide-react";
import { toast } from "sonner";

interface PrevozLimit {
  id: number;
  id_destinacije_prevoza: number;
  destinacija_prevoz_naziv: string | null;
  id_destinacije: number | null;
  id_grupe_termina: number | null;
  datum: string | null; // ISO yyyy-mm-dd
  smer: string;
  limit: number;
  dodatna_mesta: number;
  ukupno: number;
}

interface DestinacijaPrevoz { id: number; naziv: string }

interface FormState {
  id_destinacije_prevoza: string;
  datum: string; // yyyy-mm-dd
  smer: string;
  limit: string;
  dodatna_mesta: string;
}

const NISTA = "nista";
const SMEROVI = ["Odlazak", "Povratak"];
const prazno: FormState = {
  id_destinacije_prevoza: NISTA, datum: "", smer: "Odlazak", limit: "", dodatna_mesta: "0",
};

// Ceo broj; dodatna mesta mogu biti negativna
function celBroj(v: string, negativan: boolean): number | null {
  const t = v.trim();
  if (!/^-?\d+$/.test(t)) return null;
  const n = Number(t);
  if (!negativan && n < 0) return null;
  return n;
}

function datumSr(iso: string | null): string {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-");
  return `${d}.${m}.${y}`;
}

export default function PrevozLimitiPage() {
  const [items, setItems] = useState<PrevozLimit[]>([]);
  const [destinacije, setDestinacije] = useState<DestinacijaPrevoz[]>([]);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<PrevozLimit | null>(null);
  const [form, setForm] = useState<FormState>(prazno);
  const [saving, setSaving] = useState(false);
  const [generisi, setGenerisi] = useState(false);
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

  async function ucitajDestinacije() {
    try {
      setDestinacije(await apiFetch<DestinacijaPrevoz[]>("/destinacija-prevoz"));
    } catch {
      /* prikaz ostaje prazan */
    }
  }

  useEffect(() => {
    const t = setTimeout(() => { void ucitaj(q.trim()); }, 300);
    return () => clearTimeout(t);
  }, [q]);

  useEffect(() => {
    void ucitajDestinacije();
  }, []);

  function otvoriNovi() {
    setEditing(null);
    setForm(prazno);
    setDialogOpen(true);
  }

  function otvoriIzmenu(r: PrevozLimit) {
    setEditing(r);
    setForm({
      id_destinacije_prevoza: String(r.id_destinacije_prevoza),
      datum: r.datum ?? "",
      smer: r.smer,
      limit: String(r.limit),
      dodatna_mesta: String(r.dodatna_mesta),
    });
    setDialogOpen(true);
  }

  async function snimi() {
    if (saving) return;
    if (form.id_destinacije_prevoza === NISTA || !form.datum) {
      toast.error("Izaberite destinaciju i datum");
      return;
    }
    const limit = celBroj(form.limit, false);
    if (limit == null) { toast.error("Limit mora biti ceo broj 0 ili veći"); return; }
    const dodatna = celBroj(form.dodatna_mesta, true);
    if (dodatna == null) { toast.error("Dodatna mesta moraju biti ceo broj (može i negativan)"); return; }

    const body = {
      id_destinacije_prevoza: Number(form.id_destinacije_prevoza),
      datum: form.datum,
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

  async function pokreniGenerisanje() {
    if (generisi) return;
    setGenerisi(true);
    try {
      const r = await apiFetch<{ dodato: number }>(
        "/prevoz-limit/generisi", { method: "POST" },
      );
      toast.success(`Dodato limita: ${r.dodato}`);
      await ucitajDestinacije();
      await ucitaj(q.trim());
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Greška pri generisanju");
    } finally {
      setGenerisi(false);
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

  return (
    <div className="p-4 md:p-6 space-y-4">
      <Card>
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3 space-y-0">
          <CardTitle className="text-base flex items-center gap-2">
            <Armchair className="w-4 h-4" />Limiti prevoz
          </CardTitle>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={pokreniGenerisanje} disabled={generisi}>
              {generisi ? <Loader2 className="w-4 h-4 mr-1 animate-spin" /> : <Wand2 className="w-4 h-4 mr-1" />}
              Generiši iz grupa termina
            </Button>
            <Button size="sm" onClick={otvoriNovi}>
              <Plus className="w-4 h-4 mr-1" />Dodaj limit
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="relative max-w-md">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              aria-label="Pretraga limita"
              placeholder="Pretraga: destinacija-grupa termina, smer…"
              className="pl-8 h-9"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>

          {loading ? (
            <div className="flex justify-center py-10"><Loader2 className="w-5 h-5 animate-spin" /></div>
          ) : items.length === 0 ? (
            <p className="text-sm text-muted-foreground py-8 text-center">
              {q.trim() ? "Nema limita za zadatu pretragu." : "Još nema unetih limita. Kliknite „Generiši iz grupa termina“."}
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Destinacija-Grupa termina</TableHead>
                  <TableHead>Datum</TableHead>
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
                    <TableCell className="max-w-[360px] truncate" title={r.destinacija_prevoz_naziv ?? ""}>
                      {r.destinacija_prevoz_naziv ?? "—"}
                    </TableCell>
                    <TableCell className="tabular-nums">{datumSr(r.datum)}</TableCell>
                    <TableCell><Badge variant="outline">{r.smer}</Badge></TableCell>
                    <TableCell className="text-right tabular-nums">{r.limit}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {r.dodatna_mesta > 0 ? `+${r.dodatna_mesta}` : r.dodatna_mesta}
                    </TableCell>
                    <TableCell className="text-right tabular-nums font-medium">{r.ukupno}</TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-1">
                        <Button size="icon" variant="ghost" className="h-8 w-8"
                          aria-label={`Izmeni limit ${r.destinacija_prevoz_naziv ?? r.id}`}
                          onClick={() => otvoriIzmenu(r)}>
                          <Pencil className="w-4 h-4" />
                        </Button>
                        <Button size="icon" variant="ghost" className="h-8 w-8 text-destructive"
                          aria-label={`Obriši limit ${r.destinacija_prevoz_naziv ?? r.id}`}
                          onClick={() => setDeleteItem(r)}>
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
        <DialogContent className="bg-card sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{editing ? "Izmena limita" : "Novi limit prevoza"}</DialogTitle>
          </DialogHeader>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1 sm:col-span-2">
              <Label className="text-xs">Destinacija-Grupa termina</Label>
              <Select value={form.id_destinacije_prevoza}
                onValueChange={(v) => setForm({ ...form, id_destinacije_prevoza: v })}>
                <SelectTrigger aria-label="Destinacija-Grupa termina" className="h-9">
                  <SelectValue placeholder="Izaberite destinaciju" />
                </SelectTrigger>
                <SelectContent>
                  {destinacije.map((d) => (
                    <SelectItem key={d.id} value={String(d.id)}>{d.naziv}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label className="text-xs" htmlFor="pl-datum">Datum</Label>
              <Input id="pl-datum" type="date" className="h-9" value={form.datum}
                onChange={(e) => setForm({ ...form, datum: e.target.value })} />
            </div>
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
              „{deleteItem?.destinacija_prevoz_naziv} · {datumSr(deleteItem?.datum ?? null)} · {deleteItem?.smer}“ biće trajno obrisan.
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
