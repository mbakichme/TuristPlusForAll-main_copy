import { useState, useEffect, useMemo } from "react";
import type { Soba, Smestaj, KoefZapis } from "../types";
import { apiFetch } from "../lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow
} from "@/components/ui/table";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle
} from "@/components/ui/dialog";
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
import { Plus, Pencil, Trash2, Loader2, DoorOpen, Search, Sigma } from "lucide-react";
import { toast } from "sonner";

interface SobaForm {
  veza_id_smestaj: string;
  broj_sobe: string;
  tip: string;
  status: string;
  opis: string;
  opis_dodatno: string;
  veliki_opis: string;
}

const emptyForm: SobaForm = { veza_id_smestaj: "", broj_sobe: "", tip: "", status: "1", opis: "", opis_dodatno: "", veliki_opis: "" };

const INT_RE = /^\d+$/;
const KOEF_RE = /^\d*(?:\.\d{1,4})?$/;

/** double → prikaz bez suvišnih nula (1.50 → „1.5“, 2 → „2“). */
function fmtKoef(vrednost: number): string {
  return String(Math.round(vrednost * 1000000) / 1000000);
}

interface KoefForma {
  adl: string;
  chd: string;
  inf: string;
  koeficijent: string;
}

const emptyKoefForma: KoefForma = { adl: "0", chd: "0", inf: "0", koeficijent: "0" };

