import { useState, useEffect } from "react";
import { apiFetch, getToken } from "../lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow
} from "@/components/ui/table";
import { Loader2, Printer, ReceiptText, Search } from "lucide-react";
import { toast } from "sonner";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";

interface AvansniRacun {
  id: number;
  faktura: string;
  datumf: string;
  datump: string;
  subagent: string;
  nosilac: string;
  destinacija: string;
  period: string;
  zaduzenje: number;
  uplaceno: number;
  saldo: number;
  napomena: string;
  status_efaktura: string;
  na_sef: boolean;
}

interface AvansniResponse {
  rows: AvansniRacun[];
  total: number;
  poslato_na_sef: number;
}

const datumSr = (iso: string) => {
  const [g, m, d] = (iso || "").split("-");
  return g && m && d ? `${d}.${m}.${g}` : iso || "—";
};

const iznosSr = (n: number) =>
  n.toLocaleString("sr-RS", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export default function AvansniRacuniPage() {
  const [rows, setRows] = useState<AvansniRacun[]>([]);
  const [total, setTotal] = useState(0);
  const [poslato, setPoslato] = useState(0);
  const [ucitava, setUcitava] = useState(false);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [stampaId, setStampaId] = useState<number | null>(null);
  const [pdf, setPdf] = useState<{ id: number; faktura: string; url: string } | null>(null);

  async function stampaj(r: AvansniRacun) {
    if (stampaId != null) return;
    setStampaId(r.id);
    try {
      const token = getToken();
      const res = await fetch(`/api/avansni-racuni/${r.id}/pdf`, {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      });
      if (!res.ok) {
        const j = await res.json().catch(() => null);
        throw new Error(j?.detail || `HTTP ${res.status}`);
      }
      const blob = new Blob([await res.arrayBuffer()], { type: "application/pdf" });
      setPdf({ id: r.id, faktura: r.faktura, url: URL.createObjectURL(blob) });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Štampa nije uspela");
    } finally {
      setStampaId(null);
    }
  }

  function zatvoriPdf() {
    if (pdf) URL.revokeObjectURL(pdf.url);
    setPdf(null);
  }

  useEffect(() => {
    const t = setTimeout(() => setSearch(searchInput.trim()), 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  useEffect(() => {
    let aktivan = true;
    setUcitava(true);
    const qs = search ? `?q=${encodeURIComponent(search)}` : "";
    apiFetch<AvansniResponse>(`/avansni-racuni${qs}`)
      .then((r) => {
        if (!aktivan) return;
        setRows(r.rows);
        setTotal(r.total);
        setPoslato(r.poslato_na_sef);
      })
      .catch(() => toast.error("Avansni računi nisu učitani"))
      .finally(() => aktivan && setUcitava(false));
    return () => { aktivan = false; };
  }, [search]);

  return (
    <div className="space-y-4 p-4 md:p-6">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold">
          <ReceiptText className="h-6 w-6" />
          Avansne fakture
        </h1>
        <p className="text-sm text-muted-foreground">Pregled izdatih avansa i statusa slanja na SEF</p>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <CardTitle className="flex flex-wrap items-center gap-3 text-base">
              Izdati avansi
              <span className="text-xs font-normal text-muted-foreground">Ukupno {total}</span>
              <span className="text-xs font-normal text-emerald-700">Poslato na SEF: {poslato}</span>
              <span className="text-xs font-normal text-red-700">Nije poslato: {total - poslato}</span>
            </CardTitle>
            <div className="relative w-full sm:w-80">
              <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                id="Pretraga avansnih faktura"
                aria-label="Pretraga avansnih faktura"
                placeholder="Pretraga (broj, subagent, nosilac, iznos…)"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                className="pl-8"
              />
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <Table className="text-xs">
              <TableHeader>
                <TableRow>
                  <TableHead className="h-8 px-3 text-xs">Faktura</TableHead>
                  <TableHead className="h-8 px-3 text-xs">Datum fakture</TableHead>
                  <TableHead className="h-8 px-3 text-xs">Datum uplate</TableHead>
                  <TableHead className="h-8 px-3 text-xs">Subagent</TableHead>
                  <TableHead className="h-8 px-3 text-xs">Nosilac</TableHead>
                  <TableHead className="h-8 px-3 text-xs">Destinacija</TableHead>
                  <TableHead className="h-8 px-3 text-xs">Period</TableHead>
                  <TableHead className="h-8 px-3 text-right text-xs">Zaduženje</TableHead>
                  <TableHead className="h-8 px-3 text-right text-xs">Uplaćeno</TableHead>
                  <TableHead className="h-8 px-3 text-right text-xs">Saldo</TableHead>
                  <TableHead className="h-8 px-3 text-xs">Napomena</TableHead>
                  <TableHead className="h-8 px-3 text-center text-xs">Na SEF</TableHead>
                  <TableHead className="h-8 px-3 text-center text-xs">Štampa</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {ucitava && rows.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={13} className="py-6 text-center">
                      <Loader2 className="mx-auto size-4 animate-spin text-muted-foreground" />
                    </TableCell>
                  </TableRow>
                ) : rows.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={13} className="py-6 text-center text-muted-foreground">
                      Nema avansnih faktura za zadatu pretragu.
                    </TableCell>
                  </TableRow>
                ) : rows.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell className="px-3 py-1.5 font-mono font-medium">{r.faktura}</TableCell>
                    <TableCell className="px-3 py-1.5">{datumSr(r.datumf)}</TableCell>
                    <TableCell className="px-3 py-1.5">{datumSr(r.datump)}</TableCell>
                    <TableCell className="px-3 py-1.5">{r.subagent || "—"}</TableCell>
                    <TableCell className="px-3 py-1.5">{r.nosilac || "—"}</TableCell>
                    <TableCell className="px-3 py-1.5">{r.destinacija || "—"}</TableCell>
                    <TableCell className="px-3 py-1.5">{r.period || "—"}</TableCell>
                    <TableCell className="px-3 py-1.5 text-right font-mono">{iznosSr(r.zaduzenje)}</TableCell>
                    <TableCell className="px-3 py-1.5 text-right font-mono">{iznosSr(r.uplaceno)}</TableCell>
                    <TableCell className="px-3 py-1.5 text-right font-mono">{iznosSr(r.saldo)}</TableCell>
                    <TableCell className="px-3 py-1.5">{r.napomena || "—"}</TableCell>
                    <TableCell className="px-3 py-1.5 text-center">
                      <span
                        title={`status_efaktura: ${r.status_efaktura}`}
                        className={r.na_sef
                          ? "rounded-full bg-emerald-100 px-2 py-0.5 text-emerald-700"
                          : "rounded-full bg-red-100 px-2 py-0.5 text-red-700"}
                      >
                        {r.na_sef ? "Da" : "Ne"}
                      </span>
                    </TableCell>
                    <TableCell className="px-3 py-1.5 text-center">
                      {r.na_sef ? (
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7"
                          title="Štampaj fakturu sa SEF-a"
                          aria-label={`Štampaj ${r.faktura}`}
                          disabled={stampaId === r.id}
                          onClick={() => stampaj(r)}
                        >
                          {stampaId === r.id ? <Loader2 className="size-4 animate-spin" /> : <Printer className="size-4" />}
                        </Button>
                      ) : "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      <Dialog open={pdf !== null} onOpenChange={(open) => { if (!open) zatvoriPdf(); }}>
        <DialogContent className="max-w-4xl bg-card">
          <DialogHeader>
            <DialogTitle>Avansna faktura {pdf?.faktura}</DialogTitle>
          </DialogHeader>
          {pdf && (
            <>
              <iframe src={pdf.url} title={`Faktura ${pdf.faktura}`} className="h-[70vh] w-full rounded-md border" />
              <div className="flex justify-end gap-2">
                <a
                  href={pdf.url}
                  download={`avans-${pdf.faktura.replace("/", "-")}.pdf`}
                  className="inline-flex h-9 items-center rounded-md border px-3 text-sm hover:bg-muted"
                >
                  Preuzmi PDF
                </a>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
