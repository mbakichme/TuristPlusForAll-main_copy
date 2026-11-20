import { useState, useEffect, useMemo } from "react";
import type { Soba, Smestaj } from "../types";
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
  opis_ugovor: string;
}

const OPIS_UGOVOR_OPCIJE = [
  "Direktan pogled more", "Bočni pogled more", "Economy", "Economy UT", "Economy IT",
  "Economy ZT", "Economy PT", "Economy PZ", "Economy MTPZ", "Economy VTPZ", "Graden",
];

const emptyForm: SobaForm = { veza_id_smestaj: "", broj_sobe: "", tip: "", status: "1", opis: "", opis_dodatno: "", veliki_opis: "", opis_ugovor: "" };

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

  // Koeficijenti sobe (dialog): osnovni naziv = tip sobe + dodatni definisani nazivi
  const [koefSoba, setKoefSoba] = useState<Soba | null>(null);
  const [koefTip, setKoefTip] = useState("");
  const [koefDodati, setKoefDodati] = useState<string[]>([]);
  const [koefOpcije, setKoefOpcije] = useState<string[]>([]); // definisani koeficijenti (nazivi)
  const [koefLoading, setKoefLoading] = useState(false);
  const [koefNova, setKoefNova] = useState("");
  const [koefDodajOpen, setKoefDodajOpen] = useState(false);
  const [koefSnima, setKoefSnima] = useState(false);
  const [koefBrise, setKoefBrise] = useState<string | null>(null);

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
      [b.broj_sobe, b.tip, b.opis, b.opis_dodatno, b.veliki_opis, b.smestaj_naziv, b.mesto_naziv, b.grupa_datuma_naziv]
        .some((v) => (v || "").toLowerCase().includes(q))
    );
  }, [items, search]);

  // ── Koeficijenti sobe: nazivi (osnovni = tip sobe) + dodatni definisani ────

  const koefDostupne = useMemo(
    () => koefOpcije.filter((s) => s !== koefTip && !koefDodati.includes(s)),
    [koefOpcije, koefTip, koefDodati],
  );

  async function ucitajKoefSobe(soba: Soba) {
    setKoefLoading(true);
    try {
      const [podaci, definisani] = await Promise.all([
        apiFetch<{ tip: string; dodati: string[] }>(`/sobe/${soba.id}/koeficijenti`),
        apiFetch<{ strukture: string[]; redovi: { struktura: string }[] }>("/koeficijenti"),
      ]);
      setKoefTip(podaci.tip);
      setKoefDodati(podaci.dodati);
      const skup = new Set(definisani.strukture);
      for (const r of definisani.redovi) if (r.struktura) skup.add(r.struktura);
      setKoefOpcije([...skup].sort((a, b) => a.localeCompare(b, "sr")));
    } catch {
      toast.error("Učitavanje koeficijenata nije uspelo");
    } finally {
      setKoefLoading(false);
    }
  }

  function otvoriKoeficijente(soba: Soba) {
    setKoefSoba(soba);
    setKoefDodajOpen(false);
    setKoefNova("");
    void ucitajKoefSobe(soba);
  }

  async function dodajKoefSobi() {
    if (!koefSoba || koefSnima || !koefNova) return;
    const struktura = koefNova;
    setKoefSnima(true);
    try {
      const d = await apiFetch<{ tip: string; dodati: string[] }>(
        `/sobe/${koefSoba.id}/koeficijenti`,
        { method: "POST", body: JSON.stringify({ struktura }) },
      );
      setKoefTip(d.tip);
      setKoefDodati(d.dodati);
      setKoefDodajOpen(false);
      setKoefNova("");
      toast.success(`Koeficijent ${struktura} je dodat sobi`);
      void load(); // osveži prikaz u koloni tabele
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Greška");
    } finally {
      setKoefSnima(false);
    }
  }

  async function obrisiKoefSobi(struktura: string) {
    if (!koefSoba || koefBrise) return;
    setKoefBrise(struktura);
    try {
      const d = await apiFetch<{ tip: string; dodati: string[] }>(
        `/sobe/${koefSoba.id}/koeficijenti?struktura=${encodeURIComponent(struktura)}`,
        { method: "DELETE" },
      );
      setKoefTip(d.tip);
      setKoefDodati(d.dodati);
      toast.success(`Koeficijent ${struktura} je uklonjen`);
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
      opis_ugovor: item.opis_ugovor || "",
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
        opis_ugovor: form.opis_ugovor,
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
          <Table className="text-xs">
            <TableHeader>
              <TableRow>
                <TableHead className="h-8 px-2 text-xs">Smeštaj</TableHead>
                <TableHead className="h-8 px-2 text-xs">Mesto</TableHead>
                <TableHead className="h-8 px-2 text-xs">Grupa termina</TableHead>
                <TableHead className="h-8 px-2 text-xs">Broj sobe</TableHead>
                <TableHead className="h-8 px-2 text-xs">Tip (opis)</TableHead>
                <TableHead className="h-8 px-2 text-xs">Koeficijenti</TableHead>
                <TableHead className="h-8 px-2 text-xs">Status</TableHead>
                <TableHead className="h-8 w-20 px-2 text-right text-xs">Akcije</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.length === 0 ? (
                <TableRow><TableCell colSpan={8} className="py-6 text-center text-xs text-muted-foreground">
                  {search.trim() ? "Nema rezultata za pretragu" : "Nema soba. Kliknite Dodaj da kreirate prvu."}
                </TableCell></TableRow>
              ) : filtered.map((item) => (
                <TableRow key={item.id}>
                  <TableCell className="px-2 py-1.5 font-medium">{item.smestaj_naziv || `#${item.veza_id_smestaj}`}</TableCell>
                  <TableCell className="px-2 py-1.5 text-muted-foreground">{item.mesto_naziv || "—"}</TableCell>
                  <TableCell className="px-2 py-1.5">{item.grupa_datuma_naziv || <span className="text-muted-foreground">—</span>}</TableCell>
                  <TableCell className="px-2 py-1.5">
                    <span className="inline-flex min-w-8 items-center justify-center rounded-md border border-primary/40 bg-primary/10 px-2 py-0.5 font-mono text-sm font-bold text-primary">
                      {item.broj_sobe || "—"}
                    </span>
                  </TableCell>
                  <TableCell className="max-w-xs truncate px-2 py-1.5" title={item.tip && item.opis ? `${item.tip} (${item.opis})` : item.tip || item.opis || undefined}>
                    {item.tip && item.opis ? (
                      <>{item.tip} <span className="text-muted-foreground">({item.opis})</span></>
                    ) : item.tip || item.opis ? (
                      item.tip || item.opis
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell className="px-2 py-1.5">
                    {item.tip?.trim() ? (
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-6 gap-1 px-2 text-xs"
                        aria-label={`Koeficijenti — soba ${item.broj_sobe || item.id}`}
                        onClick={() => otvoriKoeficijente(item)}
                      >
                        <Sigma className="h-3 w-3 text-muted-foreground" />
                        <span className="tabular-nums">
                          {item.koeficijenti && item.koeficijenti.length > 0
                            ? item.koeficijenti.join(" · ")
                            : "—"}
                        </span>
                      </Button>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell className="px-2 py-1.5">
                    <Badge variant={item.status === 1 ? "default" : "secondary"} className="px-1.5 py-0 text-[10px]">
                      {item.status === 1 ? "Aktivan" : "Neaktivan"}
                    </Badge>
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
              <Label>Opis za ugovor</Label>
              <Select value={form.opis_ugovor || "_nema"} onValueChange={(v) => setField("opis_ugovor", v === "_nema" ? "" : v)}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="_nema">— nije izabran —</SelectItem>
                  {OPIS_UGOVOR_OPCIJE.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}
                </SelectContent>
              </Select>
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
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>
              Koeficijenti — {koefSoba?.smestaj_naziv}{koefSoba?.broj_sobe ? ` · ${koefSoba.broj_sobe}` : ""}
            </DialogTitle>
            <DialogDescription>
              Osnovni koeficijent prati strukturu sobe. Dodatni koeficijenti se biraju iz već
              definisanih na stranici Koeficijenti prodaje.
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
                      <th className="px-3 py-2 text-left font-medium">Koeficijent</th>
                      <th className="w-24 px-3 py-2 text-center font-medium">Vrsta</th>
                      <th className="w-12 px-2 py-2"><span className="sr-only">Akcije</span></th>
                    </tr>
                  </thead>
                  <tbody>
                    {koefTip && (
                      <tr className="border-b last:border-b-0 hover:bg-muted/20">
                        <td className="px-3 py-1.5 font-medium tabular-nums">{koefTip}</td>
                        <td className="px-3 py-1.5 text-center"><Badge variant="secondary">Osnovni</Badge></td>
                        <td />
                      </tr>
                    )}
                    {koefDodati.map((s) => (
                      <tr key={s} className="border-b last:border-b-0 hover:bg-muted/20">
                        <td className="px-3 py-1.5 font-medium tabular-nums">{s}</td>
                        <td className="px-3 py-1.5 text-center"><Badge variant="outline">Dodatni</Badge></td>
                        <td className="px-2 py-1.5 text-center">
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-7 w-7 text-muted-foreground hover:text-destructive"
                            aria-label={`Ukloni koeficijent ${s}`}
                            onClick={() => void obrisiKoefSobi(s)}
                            disabled={koefBrise !== null}
                          >
                            {koefBrise === s
                              ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                              : <Trash2 className="h-3.5 w-3.5" />}
                          </Button>
                        </td>
                      </tr>
                    ))}
                    {!koefTip && koefDodati.length === 0 && (
                      <tr>
                        <td colSpan={3} className="px-3 py-6 text-center text-muted-foreground">
                          Nema koeficijenata.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>

              {koefDodajOpen && (
                <div className="space-y-3 rounded-lg border p-3">
                  <div className="space-y-1.5">
                    <Label className="text-xs text-muted-foreground">Koeficijent (naziv)</Label>
                    <Select value={koefNova} onValueChange={setKoefNova} disabled={koefSnima}>
                      <SelectTrigger className="h-9 w-full bg-background" aria-label="Novi koeficijent — naziv">
                        <SelectValue
                          placeholder={koefDostupne.length ? "Izaberite koeficijent" : "Nema dostupnih koeficijenata"}
                        />
                      </SelectTrigger>
                      <SelectContent>
                        {koefDostupne.length === 0 ? (
                          <SelectItem value="_nema" disabled>Svi definisani koeficijenti su već dodati</SelectItem>
                        ) : (
                          koefDostupne.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)
                        )}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="flex justify-end gap-2">
                    <Button variant="outline" size="sm" onClick={() => { setKoefDodajOpen(false); setKoefNova(""); }}>
                      Otkaži
                    </Button>
                    <Button size="sm" onClick={() => void dodajKoefSobi()} disabled={koefSnima || !koefNova}>
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
              <Button
                variant="outline"
                onClick={() => { setKoefDodajOpen(true); setKoefNova(koefDostupne[0] ?? ""); }}
              >
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
