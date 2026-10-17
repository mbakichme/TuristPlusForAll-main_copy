import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Bell, Loader2, Search, Send } from "lucide-react";
import { apiFetch } from "../lib/api";
import type { Notifikacija, NotifikacijeResponse } from "../types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

const MAX = 1000;
const PODRAZUMEVANO = 100;

function formatDatum(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString("sr-RS", { dateStyle: "short", timeStyle: "short" });
}

export default function NotifikacijePage() {
  const [poruka, setPoruka] = useState("");
  const [snimanje, setSnimanje] = useState(false);
  const [pretraga, setPretraga] = useState("");
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<Notifikacija[]>([]);
  const [ukupno, setUkupno] = useState(0);
  const [ucitava, setUcitava] = useState(true);
  const [osvezi, setOsvezi] = useState(0);

  // Debounce pretrage
  useEffect(() => {
    const t = setTimeout(() => setQ(pretraga.trim()), 300);
    return () => clearTimeout(t);
  }, [pretraga]);

  useEffect(() => {
    let aktivan = true;
    setUcitava(true);
    const params = new URLSearchParams({ limit: String(PODRAZUMEVANO) });
    if (q) params.set("q", q);
    apiFetch<NotifikacijeResponse>(`/notifikacije?${params}`)
      .then((d) => { if (aktivan) { setRows(d.rows); setUkupno(d.ukupno); } })
      .catch(() => { if (aktivan) toast.error("Učitavanje poruka nije uspelo"); })
      .finally(() => { if (aktivan) setUcitava(false); });
    return () => { aktivan = false; };
  }, [q, osvezi]);

  async function sacuvaj() {
    const tekst = poruka.trim();
    if (!tekst) { toast.error("Unesite poruku"); return; }
    if (tekst.length > MAX) { toast.error(`Poruka je predugačka (najviše ${MAX} znakova)`); return; }
    setSnimanje(true);
    try {
      await apiFetch<Notifikacija>("/notifikacije", { method: "POST", body: JSON.stringify({ poruka: tekst }) });
      setPoruka("");
      toast.success("Poruka je sačuvana i prikazuje se na naslovnoj");
      setOsvezi((n) => n + 1);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Čuvanje nije uspelo");
    } finally {
      setSnimanje(false);
    }
  }

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-foreground">Notifikacije</h1>
        <p className="text-muted-foreground mt-1">
          Poruka koju ostavite prikazuje se na naslovnoj strani.
        </p>
      </div>

      <Card className="border-violet-200 bg-violet-50/40">
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2 text-violet-800">
            <Bell className="w-4 h-4" /> Nova poruka
          </CardTitle>
          <CardDescription>Najviše {MAX} znakova. Čuva se ime autora i vreme objave.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <Textarea
            id="notif-poruka"
            aria-label="Tekst poruke"
            placeholder="Npr. Sutra od 9h zatvoreni smo zbog inventure."
            value={poruka}
            maxLength={MAX}
            rows={3}
            onChange={(e) => setPoruka(e.target.value)}
          />
          <div className="flex items-center justify-between gap-3">
            <span className="text-xs text-muted-foreground">{poruka.length}/{MAX}</span>
            <Button
              onClick={sacuvaj}
              disabled={snimanje || !poruka.trim()}
              className="bg-violet-600 hover:bg-violet-700 text-white"
            >
              {snimanje ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Send className="w-4 h-4 mr-2" />}
              Sačuvaj poruku
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Sve poruke</CardTitle>
          <CardDescription>
            {q
              ? `Pronađeno ${ukupno} — prikazano do ${PODRAZUMEVANO}`
              : `Ukupno ${ukupno} — prikazano poslednjih ${Math.min(PODRAZUMEVANO, ukupno)}`}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="relative max-w-sm">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input
              aria-label="Pretraga poruka"
              placeholder="Pretraži poruke ili autora…"
              value={pretraga}
              onChange={(e) => setPretraga(e.target.value)}
              className="pl-9"
            />
          </div>

          <div className="rounded-md border overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted/50 text-left">
                <tr>
                  <th className="px-3 py-2 font-medium whitespace-nowrap">Datum</th>
                  <th className="px-3 py-2 font-medium whitespace-nowrap">Autor</th>
                  <th className="px-3 py-2 font-medium">Poruka</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {ucitava ? (
                  <tr><td colSpan={3} className="px-3 py-6 text-center text-muted-foreground">Učitavanje…</td></tr>
                ) : rows.length === 0 ? (
                  <tr><td colSpan={3} className="px-3 py-6 text-center text-muted-foreground">
                    {q ? `Nema poruka za „${q}”` : "Još nema poruka."}
                  </td></tr>
                ) : rows.map((r, i) => (
                  <tr key={r.id} className="align-top hover:bg-muted/40">
                    <td className="px-3 py-2 whitespace-nowrap text-muted-foreground">{formatDatum(r.created_at)}</td>
                    <td className="px-3 py-2 whitespace-nowrap">{r.autor_ime || r.autor_username}</td>
                    <td className="px-3 py-2 whitespace-pre-wrap break-words">
                      {r.poruka}
                      {i === 0 && !q && (
                        <span className="ml-2 text-xs font-medium text-violet-700">• na naslovnoj</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
