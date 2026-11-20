import { useEffect, useState } from "react";
import { CreditCard } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { KarticaPodaci } from "@/types";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  vrednost: KarticaPodaci;
  tipovi: string[];
  naslov: string;
  opis: string;
  cuva: boolean;
  onSacuvaj: (k: KarticaPodaci) => void;
}

const PRAZNO: KarticaPodaci = { brojPotvrde: "", tipKartice: "", brojKartice: "", brojOdobrenja: "" };

/** Popup za podatke kartice uz već snimljenu uplatu. Obavezan je samo tip kartice. */
export function KarticaPopup({ open, onOpenChange, vrednost, tipovi, naslov, opis, cuva, onSacuvaj }: Props) {
  const [draft, setDraft] = useState<KarticaPodaci>(PRAZNO);

  useEffect(() => {
    // draft se puni samo pri otvaranju — ne resetovati dok korisnik kuca
    if (open) setDraft({ ...vrednost });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const upd = (patch: Partial<KarticaPodaci>) => setDraft((d) => ({ ...d, ...patch }));

  function potvrdi() {
    if (!draft.tipKartice) return;
    onSacuvaj({ ...draft, brojKartice: draft.brojKartice.trim() });
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md bg-card">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-base">
            <CreditCard className="size-4 text-primary" />{naslov}
          </DialogTitle>
          <DialogDescription>{opis}</DialogDescription>
        </DialogHeader>

        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">Broj potvrde</label>
            <Input value={draft.brojPotvrde} maxLength={100} onChange={(e) => upd({ brojPotvrde: e.target.value })} aria-label="Broj potvrde" />
          </div>
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">Tip kartice</label>
            <Select value={draft.tipKartice || undefined} onValueChange={(v) => upd({ tipKartice: v })}>
              <SelectTrigger className="w-full" aria-label="Tip kartice"><SelectValue placeholder="Izaberite" /></SelectTrigger>
              <SelectContent>
                {tipovi.map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">Broj kartice</label>
            <Input
              value={draft.brojKartice}
              onChange={(e) => upd({ brojKartice: e.target.value })}
              aria-label="Broj kartice"
            />
          </div>
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">Broj odobrenja</label>
            <Input value={draft.brojOdobrenja} maxLength={100} onChange={(e) => upd({ brojOdobrenja: e.target.value })} aria-label="Broj odobrenja" />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={cuva}>Odustani</Button>
          <Button onClick={potvrdi} disabled={cuva || !draft.tipKartice}>
            {cuva ? "Čuvanje…" : "Sačuvaj"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
