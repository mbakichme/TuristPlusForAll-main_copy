import { useEffect, useState } from "react";
import { apiFetch } from "../lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow
} from "@/components/ui/table";
import { ClipboardCheck, Loader2 } from "lucide-react";
import { toast } from "sonner";

// Ugovori sa štikliranim OW / RT bez izabrane destinacije prevoza (nosilac i saputnici)
interface KontrolaRed {
  kljuc: string;
  datumod: string | null;
  datumdo: string | null;
  osoba_ime: string | null;
  osoba: "Nosilac" | "Saputnik";
  prevoz: "OW" | "RT";
  nedostaje: string;
}

interface KontrolaResp {
  rows: KontrolaRed[];
  total: number;
  ugovori: number;
}

function fmtDatum(iso: string | null): string {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-");
  return y && m && d ? `${d}.${m}.${y}` : iso;
}

export default function KontrolaUgovoraPage() {
  const [data, setData] = useState<KontrolaResp | null>(null);
  const [ucitava, setUcitava] = useState(true);

  useEffect(() => {
    let aktivno = true;
    setUcitava(true);
    apiFetch<KontrolaResp>("/kontrola-ugovora")
      .then((r) => { if (aktivno) setData(r); })
      .catch(() => { if (aktivno) toast.error("Učitavanje kontrole ugovora nije uspelo"); })
      .finally(() => { if (aktivno) setUcitava(false); });
    return () => { aktivno = false; };
  }, []);

  return (
    <div className="p-4 sm:p-6 space-y-4">
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <ClipboardCheck className="size-5 text-muted-foreground" />
            <CardTitle>Kontrola ugovora</CardTitle>
            {data && data.total > 0 && (
              <Badge variant="destructive" className="ml-auto">{data.ugovori} ugovora · {data.total} stavki</Badge>
            )}
          </div>
          <CardDescription>
            Ugovori sa štiklom OW ili RT (nosilac ili saputnik) kojima nije izabrana destinacija prevoza:
            OW — Destinacija OW, RT — Destinacija polaska.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {ucitava ? (
            <div className="py-8 text-center">
              <Loader2 className="w-5 h-5 animate-spin mx-auto text-muted-foreground" />
            </div>
          ) : !data || data.rows.length === 0 ? (
            <p className="text-sm text-muted-foreground py-8 text-center">
              Nema ugovora bez izabrane destinacije prevoza.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Ugovor</TableHead>
                    <TableHead>Datum od</TableHead>
                    <TableHead>Datum do</TableHead>
                    <TableHead>Putnik</TableHead>
                    <TableHead>Uloga</TableHead>
                    <TableHead>Prevoz</TableHead>
                    <TableHead>Nedostaje</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.rows.map((r, i) => (
                    <TableRow key={`${r.kljuc}-${r.osoba}-${r.prevoz}-${i}`}>
                      <TableCell className="whitespace-nowrap font-medium">{r.kljuc}</TableCell>
                      <TableCell className="whitespace-nowrap">{fmtDatum(r.datumod)}</TableCell>
                      <TableCell className="whitespace-nowrap">{fmtDatum(r.datumdo)}</TableCell>
                      <TableCell>{r.osoba_ime?.trim() || "—"}</TableCell>
                      <TableCell>{r.osoba}</TableCell>
                      <TableCell>{r.prevoz}</TableCell>
                      <TableCell className="text-red-600">{r.nedostaje}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
