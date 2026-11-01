import { useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { apiFetch } from "@/lib/api";
import type { DodatnaStavka, DodatnaUslugaKatalog } from "@/types";

const BEZ_KATALOGA = "nema";

function formatIznos(value: number | null | undefined): string {
  return value == null ? "" : String(value).replace(".", ",");
}

function iznos(value: string): number | null {
  const clean = value.trim().replace(",", ".");
  if (!clean) return null;
  if (!/^-?\d+(?:\.\d{1,2})?$/.test(clean) || !Number.isFinite(Number(clean))) {
    throw new Error("Iznos mora biti broj sa najviše dve decimale (npr. -12,50).");
  }
  return Number(clean);
}

export function DodatnaStavkaForma({ ugovor, original, onSaved, onCancel }: {
  ugovor: string;
  original: DodatnaStavka | null;
  onSaved: (stavka: DodatnaStavka) => void;
  onCancel: () => void;
}) {
  const [usluga, setUsluga] = useState(original?.usluga ?? "");
  const [eur, setEur] = useState(formatIznos(original?.eur));
  const [din, setDin] = useState(formatIznos(original?.din));
  const [katalogId, setKatalogId] = useState<number | null>(original?.dodatna_usluga_id ?? null);
  const [katalog, setKatalog] = useState<DodatnaUslugaKatalog[]>([]);
  const [saving, setSaving] = useState(false);
  const lock = useRef(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    apiFetch<DodatnaUslugaKatalog[]>("/dodatne-usluge")
      .then((rows) => { if (mounted.current) setKatalog(rows); })
      .catch(() => { if (mounted.current) setKatalog([]); });
    return () => { mounted.current = false; };
  }, []);
  function izaberiIzKataloga(value: string) {
    if (value === BEZ_KATALOGA) {
      setKatalogId(null);
      return;
    }
    const id = Number(value);
    const stavka = katalog.find((k) => k.id === id);
    setKatalogId(id);
    if (stavka) {
      setUsluga(stavka.naziv);
      setEur(formatIznos(stavka.iznos_eur));
      setDin(formatIznos(stavka.iznos_din));
    }
  }
  async function save() {
    if (lock.current) return;
    try {
      if (!usluga.trim() || usluga.trim().length > 150) throw new Error("Unesite naziv usluge (do 150 znakova).");
      const body = { usluga: usluga.trim(), eur: iznos(eur), din: iznos(din), dodatna_usluga_id: katalogId,
        ...(original ? { original: { usluga: original.usluga, eur: original.eur, din: original.din } } : {}) };
      lock.current = true;
      setSaving(true);
      const path = `/ugovori/${encodeURIComponent(ugovor)}/dodatne${original ? `/${original.stavka_id}` : ""}`;
      const result = await apiFetch<DodatnaStavka>(path, { method: original ? "PATCH" : "POST", body: JSON.stringify(body) });
      if (mounted.current) onSaved(result);
      toast.success(original ? "Dodatna stavka je izmenjena" : "Dodatna stavka je dodata", { description: `Ugovor: ${ugovor}` });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Stavka nije sačuvana");
    } finally {
      lock.current = false;
      if (mounted.current) setSaving(false);
    }
  }
  return (
    <div className="space-y-3 border-b bg-muted/20 p-4">
      <p className="text-sm font-semibold">{original ? "Izmena dodatne stavke" : "Nova dodatna stavka"}</p>
      <div className="space-y-1">
        <Label htmlFor="dodatna-katalog">Iz kataloga (opciono)</Label>
        <Select value={katalogId == null ? BEZ_KATALOGA : String(katalogId)} onValueChange={izaberiIzKataloga} disabled={saving}>
          <SelectTrigger id="dodatna-katalog" className="md:w-[360px]"><SelectValue placeholder="Slobodan unos" /></SelectTrigger>
          <SelectContent>
            <SelectItem value={BEZ_KATALOGA}>Slobodan unos</SelectItem>
            {katalog.map((k) => (
              <SelectItem key={k.id} value={String(k.id)}>{k.naziv}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="grid gap-3 md:grid-cols-[2fr_1fr_1fr]">
        <div className="space-y-1"><Label htmlFor="dodatna-usluga">Usluga</Label><Input id="dodatna-usluga" value={usluga} maxLength={150} disabled={saving} onChange={(e) => setUsluga(e.target.value)} placeholder="Naziv usluge" /></div>
        <div className="space-y-1"><Label htmlFor="dodatna-eur">EUR</Label><Input id="dodatna-eur" inputMode="decimal" value={eur} disabled={saving} onChange={(e) => setEur(e.target.value)} placeholder="0,00" /></div>
        <div className="space-y-1"><Label htmlFor="dodatna-din">RSD</Label><Input id="dodatna-din" inputMode="decimal" value={din} disabled={saving} onChange={(e) => setDin(e.target.value)} placeholder="0,00" /></div>
      </div>
      <div className="flex gap-2">
        <Button type="button" size="sm" disabled={saving} onClick={save}>{saving && <Loader2 className="size-4 animate-spin" />}{saving ? "Snimanje…" : "Sačuvaj stavku"}</Button>
        <Button type="button" size="sm" variant="outline" disabled={saving} onClick={onCancel}>Otkaži</Button>
      </div>
    </div>
  );
}
