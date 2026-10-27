import { useEffect, useRef, useState } from "react";
import { ArrowRightLeft, CalendarDays, Loader2, Search, TriangleAlert, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { apiFetch } from "../lib/api";
import type { UgovorRow, UgovoriResponse } from "../types";

interface PrebacivanjeUplatePopupProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** uplata koja se prebacuje */
  uplata: { kljuc: number; din: number | null; danas: string | null };
  /** ugovor sa kog se uplata prebacuje (broj ili ključ) */
  izvorUgovor: string;
  /** poziva se posle uspešnog prebacivanja, sa ključem novog ugovora */
  onPrebaceno: (novUgovor: string) => void;
}

const nf2 = new Intl.NumberFormat("sr-RS", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function danasnjiDatum(): string {
  const d = new Date();
  const dd = String(d.getDate()).padStart(2, "0");
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  return `${dd}.${mm}.${d.getFullYear()}.`;
}

/** Povraćaj: izbor novog ugovora i prebacivanje uplate (sa upozorenjem pre potvrde). */
export function PrebacivanjeUplatePopup({ open, onOpenChange, uplata, izvorUgovor, onPrebaceno }: PrebacivanjeUplatePopupProps) {
  const [pretraga, setPretraga] = useState("");
  const [rezultati, setRezultati] = useState<UgovorRow[]>([]);
  const [ucitava, setUcitava] = useState(false);
  const [izabran, setIzabran] = useState<UgovorRow | null>(null);
  const [potvrda, setPotvrda] = useState(false);
  const [cuva, setCuva] = useState(false);
  const request = useRef(0);

  const izvorBroj = izvorUgovor.split("/")[0].trim();

  // Pretraga ugovora (ista pravila kao na naslovnoj: putnik / broj ugovora), 400 ms debounce
  useEffect(() => {
    if (!open) return;
    const req = ++request.current;
    const q = pretraga.trim();
    if (q.length < 2) {
      setRezultati([]);
      setUcitava(false);
      return;
    }
    setUcitava(true);
    const timer = setTimeout(() => {
      const params = new URLSearchParams({ search: q, search_in: "putnik,kljuc", page_size: "20", sort: "kljuc", dir: "asc" });
      apiFetch<UgovoriResponse>(`/ugovori?${params}`)
        .then((data) => {
          if (req !== request.current) return;
          // ugovor sa kog se prebacuje ne nudimo kao cilj
          setRezultati(data.rows.filter((r) => r.kljuc.split("/")[0].trim() !== izvorBroj));
        })
        .catch(() => { if (req === request.current) toast.error("Pretraga ugovora nije uspela"); })
        .finally(() => { if (req === request.current) setUcitava(false); });
    }, 400);
    return () => clearTimeout(timer);
  }, [pretraga, open, izvorBroj]);

  // reset pri zatvaranju
  useEffect(() => {
    if (!open) {
      setPretraga("");
      setRezultati([]);
      setIzabran(null);
      setPotvrda(false);
    }
  }, [open]);

  async function prebaci() {
    if (!izabran || cuva) return;
    setCuva(true);
    try {
      await apiFetch(`/uplate/${uplata.kljuc}/prebaci`, {
        method: "POST",
        body: JSON.stringify({ ugovor: izabran.kljuc }),
      });
      setPotvrda(false);
      toast.warning(
        `Uplata ${uplata.kljuc} se prebacuje sa ugovora ${izvorUgovor} na ugovor ${izabran.kljuc}`,
        { duration: 8000 },
      );
      onPrebaceno(izabran.kljuc);
      onOpenChange(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Prebacivanje uplate nije uspelo");
    } finally {
      setCuva(false);
    }
  }

  return (
    <>
      <Dialog open={open} onOpenChange={(o) => { if (!cuva) onOpenChange(o); }}>
        <DialogContent className="sm:max-w-lg bg-card">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <ArrowRightLeft className="w-5 h-5 text-primary" />Povraćaj — prebacivanje uplate
            </DialogTitle>
            <DialogDescription>
              Uplata se povezuje na izabrani aranžman. Obe napomene interne se automatski dopunjuju.
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-4">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label>Datum prebacivanja</Label>
                <div className="flex h-9 items-center gap-2 rounded-md border bg-muted/40 px-3 text-sm">
                  <CalendarDays className="w-4 h-4 text-muted-foreground" />
                  {danasnjiDatum()}
                </div>
              </div>
              <div className="space-y-1.5">
                <Label>Uplata</Label>
                <div className="flex h-9 items-center gap-2 rounded-md border bg-muted/40 px-3 text-sm">
                  <span className="font-mono">{uplata.kljuc}</span>
                  <span className="text-muted-foreground">·</span>
                  <span>{uplata.din != null ? `${nf2.format(uplata.din)} din` : "—"}</span>
                  <span className="ml-auto text-xs text-muted-foreground">sa {izvorUgovor}</span>
                </div>
              </div>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="prebaci-ugovor">Ugovor na koji se uplata prebacuje</Label>
              {izabran ? (
                <div className="flex items-center gap-2 rounded-md border border-primary/40 bg-primary/5 px-3 py-2 text-sm">
                  <span className="font-mono font-semibold">{izabran.kljuc}</span>
                  <span className="truncate text-muted-foreground">{izabran.putnik}</span>
                  <span className="truncate text-xs text-muted-foreground">{izabran.naziv}</span>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="ml-auto size-7"
                    aria-label="Ukloni izbor ugovora"
                    disabled={cuva}
                    onClick={() => setIzabran(null)}
                  >
                    <X className="size-4" />
                  </Button>
                </div>
              ) : (
                <>
                  <div className="relative">
                    <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                    <Input
                      id="prebaci-ugovor"
                      className="pl-8"
                      placeholder="Broj ugovora ili ime putnika (min. 2 znaka)"
                      value={pretraga}
                      onChange={(e) => setPretraga(e.target.value)}
                      autoComplete="off"
                    />
                    {ucitava && <Loader2 className="absolute right-2.5 top-2.5 h-4 w-4 animate-spin text-muted-foreground" />}
                  </div>
                  {rezultati.length > 0 && (
                    <div className="max-h-60 overflow-y-auto rounded-md border">
                      {rezultati.map((r) => (
                        <button
                          key={r.kljuc}
                          type="button"
                          onClick={() => setIzabran(r)}
                          className="flex w-full flex-wrap items-center gap-x-3 gap-y-0.5 border-b px-3 py-2 text-left text-sm transition-colors last:border-0 hover:bg-accent"
                        >
                          <span className="font-mono font-semibold">{r.kljuc}</span>
                          <span className="truncate">{r.putnik}</span>
                          <span className="truncate text-xs text-muted-foreground">{r.naziv}</span>
                          {r.datumod && <Badge variant="secondary" className="ml-auto">{r.datumod}</Badge>}
                        </button>
                      ))}
                    </div>
                  )}
                  {!ucitava && pretraga.trim().length >= 2 && rezultati.length === 0 && (
                    <p className="text-xs text-muted-foreground">Nema ugovora za ovu pretragu.</p>
                  )}
                </>
              )}
            </div>

            {izabran && (
              <div className="flex gap-2 rounded-md border border-amber-400/60 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" />
                <span>
                  Uplata {uplata.kljuc} će biti prebačena sa ugovora {izvorUgovor} na ugovor {izabran.kljuc}.
                  Posle potvrde prebacivanje se ne može poništiti jednim klikom.
                </span>
              </div>
            )}
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" disabled={cuva} onClick={() => onOpenChange(false)}>Odustani</Button>
            <Button disabled={!izabran || cuva} onClick={() => setPotvrda(true)}>
              <ArrowRightLeft className="w-4 h-4 mr-1.5" />Prebaci uplatu
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <AlertDialog open={potvrda} onOpenChange={(o) => { if (!cuva) setPotvrda(o); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="flex items-center gap-2 text-amber-700">
              <TriangleAlert className="w-5 h-5" />Uplata se prebacuje
            </AlertDialogTitle>
            <AlertDialogDescription>
              Uplata {uplata.kljuc} ({uplata.din != null ? `${nf2.format(uplata.din)} din` : "—"}) prebacuje se sa ugovora{" "}
              <strong>{izvorUgovor}</strong> na ugovor <strong>{izabran?.kljuc}</strong>. Napomene interne oba ugovora
              će biti dopunjene. Da li želite da nastavite?
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={cuva}>Odustani</AlertDialogCancel>
            <AlertDialogAction
              disabled={cuva}
              onClick={(e) => { e.preventDefault(); void prebaci(); }}
            >
              {cuva && <Loader2 className="w-4 h-4 mr-1.5 animate-spin" />}
              Potvrdi prebacivanje
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
