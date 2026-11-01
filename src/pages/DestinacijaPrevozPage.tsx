import { useState, useEffect, useMemo } from "react";
import { apiFetch } from "../lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
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
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Plus, Pencil, Trash2, Loader2, Bus } from "lucide-react";
import { toast } from "sonner";

interface GrupaVeza { id: number; naziv: string }
interface DestinacijaPrevoz {
  id: number;
  id_destinacije: number;
  naziv: string;
  grupe: GrupaVeza[];
}
interface Destinacija { id: number; naziv: string }
interface GrupaOpcija { id: number; naziv: string; zauzeta: boolean }

const NISTA = "nista";

export default function DestinacijaPrevozPage() {
  const [items, setItems] = useState<DestinacijaPrevoz[]>([]);
  const [destinacije, setDestinacije] = useState<Destinacija[]>([]);
  const [loading, setLoading] = useState(true);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<DestinacijaPrevoz | null>(null);
  const [izabranaDest, setIzabranaDest] = useState<string>(NISTA);
  const [grupe, setGrupe] = useState<GrupaOpcija[]>([]);
  const [grupeUcitavaju, setGrupeUcitavaju] = useState(false);
  const [izabrane, setIzabrane] = useState<Set<number>>(new Set());
  const [saving, setSaving] = useState(false);

  const [deleteItem, setDeleteItem] = useState<DestinacijaPrevoz | null>(null);
  const [deleting, setDeleting] = useState(false);

  async function ucitaj() {
    try {
      setItems(await apiFetch<DestinacijaPrevoz[]>("/destinacija-prevoz"));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Greška pri učitavanju");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void ucitaj();
    apiFetch<Destinacija[]>("/destinacija").then(setDestinacije).catch(() => {});
  }, []);

  // Destinacije koje već imaju destinaciju prevoza ne nude se pri kreiranju
  const destinacijeZaIzbor = useMemo(() => {
    const zauzete = new Set(items.map((i) => i.id_destinacije));
    return destinacije.filter((d) => !zauzete.has(d.id));
  }, [destinacije, items]);

  async function ucitajGrupe(idDest: number, dpId: number | null) {
    setGrupeUcitavaju(true);
    try {
      const upit = `id_destinacije=${idDest}${dpId != null ? `&dp_id=${dpId}` : ""}`;
      const data = await apiFetch<GrupaOpcija[]>(`/destinacija-prevoz/grupe?${upit}`);
      setGrupe(data);
      return data;
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Greška pri učitavanju grupa termina");
      setGrupe([]);
      return [];
    } finally {
      setGrupeUcitavaju(false);
    }
  }

  function otvoriNovi() {
    setEditing(null);
    setIzabranaDest(NISTA);
    setGrupe([]);
    setIzabrane(new Set());
    setDialogOpen(true);
  }

  async function otvoriIzmenu(r: DestinacijaPrevoz) {
    setEditing(r);
    setIzabranaDest(String(r.id_destinacije));
    setIzabrane(new Set(r.grupe.map((g) => g.id)));
    setDialogOpen(true);
    await ucitajGrupe(r.id_destinacije, r.id);
  }

  async function izaberiDestinaciju(v: string) {
    setIzabranaDest(v);
    setIzabrane(new Set());
    setGrupe([]);
    if (v !== NISTA) await ucitajGrupe(Number(v), null);
  }

  const dostupne = useMemo(() => grupe.filter((g) => !g.zauzeta), [grupe]);
  const sveIzabrane = dostupne.length > 0 && dostupne.every((g) => izabrane.has(g.id));

  function prebaciGrupu(id: number, on: boolean) {
    setIzabrane((prev) => {
      const next = new Set(prev);
      if (on) next.add(id); else next.delete(id);
      return next;
    });
  }

  function prebaciSve(on: boolean) {
    setIzabrane(on ? new Set(dostupne.map((g) => g.id)) : new Set());
  }

  async function snimi() {
    if (saving) return;
    if (!editing && izabranaDest === NISTA) {
      toast.error("Izaberite destinaciju");
      return;
    }
    if (izabrane.size === 0) {
      toast.error("Izaberite bar jednu grupu termina");
      return;
    }
    setSaving(true);
    try {
      const grupeIds = Array.from(izabrane);
      if (editing) {
        await apiFetch(`/destinacija-prevoz/${editing.id}`, {
          method: "PUT", body: JSON.stringify({ grupe: grupeIds }),
        });
        toast.success("Destinacija prevoza je sačuvana");
      } else {
        await apiFetch("/destinacija-prevoz", {
          method: "POST",
          body: JSON.stringify({ id_destinacije: Number(izabranaDest), grupe: grupeIds }),
        });
        toast.success("Destinacija prevoza je dodata");
      }
      setDialogOpen(false);
      await ucitaj();
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
      const r = await apiFetch<{ broj_limita: number }>(
        `/destinacija-prevoz/${deleteItem.id}`, { method: "DELETE" },
      );
      toast.success(`Destinacija prevoza je obrisana (limita: ${r.broj_limita})`);
      setDeleteItem(null);
      await ucitaj();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Greška pri brisanju");
    } finally {
      setDeleting(false);
    }
  }

  const nazivIzabrane = editing?.naziv
    ?? destinacije.find((d) => String(d.id) === izabranaDest)?.naziv
    ?? "";

  return (
    <div className="p-4 md:p-6 space-y-4">
      <Card>
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3 space-y-0">
          <CardTitle className="text-base flex items-center gap-2">
            <Bus className="w-4 h-4" />Destinacija prevoz
          </CardTitle>
          <Button size="sm" onClick={otvoriNovi} disabled={!loading && destinacijeZaIzbor.length === 0}>
            <Plus className="w-4 h-4 mr-1" />Dodaj destinaciju prevoza
          </Button>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="flex justify-center py-10"><Loader2 className="w-5 h-5 animate-spin" /></div>
          ) : items.length === 0 ? (
            <p className="text-sm text-muted-foreground py-8 text-center">
              Još nema destinacija prevoza. Kliknite „Dodaj destinaciju prevoza“.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Destinacija</TableHead>
                  <TableHead>Grupe termina</TableHead>
                  <TableHead className="text-right">Akcije</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell className="font-medium">{r.naziv}</TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        {r.grupe.length === 0 && <span className="text-muted-foreground">—</span>}
                        {r.grupe.map((g) => (
                          <Badge key={g.id} variant="secondary">{g.naziv}</Badge>
                        ))}
                      </div>
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-1">
                        <Button size="icon" variant="ghost" className="h-8 w-8"
                          aria-label={`Izmeni destinaciju prevoza ${r.naziv}`}
                          onClick={() => void otvoriIzmenu(r)}>
                          <Pencil className="w-4 h-4" />
                        </Button>
                        <Button size="icon" variant="ghost" className="h-8 w-8 text-destructive"
                          aria-label={`Obriši destinaciju prevoza ${r.naziv}`}
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
            <DialogTitle>{editing ? "Izmena destinacije prevoza" : "Nova destinacija prevoza"}</DialogTitle>
          </DialogHeader>

          <div className="space-y-4">
            <div className="space-y-1">
              <Label className="text-xs">Destinacija</Label>
              {editing ? (
                <p className="text-sm font-medium">{editing.naziv}</p>
              ) : (
                <Select value={izabranaDest} onValueChange={(v) => void izaberiDestinaciju(v)}>
                  <SelectTrigger aria-label="Destinacija" className="h-9">
                    <SelectValue placeholder="Izaberite destinaciju" />
                  </SelectTrigger>
                  <SelectContent>
                    {destinacijeZaIzbor.map((d) => (
                      <SelectItem key={d.id} value={String(d.id)}>{d.naziv}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label className="text-xs">Grupe termina</Label>
                {grupe.length > 0 && (
                  <div className="flex items-center gap-2">
                    <Checkbox id="dp-sve" checked={sveIzabrane} disabled={dostupne.length === 0}
                      onCheckedChange={(v) => prebaciSve(v === true)} />
                    <Label htmlFor="dp-sve" className="text-xs">Sve</Label>
                  </div>
                )}
              </div>

              {nazivIzabrane === "" ? (
                <p className="text-xs text-muted-foreground">Izaberite destinaciju da se prikažu grupe termina.</p>
              ) : grupeUcitavaju ? (
                <div className="flex justify-center py-6"><Loader2 className="w-5 h-5 animate-spin" /></div>
              ) : grupe.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  Za ovu destinaciju nema grupa termina (grupa se vezuje preko mesta).
                </p>
              ) : (
                <div className="grid gap-2 sm:grid-cols-2 max-h-[50vh] overflow-y-auto pr-1">
                  {grupe.map((g) => (
                    <div key={g.id}
                      className={`flex items-center gap-2 rounded-md border px-3 py-2 ${g.zauzeta ? "opacity-50" : ""}`}>
                      <Checkbox id={`dp-g-${g.id}`} checked={izabrane.has(g.id)} disabled={g.zauzeta}
                        onCheckedChange={(v) => prebaciGrupu(g.id, v === true)} />
                      <Label htmlFor={`dp-g-${g.id}`} className="text-sm leading-tight">
                        {g.naziv}
                        {g.zauzeta && <span className="block text-xs text-muted-foreground">vezana za drugu destinaciju prevoza</span>}
                      </Label>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)} disabled={saving}>Odustani</Button>
            <Button onClick={snimi} disabled={saving || grupeUcitavaju}>
              {saving && <Loader2 className="w-4 h-4 mr-1 animate-spin" />}Sačuvaj
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog open={deleteItem !== null} onOpenChange={(o) => { if (!o && !deleting) setDeleteItem(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Obrisati destinaciju prevoza?</AlertDialogTitle>
            <AlertDialogDescription>
              „{deleteItem?.naziv}“ biće trajno obrisana, zajedno sa vezama na grupe termina i svim
              limitima prevoza za ovu destinaciju.
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
