import { useEffect, useMemo, useState } from "react";
import { ArrowRightLeft, Loader2, Search } from "lucide-react";
import { toast } from "sonner";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { apiFetch } from "../lib/api";

interface PrebacivanjeRow {
  id: number;
  datum: string | null;
  uplata_kljuc: number;
  iznos: number;
  stari_ugovor: string;
  novi_ugovor: string;
  operater_id: number | null;
  operater: string;
}

interface PrebacivanjaResponse {
  rows: PrebacivanjeRow[];
  total: number;
}

const nf2 = new Intl.NumberFormat("sr-RS", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function fmtDatum(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const dd = String(d.getDate()).padStart(2, "0");
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mi = String(d.getMinutes()).padStart(2, "0");
  return `${dd}.${mm}.${d.getFullYear()}. ${hh}:${mi}`;
}

export default function PrebacivanjaPage() {
  const [q, setQ] = useState("");
  const [pojam, setPojam] = useState("");
  const [redovi, setRedovi] = useState<PrebacivanjeRow[] | null>(null);
  const [ucitava, setUcitava] = useState(false);

  // pretraga sa 400 ms debounce
  useEffect(() => {
    const t = setTimeout(() => setPojam(q.trim()), 400);
    return () => clearTimeout(t);
  }, [q]);

  useEffect(() => {
    let aktivan = true;
    setUcitava(true);
    const params = new URLSearchParams({ limit: "500" });
    if (pojam) params.set("q", pojam);
    apiFetch<PrebacivanjaResponse>(`/prebacivanja?${params}`)
      .then((d) => { if (aktivan) setRedovi(d.rows); })
      .catch(() => { if (aktivan) { setRedovi([]); toast.error("Učitavanje prebacivanja nije uspelo"); } })
      .finally(() => { if (aktivan) setUcitava(false); });
    return () => { aktivan = false; };
  }, [pojam]);

  const zbirDin = useMemo(
    () => Math.round((redovi ?? []).reduce((s, r) => s + (r.iznos ?? 0), 0) * 100) / 100,
    [redovi],
  );

  return (
    <div className="space-y-4 p-4 md:p-6">
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <ArrowRightLeft className="w-5 h-5 text-primary" />Prebacivanje uplata
          </CardTitle>
          <CardDescription>Evidencija uplata prebačenih sa jednog ugovora na drugi (Povraćaj)</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative w-full max-w-sm">
              <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                className="pl-8"
                placeholder="Ugovor, ključ uplate ili operater"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                aria-label="Pretraga prebacivanja"
              />
            </div>
            {redovi && redovi.length > 0 && (
              <Badge variant="secondary">{redovi.length} prebacivanja · {nf2.format(zbirDin)} din</Badge>
            )}
          </div>

          {ucitava && !redovi ? (
            <div className="py-8 text-center">
              <Loader2 className="w-5 h-5 animate-spin mx-auto text-muted-foreground" />
            </div>
          ) : redovi && redovi.length > 0 ? (
            <div className="overflow-x-auto rounded-lg border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Datum</TableHead>
                    <TableHead className="text-right">Ključ uplate</TableHead>
                    <TableHead className="text-right">Iznos (din)</TableHead>
                    <TableHead>Sa ugovora</TableHead>
                    <TableHead>Na ugovor</TableHead>
                    <TableHead>Operater</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {redovi.map((r) => (
                    <TableRow key={r.id}>
                      <TableCell className="whitespace-nowrap">{fmtDatum(r.datum)}</TableCell>
                      <TableCell className="text-right font-mono">{r.uplata_kljuc}</TableCell>
                      <TableCell className="text-right whitespace-nowrap">{nf2.format(r.iznos)}</TableCell>
                      <TableCell className="font-mono">{r.stari_ugovor}</TableCell>
                      <TableCell className="font-mono">{r.novi_ugovor}</TableCell>
                      <TableCell>{r.operater?.trim() || "—"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : (
            <div className="py-6 text-center text-sm text-muted-foreground">
              {pojam ? "Nema prebacivanja za ovu pretragu." : "Još nema prebačenih uplata."}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
