import { useState, useEffect } from "react";
import { apiFetch } from "../lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle
} from "@/components/ui/alert-dialog";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow
} from "@/components/ui/table";
import { Landmark, Loader2, Pencil, Search, Trash2 } from "lucide-react";
import { toast } from "sonner";

interface Banka {
  id: number;
  sifra: string;
  naziv: string;
  racun: string;
  mesto: string;
}

interface BankeResponse {
  rows: Banka[];
  total: number;
}

type Forma = Omit<Banka, "id">;

const PRAZNA_FORMA: Forma = { sifra: "", naziv: "", racun: "", mesto: "" };

export default function BankePage() {
  const [rows, setRows] = useState<Banka[]>([]);
  const [total, setTotal] = useState(0);
  const [ucitava, setUcitava] = useState(false);
  const [osvezi, setOsvezi] = useState(0);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");

  const [editId, setEditId] = useState<number | null>(null);
  const [forma, setForma] = useState<Forma>(PRAZNA_FORMA);
  const [cuvanje, setCuvanje] = useState(false);

  const [zaBrisanje, setZaBrisanje] = useState<Banka | null>(null);
  const [brisanje, setBrisanje] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setSearch(searchInput.trim()), 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  useEffect(() => {
    let aktivan = true;
    setUcitava(true);
    const qs = search ? `?q=${encodeURIComponent(search)}` : "";
    apiFetch<BankeResponse>(`/banke${qs}`)
      .then((r) => {
        if (!aktivan) return;
        setRows(r.rows);
        setTotal(r.total);
      })
      .catch(() => toast.error("Banke nisu učitane"))
      .finally(() => aktivan && setUcitava(false));
    return () => { aktivan = false; };
  }, [search, osvezi]);

  const otvoriIzmenu = (b: Banka) => {
    setEditId(b.id);
    setForma({ sifra: b.sifra, naziv: b.naziv, racun: b.racun, mesto: b.mesto });
  };

  const otkazi = () => {
    setEditId(null);
    setForma(PRAZNA_FORMA);
  };

  const sacuvaj = async () => {
    const telo = {
      sifra: forma.sifra.trim(),
      naziv: forma.naziv.trim(),
      racun: forma.racun.trim(),
      mesto: forma.mesto.trim(),
    };
    if (!telo.sifra) { toast.error("Šifra je obavezna"); return; }
    if (!telo.naziv) { toast.error("Naziv banke je obavezan"); return; }
    if (!telo.racun) { toast.error("Broj računa banke je obavezan"); return; }
    if (!telo.mesto) { toast.error("Mesto banke je obavezno"); return; }
    setCuvanje(true);
    try {
      if (editId === null) {
        await apiFetch<{ status: string; id: number }>("/banke", {
          method: "POST",
          body: JSON.stringify(telo),
        });
        toast.success("Banka je dodata");
      } else {
        await apiFetch<{ status: string; id: number }>(`/banke/${editId}`, {
          method: "PUT",
          body: JSON.stringify(telo),
        });
        toast.success("Izmene su sačuvane");
      }
      setEditId(null);
      setForma(PRAZNA_FORMA);
      setOsvezi((n) => n + 1);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Čuvanje nije uspelo");
    } finally {
      setCuvanje(false);
    }
  };

  const obrisi = async () => {
    if (!zaBrisanje) return;
    setBrisanje(true);
    try {
      await apiFetch<{ status: string; id: number }>(`/banke/${zaBrisanje.id}`, { method: "DELETE" });
      toast.success("Banka je obrisana");
      setZaBrisanje(null);
      setOsvezi((n) => n + 1);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Brisanje nije uspelo");
    } finally {
      setBrisanje(false);
    }
  };

  return (
    <div className="space-y-4 p-4 md:p-6">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold">
          <Landmark className="h-6 w-6" />
          Banke
        </h1>
        <p className="text-sm text-muted-foreground">Evidencija banaka i računa agencije</p>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">{editId === null ? "Nova banka" : "Izmena banke"}</CardTitle>
          <p className="text-sm text-muted-foreground">Sva polja su obavezna.</p>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 gap-x-4 gap-y-3 sm:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="Šifra" className="text-xs">Šifra</Label>
              <Input
                id="Šifra"
                aria-label="Šifra"
                value={forma.sifra}
                onChange={(e) => setForma((f) => ({ ...f, sifra: e.target.value }))}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="Naziv banke" className="text-xs">Naziv banke</Label>
              <Input
                id="Naziv banke"
                aria-label="Naziv banke"
                value={forma.naziv}
                onChange={(e) => setForma((f) => ({ ...f, naziv: e.target.value }))}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="Broj računa banke" className="text-xs">Broj računa banke</Label>
              <Input
                id="Broj računa banke"
                aria-label="Broj računa banke"
                className="font-mono"
                value={forma.racun}
                onChange={(e) => setForma((f) => ({ ...f, racun: e.target.value }))}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="Mesto banke" className="text-xs">Mesto banke</Label>
              <Input
                id="Mesto banke"
                aria-label="Mesto banke"
                value={forma.mesto}
                onChange={(e) => setForma((f) => ({ ...f, mesto: e.target.value }))}
              />
            </div>
          </div>
          <div className="mt-4 flex justify-end gap-2">
            {editId !== null && (
              <Button variant="outline" onClick={otkazi} disabled={cuvanje}>
                Otkaži
              </Button>
            )}
            <Button onClick={sacuvaj} disabled={cuvanje}>
              {cuvanje && <Loader2 className="mr-1 h-4 w-4 animate-spin" />}
              {editId === null ? "Sačuvaj" : "Sačuvaj izmene"}
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <CardTitle className="flex items-center gap-2 text-base">
              Lista banaka
              <span className="text-xs font-normal text-muted-foreground">Ukupno {total}</span>
            </CardTitle>
            <div className="relative w-full sm:w-72">
              <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                id="Pretraga banaka"
                aria-label="Pretraga banaka"
                placeholder="Pretraga (šifra, naziv, mesto…)"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                className="pl-8"
              />
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <Table className="text-xs">
              <TableHeader>
                <TableRow>
                  <TableHead className="h-8 px-3 text-xs">Šifra</TableHead>
                  <TableHead className="h-8 px-3 text-xs">Naziv banke</TableHead>
                  <TableHead className="h-8 px-3 text-xs">Broj računa banke</TableHead>
                  <TableHead className="h-8 px-3 text-xs">Mesto banke</TableHead>
                  <TableHead className="h-8 w-20 px-3 text-xs" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {ucitava && rows.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={5} className="py-6 text-center">
                      <Loader2 className="mx-auto size-4 animate-spin text-muted-foreground" />
                    </TableCell>
                  </TableRow>
                ) : rows.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={5} className="py-6 text-center text-muted-foreground">
                      Nema banaka za zadatu pretragu.
                    </TableCell>
                  </TableRow>
                ) : rows.map((b) => (
                  <TableRow key={b.id}>
                    <TableCell className="px-3 py-1.5 font-medium">{b.sifra || "—"}</TableCell>
                    <TableCell className="px-3 py-1.5">{b.naziv || "—"}</TableCell>
                    <TableCell className="px-3 py-1.5 font-mono">{b.racun || "—"}</TableCell>
                    <TableCell className="px-3 py-1.5">{b.mesto || "—"}</TableCell>
                    <TableCell className="px-3 py-1.5">
                      <div className="flex justify-end gap-1">
                        <Button
                          variant="ghost" size="icon" className="h-7 w-7"
                          aria-label={`Izmeni banku ${b.naziv || b.id}`}
                          onClick={() => otvoriIzmenu(b)}
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                        <Button
                          variant="ghost" size="icon" className="h-7 w-7 text-destructive"
                          aria-label={`Obriši banku ${b.naziv || b.id}`}
                          onClick={() => setZaBrisanje(b)}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      <AlertDialog open={zaBrisanje !== null} onOpenChange={(o) => !o && !brisanje && setZaBrisanje(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Obrisati banku?</AlertDialogTitle>
            <AlertDialogDescription>
              {zaBrisanje?.naziv ?? "Banka"} će biti trajno obrisana. Ova radnja se ne može opozvati.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={brisanje}>Otkaži</AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => { e.preventDefault(); obrisi(); }}
              disabled={brisanje}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {brisanje && <Loader2 className="mr-1 h-4 w-4 animate-spin" />}
              Obriši
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
