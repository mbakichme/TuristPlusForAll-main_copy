import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Loader2, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api";

// ── Tipovi ──────────────────────────────────────────────────────────────────

interface KoefRed {
  rid: number; // klijentski ključ za redove bez ID-ja
  id: number | null;
  struktura: string;
  adl: string;
  chd: string;
  inf: string;
  koeficijent: string;
  rucno: boolean;
}

interface KoefRedBaza {
  id: number;
  struktura: string;
  adl: number;
  chd: number;
  inf: number;
  koeficijent: number;
  rucno: boolean;
}

interface KoefOdgovor {
  strukture: string[];
  redovi: KoefRedBaza[];
}

type Polje = "adl" | "chd" | "inf" | "koeficijent";

// ── Pomoćne funkcije ────────────────────────────────────────────────────────

const INT_RE = /^\d+$/;
const KOEF_RE = /^\d*(?:\.\d{1,4})?$/;

/** Zarez → tačka (samo normalizacija unosa, validacija je odvojena). */
function normalizujZarez(vrednost: string): string {
  return vrednost.replace(/,/g, ".");
}

/** double → prikaz bez suvišnih nula (1.50 → „1.5“, 2.0 → „2“). */
function fmtKoef(vrednost: number): string {
  return String(Math.round(vrednost * 1000000) / 1000000);
}

/** Sortiranje struktura: 1/2 < 1/2 ECO < 1/2+1 < 1/3 < 1/3 ECO < 1/10; nenumeričke na kraj. */
function porediStrukture(a: string, b: string): number {
  const ma = /^(\d+)\s*\/\s*(\d+)(.*)$/.exec(a.trim());
  const mb = /^(\d+)\s*\/\s*(\d+)(.*)$/.exec(b.trim());
  if (ma && mb) {
    const raz = Number(ma[1]) - Number(mb[1]) || Number(ma[2]) - Number(mb[2]);
    if (raz !== 0) return raz;
    return ma[3].trim().localeCompare(mb[3].trim(), "sr");
  }
  if (ma) return -1;
  if (mb) return 1;
  return a.trim().localeCompare(b.trim(), "sr");
}

function snapshotStringa(redovi: KoefRed[]): string {
  return JSON.stringify(
    redovi.map((r) => [r.struktura, r.adl, r.chd, r.inf, r.koeficijent, r.rucno]),
  );
}

/** Redovi iz baze + automatski nulti red za svaku strukturu iz soba koja nema zapis. */
function mergeRedovi(
  izBaze: KoefRedBaza[],
  strukture: string[],
  sledeciRid: () => number,
): KoefRed[] {
  const postojece = new Set<string>();
  const redovi: KoefRed[] = izBaze.map((r) => {
    const struktura = (r.struktura || "").trim();
    postojece.add(struktura);
    return {
      rid: sledeciRid(),
      id: r.id,
      struktura,
      adl: String(r.adl ?? 0),
      chd: String(r.chd ?? 0),
      inf: String(r.inf ?? 0),
      koeficijent: fmtKoef(Number(r.koeficijent ?? 0)),
      rucno: Boolean(r.rucno),
    };
  });
  for (const s of strukture) {
    const struktura = (s || "").trim();
    if (!struktura || postojece.has(struktura)) continue;
    postojece.add(struktura);
    redovi.push({
      rid: sledeciRid(),
      id: null,
      struktura,
      adl: "0",
      chd: "0",
      inf: "0",
      koeficijent: "0",
      rucno: false,
    });
  }
  return redovi.sort((a, b) => {
    const p = porediStrukture(a.struktura, b.struktura);
    if (p !== 0) return p;
    return (a.id ?? Number.MAX_SAFE_INTEGER) - (b.id ?? Number.MAX_SAFE_INTEGER);
  });
}

// ── Stranica ────────────────────────────────────────────────────────────────

