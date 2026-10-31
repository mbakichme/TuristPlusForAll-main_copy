import { useState, useEffect, useMemo } from "react";
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
import { Plus, Pencil, Trash2, Loader2, Armchair, Search, Wand2 } from "lucide-react";
import { toast } from "sonner";

interface PrevozLimit {
  id: number;
  naziv: string;
  drzava_id: number | null;
  drzava_naziv: string | null;
  destinacija_id: number | null;
  destinacija_naziv: string | null;
  mesto_id: number | null;
  mesto_naziv: string | null;
  grupa_datuma_id: number | null;
  grupa_datuma_naziv: string | null;
  datum: string | null; // ISO yyyy-mm-dd
  smer: string;
  limit: number;
  dodatna_mesta: number;
  ukupno: number;
}

interface Drzava { id: number; naziv: string }
interface Destinacija { id: number; naziv: string; drzava: number | null }
interface Mesto { id: number; naziv: string; destinacija: number | null; grupa_datuma: number | null; grupe: number[] }
interface Grupa { id: number; naziv: string }

interface FormState {
  drzava_id: string;
  destinacija_id: string;
  mesto_id: string;
  grupa_datuma_id: string;
  datum: string; // yyyy-mm-dd
  smer: string;
  limit: string;
  dodatna_mesta: string;
}

