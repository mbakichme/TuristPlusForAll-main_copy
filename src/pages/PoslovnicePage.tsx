import { useEffect, useState } from "react";
import { apiFetch } from "../lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Loader2, Pencil, Plus, Store, Trash2 } from "lucide-react";
import { toast } from "sonner";

interface Poslovnica {
  id: number;
  naziv: string;
  adresa: string;
  grad: string;
  opstina_rgz: string;
  opstina_naziv: string;
  mesto_rgz: string;
  mesto_naziv: string;
  ulica_rgz: string;
  ulica_naziv: string;
}

type PoslovnicaForm = Omit<Poslovnica, "id">;

const prazna: PoslovnicaForm = {
  naziv: "", adresa: "", grad: "",
  opstina_rgz: "", opstina_naziv: "", mesto_rgz: "", mesto_naziv: "",
  ulica_rgz: "", ulica_naziv: "",
};

const RGZ_POLJA: { name: keyof PoslovnicaForm; label: string }[] = [
  { name: "opstina_rgz", label: "Opština RGZ" },
  { name: "opstina_naziv", label: "Opština naziv" },
  { name: "mesto_rgz", label: "Mesto RGZ" },
  { name: "mesto_naziv", label: "Mesto naziv" },
  { name: "ulica_rgz", label: "Ulica RGZ" },
  { name: "ulica_naziv", label: "Ulica naziv" },
];

export default function PoslovnicePage() {
  const [lista, setLista] = useState<Poslovnica[]>([]);
  const [loading, setLoading] = useState(true);
  const [dijalog, setDijalog] = useState<{ id: number | null; form: PoslovnicaForm } | null>(null);
  const [saving, setSaving] = useState(false);
  const [zaBrisanje, setZaBrisanje] = useState<Poslovnica | null>(null);

  function ucitaj() {
    return apiFetch<{ poslovnice: Poslovnica[] }>("/poslovnice")
      .then((d) => setLista(d.poslovnice))
      .catch(() => toast.error("Greška pri učitavanju poslovnica"))
      .finally(() => setLoading(false));
  }

  useEffect(() => { ucitaj(); }, []);

  function setPolje(name: keyof PoslovnicaForm, val: string) {
    setDijalog((d) => (d ? { ...d, form: { ...d.form, [name]: val } } : d));
  }

  async function sacuvaj() {
    if (!dijalog) return;
    if (!dijalog.form.naziv.trim()) {
      toast.error("Naziv poslovnice je obavezan");
      return;
    }
    setSaving(true);
    try {
      const putanja = dijalog.id === null ? "/poslovnice" : `/poslovnice/${dijalog.id}`;
      await apiFetch(putanja, {
        method: dijalog.id === null ? "POST" : "PUT",
        body: JSON.stringify(dijalog.form),
      });
      toast.success(dijalog.id === null ? "Poslovnica je dodata" : "Poslovnica je sačuvana");
      setDijalog(null);
      await ucitaj();
    } catch {
      toast.error("Greška pri čuvanju poslovnice");
    } finally {
      setSaving(false);
    }
  }

  async function obrisi() {
    if (!zaBrisanje) return;
    try {
      await apiFetch(`/poslovnice/${zaBrisanje.id}`, { method: "DELETE" });
      toast.success("Poslovnica je obrisana");
      await ucitaj();
    } catch {
      toast.error("Greška pri brisanju poslovnice");
    } finally {
      setZaBrisanje(null);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
            <Store className="w-6 h-6" /> Poslovnice
          </h1>
          <p className="text-muted-foreground mt-1 text-sm">Poslovnice agencije sa adresom i RGZ podacima</p>
        </div>
        <Button className="gap-2" onClick={() => setDijalog({ id: null, form: { ...prazna } })}>
          <Plus className="w-4 h-4" /> Dodaj poslovnicu
        </Button>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Lista poslovnica ({lista.length})</CardTitle>
        </CardHeader>
        <CardContent className="pt-2">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Naziv</TableHead>
                <TableHead>Adresa</TableHead>
                <TableHead>Grad</TableHead>
                <TableHead>Opština RGZ</TableHead>
                <TableHead>Mesto RGZ</TableHead>
                <TableHead>Ulica RGZ</TableHead>
                <TableHead className="w-24 text-right">Akcije</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {lista.length === 0 && (
                <TableRow>
                  <TableCell colSpan={7} className="text-center text-muted-foreground py-8">
                    Nema poslovnica. Dodajte prvu.
                  </TableCell>
                </TableRow>
              )}
              {lista.map((p) => (
                <TableRow key={p.id}>
                  <TableCell className="font-medium">{p.naziv}</TableCell>
                  <TableCell>{p.adresa}</TableCell>
                  <TableCell>{p.grad}</TableCell>
                  <TableCell>{[p.opstina_rgz, p.opstina_naziv].filter(Boolean).join(" · ")}</TableCell>
                  <TableCell>{[p.mesto_rgz, p.mesto_naziv].filter(Boolean).join(" · ")}</TableCell>
                  <TableCell>{[p.ulica_rgz, p.ulica_naziv].filter(Boolean).join(" · ")}</TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={`Izmeni ${p.naziv}`}
                      onClick={() => {
                        const { id, ...form } = p;
                        setDijalog({ id, form });
                      }}
                    >
                      <Pencil className="w-4 h-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={`Obriši ${p.naziv}`}
                      className="text-destructive"
                      onClick={() => setZaBrisanje(p)}
                    >
                      <Trash2 className="w-4 h-4" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Dialog open={dijalog !== null} onOpenChange={(o) => { if (!o) setDijalog(null); }}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{dijalog?.id === null ? "Nova poslovnica" : "Izmena poslovnice"}</DialogTitle>
            <DialogDescription>Naziv je obavezan; ostala polja su opciona.</DialogDescription>
          </DialogHeader>
          {dijalog && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="space-y-1.5 sm:col-span-2">
                <Label htmlFor="pos-naziv">Naziv poslovnice</Label>
                <Input id="pos-naziv" value={dijalog.form.naziv} onChange={(e) => setPolje("naziv", e.target.value)} />
              </div>
              <div className="space-y-1.5 sm:col-span-2">
                <Label htmlFor="pos-adresa">Adresa</Label>
                <Input id="pos-adresa" value={dijalog.form.adresa} onChange={(e) => setPolje("adresa", e.target.value)} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="pos-grad">Grad</Label>
                <Input id="pos-grad" value={dijalog.form.grad} onChange={(e) => setPolje("grad", e.target.value)} />
              </div>
              {RGZ_POLJA.map((f) => (
                <div key={f.name} className="space-y-1.5">
                  <Label htmlFor={`pos-${f.name}`}>{f.label}</Label>
                  <Input
                    id={`pos-${f.name}`}
                    value={dijalog.form[f.name]}
                    onChange={(e) => setPolje(f.name, e.target.value)}
                  />
                </div>
              ))}
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setDijalog(null)} disabled={saving}>Otkaži</Button>
            <Button onClick={sacuvaj} disabled={saving}>
              {saving && <Loader2 className="w-4 h-4 animate-spin mr-2" />}
              Sačuvaj
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog open={zaBrisanje !== null} onOpenChange={(o) => { if (!o) setZaBrisanje(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Obrisati poslovnicu?</AlertDialogTitle>
            <AlertDialogDescription>
              {zaBrisanje?.naziv} će biti trajno obrisana.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Otkaži</AlertDialogCancel>
            <AlertDialogAction onClick={obrisi}>Obriši</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