export default function KoeficijentiPage() {
  const navigate = useNavigate();
  const ridRef = useRef(0);
  const sledeciRid = () => ++ridRef.current;

  const [ucitano, setUcitano] = useState(false);
  const [strukture, setStrukture] = useState<string[]>([]);
  const [redovi, setRedovi] = useState<KoefRed[]>([]);
  const [snapshot, setSnapshot] = useState<string | null>(null);
  const [snima, setSnima] = useState(false);

  const [confirmOpen, setConfirmOpen] = useState(false);
  const pendingConfirm = useRef<(() => void) | null>(null);

  useEffect(() => {
    let otkazano = false;
    apiFetch<KoefOdgovor>("/koeficijenti")
      .then((d) => {
        if (otkazano) return;
        const spajano = mergeRedovi(d.redovi, d.strukture, sledeciRid);
        setStrukture(d.strukture);
        setRedovi(spajano);
        setSnapshot(snapshotStringa(spajano));
        setUcitano(true);
      })
      .catch(() => {
        if (!otkazano) toast.error("Učitavanje koeficijenata nije uspelo");
      });
    return () => { otkazano = true; };
  }, []);

  const prljavo = snapshot !== null && snapshotStringa(redovi) !== snapshot;

  // Opcije za ručni red: strukture iz baze + već upisane strukture redova
  const opcijeStruktura = useMemo(() => {
    const skup = new Set(strukture);
    for (const r of redovi) if (r.struktura) skup.add(r.struktura);
    return [...skup].sort(porediStrukture);
  }, [strukture, redovi]);

  // Zaštita nesačuvanih izmena: navigacija klikom na link + zatvaranje taba
  useEffect(() => {
    if (!prljavo) return;
    const preZatvaranja = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    const preNavigacije = (event: MouseEvent) => {
      const anchor = event.target instanceof Element ? event.target.closest("a[href]") : null;
      if (!(anchor instanceof HTMLAnchorElement) || anchor.target === "_blank" || anchor.hasAttribute("download")) return;
      if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      if (anchor.origin === window.location.origin && anchor.pathname === window.location.pathname) return;
      event.preventDefault();
      event.stopPropagation();
      const destination = anchor.href;
      pendingConfirm.current = () => {
        if (anchor.origin === window.location.origin) {
          navigate(new URL(destination).pathname + new URL(destination).search + new URL(destination).hash);
        } else {
          window.location.assign(destination);
        }
      };
      setConfirmOpen(true);
    };
    window.addEventListener("beforeunload", preZatvaranja);
    document.addEventListener("click", preNavigacije, true);
    return () => {
      window.removeEventListener("beforeunload", preZatvaranja);
      document.removeEventListener("click", preNavigacije, true);
    };
  }, [prljavo, navigate]);

  function izvrsiPotvrdu() {
    const fn = pendingConfirm.current;
    pendingConfirm.current = null;
    setConfirmOpen(false);
    fn?.();
  }

  function izmeniPolje(indeks: number, polje: Polje, vrednost: string) {
    setRedovi((pre) => pre.map((r, i) => (i === indeks ? { ...r, [polje]: vrednost } : r)));
  }

  function izmeniStrukturu(indeks: number, vrednost: string) {
    setRedovi((pre) => pre.map((r, i) => (i === indeks ? { ...r, struktura: vrednost } : r)));
  }

  function dodajRed() {
    setRedovi((pre) => [
      ...pre,
      {
        rid: sledeciRid(),
        id: null,
        struktura: opcijeStruktura[0] ?? "",
        adl: "0",
        chd: "0",
        inf: "0",
        koeficijent: "0",
        rucno: true,
      },
    ]);
  }

  function obrisiRed(indeks: number) {
    setRedovi((pre) => pre.filter((_, i) => i !== indeks));
  }

  /** Validacija na klijentu — ista pravila kao na serveru; baca Error, ne prepravlja unos. */
  function gradPayload() {
    const out: {
      id: number | null;
      struktura: string;
      adl: number;
      chd: number;
      inf: number;
      koeficijent: number;
      rucno: boolean;
    }[] = [];
    for (let i = 0; i < redovi.length; i++) {
      const r = redovi[i];
      const redBr = i + 1;
      const struktura = r.struktura.trim();
      if (!struktura) throw new Error(`Red ${redBr}: struktura je obavezna.`);
      for (const polje of ["adl", "chd", "inf"] as const) {
        const v = r[polje].trim();
        if (v === "") continue;
        if (!INT_RE.test(v) || Number(v) > 99) {
          throw new Error(`Red ${redBr} (${struktura}): ${polje.toUpperCase()} mora biti ceo broj od 0 do 99.`);
        }
      }
      const k = normalizujZarez(r.koeficijent.trim());
      if (k !== "" && !KOEF_RE.test(k)) {
        throw new Error(`Red ${redBr} (${struktura}): koeficijent mora biti nenegativan broj sa najviše 4 decimale (npr. 1,25).`);
      }
      const koef = k === "" ? 0 : Number(k);
      if (!Number.isFinite(koef) || koef >= 1000000) {
        throw new Error(`Red ${redBr} (${struktura}): koeficijent mora biti manji od 1.000.000.`);
      }
      out.push({
        id: r.id,
        struktura,
        adl: r.adl.trim() === "" ? 0 : Number(r.adl),
        chd: r.chd.trim() === "" ? 0 : Number(r.chd),
        inf: r.inf.trim() === "" ? 0 : Number(r.inf),
        koeficijent: koef,
        rucno: r.rucno,
      });
    }
    return out;
  }

  async function sacuvaj() {
    if (snima) return;
    let payload;
    try {
      payload = gradPayload();
    } catch (e) {
      toast.error("Nesačuvano", {
        description: e instanceof Error ? e.message : String(e),
        duration: 8000,
      });
      return;
    }
    setSnima(true);
    try {
      const d = await apiFetch<KoefOdgovor>("/koeficijenti", {
        method: "PUT",
        body: JSON.stringify({ redovi: payload }),
      });
      const spajano = mergeRedovi(d.redovi, d.strukture, sledeciRid);
      setStrukture(d.strukture);
      setRedovi(spajano);
      setSnapshot(snapshotStringa(spajano));
      toast.success("Koeficijenti su sačuvani.");
    } catch (e) {
      toast.error("Čuvanje nije uspelo", {
        description: e instanceof Error ? e.message : undefined,
        duration: 8000,
      });
    } finally {
      setSnima(false);
    }
  }

  if (!ucitano) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold">Koeficijenti prodaje</h1>
        <p className="text-sm text-muted-foreground">
          Adl / Chd / Inf i koeficijent po strukturi sobe — strukture se povlače iz šifarnika soba
        </p>
      </div>

      <Card>
        <CardHeader className="pb-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle className="text-base">Koeficijenti po strukturama</CardTitle>
              <CardDescription>
                Svaka struktura iz soba prikazuje se jednom i počinje sa nulama dok se ne popuni.
                „Dodaj red“ dodaje dodatni zapis za istu strukturu.
              </CardDescription>
            </div>
            <div className="flex items-center gap-2">
              <Button variant="outline" onClick={dodajRed} disabled={snima}>
                <Plus className="h-4 w-4" />
                Dodaj red
              </Button>
              <Button onClick={() => void sacuvaj()} disabled={snima}>
                {snima && <Loader2 className="h-4 w-4 animate-spin" />}
                Sačuvaj
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full min-w-[560px] border-collapse text-sm">
              <thead>
                <tr className="border-b bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
                  <th className="px-3 py-2 text-left font-medium">Struktura</th>
                  <th className="w-24 px-3 py-2 text-center font-medium">Adl</th>
                  <th className="w-24 px-3 py-2 text-center font-medium">Chd</th>
                  <th className="w-24 px-3 py-2 text-center font-medium">Inf</th>
                  <th className="w-32 px-3 py-2 text-center font-medium">Koeficijent</th>
                  <th className="w-12 px-2 py-2">
                    <span className="sr-only">Akcije</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {redovi.map((r, i) => (
                  <tr key={r.id ?? `n${r.rid}`} className="border-b last:border-b-0 hover:bg-muted/20">
                    <td className="px-3 py-1.5">
                      {r.rucno ? (
                        opcijeStruktura.length > 0 ? (
                          <Select
                            value={r.struktura}
                            onValueChange={(v) => izmeniStrukturu(i, v)}
                            disabled={snima}
                          >
                            <SelectTrigger
                              className="h-8 w-36 bg-background"
                              aria-label={`Struktura — red ${i + 1}`}
                            >
                              <SelectValue placeholder="Struktura" />
                            </SelectTrigger>
                            <SelectContent>
                              {opcijeStruktura.map((s) => (
                                <SelectItem key={s} value={s}>{s}</SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        ) : (
                          <Input
                            value={r.struktura}
                            onChange={(e) => izmeniStrukturu(i, e.target.value)}
                            className="h-8 w-36 bg-background"
                            aria-label={`Struktura — red ${i + 1}`}
                            disabled={snima}
                          />
                        )
                      ) : (
                        <span className="font-medium tabular-nums">{r.struktura}</span>
                      )}
                    </td>
                    <td className="px-3 py-1.5 text-center">
                      <Input
                        value={r.adl}
                        inputMode="numeric"
                        onChange={(e) => izmeniPolje(i, "adl", e.target.value)}
                        className="mx-auto h-8 w-16 bg-background px-1.5 text-center tabular-nums"
                        aria-label={`Adl — red ${i + 1}`}
                        disabled={snima}
                      />
                    </td>
                    <td className="px-3 py-1.5 text-center">
                      <Input
                        value={r.chd}
                        inputMode="numeric"
                        onChange={(e) => izmeniPolje(i, "chd", e.target.value)}
                        className="mx-auto h-8 w-16 bg-background px-1.5 text-center tabular-nums"
                        aria-label={`Chd — red ${i + 1}`}
                        disabled={snima}
                      />
                    </td>
                    <td className="px-3 py-1.5 text-center">
                      <Input
                        value={r.inf}
                        inputMode="numeric"
                        onChange={(e) => izmeniPolje(i, "inf", e.target.value)}
                        className="mx-auto h-8 w-16 bg-background px-1.5 text-center tabular-nums"
                        aria-label={`Inf — red ${i + 1}`}
                        disabled={snima}
                      />
                    </td>
                    <td className="px-3 py-1.5 text-center">
                      <Input
                        value={r.koeficijent}
                        inputMode="decimal"
                        onChange={(e) => izmeniPolje(i, "koeficijent", e.target.value)}
                        className="mx-auto h-8 w-24 bg-background px-1.5 text-center tabular-nums"
                        aria-label={`Koeficijent — red ${i + 1}`}
                        disabled={snima}
                      />
                    </td>
                    <td className="px-2 py-1.5 text-center">
                      {r.rucno && (
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 text-muted-foreground hover:text-destructive"
                          aria-label={`Obriši red ${i + 1}`}
                          onClick={() => obrisiRed(i)}
                          disabled={snima}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
                {redovi.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-3 py-8 text-center text-sm text-muted-foreground">
                      Nema zapisa — kliknite „Dodaj red“.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      {/* Potvrda odbacivanja nesačuvanih izmena */}
      <AlertDialog
        open={confirmOpen}
        onOpenChange={(o) => {
          if (!o) pendingConfirm.current = null;
          setConfirmOpen(o);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Odbaciti nesačuvane izmene?</AlertDialogTitle>
            <AlertDialogDescription>
              Tabela koeficijenata sadrži nesačuvane izmene. Ako nastavite, one će biti izgubljene.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Otkaži</AlertDialogCancel>
            <AlertDialogAction
              onClick={izvrsiPotvrdu}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Nastavi
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
