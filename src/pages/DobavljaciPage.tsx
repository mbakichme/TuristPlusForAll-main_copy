import { useState, useEffect } from "react";
import { apiFetch } from "../lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle
} from "@/components/ui/dialog";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle
} from "@/components/ui/alert-dialog";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow
} from "@/components/ui/table";
import { Loader2, Pencil, Plus, Search, Store, Trash2 } from "lucide-react";
import { toast } from "sonner";

interface Dobavljac {
  id: number;
  naziv: string | null;
  punnaziv: string | null;
  adresa: string | null;
  mesto: string | null;
  osoba: string | null;
  tel: string | null;
  tel1: string | null;
  tel2: string | null;
  fax: string | null;
  racun: string | null;
  pib: string | null;
  matbroj: string | null;
  email: string | null;
  kontakt: string | null;
}

interface DobavljaciResponse {
  rows: Dobavljac[];
  total: number;
}

type Forma = Omit<Dobavljac, "id">;

const PRAZNA_FORMA: Forma = {
  naziv: "", punnaziv: "", adresa: "", mesto: "", osoba: "", tel: "", tel1: "", tel2: "",
  fax: "", racun: "", pib: "", matbroj: "", email: "", kontakt: "",
};

// Polja forme: [ključ, labela, širina]
const POLJA_FORME: { k: keyof Forma; label: string; puna?: boolean; mono?: boolean }[] = [
  { k: "naziv", label: "Naziv *", puna: true },
  { k: "punnaziv", label: "Puni naziv", puna: true },
  { k: "adresa", label: "Adresa", puna: true },
  { k: "mesto", label: "Mesto" },
  { k: "osoba", label: "Kontakt osoba" },
  { k: "tel", label: "Telefon" },
  { k: "tel1", label: "Telefon 1" },
  { k: "tel2", label: "Telefon 2" },
  { k: "fax", label: "Fax" },
  { k: "email", label: "Email" },
  { k: "pib", label: "PIB", mono: true },
  { k: "matbroj", label: "Matični broj", mono: true },
  { k: "racun", label: "Žiro račun", puna: true, mono: true },
  { k: "kontakt", label: "Napomena / kontakt", puna: true },
];

const txt = (v: string | null | undefined) => (v && v.trim() ? v : "—");

