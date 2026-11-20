import { useEffect, useState } from "react";
import { format } from "date-fns";
import { Ban, Download, FilePlus, Loader2, Search } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { apiFetch, getToken } from "../lib/api";

interface ZabranaRow {
  id: number;
  id_aranzmana: string;
  brojzabrane: string;
  preduzece: string;
  datum: string | null;
  mestoobracuna: string;
  prvarata: string | null;
  polurata: string | null;
  brojrata: number | null;
  ukupno: number | null;
  valuta: string;
  operater: string;
  preuzeta: string | null;
  preuzeta_datum: string | null;
}

interface ZabraneResponse {
  rows: ZabranaRow[];
  total: number;
}

const nf2 = new Intl.NumberFormat("sr-RS", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

interface RataDetalj {
  rb: number;
  datum: string;
  iznos: number;
  rasknjizeno: boolean;
}

interface ZabranaDetalj {
  broj: string;
  preduzece: string;
  mesto_obracuna: string;
  datum: string;
  preuzeta_datum: string | null;
  broj_rata: number;
  smestaj: number;
  prevoz: number;
  dod: number;
  ukupno: number;
  nosilac: { ime: string; rodjen: string; adresa: string; telefon: string };
  putnici: { ime: string; rodjen: string }[];
  aranzman: { mesto: string; naziv: string; termin: string; apartman: string };
  rate: RataDetalj[];
}

/** Dijalog sa svim ratama zabrane i preuzimanjem PDF-a. */
function ZabranaDetaljDialog({ broj, onClose, onPromena }: {
  broj: string | null;
  onClose: () => void;
  onPromena: () => void;
}) {
  const [d, setD] = useState<ZabranaDetalj | null>(null);
  const [ucitava, setUcitava] = useState(false);
  const [pdfUcitava, setPdfUcitava] = useState(false);
  const [preuzetaUcitava, setPreuzetaUcitava] = useState(false);

  useEffect(() => {
    if (!broj) return;
    let aktivan = true;
    setD(null);
    setUcitava(true);
    apiFetch<ZabranaDetalj>(`/zabrane/detalj?${new URLSearchParams({ broj })}`)
      .then((x) => { if (aktivan) setD(x); })
      .catch((error) => {
        if (aktivan) toast.error(error instanceof Error ? error.message : "Učitavanje zabrane nije uspelo");
      })
      .finally(() => { if (aktivan) setUcitava(false); });
    return () => { aktivan = false; };
  }, [broj]);

  async function oznaciPreuzeta(datum: string | null) {
    if (!broj) return;
    setPreuzetaUcitava(true);
    try {
      const r = await apiFetch<{ preuzeta_datum: string }>(
        `/zabrane/preuzeta?${new URLSearchParams({ broj })}`,
        { method: "PUT", body: JSON.stringify({ datum }) },
      );
      setD((prev) => (prev ? { ...prev, preuzeta_datum: r.preuzeta_datum || null } : prev));
      onPromena();
      toast.success(datum ? "Zabrana je označena kao preuzeta" : "Oznaka preuzimanja je poništena");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Čuvanje nije uspelo");
    } finally {
      setPreuzetaUcitava(false);
    }
  }

  async function preuzmiPdf() {
    if (!broj) return;
    setPdfUcitava(true);
    try {
      const token = getToken();
      const res = await fetch(`/api/zabrane/pdf?${new URLSearchParams({ broj })}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `Administrativna_zabrana_${broj.replace("/", "-")}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch {
      toast.error("Greška pri generisanju PDF-a");
    } finally {
      setPdfUcitava(false);
    }
  }

  return (
    <Dialog open={broj !== null} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto bg-card">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Ban className="size-5 text-red-600" />Administrativna zabrana {broj}
          </DialogTitle>
          <DialogDescription>
            {d ? `${d.broj_rata} rata · ukupno ${nf2.format(d.ukupno)} RSD` : "Učitavanje…"}
          </DialogDescription>
        </DialogHeader>

        {ucitava || !d ? (
          <div className="py-8 text-center">
            <Loader2 className="w-5 h-5 animate-spin mx-auto text-muted-foreground" />
          </div>
        ) : (
          <div className="space-y-4 text-sm">
            <div className="grid grid-cols-1 gap-x-6 gap-y-1 sm:grid-cols-2">
              <div><span className="text-muted-foreground">Subagent: </span>{d.preduzece || "—"}</div>
              <div><span className="text-muted-foreground">Mesto obračuna: </span>{d.mesto_obracuna || "—"}</div>
              <div><span className="text-muted-foreground">Datum: </span>{d.datum || "—"}</div>
              <div><span className="text-muted-foreground">Korisnik usluge: </span>{d.nosilac.ime || "—"}</div>
              <div className="sm:col-span-2">
                <span className="text-muted-foreground">Aranžman: </span>
                {[d.aranzman.mesto, d.aranzman.naziv, d.aranzman.termin].filter(Boolean).join(" · ") || "—"}
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2 rounded-md border p-3 sm:grid-cols-4">
              <div><div className="text-xs text-muted-foreground">Smeštaj</div><div className="tabular-nums">{nf2.format(d.smestaj)} RSD</div></div>
              <div><div className="text-xs text-muted-foreground">Prevoz</div><div className="tabular-nums">{nf2.format(d.prevoz)} RSD</div></div>
              <div><div className="text-xs text-muted-foreground">Usluga +</div><div className="tabular-nums">{nf2.format(d.dod)} RSD</div></div>
              <div><div className="text-xs text-muted-foreground">Ukupno</div><div className="font-semibold tabular-nums">{nf2.format(d.ukupno)} RSD</div></div>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border p-3">
              <div>
                <div className="text-xs text-muted-foreground">Zabrana preuzeta</div>
                {d.preuzeta_datum ? (
                  <Badge className="mt-0.5 bg-emerald-600 text-white hover:bg-emerald-600 tabular-nums">
                    Preuzeta {d.preuzeta_datum}
                  </Badge>
                ) : (
                  <div className="text-muted-foreground">Nije preuzeta</div>
                )}
              </div>
              {d.preuzeta_datum ? (
                <Button variant="outline" size="sm" disabled={preuzetaUcitava}
                  onClick={() => void oznaciPreuzeta(null)}>
                  Poništi preuzimanje
                </Button>
              ) : (
                <Button size="sm" className="bg-emerald-600 text-white hover:bg-emerald-700"
                  disabled={preuzetaUcitava}
                  onClick={() => void oznaciPreuzeta(format(new Date(), "yyyy-MM-dd"))}>
                  Označi kao preuzetu (danas)
                </Button>
              )}
            </div>

            <div className="overflow-x-auto rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-16">r.b.</TableHead>
                    <TableHead>Datum rate</TableHead>
                    <TableHead className="text-right">Iznos rate (RSD)</TableHead>
                    <TableHead>Proknjiženo</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {d.rate.map((r) => (
                    <TableRow key={r.rb}>
                      <TableCell>{r.rb}</TableCell>
                      <TableCell className="whitespace-nowrap">{r.datum}</TableCell>
                      <TableCell className="text-right tabular-nums">{nf2.format(r.iznos)}</TableCell>
                      <TableCell>{r.rasknjizeno ? "Da" : "Ne"}</TableCell>
                    </TableRow>
                  ))}
                  <TableRow>
                    <TableCell colSpan={2} className="font-semibold">UKUPNO</TableCell>
                    <TableCell className="text-right font-semibold tabular-nums">
                      {nf2.format(d.rate.reduce((s, r) => s + r.iznos, 0))}
                    </TableCell>
                    <TableCell />
                  </TableRow>
                </TableBody>
              </Table>
            </div>
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" disabled={!d}>
            <FilePlus className="mr-1.5 size-4" />
            Kreiraj knjižno odobrenje
          </Button>
          <Button variant="outline" onClick={() => void preuzmiPdf()} disabled={!d || pdfUcitava}>
            {pdfUcitava ? <Loader2 className="mr-1.5 size-4 animate-spin" /> : <Download className="mr-1.5 size-4" />}
            Preuzmi PDF
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function ZabranePage() {
  const [q, setQ] = useState("");
  const [pojam, setPojam] = useState("");
  const [redovi, setRedovi] = useState<ZabranaRow[] | null>(null);
  const [ucitava, setUcitava] = useState(false);
  const [otvorenaZabrana, setOtvorenaZabrana] = useState<string | null>(null);
  const [osvezi, setOsvezi] = useState(0);

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
    apiFetch<ZabraneResponse>(`/zabrane?${params}`)
      .then((d) => { if (aktivan) setRedovi(d.rows); })
      .catch((error) => {
        if (aktivan) {
          setRedovi([]);
          toast.error(error instanceof Error ? error.message : "Učitavanje zabrana nije uspelo");
        }
      })
      .finally(() => { if (aktivan) setUcitava(false); });
    return () => { aktivan = false; };
  }, [pojam, osvezi]);

  return (
    <div className="space-y-4 p-4 md:p-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-xl">
            <Ban className="w-6 h-6 text-red-600" />Administrativne zabrane
          </CardTitle>
          <CardDescription>Zabrane kreirane sa Rezervacija (dugme Administrativna zabrana), najnovije prve.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative w-full max-w-md">
              <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                className="pl-8"
                placeholder="Broj zabrane, ugovor, subagent, mesto ili operater"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                aria-label="Pretraga zabrana"
              />
            </div>
            {redovi && redovi.length > 0 && (
              <Badge variant="secondary">{redovi.length} zabrana · {nf2.format(redovi.reduce((s, r) => s + (r.ukupno ?? 0), 0))} RSD</Badge>
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
                    <TableHead>Broj zabrane</TableHead>
                    <TableHead>Ugovor</TableHead>
                    <TableHead>Subagent</TableHead>
                    <TableHead>Mesto obračuna</TableHead>
                    <TableHead>Datum</TableHead>
                    <TableHead>Prva rata</TableHead>
                    <TableHead>Prva polurata</TableHead>
                    <TableHead className="text-right">Rata</TableHead>
                    <TableHead className="text-right">Iznos (RSD)</TableHead>
                    <TableHead>Operater</TableHead>
                    <TableHead>Preuzeta</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {redovi.map((r) => (
                    <TableRow
                      key={r.id}
                      className={r.preuzeta_datum ? "cursor-pointer bg-emerald-50/60" : "cursor-pointer"}
                      onClick={() => setOtvorenaZabrana(r.brojzabrane)}
                    >
                      <TableCell className="font-mono whitespace-nowrap">{r.brojzabrane}</TableCell>
                      <TableCell className="font-mono whitespace-nowrap">{r.id_aranzmana}</TableCell>
                      <TableCell>{r.preduzece || "—"}</TableCell>
                      <TableCell>{r.mestoobracuna || "—"}</TableCell>
                      <TableCell className="whitespace-nowrap">{r.datum ?? "—"}</TableCell>
                      <TableCell className="whitespace-nowrap">{r.prvarata ?? "—"}</TableCell>
                      <TableCell className="whitespace-nowrap">{r.polurata ?? "—"}</TableCell>
                      <TableCell className="text-right whitespace-nowrap">{r.brojrata ?? "—"}</TableCell>
                      <TableCell className="text-right whitespace-nowrap">
                        {r.ukupno != null ? `${nf2.format(r.ukupno)} RSD` : "—"}
                      </TableCell>
                      <TableCell>{r.operater?.trim() || "—"}</TableCell>
                      <TableCell className="whitespace-nowrap">
                        {r.preuzeta_datum ? (
                          <Badge className="bg-emerald-600 text-white hover:bg-emerald-600 tabular-nums">
                            {r.preuzeta_datum}
                          </Badge>
                        ) : "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : (
            <div className="py-6 text-center text-sm text-muted-foreground">
              {pojam ? "Nema zabrana za ovu pretragu." : "Još nema administrativnih zabrana."}
            </div>
          )}
        </CardContent>
      </Card>
      <ZabranaDetaljDialog
        broj={otvorenaZabrana}
        onClose={() => setOtvorenaZabrana(null)}
        onPromena={() => setOsvezi((n) => n + 1)}
      />
    </div>
  );
}
