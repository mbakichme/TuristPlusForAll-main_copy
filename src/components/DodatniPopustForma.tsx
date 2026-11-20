import { useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiFetch } from "@/lib/api";
import type { DodatniPopust } from "@/types";

function formatIznos(value: number | null | undefined): string {
  return value == null ? "" : String(value).replace(".", ",");
}

// prazno = null; inače nenegativan broj sa najviše dve decimale (zarez ili tačka)
function iznos(value: string): number | null {
  const clean = value.trim().replace(",", ".");
  if (!clean) return null;
  if (!/^\d+(?:\.\d{1,2})?$/.test(clean)) {
    throw new Error("Iznos mora biti nenegativan broj sa najviše dve decimale (npr. 12,50).");
  }
  return Number(clean);
}

export function DodatniPopustForma({ ugovor, original, brutoEUR, onSaved, onCancel, onUzivo }: {
  ugovor: string;
  original: DodatniPopust | null;
  /** bruto smeštaj iz forme rezervacije (uživo) — osnova za procenat */
  brutoEUR: number;
  onSaved: (popust: DodatniPopust) => void;
  onCancel: () => void;
  /** uživo procenat (null = nema procenta) — roditelj ga odmah uračunava u UKUPNO */
  onUzivo?: (procenat: number | null) => void;
}) {
  const [naziv, setNaziv] = useState(original?.naziv ?? "");
  const [procenat, setProcenat] = useState(formatIznos(original?.procenat));
  const [eur, setEur] = useState(original?.procenat != null ? "" : formatIznos(original?.eur));
  const [saving, setSaving] = useState(false);
  const lock = useRef(false);

  // uživo iznos iz procenta (ne čeka snimanje)
  const pctBroj = (() => { try { return iznos(procenat); } catch { return null; } })();
  const pretEUR = pctBroj != null && pctBroj > 0 ? (brutoEUR * pctBroj) / 100 : null;
  const nf = new Intl.NumberFormat("sr-RS", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  useEffect(() => {
    onUzivo?.(pctBroj != null && pctBroj > 0 && pctBroj <= 100 ? pctBroj : null);
  }, [pctBroj, onUzivo]);
  useEffect(() => () => onUzivo?.(null), [onUzivo]);

  async function save() {
    if (lock.current) return;
    let body: { naziv: string; eur: number | null; rsd: number | null; procenat: number | null };
    try {
      if (!naziv.trim()) throw new Error("Unesite naziv popusta.");
      const p = iznos(procenat);
      const e = iznos(eur);
      if (p != null) {
        if (!(p > 0 && p <= 100)) throw new Error("Procenat mora biti između 0 i 100.");
        if ((e ?? 0) > 0) throw new Error("Unesite ili procenat ili iznos, ne oba.");
        body = { naziv: naziv.trim(), procenat: p, eur: null, rsd: null };
      } else {
        if (!(e && e > 0)) throw new Error("Unesite procenat ili iznos u EUR.");
        // RSD se za sada ne računa — šalje se 0
        body = { naziv: naziv.trim(), procenat: null, eur: e, rsd: 0 };
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Popust nije sačuvan");
      return;
    }
    lock.current = true;
    setSaving(true);
    try {
      const path = original
        ? `/ugovori/${encodeURIComponent(ugovor)}/dodatni-popusti/${original.id}`
        : `/ugovori/${encodeURIComponent(ugovor)}/dodatni-popusti`;
      const result = await apiFetch<DodatniPopust>(path, { method: original ? "PATCH" : "POST", body: JSON.stringify(body) });
      onSaved(result);
      toast.success(original ? "Dodatni popust je izmenjen" : "Dodatni popust je dodat", { description: `Ugovor: ${ugovor}` });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Popust nije sačuvan");
    } finally {
      lock.current = false;
      setSaving(false);
    }
  }

  return (
    <div className="space-y-3 border-b bg-muted/20 p-4">
      <p className="text-sm font-semibold">{original ? "Izmena dodatnog popusta" : "Novi dodatni popust"}</p>
      <div className="grid gap-3 md:grid-cols-[2fr_1fr_1fr]">
        <div className="space-y-1"><Label htmlFor="dp-naziv">Naziv</Label><Input id="dp-naziv" value={naziv} maxLength={150} disabled={saving} onChange={(e) => setNaziv(e.target.value)} placeholder="Naziv popusta" /></div>
        <div className="space-y-1"><Label htmlFor="dp-procenat">Procenat (%)</Label><Input id="dp-procenat" inputMode="decimal" value={procenat} disabled={saving} onChange={(e) => setProcenat(e.target.value)} placeholder="0" />
          {pretEUR != null && <p className="text-xs text-muted-foreground" data-testid="dp-pretprikaz">= {nf.format(pretEUR)} €</p>}
        </div>
        <div className="space-y-1"><Label htmlFor="dp-eur">EUR</Label><Input id="dp-eur" inputMode="decimal" value={eur} disabled={saving} onChange={(e) => setEur(e.target.value)} placeholder="0,00" /></div>
      </div>
      <p className="text-xs text-muted-foreground">Ili procenat od bruto smeštaja, ili fiksni iznos u EUR.</p>
      <div className="flex gap-2">
        <Button type="button" size="sm" disabled={saving} onClick={save}>{saving && <Loader2 className="size-4 animate-spin" />}{saving ? "Snimanje…" : "Sačuvaj popust"}</Button>
        <Button type="button" size="sm" variant="outline" disabled={saving} onClick={onCancel}>Otkaži</Button>
      </div>
    </div>
  );
}