const NISTA = "nista";
const SMEROVI = ["Odlazak", "Povratak"];
const prazno: FormState = {
  drzava_id: NISTA, destinacija_id: NISTA, mesto_id: NISTA, grupa_datuma_id: NISTA,
  datum: "", smer: "Odlazak", limit: "", dodatna_mesta: "0",
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

interface IzborProps {
  label: string;
  value: string;
  onChange: (v: string) => void;
  opcije: { id: number; naziv: string }[];
  placeholder: string;
  disabled?: boolean;
}

function Izbor({ label, value, onChange, opcije, placeholder, disabled }: IzborProps) {
  return (
    <div className="space-y-1">
      <Label className="text-xs">{label}</Label>
      <Select value={value} onValueChange={onChange} disabled={disabled}>
        <SelectTrigger aria-label={label} className="h-9"><SelectValue placeholder={placeholder} /></SelectTrigger>
        <SelectContent>
          {opcije.map((o) => (
            <SelectItem key={o.id} value={String(o.id)}>{o.naziv}</SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

export default function PrevozLimitiPage() {
  const [items, setItems] = useState<PrevozLimit[]>([]);
  const [drzave, setDrzave] = useState<Drzava[]>([]);
  const [destinacije, setDestinacije] = useState<Destinacija[]>([]);
  const [mesta, setMesta] = useState<Mesto[]>([]);
  const [grupe, setGrupe] = useState<Grupa[]>([]);
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

  useEffect(() => {
    const t = setTimeout(() => { void ucitaj(q.trim()); }, 300);
    return () => clearTimeout(t);
  }, [q]);

  useEffect(() => {
    apiFetch<Drzava[]>("/drzava").then(setDrzave).catch(() => {});
    apiFetch<Destinacija[]>("/destinacija").then(setDestinacije).catch(() => {});
    apiFetch<Mesto[]>("/mesto").then(setMesta).catch(() => {});
    apiFetch<Grupa[]>("/period-grupa").then(setGrupe).catch(() => {});
  }, []);

  // ── Zavisna polja: država → destinacija → mesto → grupa termina ──
  const destZaDrzavu = useMemo(
    () => destinacije.filter((d) => String(d.drzava) === form.drzava_id),
    [destinacije, form.drzava_id],
  );
  const mestaZaDest = useMemo(
    () => mesta.filter((m) => String(m.destinacija) === form.destinacija_id),
    [mesta, form.destinacija_id],
  );
  const grupeZaMesto = useMemo(() => {
    const m = mesta.find((x) => String(x.id) === form.mesto_id);
    if (!m) return [];
    const ids = new Set<number>(m.grupe ?? []);
    if (m.grupa_datuma != null) ids.add(m.grupa_datuma);
    return grupe.filter((g) => ids.has(g.id));
  }, [mesta, grupe, form.mesto_id]);

  // Promena roditelja resetuje decu (izbor mora ostati u skladu sa hijerarhijom)
  function izaberiDrzavu(v: string) {
    setForm({ ...form, drzava_id: v, destinacija_id: NISTA, mesto_id: NISTA, grupa_datuma_id: NISTA });
  }
  function izaberiDestinaciju(v: string) {
    setForm({ ...form, destinacija_id: v, mesto_id: NISTA, grupa_datuma_id: NISTA });
  }
  function izaberiMesto(v: string) {
    setForm({ ...form, mesto_id: v, grupa_datuma_id: NISTA });
  }

  const nazivPregled = useMemo(() => {
    const dr = drzave.find((x) => String(x.id) === form.drzava_id)?.naziv;
    const de = destinacije.find((x) => String(x.id) === form.destinacija_id)?.naziv;
    const me = mesta.find((x) => String(x.id) === form.mesto_id)?.naziv;
    const gr = grupe.find((x) => String(x.id) === form.grupa_datuma_id)?.naziv;
    if (!dr || !de || !me || !gr || !form.datum) return "";
    return `${dr}-${de}-${me}-${gr}-${datumSr(form.datum)}`;
  }, [drzave, destinacije, mesta, grupe, form]);

  function otvoriNovi() {
    setEditing(null);
    setForm(prazno);
    setDialogOpen(true);
  }

  function otvoriIzmenu(r: PrevozLimit) {
    setEditing(r);
    setForm({
      drzava_id: r.drzava_id != null ? String(r.drzava_id) : NISTA,
      destinacija_id: r.destinacija_id != null ? String(r.destinacija_id) : NISTA,
      mesto_id: r.mesto_id != null ? String(r.mesto_id) : NISTA,
      grupa_datuma_id: r.grupa_datuma_id != null ? String(r.grupa_datuma_id) : NISTA,
      datum: r.datum ?? "",
      smer: r.smer,
      limit: String(r.limit),
      dodatna_mesta: String(r.dodatna_mesta),
    });
    setDialogOpen(true);
  }

  async function snimi() {
    if (saving) return;
    if (form.drzava_id === NISTA || form.destinacija_id === NISTA || form.mesto_id === NISTA
        || form.grupa_datuma_id === NISTA || !form.datum) {
      toast.error("Izaberite državu, destinaciju, mesto, grupu termina i datum");
      return;
    }
    const limit = celBroj(form.limit, false);
    if (limit == null) { toast.error("Limit mora biti ceo broj 0 ili veći"); return; }
    const dodatna = celBroj(form.dodatna_mesta, true);
    if (dodatna == null) { toast.error("Dodatna mesta moraju biti ceo broj (može i negativan)"); return; }

    const body = {
      drzava_id: Number(form.drzava_id),
      destinacija_id: Number(form.destinacija_id),
      mesto_id: Number(form.mesto_id),
      grupa_datuma_id: Number(form.grupa_datuma_id),
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
      const r = await apiFetch<{ dodato: number; postojeci: number; preskoceno: number }>(
        "/prevoz-limit/generisi", { method: "POST" },
      );
      toast.success(`Dodato ${r.dodato}, već postoji ${r.postojeci}${r.preskoceno ? `, preskočeno ${r.preskoceno} (nedostaje destinacija ili država)` : ""}`);
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
              placeholder="Pretraga: država, destinacija, mesto, grupa, smer…"
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
                  <TableHead>Naziv</TableHead>
                  <TableHead>Država</TableHead>
                  <TableHead>Destinacija</TableHead>
                  <TableHead>Mesto</TableHead>
                  <TableHead>Grupa termina</TableHead>
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
                    <TableCell className="text-xs text-muted-foreground max-w-[260px] truncate" title={r.naziv}>{r.naziv}</TableCell>
                    <TableCell>{r.drzava_naziv ?? "—"}</TableCell>
                    <TableCell>{r.destinacija_naziv ?? "—"}</TableCell>
                    <TableCell>{r.mesto_naziv ?? "—"}</TableCell>
                    <TableCell>{r.grupa_datuma_naziv ?? "—"}</TableCell>
                    <TableCell className="tabular-nums">{datumSr(r.datum)}</TableCell>
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
            <DialogDescription>
              Svako polje sužava sledeće: izaberite državu pa destinaciju, mesto i grupu termina.
            </DialogDescription>
          </DialogHeader>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <Izbor label="Država" placeholder="Izaberite državu" value={form.drzava_id}
              onChange={izaberiDrzavu} opcije={drzave} />
            <Izbor label="Destinacija" placeholder={form.drzava_id === NISTA ? "Prvo izaberite državu" : "Izaberite destinaciju"}
              value={form.destinacija_id} onChange={izaberiDestinaciju} opcije={destZaDrzavu}
              disabled={form.drzava_id === NISTA} />
            <Izbor label="Mesto" placeholder={form.destinacija_id === NISTA ? "Prvo izaberite destinaciju" : "Izaberite mesto"}
              value={form.mesto_id} onChange={izaberiMesto} opcije={mestaZaDest}
              disabled={form.destinacija_id === NISTA} />
            <Izbor label="Grupa termina" placeholder={form.mesto_id === NISTA ? "Prvo izaberite mesto" : "Izaberite grupu termina"}
              value={form.grupa_datuma_id}
              onChange={(v) => setForm({ ...form, grupa_datuma_id: v })} opcije={grupeZaMesto}
              disabled={form.mesto_id === NISTA} />
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
            <p className="sm:col-span-2 text-xs text-muted-foreground break-all">
              Naziv: {nazivPregled || "— biće određen izborom veza i datuma"}
            </p>
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
              „{deleteItem?.naziv}“ biće trajno obrisan.
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
