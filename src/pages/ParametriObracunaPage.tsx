import { useEffect, useState } from "react";
import { Calculator, Save, Loader2, Info } from "lucide-react";
import { toast } from "sonner";
import { apiFetch } from "../lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface Parametri {
  visina_popusta: number;
  datumod1: string | null;
  datumdo1: string | null;
  koeficijent1: number | null;
  datumod2: string | null;
  datumdo2: string | null;
  koeficijent2: number | null;
}

// Forma drži sve kao string radi slobodnog unosa; pretvaranje se radi pri snimanju.
interface Forma {
  visina_popusta: string;
  datumod1: string;
  datumdo1: string;
  koeficijent1: string;
  datumod2: string;
  datumdo2: string;
  koeficijent2: string;
}

function uForme(p: Parametri): Forma {
  return {
    visina_popusta: String(p.visina_popusta ?? 0),
    datumod1: p.datumod1 ?? "",
    datumdo1: p.datumdo1 ?? "",
    koeficijent1: p.koeficijent1 != null ? String(p.koeficijent1) : "",
    datumod2: p.datumod2 ?? "",
    datumdo2: p.datumdo2 ?? "",
    koeficijent2: p.koeficijent2 != null ? String(p.koeficijent2) : "",
  };
}

export default function ParametriObracunaPage() {
  const [form, setForm] = useState<Forma | null>(null);
  const [saved, setSaved] = useState<Forma | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);
    apiFetch<Parametri>("/parametri-obracuna")
      .then((data) => {
        if (!cancelled) { const f = uForme(data); setForm(f); setSaved(f); }
      })
      .catch(() => {
        if (!cancelled) { setError(true); toast.error("Parametri obračuna nisu učitani"); }
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [retry]);

  const changed = form !== null && saved !== null && JSON.stringify(form) !== JSON.stringify(saved);

  function postavi<K extends keyof Forma>(kljuc: K, vrednost: string) {
    setForm((prev) => (prev ? { ...prev, [kljuc]: vrednost } : prev));
  }

  function validiraj(f: Forma): string | null {
    const popust = Number(f.visina_popusta.trim());
    if (f.visina_popusta.trim() === "" || !Number.isInteger(popust) || popust < 0 || popust > 100) {
      return "Visina popusta mora biti ceo broj između 0 i 100";
    }
    for (const n of ["1", "2"] as const) {
      const od = n === "1" ? f.datumod1 : f.datumod2;
      const doo = n === "1" ? f.datumdo1 : f.datumdo2;
      const koef = (n === "1" ? f.koeficijent1 : f.koeficijent2).trim().replace(",", ".");
      if (od && doo && od > doo) return `Datum početka mora biti pre ili jednak datumu kraja (${n}. period)`;
      if (koef !== "") {
        const k = Number(koef);
        if (!Number.isFinite(k) || k < 0) return `Koeficijent ${n} mora biti nenegativan broj`;
      }
    }
    return null;
  }

  async function sacuvaj() {
    if (!form) return;
    const greska = validiraj(form);
    if (greska) { toast.error(greska); return; }
    const broj = (s: string) => {
      const t = s.trim().replace(",", ".");
      return t === "" ? null : Number(t);
    };
    const datum = (s: string) => (s === "" ? null : s);
    setSaving(true);
    try {
      await apiFetch("/parametri-obracuna", {
        method: "PUT",
        body: JSON.stringify({
          visina_popusta: Number(form.visina_popusta.trim()),
          datumod1: datum(form.datumod1),
          datumdo1: datum(form.datumdo1),
          koeficijent1: broj(form.koeficijent1),
          datumod2: datum(form.datumod2),
          datumdo2: datum(form.datumdo2),
          koeficijent2: broj(form.koeficijent2),
        }),
      });
      setSaved(form);
      toast.success("Parametri obračuna sačuvani");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Greška pri čuvanju");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
            <Calculator className="h-6 w-6" /> Parametri obračuna
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">Globalne vrednosti koje učestvuju u obračunu cene.</p>
        </div>
        <Button onClick={() => void sacuvaj()} disabled={loading || error || saving || !changed}>
          {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}Sačuvaj
        </Button>
      </div>

      {loading ? (
        <div className="flex justify-center p-12"><Loader2 className="h-6 w-6 animate-spin" aria-label="Učitavanje parametara" /></div>
      ) : error ? (
        <div className="rounded-xl border p-6 text-center">
          <p className="mb-3 text-muted-foreground">Parametri nisu dostupni.</p>
          <Button variant="outline" onClick={() => setRetry((n) => n + 1)}>Pokušaj ponovo</Button>
        </div>
      ) : form && (
        <>
          <section className="space-y-4 rounded-2xl border bg-card p-5 shadow-sm">
            <div className="space-y-1">
              <Label htmlFor="visina_popusta" className="text-sm font-semibold">Visina popusta (%)</Label>
              <p className="text-xs text-muted-foreground">Ceo broj od 0 do 100.</p>
            </div>
            <Input
              id="visina_popusta"
              inputMode="numeric"
              className="w-32"
              value={form.visina_popusta}
              disabled={saving}
              onChange={(e) => postavi("visina_popusta", e.target.value)}
            />
          </section>

          {([1, 2] as const).map((n) => {
            const od = n === 1 ? "datumod1" : "datumod2";
            const doo = n === 1 ? "datumdo1" : "datumdo2";
            const koef = n === 1 ? "koeficijent1" : "koeficijent2";
            return (
              <section key={n} className="space-y-4 rounded-2xl border bg-card p-5 shadow-sm">
                <div className="space-y-1">
                  <h2 className="text-sm font-semibold">{n}. period — struktura 1/1</h2>
                  <p className="text-xs text-muted-foreground">Datumi na koje se odnosi koeficijent za strukturu 1/1.</p>
                </div>
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                  <div className="space-y-2">
                    <Label htmlFor={`datumod${n}`}>Datum od</Label>
                    <Input id={`datumod${n}`} type="date" value={form[od]} disabled={saving} onChange={(e) => postavi(od, e.target.value)} />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor={`datumdo${n}`}>Datum do</Label>
                    <Input id={`datumdo${n}`} type="date" value={form[doo]} disabled={saving} onChange={(e) => postavi(doo, e.target.value)} />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor={`koeficijent${n}`}>Koeficijent</Label>
                    <Input id={`koeficijent${n}`} inputMode="decimal" placeholder="npr. 1.25" value={form[koef]} disabled={saving} onChange={(e) => postavi(koef, e.target.value)} />
                  </div>
                </div>
              </section>
            );
          })}
        </>
      )}

      <div className="flex items-start gap-3 rounded-xl border bg-muted/40 p-4 text-sm text-muted-foreground">
        <Info className="mt-0.5 h-4 w-4 shrink-0" />
        <p>{changed ? "Imate nesačuvane izmene." : "Prikazane su sačuvane vrednosti iz baze."}</p>
      </div>
    </div>
  );
}