export default function DobavljaciPage() {
  const [rows, setRows] = useState<Dobavljac[]>([]);
  const [total, setTotal] = useState(0);
  const [ucitava, setUcitava] = useState(false);
  const [osvezi, setOsvezi] = useState(0);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");

  const [formaOtvorena, setFormaOtvorena] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [forma, setForma] = useState<Forma>(PRAZNA_FORMA);
  const [cuvanje, setCuvanje] = useState(false);

  const [zaBrisanje, setZaBrisanje] = useState<Dobavljac | null>(null);
  const [brisanje, setBrisanje] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setSearch(searchInput.trim()), 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  useEffect(() => {
    let aktivan = true;
    setUcitava(true);
    const qs = search ? `?q=${encodeURIComponent(search)}` : "";
    apiFetch<DobavljaciResponse>(`/dobavljaci${qs}`)
      .then((r) => {
        if (!aktivan) return;
        setRows(r.rows);
        setTotal(r.total);
      })
      .catch(() => toast.error("Dobavljači nisu učitani"))
      .finally(() => aktivan && setUcitava(false));
    return () => { aktivan = false; };
  }, [search, osvezi]);

  const otvoriNovi = () => {
    setEditId(null);
    setForma(PRAZNA_FORMA);
    setFormaOtvorena(true);
  };

  const otvoriIzmenu = (d: Dobavljac) => {
    setEditId(d.id);
    setForma({
      naziv: d.naziv ?? "", punnaziv: d.punnaziv ?? "", adresa: d.adresa ?? "",
      mesto: d.mesto ?? "", osoba: d.osoba ?? "", tel: d.tel ?? "", tel1: d.tel1 ?? "",
      tel2: d.tel2 ?? "", fax: d.fax ?? "", racun: d.racun ?? "", pib: d.pib ?? "",
      matbroj: d.matbroj ?? "", email: d.email ?? "", kontakt: d.kontakt ?? "",
    });
    setFormaOtvorena(true);
  };

  const sacuvaj = async () => {
    if (!(forma.naziv ?? "").trim()) {
      toast.error("Naziv je obavezan");
      return;
    }
    setCuvanje(true);
    try {
      if (editId === null) {
        await apiFetch("/dobavljaci", { method: "POST", body: JSON.stringify(forma) });
        toast.success("Dobavljač je dodat");
      } else {
        await apiFetch(`/dobavljaci/${editId}`, { method: "PUT", body: JSON.stringify(forma) });
        toast.success("Izmene su sačuvane");
      }
      setFormaOtvorena(false);
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
      await apiFetch(`/dobavljaci/${zaBrisanje.id}`, { method: "DELETE" });
      toast.success("Dobavljač je obrisan");
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
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Dobavljači</h1>
          <p className="text-sm text-muted-foreground">Lista dobavljača i kontakata</p>
        </div>
        <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">
          <div className="relative w-full sm:w-72">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              aria-label="Pretraga dobavljača"
              placeholder="Pretraga (naziv, mesto, PIB…)"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              className="pl-8"
            />
          </div>
          <Button onClick={otvoriNovi}>
            <Plus className="mr-1 h-4 w-4" />
            Novi dobavljač
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-base">
            <Store className="h-4 w-4" />
            Lista dobavljača
            <span className="ml-auto text-xs font-normal text-muted-foreground">Ukupno {total}</span>
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <Table className="text-xs">
              <TableHeader>
                <TableRow>
                  <TableHead className="h-8 px-3 text-xs">Naziv</TableHead>
                  <TableHead className="h-8 px-3 text-xs">Mesto</TableHead>
                  <TableHead className="h-8 px-3 text-xs">Adresa</TableHead>
                  <TableHead className="h-8 px-3 text-xs">PIB/Osoba</TableHead>
                  <TableHead className="h-8 px-3 text-xs">Telefon</TableHead>
                  <TableHead className="h-8 px-3 text-xs">PIB</TableHead>
                  <TableHead className="h-8 px-3 text-xs">Mat. broj</TableHead>
                  <TableHead className="h-8 px-3 text-xs">Email</TableHead>
                  <TableHead className="h-8 px-3 text-xs">Račun</TableHead>
                  <TableHead className="h-8 w-20 px-3 text-xs" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {ucitava && rows.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={10} className="py-6 text-center">
                      <Loader2 className="mx-auto size-4 animate-spin text-muted-foreground" />
                    </TableCell>
                  </TableRow>
                ) : rows.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={10} className="py-6 text-center text-muted-foreground">
                      Nema dobavljača za zadatu pretragu.
                    </TableCell>
                  </TableRow>
                ) : rows.map((d) => (
                  <TableRow key={d.id}>
                    <TableCell className="px-3 py-1.5 font-medium">{txt(d.naziv)}</TableCell>
                    <TableCell className="px-3 py-1.5">{txt(d.mesto)}</TableCell>
                    <TableCell className="px-3 py-1.5">{txt(d.adresa)}</TableCell>
                    <TableCell className="px-3 py-1.5">{txt(d.osoba)}</TableCell>
                    <TableCell className="px-3 py-1.5">{txt(d.tel)}</TableCell>
                    <TableCell className="px-3 py-1.5 font-mono">{txt(d.pib)}</TableCell>
                    <TableCell className="px-3 py-1.5 font-mono">{txt(d.matbroj)}</TableCell>
                    <TableCell className="px-3 py-1.5">{txt(d.email)}</TableCell>
                    <TableCell className="px-3 py-1.5 font-mono">{txt(d.racun)}</TableCell>
                    <TableCell className="px-3 py-1.5">
                      <div className="flex justify-end gap-1">
                        <Button
                          variant="ghost" size="icon" className="h-7 w-7"
                          aria-label={`Izmeni dobavljača ${d.naziv ?? d.id}`}
                          onClick={() => otvoriIzmenu(d)}
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                        <Button
                          variant="ghost" size="icon" className="h-7 w-7 text-destructive"
                          aria-label={`Obriši dobavljača ${d.naziv ?? d.id}`}
                          onClick={() => setZaBrisanje(d)}
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

      <Dialog open={formaOtvorena} onOpenChange={(o) => !cuvanje && setFormaOtvorena(o)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{editId === null ? "Novi dobavljač" : "Izmena dobavljača"}</DialogTitle>
            <DialogDescription>Polja označena zvezdicom su obavezna.</DialogDescription>
          </DialogHeader>
          <div className="grid grid-cols-1 gap-x-4 gap-y-3 sm:grid-cols-2">
            {POLJA_FORME.map((p) => (
              <div key={p.k} className={p.puna ? "sm:col-span-2 space-y-1" : "space-y-1"}>
                <Label htmlFor={`dob-${p.k}`} className="text-xs">{p.label}</Label>
                <Input
                  id={`dob-${p.k}`}
                  value={forma[p.k] ?? ""}
                  className={p.mono ? "font-mono" : undefined}
                  onChange={(e) => setForma((f) => ({ ...f, [p.k]: e.target.value }))}
                />
              </div>
            ))}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setFormaOtvorena(false)} disabled={cuvanje}>
              Otkaži
            </Button>
            <Button onClick={sacuvaj} disabled={cuvanje}>
              {cuvanje && <Loader2 className="mr-1 h-4 w-4 animate-spin" />}
              Sačuvaj
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog open={zaBrisanje !== null} onOpenChange={(o) => !o && !brisanje && setZaBrisanje(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Obrisati dobavljača?</AlertDialogTitle>
            <AlertDialogDescription>
              {zaBrisanje?.naziv ?? "Dobavljač"} će biti trajno obrisan. Ova radnja se ne može opozvati.
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
