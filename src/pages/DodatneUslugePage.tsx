import { useState, useEffect } from "react";
import { apiFetch } from "../lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow
} from "@/components/ui/table";
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle
} from "@/components/ui/dialog";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Plus, Loader2, Receipt } from "lucide-react";
import { toast } from "sonner";

interface DodatnaUsluga {
  id: number;
  naziv: string;
  iznos_eur: number;
  iznos_din: number;
}

const formatIznos = (v: number) =>
  v.toLocaleString("sr-RS", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export default function DodatneUslugePage() {
  const [items, setItems] = useState<DodatnaUsluga[]>([]);
  const [loading, setLoading] = useState(true);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [naziv, setNaziv] = useState("");
  const [eur, setEur] = useState("");
  const [din, setDin] = useState("");
  const [saving, setSaving] = useState(false);

  async function ucitaj() {
    try {
      setItems(await apiFetch<DodatnaUsluga[]>("/dodatne-usluge"));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Greška pri učitavanju");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void ucitaj(); }, []);

  function otvoriNovu() {
    setNaziv("");
    setEur("");
    setDin("");
    setDialogOpen(true);
  }

  function parsiraj(vrednost: string): number | null {
    const t = vrednost.trim().replace(",", ".");
    if (t === "") return 0;
    const n = Number(t);
    if (!Number.isFinite(n) || n < 0) return null;
    return Math.round(n * 100) / 100;
  }

  async function snimi() {
    const imeTrim = naziv.trim();
    if (!imeTrim) {
      toast.error("Naziv je obavezan");
      return;
    }
    const iznosEur = parsiraj(eur);
    const iznosDin = parsiraj(din);
    if (iznosEur === null || iznosDin === null) {
      toast.error("Iznos mora biti broj veći ili jednak 0");
      return;
    }
    setSaving(true);
    try {
      await apiFetch("/dodatne-usluge", {
        method: "POST",
        body: JSON.stringify({ naziv: imeTrim, iznos_eur: iznosEur, iznos_din: iznosDin }),
      });
      toast.success("Dodatna usluga je dodata");
      setDialogOpen(false);
      await ucitaj();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Čuvanje nije uspelo");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="p-4 md:p-6 space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <h1 className="text-xl font-semibold flex items-center gap-2">
            <Receipt className="w-5 h-5" />Dodatne usluge
          </h1>
          {!loading && <Badge variant="secondary" className="tabular-nums">{items.length}</Badge>}
        </div>
        <Button onClick={otvoriNovu}>
          <Plus className="w-4 h-4 mr-1" />Dodaj uslugu
        </Button>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Spisak</CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="flex justify-center py-8"><Loader2 className="w-5 h-5 animate-spin text-muted-foreground" /></div>
          ) : items.length === 0 ? (
            <p className="text-sm text-muted-foreground py-6 text-center">
              Još nema unetih dodatnih usluga. Kliknite „Dodaj uslugu“.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Naziv</TableHead>
                  <TableHead className="text-right">Iznos (EUR)</TableHead>
                  <TableHead className="text-right">Iznos (din)</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((u) => (
                  <TableRow key={u.id}>
                    <TableCell className="font-medium">{u.naziv}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatIznos(u.iznos_eur)}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatIznos(u.iznos_din)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Dialog open={dialogOpen} onOpenChange={(o) => { if (!saving) setDialogOpen(o); }}>
        <DialogContent className="sm:max-w-md bg-card">
          <DialogHeader>
            <DialogTitle>Nova dodatna usluga</DialogTitle>
          </DialogHeader>

          <div className="space-y-3">
            <div className="space-y-1">
              <Label htmlFor="du-naziv" className="text-xs">Naziv</Label>
              <Input id="du-naziv" className="h-9" maxLength={200} value={naziv}
                onChange={(e) => setNaziv(e.target.value)} />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label htmlFor="du-eur" className="text-xs">Iznos (EUR)</Label>
                <Input id="du-eur" className="h-9 tabular-nums" inputMode="decimal" placeholder="0.00"
                  value={eur} onChange={(e) => setEur(e.target.value)} />
              </div>
              <div className="space-y-1">
                <Label htmlFor="du-din" className="text-xs">Iznos (din)</Label>
                <Input id="du-din" className="h-9 tabular-nums" inputMode="decimal" placeholder="0.00"
                  value={din} onChange={(e) => setDin(e.target.value)} />
              </div>
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
    </div>
  );
}
