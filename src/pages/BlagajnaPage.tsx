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
import { Loader2, Pencil, Search, Trash2, Wallet } from "lucide-react";
import { toast } from "sonner";

interface StavkaBlagajne {
  id: number;
  datum_blagajne: string;
  datum_uplate: string;
  iznos: number;
  uplaceno: boolean;
}

interface BlagajnaResponse {
  rows: StavkaBlagajne[];
  total: number;
}

interface Forma {
  datum_blagajne: string;
  datum_uplate: string;
  iznos: string;
  uplaceno: boolean;
}

const PRAZNA_FORMA: Forma = { datum_blagajne: "", datum_uplate: "", iznos: "", uplaceno: false };

const datumSr = (iso: string) => {
  const [g, m, d] = iso.split("-");
  return g && m && d ? `${d}.${m}.${g}` : iso;
};

const iznosSr = (n: number) =>
  n.toLocaleString("sr-RS", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export default function BlagajnaPage() {
  const [rows, setRows] = useState<StavkaBlagajne[]>([]);
  const [total, setTotal] = useState(0);
  const [ucitava, setUcitava] = useState(false);
  const [osvezi, setOsvezi] = useState(0);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");

  const [editId, setEditId] = useState<number | null>(null);
  const [forma, setForma] = useState<Forma>(PRAZNA_FORMA);
  const [cuvanje, setCuvanje] = useState(false);

  const [zaBrisanje, setZaBrisanje] = useState<StavkaBlagajne | null>(null);
  const [brisanje, setBrisanje] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setSearch(searchInput.trim()), 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  useEffect(() => {
    let aktivan = true;
    setUcitava(true);
    const qs = search ? `?q=${encodeURIComponent(search)}` : "";
    apiFetch<BlagajnaResponse>(`/blagajna${qs}`)
      .then((r) => {
        if (!aktivan) return;
        setRows(r.rows);
        setTotal(r.total);
      })
      .catch(() => toast.error("Stavke blagajne nisu učitane"))
      .finally(() => aktivan && setUcitava(false));
    return () => { aktivan = false; };
  }, [search, osvezi]);

  const otvoriIzmenu = (s: StavkaBlagajne) => {
    setEditId(s.id);
    setForma({
      datum_blagajne: s.datum_blagajne,
      datum_uplate: s.datum_uplate,
      iznos: String(s.iznos),
      uplaceno: s.uplaceno,
    });
  };

  const otkazi = () => {
    setEditId(null);
    setForma(PRAZNA_FORMA);
  };

  const sacuvaj = async () => {
    const iznos = Number(forma.iznos.replace(",", "."));
    if (!forma.datum_blagajne) { toast.error("Datum blagajne je obavezan"); return; }
    if (!forma.datum_uplate) { toast.error("Datum uplate je obavezan"); return; }
    if (!forma.iznos.trim() || Number.isNaN(iznos) || iznos < 0) { toast.error("Iznos nije ispravan"); return; }
    const telo = {
      datum_blagajne: forma.datum_blagajne,
      datum_uplate: forma.datum_uplate,
      iznos: Math.round(iznos * 100) / 100,
      uplaceno: forma.uplaceno,
    };
    setCuvanje(true);
    try {
      if (editId === null) {
        await apiFetch<{ status: string; id: number }>("/blagajna", {
          method: "POST",
          body: JSON.stringify(telo),
        });
        toast.success("Stavka je dodata");
      } else {
        await apiFetch<{ status: string; id: number }>(`/blagajna/${editId}`, {
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
      await apiFetch<{ status: string; id: number }>(`/blagajna/${zaBrisanje.id}`, { method: "DELETE" });
      toast.success("Stavka je obrisana");
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
          <Wallet className="h-6 w-6" />
          Blagajna
        </h1>
        <p className="text-sm text-muted-foreground">Evidencija uplata po datumu blagajne</p>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">{editId === null ? "Nova stavka" : "Izmena stavke"}</CardTitle>
          <p className="text-sm text-muted-foreground">Sva polja su obavezna.</p>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 gap-x-4 gap-y-3 sm:grid-cols-2 xl:grid-cols-4">
            <div className="space-y-1">
              <Label htmlFor="Datum blagajne" className="text-xs">Datum blagajne</Label>
              <Input
                id="Datum blagajne"
                aria-label="Datum blagajne"
                type="date"
                value={forma.datum_blagajne}
                onChange={(e) => setForma((f) => ({ ...f, datum_blagajne: e.target.value }))}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="Datum uplate" className="text-xs">Datum uplate</Label>
              <Input
                id="Datum uplate"
                aria-label="Datum uplate"
                type="date"
                value={forma.datum_uplate}
                onChange={(e) => setForma((f) => ({ ...f, datum_uplate: e.target.value }))}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="Iznos" className="text-xs">Iznos (RSD)</Label>
              <Input
                id="Iznos"
                aria-label="Iznos"
                inputMode="decimal"
                className="text-right font-mono"
                value={forma.iznos}
                onChange={(e) => setForma((f) => ({ ...f, iznos: e.target.value }))}
              />
            </div>
            <div className="flex items-end gap-2 pb-2">
              <input
                id="Uplaceno"
                aria-label="Uplaceno"
                type="checkbox"
                className="h-4 w-4"
                checked={forma.uplaceno}
                onChange={(e) => setForma((f) => ({ ...f, uplaceno: e.target.checked }))}
              />
              <Label htmlFor="Uplaceno" className="text-sm">Uplaćeno</Label>
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
              Stavke blagajne
              <span className="text-xs font-normal text-muted-foreground">Ukupno {total}</span>
            </CardTitle>
            <div className="relative w-full sm:w-72">
              <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                id="Pretraga blagajne"
                aria-label="Pretraga blagajne"
                placeholder="Pretraga (datum, iznos, uplaćeno…)"
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
                  <TableHead className="h-8 px-3 text-xs">Datum blagajne</TableHead>
                  <TableHead className="h-8 px-3 text-xs">Datum uplate</TableHead>
                  <TableHead className="h-8 px-3 text-right text-xs">Iznos</TableHead>
                  <TableHead className="h-8 px-3 text-center text-xs">Uplaćeno</TableHead>
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
                      Nema stavki za zadatu pretragu.
                    </TableCell>
                  </TableRow>
                ) : rows.map((s) => (
                  <TableRow key={s.id}>
                    <TableCell className="px-3 py-1.5 font-medium">{datumSr(s.datum_blagajne)}</TableCell>
                    <TableCell className="px-3 py-1.5">{datumSr(s.datum_uplate)}</TableCell>
                    <TableCell className="px-3 py-1.5 text-right font-mono">{iznosSr(s.iznos)}</TableCell>
                    <TableCell className="px-3 py-1.5 text-center">
                      <span className={s.uplaceno
                        ? "rounded-full bg-emerald-100 px-2 py-0.5 text-emerald-700"
                        : "rounded-full bg-red-100 px-2 py-0.5 text-red-700"}>
                        {s.uplaceno ? "Da" : "Ne"}
                      </span>
                    </TableCell>
                    <TableCell className="px-3 py-1.5">
                      <div className="flex justify-end gap-1">
                        <Button
                          variant="ghost" size="icon" className="h-7 w-7"
                          aria-label={`Izmeni stavku ${s.id}`}
                          onClick={() => otvoriIzmenu(s)}
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                        <Button
                          variant="ghost" size="icon" className="h-7 w-7 text-destructive"
                          aria-label={`Obriši stavku ${s.id}`}
                          onClick={() => setZaBrisanje(s)}
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
            <AlertDialogTitle>Obrisati stavku blagajne?</AlertDialogTitle>
            <AlertDialogDescription>
              Stavka blagajne od {zaBrisanje ? datumSr(zaBrisanje.datum_blagajne) : ""} biće trajno obrisana.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={brisanje}>Otkaži</AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => { e.preventDefault(); void obrisi(); }}
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
