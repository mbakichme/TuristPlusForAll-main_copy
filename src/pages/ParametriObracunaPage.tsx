import { useEffect, useState } from "react";
import { Calculator, Save, Loader2, Info } from "lucide-react";
import { toast } from "sonner";
import { apiFetch } from "../lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface Parametri {
  visina_popusta: number;
  visina_provizije: number;
  donja_platforma_eur: number;
  gornja_platforma_eur: number;
  dole_za_stolom_eur: number;
  dole_zadnji_red_eur: number;
  gore_izlog_eur: number;
  gore_sto_eur: number;
  sarage_eur: number;
  datumod1: string | null;
  datumdo1: string | null;
  koeficijent1: number | null;
  datumod2: string | null;
  datumdo2: string | null;
  koeficijent2: number | null;
}

type KljucSedenja = "donja_platforma_eur" | "gornja_platforma_eur" | "dole_za_stolom_eur"
  | "dole_zadnji_red_eur" | "gore_izlog_eur" | "gore_sto_eur" | "sarage_eur";

const MESTA_SEDENJA: { kljuc: KljucSedenja; naziv: string }[] = [
  { kljuc: "donja_platforma_eur", naziv: "Donja platforma" },
  { kljuc: "gornja_platforma_eur", naziv: "Gornja platforma" },
  { kljuc: "dole_za_stolom_eur", naziv: "Dole za stolom" },
  { kljuc: "dole_zadnji_red_eur", naziv: "Dole zadnji red" },
  { kljuc: "gore_izlog_eur", naziv: "Gore izlog" },
  { kljuc: "gore_sto_eur", naziv: "Gore sto" },
  { kljuc: "sarage_eur", naziv: "Šarage" },
];

// Forma drži sve kao string radi slobodnog unosa; pretvaranje se radi pri snimanju.
interface Forma {
  visina_popusta: string;
  visina_provizije: string;
  datumod1: string;
  datumdo1: string;
  koeficijent1: string;
  datumod2: string;
  datumdo2: string;
  koeficijent2: string;
  donja_platforma_eur: string;
  gornja_platforma_eur: string;
  dole_za_stolom_eur: string;
  dole_zadnji_red_eur: string;
  gore_izlog_eur: string;
  gore_sto_eur: string;
  sarage_eur: string;
}

function uForme(p: Parametri): Forma {
  return {
    visina_popusta: String(p.visina_popusta ?? 0),
    visina_provizije: String(p.visina_provizije ?? 10),
    ...Object.fromEntries(MESTA_SEDENJA.map(({ kljuc }) => [kljuc, String(p[kljuc] ?? 0)])) as Pick<Forma, KljucSedenja>,
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
    const provizija = Number(f.visina_provizije.trim());
    if (f.visina_provizije.trim() === "" || !Number.isInteger(provizija) || provizija < 0 || provizija > 100) {
      return "Visina provizije mora biti ceo broj između 0 i 100";
    }
    const platforme = MESTA_SEDENJA.map(({ kljuc, naziv }) => {
      const t = f[kljuc].trim().replace(",", ".");
      return { naziv, ok: t !== "" && Number.isFinite(Number(t)) && Number(t) >= 0 };
    });
    const nevalidna = platforme.find((p) => !p.ok);
    if (nevalidna) return `Doplata za „${nevalidna.naziv}" mora biti nenegativan broj`;
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
          visina_provizije: Number(form.visina_provizije.trim()),
          ...Object.fromEntries(MESTA_SEDENJA.map(({ kljuc }) => [kljuc, Number(form[kljuc].trim().replace(",", "."))])),
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

          <section className="space-y-4 rounded-2xl border bg-card p-5 shadow-sm">
            <div className="space-y-1">
              <Label htmlFor="visina_provizije" className="text-sm font-semibold">Visina provizije (%)</Label>
              <p className="text-xs text-muted-foreground">
                Ceo broj od 0 do 100. Primenjuje se na subagenta kada popust na smeštaj premašuje visinu popusta.
              </p>
            </div>
            <Input
              id="visina_provizije"
              inputMode="numeric"
              className="w-32"
              value={form.visina_provizije}
              disabled={saving}
              onChange={(e) => postavi("visina_provizije", e.target.value)}
            />
          </section>

          <section className="space-y-4 rounded-2xl border bg-card p-5 shadow-sm">
            <div className="space-y-1">
              <h2 className="text-sm font-semibold">Mesta za sedenje — doplata (EUR)</h2>
              <p className="text-xs text-muted-foreground">Doplata za izbor mesta za sedenje; važi za sve.</p>
            </div>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              {MESTA_SEDENJA.map(({ kljuc, naziv }) => (
                <div key={kljuc} className="space-y-2">
                  <Label htmlFor={kljuc}>{naziv}</Label>
                  <Input
                    id={kljuc}
                    inputMode="decimal"
                    placeholder="npr. 10"
                    value={form[kljuc]}
                    disabled={saving}
                    onChange={(e) => postavi(kljuc, e.target.value)}
                  />
                </div>
              ))}
            </div>
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