export default function SobePage() {
  const [items, setItems] = useState<Soba[]>([]);
  const [smestaji, setSmestaji] = useState<Smestaj[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [deleteId, setDeleteId] = useState<number | null>(null);
  const [editing, setEditing] = useState<Soba | null>(null);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState<SobaForm>(emptyForm);

  // Koeficijenti sobe (dialog)
  const [koefSoba, setKoefSoba] = useState<Soba | null>(null);
  const [koefRedovi, setKoefRedovi] = useState<KoefZapis[]>([]);
  const [koefLoading, setKoefLoading] = useState(false);
  const [koefDodajOpen, setKoefDodajOpen] = useState(false);
  const [koefForma, setKoefForma] = useState<KoefForma>(emptyKoefForma);
  const [koefSnima, setKoefSnima] = useState(false);
  const [koefBrise, setKoefBrise] = useState<number | null>(null);

  async function load() {
    try {
      const [sobeData, smestajData] = await Promise.all([
        apiFetch<Soba[]>("/sobe"),
        apiFetch<Smestaj[]>("/smestaj"),
      ]);
      setItems(sobeData);
      setSmestaji(smestajData);
    } catch {
      toast.error("Greška pri učitavanju soba");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return items;
    return items.filter((b) =>
      [b.broj_sobe, b.tip, b.opis, b.opis_dodatno, b.veliki_opis, b.smestaj_naziv, b.mesto_naziv]
        .some((v) => (v || "").toLowerCase().includes(q))
    );
  }, [items, search]);

  // ── Koeficijenti sobe ─────────────────────────────────────────────────────

  async function ucitajKoefRedove(tip: string) {
    setKoefLoading(true);
    try {
      const d = await apiFetch<{ struktura: string; redovi: KoefZapis[] }>(
        `/koeficijenti/struktura?struktura=${encodeURIComponent(tip.trim())}`
      );
      setKoefRedovi(d.redovi);
    } catch {
      toast.error("Učitavanje koeficijenata nije uspelo");
    } finally {
      setKoefLoading(false);
    }
  }

  function otvoriKoeficijente(soba: Soba) {
    setKoefSoba(soba);
    setKoefDodajOpen(false);
    setKoefForma(emptyKoefForma);
    void ucitajKoefRedove(soba.tip);
  }

  function koefPolje(key: keyof KoefForma, vrednost: string) {
    setKoefForma((f) => ({ ...f, [key]: vrednost }));
  }

  async function sacuvajKoef() {
    if (!koefSoba || koefSnima) return;
    const struktura = koefSoba.tip.trim();
    for (const polje of ["adl", "chd", "inf"] as const) {
      const v = koefForma[polje].trim();
      if (v !== "" && (!INT_RE.test(v) || Number(v) > 99)) {
        toast.error(`${polje.toUpperCase()} mora biti ceo broj od 0 do 99`);
        return;
      }
    }
    const k = koefForma.koeficijent.trim().replace(/,/g, ".");
    if (k !== "" && !KOEF_RE.test(k)) {
      toast.error("Koeficijent mora biti nenegativan broj sa najviše 4 decimale (npr. 1,25)");
      return;
    }
    if (k !== "" && Number(k) >= 1000000) {
      toast.error("Koeficijent mora biti manji od 1.000.000");
      return;
    }
    setKoefSnima(true);
    try {
      await apiFetch("/koeficijenti/red", {
        method: "POST",
        body: JSON.stringify({
          struktura,
          adl: koefForma.adl.trim() === "" ? 0 : Number(koefForma.adl),
          chd: koefForma.chd.trim() === "" ? 0 : Number(koefForma.chd),
          inf: koefForma.inf.trim() === "" ? 0 : Number(koefForma.inf),
          koeficijent: k === "" ? 0 : Number(k),
        }),
      });
      toast.success("Koeficijent dodat");
      setKoefDodajOpen(false);
      setKoefForma(emptyKoefForma);
      await ucitajKoefRedove(struktura);
      void load(); // osveži prikaz u koloni tabele
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Greška");
    } finally {
      setKoefSnima(false);
    }
  }

  async function obrisiKoef(id: number) {
    setKoefBrise(id);
    try {
      await apiFetch(`/koeficijenti/red/${id}`, { method: "DELETE" });
      toast.success("Koeficijent obrisan");
      if (koefSoba) await ucitajKoefRedove(koefSoba.tip);
      void load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Greška");
    } finally {
      setKoefBrise(null);
    }
  }

  function openAdd() {
    setEditing(null);
    setForm(emptyForm);
    setSheetOpen(true);
  }

  function openEdit(item: Soba) {
    setEditing(item);
    setForm({
      veza_id_smestaj: item.veza_id_smestaj ? String(item.veza_id_smestaj) : "",
      broj_sobe: item.broj_sobe || "",
      tip: item.tip || "",
      status: String(item.status),
      opis: item.opis || "",
      opis_dodatno: item.opis_dodatno || "",
      veliki_opis: item.veliki_opis || "",
    });
    setSheetOpen(true);
  }

  function setField(key: keyof SobaForm, value: string) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function handleSave() {
    if (!form.veza_id_smestaj) { toast.error("Smeštaj je obavezan"); return; }
    setSaving(true);
    try {
      const payload = {
        veza_id_smestaj: Number(form.veza_id_smestaj),
        broj_sobe: form.broj_sobe,
        tip: form.tip,
        status: Number(form.status),
        opis: form.opis,
        opis_dodatno: form.opis_dodatno,
        veliki_opis: form.veliki_opis,
      };
      if (editing) {
        await apiFetch(`/sobe/${editing.id}`, { method: "PUT", body: JSON.stringify(payload) });
        toast.success("Soba ažurirana");
      } else {
        await apiFetch("/sobe", { method: "POST", body: JSON.stringify(payload) });
        toast.success("Soba kreirana");
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
      await apiFetch(`/sobe/${deleteId}`, { method: "DELETE" });
      toast.success("Soba obrisana");
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
          <h1 className="text-2xl font-bold">Sobe</h1>
          <p className="text-muted-foreground text-sm">Sobe po smeštajima</p>
        </div>
        <Button onClick={openAdd}><Plus className="w-4 h-4 mr-2" />Dodaj</Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><DoorOpen className="w-5 h-5" />Sobe</CardTitle>
          <CardDescription>
            Ukupno: <span className="font-semibold text-foreground">{items.length}</span>
            {search.trim() && <> · prikazano: <span className="font-semibold text-foreground">{filtered.length}</span></>}
          </CardDescription>
          <div className="relative max-w-md mt-2">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Pretraga: smeštaj, broj sobe, tip, opis..."
              className="pl-9"
            />
          </div>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Smeštaj</TableHead>
                <TableHead>Mesto</TableHead>
                <TableHead>Broj sobe</TableHead>
                <TableHead>Tip</TableHead>
                <TableHead>Koeficijenti</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Opis</TableHead>
                <TableHead className="w-24 text-right">Akcije</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.length === 0 ? (
                <TableRow><TableCell colSpan={8} className="text-center text-muted-foreground py-8">
                  {search.trim() ? "Nema rezultata za pretragu" : "Nema soba. Kliknite Dodaj da kreirate prvu."}
                </TableCell></TableRow>
              ) : filtered.map((item) => (
                <TableRow key={item.id}>
                  <TableCell className="font-medium">{item.smestaj_naziv || `#${item.veza_id_smestaj}`}</TableCell>
                  <TableCell className="text-muted-foreground">{item.mesto_naziv || "—"}</TableCell>
                  <TableCell className="font-mono">{item.broj_sobe || "—"}</TableCell>
                  <TableCell>{item.tip || "—"}</TableCell>
                  <TableCell>
                    {item.tip?.trim() ? (
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-8 gap-1.5"
                        aria-label={`Koeficijenti — soba ${item.broj_sobe || item.id}`}
                        onClick={() => otvoriKoeficijente(item)}
                      >
                        <Sigma className="h-3.5 w-3.5 text-muted-foreground" />
                        <span className="tabular-nums">
                          {item.koeficijenti && item.koeficijenti.length > 0
                            ? item.koeficijenti.map((k) => fmtKoef(Number(k.koeficijent))).join(" · ")
                            : "0"}
                        </span>
                      </Button>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <Badge variant={item.status === 1 ? "default" : "secondary"}>
                      {item.status === 1 ? "Aktivan" : "Neaktivan"}
                    </Badge>
                  </TableCell>
                  <TableCell className="max-w-xs truncate text-muted-foreground" title={item.opis || undefined}>
                    {item.opis || "—"}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex items-center justify-end gap-1">
                      <Button variant="ghost" size="icon" onClick={() => openEdit(item)}><Pencil className="w-4 h-4" /></Button>
                      <Button variant="ghost" size="icon" className="text-destructive hover:text-destructive" onClick={() => setDeleteId(item.id)}><Trash2 className="w-4 h-4" /></Button>
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
            <SheetTitle>{editing ? "Izmeni sobu" : "Dodaj sobu"}</SheetTitle>
          </SheetHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label>Smeštaj *</Label>
              <Select value={form.veza_id_smestaj} onValueChange={(v) => setField("veza_id_smestaj", v)}>
                <SelectTrigger><SelectValue placeholder="Izaberite smeštaj" /></SelectTrigger>
                <SelectContent>
                  {smestaji.map((s) => (
                    <SelectItem key={s.id} value={String(s.id)}>{s.naziv}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Broj sobe</Label>
              <Input value={form.broj_sobe} onChange={(e) => setField("broj_sobe", e.target.value)} placeholder="npr. 101" />
            </div>
            <div className="space-y-2">
              <Label>Tip</Label>
              <Input value={form.tip} onChange={(e) => setField("tip", e.target.value)} placeholder="npr. 1/2+2" />
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
              <Label>Opis</Label>
              <Textarea value={form.opis} onChange={(e) => setField("opis", e.target.value)} placeholder="Kratak opis sobe" rows={2} />
            </div>
            <div className="space-y-2">
              <Label>Opis dodatno</Label>
              <Textarea value={form.opis_dodatno} onChange={(e) => setField("opis_dodatno", e.target.value)} placeholder="Dodatni opis" rows={2} />
            </div>
            <div className="space-y-2">
              <Label>Veliki opis</Label>
              <Textarea value={form.veliki_opis} onChange={(e) => setField("veliki_opis", e.target.value)} placeholder="Detaljan opis sobe" rows={4} />
            </div>
          </div>
          <SheetFooter>
            <Button variant="outline" onClick={() => setSheetOpen(false)}>Otkaži</Button>
            <Button onClick={handleSave} disabled={saving}>
              {saving ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : null}
              {editing ? "Sačuvaj izmene" : "Dodaj sobu"}
            </Button>
          </SheetFooter>
        </SheetContent>
      </Sheet>

      {/* Koeficijenti sobe */}
      <Dialog open={koefSoba !== null} onOpenChange={(o) => { if (!o) setKoefSoba(null); }}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>
              Koeficijenti — {koefSoba?.smestaj_naziv}{koefSoba?.broj_sobe ? ` · ${koefSoba.broj_sobe}` : ""}
            </DialogTitle>
            <DialogDescription>
              Struktura <span className="font-semibold text-foreground">{koefSoba?.tip || "—"}</span>. Za istu
              strukturu možete definisati više koeficijenata.
            </DialogDescription>
          </DialogHeader>
          {koefLoading ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <div className="space-y-3">
              <div className="overflow-hidden rounded-lg border">
                <table className="w-full border-collapse text-sm">
                  <thead>
                    <tr className="border-b bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
                      <th className="px-3 py-2 text-center font-medium">Adl</th>
                      <th className="px-3 py-2 text-center font-medium">Chd</th>
                      <th className="px-3 py-2 text-center font-medium">Inf</th>
                      <th className="px-3 py-2 text-center font-medium">Koeficijent</th>
                      <th className="w-12 px-2 py-2"><span className="sr-only">Akcije</span></th>
                    </tr>
                  </thead>
                  <tbody>
                    {koefRedovi.map((k) => {
                      const kid = k.id;
                      return (
                        <tr key={kid ?? "auto"} className="border-b last:border-b-0 hover:bg-muted/20">
                          <td className="px-3 py-1.5 text-center tabular-nums">{k.adl}</td>
                          <td className="px-3 py-1.5 text-center tabular-nums">{k.chd}</td>
                          <td className="px-3 py-1.5 text-center tabular-nums">{k.inf}</td>
                          <td className="px-3 py-1.5 text-center font-medium tabular-nums">{fmtKoef(Number(k.koeficijent))}</td>
                          <td className="px-2 py-1.5 text-center">
                            {k.rucno && kid !== null && (
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-7 w-7 text-muted-foreground hover:text-destructive"
                                aria-label={`Obriši koeficijent ${fmtKoef(Number(k.koeficijent))}`}
                                onClick={() => void obrisiKoef(kid)}
                                disabled={koefBrise === kid}
                              >
                                {koefBrise === kid
                                  ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                  : <Trash2 className="h-3.5 w-3.5" />}
                              </Button>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                    {koefRedovi.length === 0 && (
                      <tr><td colSpan={5} className="px-3 py-6 text-center text-muted-foreground">Nema zapisa.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>

              {koefDodajOpen && (
                <div className="space-y-3 rounded-lg border p-3">
                  <div className="grid grid-cols-4 gap-2">
                    <div className="space-y-1">
                      <Label className="text-xs text-muted-foreground">Adl</Label>
                      <Input value={koefForma.adl} inputMode="numeric" aria-label="Novi koeficijent — Adl"
                        onChange={(e) => koefPolje("adl", e.target.value)}
                        className="h-8 text-center tabular-nums" />
                    </div>
                    <div className="space-y-1">
                      <Label className="text-xs text-muted-foreground">Chd</Label>
                      <Input value={koefForma.chd} inputMode="numeric" aria-label="Novi koeficijent — Chd"
                        onChange={(e) => koefPolje("chd", e.target.value)}
                        className="h-8 text-center tabular-nums" />
                    </div>
                    <div className="space-y-1">
                      <Label className="text-xs text-muted-foreground">Inf</Label>
                      <Input value={koefForma.inf} inputMode="numeric" aria-label="Novi koeficijent — Inf"
                        onChange={(e) => koefPolje("inf", e.target.value)}
                        className="h-8 text-center tabular-nums" />
                    </div>
                    <div className="space-y-1">
                      <Label className="text-xs text-muted-foreground">Koeficijent</Label>
                      <Input value={koefForma.koeficijent} inputMode="decimal" aria-label="Novi koeficijent — vrednost"
                        onChange={(e) => koefPolje("koeficijent", e.target.value)}
                        className="h-8 text-center tabular-nums" />
                    </div>
                  </div>
                  <div className="flex justify-end gap-2">
                    <Button variant="outline" size="sm" onClick={() => { setKoefDodajOpen(false); setKoefForma(emptyKoefForma); }}>
                      Otkaži
                    </Button>
                    <Button size="sm" onClick={() => void sacuvajKoef()} disabled={koefSnima}>
                      {koefSnima && <Loader2 className="h-4 w-4 animate-spin" />}
                      Dodaj
                    </Button>
                  </div>
                </div>
              )}
            </div>
          )}
          <DialogFooter>
            {!koefDodajOpen && (
              <Button variant="outline" onClick={() => { setKoefDodajOpen(true); setKoefForma(emptyKoefForma); }}>
                <Plus className="h-4 w-4" />
                Dodaj koeficijent
              </Button>
            )}
            <Button variant="secondary" onClick={() => setKoefSoba(null)}>Zatvori</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirm */}
      <AlertDialog open={deleteId !== null} onOpenChange={() => setDeleteId(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Obriši sobu?</AlertDialogTitle>
            <AlertDialogDescription>Ova akcija ne može biti poništena. Soba će biti trajno obrisana.</AlertDialogDescription>
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
