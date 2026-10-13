import { useEffect, useState } from "react";
import { Palette, Save, Loader2, Info } from "lucide-react";
import { toast } from "sonner";
import { apiFetch } from "../lib/api";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const BOJE = [
  { value: "zelena", label: "Zelena", css: "bg-green-600" },
  { value: "plava", label: "Plava", css: "bg-blue-600" },
  { value: "crvena", label: "Crvena", css: "bg-red-600" },
  { value: "zuta", label: "Žuta", css: "bg-yellow-400" },
  { value: "ljubicasta", label: "Ljubičasta", css: "bg-purple-600" },
  { value: "narandzasta", label: "Narandžasta", css: "bg-orange-500" },
  { value: "crna", label: "Crna", css: "bg-black" },
  { value: "roze", label: "Roze", css: "bg-pink-500" },
] as const;
type Boja = typeof BOJE[number]["value"];
const STAVKE = [
  { key: "isplacen", label: "Isplaćen aranžman", opis: "SALDO manji od 400 RSD" },
  { key: "predrezervacija_aktivna", label: "Predrezervacija — nije istekao time limit", opis: "Predrezervacija sa važećim rokom" },
  { key: "predrezervacija_istekla", label: "Predrezervacija — istekao time limit", opis: "Predrezervacija kojoj je rok istekao" },
  { key: "blok", label: "BLOK", opis: "Blokiran smeštaj" },
  { key: "saldo_veci", label: "Aranžman — SALDO 400 RSD ili više", opis: "Aranžman sa preostalim dugovanjem" },
  { key: "predrezervacija_subagent", label: "Predrezervacija subagent", opis: "Predrezervacija preko subagenta" },
] as const;
type Podesavanja = Record<typeof STAVKE[number]["key"], Boja>;

export default function BojeGrafikPage() {
  const [form, setForm] = useState<Podesavanja | null>(null);
  const [saved, setSaved] = useState<Podesavanja | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);
    apiFetch<Podesavanja>("/boje-grafik").then((data) => {
      if (!cancelled) { setForm(data); setSaved(data); }
    }).catch(() => {
      if (!cancelled) { setError(true); toast.error("Boje grafika nisu učitane"); }
    }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [retry]);
  const changed = !!form && STAVKE.some(({ key }) => form[key] !== saved?.[key]);
  async function sacuvaj() {
    if (!form || saving) return;
    setSaving(true);
    try {
      const data = await apiFetch<Podesavanja>("/boje-grafik", { method: "PUT", body: JSON.stringify(form) });
      setForm(data); setSaved(data);
      toast.success("Boje grafika su sačuvane u bazu");
    } catch { toast.error("Čuvanje boja nije uspelo. Pokušajte ponovo."); }
    finally { setSaving(false); }
  }
  return (
    <div className="mx-auto max-w-4xl space-y-6 p-4 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight"><Palette className="h-6 w-6" />Boje grafik</h1>
          <p className="mt-1 text-sm text-muted-foreground">Podesite boju za svaku kategoriju rezervacije.</p>
        </div>
        <Button onClick={() => void sacuvaj()} disabled={loading || error || saving || !changed}>
          {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}Sačuvaj
        </Button>
      </div>
      <div className="flex items-start gap-3 rounded-xl border bg-muted/40 p-4 text-sm text-muted-foreground">
        <Info className="mt-0.5 h-4 w-4 shrink-0" />
        <p>Sačuvane boje primenjuju se pri sledećem učitavanju Grafika. Prioritet: BLOK → predrezervacija subagenta → time limit → saldo. Predrezervacija bez time limita smatra se isteklom.</p>
      </div>
      {loading ? <div className="flex justify-center p-12"><Loader2 className="h-6 w-6 animate-spin" aria-label="Učitavanje boja" /></div> : error ? (
        <div className="rounded-xl border p-6 text-center"><p className="mb-3 text-muted-foreground">Podešavanja nisu dostupna.</p><Button variant="outline" onClick={() => setRetry((n) => n + 1)}>Pokušaj ponovo</Button></div>
      ) : form && (
        <div className="overflow-hidden rounded-2xl border bg-card shadow-sm">
          {STAVKE.map(({ key, label, opis }) => (
            <div key={key} className="flex flex-col gap-3 border-b p-5 last:border-b-0 sm:flex-row sm:items-center sm:justify-between">
              <div className="space-y-1"><Label htmlFor={key} className="text-sm font-semibold">{label}</Label><p className="text-xs text-muted-foreground">{opis}</p></div>
              <Select value={form[key]} disabled={saving} onValueChange={(value) => setForm((prev) => prev ? { ...prev, [key]: value as Boja } : prev)}>
                <SelectTrigger id={key} className="w-full sm:w-48"><SelectValue placeholder="Izaberite boju" /></SelectTrigger>
                <SelectContent>{BOJE.map((boja) => <SelectItem key={boja.value} value={boja.value}><span className="flex items-center gap-2"><span aria-hidden="true" className={`h-3.5 w-3.5 rounded-full border border-black/10 ${boja.css}`} />{boja.label}</span></SelectItem>)}</SelectContent>
              </Select>
            </div>
          ))}
        </div>
      )}
      {form && !loading && !error && <p className="text-xs text-muted-foreground" role="status">{changed ? "Imate nesačuvane izmene." : "Prikazane su sačuvane boje iz baze."}</p>}
    </div>
  );
}
