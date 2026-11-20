import { cn } from "@/lib/utils";
import { ChevronLeft, ChevronRight } from "lucide-react";

export const MESECI = ["Januar", "Februar", "Mart", "April", "Maj", "Jun", "Jul", "Avgust", "Septembar", "Oktobar", "Novembar", "Decembar"];
export const DANI_U_NED = ["Pon", "Uto", "Sre", "Čet", "Pet", "Sub", "Ned"];

export function toIso(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${dd}`;
}

export function shiftIso(iso: string, days: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(y || 2026, (m || 1) - 1, d || 1);
  dt.setDate(dt.getDate() + days);
  return toIso(dt);
}

/** ISO (YYYY-MM-DD) → lokalni Date */
export function isoToDate(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y || 2026, (m || 1) - 1, d || 1);
}

/** ISO (YYYY-MM-DD) → DD.MM.YYYY. (prikaz na triggeru) */
export function fmtDatum(iso: string): string {
  const [y, m, d] = iso.split("-");
  return d && m && y ? `${d}.${m}.${y}.` : "—";
}

/** Ključ dana (YYYY-M-D) za poređenje datuma */
export function keyOf(d: Date): string {
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

/** ISO → {y, m} za mesec kalendara */
export function viewFromIso(iso: string): { y: number; m: number } {
  const [y, m] = iso.split("-").map(Number);
  return { y: y || 2026, m: (m || 1) - 1 };
}

/** Mini kalendar (ponedeljak-first) — svi dani klikabilni */
export function Kalendar({ view, onView, selectedKey, onPick }: {
  view: { y: number; m: number };
  onView: (v: { y: number; m: number }) => void;
  selectedKey: string;
  onPick: (d: Date) => void;
}) {
  const todayKey = keyOf(new Date());
  const firstIdx = (new Date(view.y, view.m, 1).getDay() + 6) % 7;
  const daysInMonth = new Date(view.y, view.m + 1, 0).getDate();
  const cells: (Date | null)[] = [
    ...Array.from({ length: firstIdx }, () => null as Date | null),
    ...Array.from({ length: daysInMonth }, (_, i) => new Date(view.y, view.m, i + 1)),
  ];
  while (cells.length % 7 !== 0) cells.push(null);
  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <button
          type="button" aria-label="Prethodni mesec"
          onClick={() => onView(view.m === 0 ? { y: view.y - 1, m: 11 } : { y: view.y, m: view.m - 1 })}
          className="h-8 w-8 rounded-md flex items-center justify-center text-muted-foreground hover:bg-muted transition-colors"
        >
          <ChevronLeft className="w-4 h-4" />
        </button>
        <div className="text-sm font-semibold">{MESECI[view.m]} {view.y}</div>
        <button
          type="button" aria-label="Sledeći mesec"
          onClick={() => onView(view.m === 11 ? { y: view.y + 1, m: 0 } : { y: view.y, m: view.m + 1 })}
          className="h-8 w-8 rounded-md flex items-center justify-center text-muted-foreground hover:bg-muted transition-colors"
        >
          <ChevronRight className="w-4 h-4" />
        </button>
      </div>
      <div className="grid grid-cols-7 mb-1">
        {DANI_U_NED.map((d) => (
          <div key={d} className="h-7 flex items-center justify-center text-[11px] font-medium text-muted-foreground">
            {d}
          </div>
        ))}
      </div>
      <div className="grid grid-cols-7 gap-y-0.5">
        {cells.map((d, i) => {
          if (!d) return <div key={`e-${i}`} />;
          const k = keyOf(d);
          const selected = selectedKey === k;
          const today = todayKey === k;
          return (
            <button
              key={k} type="button" onClick={() => onPick(d)}
              className={cn(
                "h-8 w-8 mx-auto rounded-md text-sm flex items-center justify-center transition-colors",
                selected
                  ? "bg-primary text-primary-foreground font-semibold"
                  : today
                    ? "border border-primary text-primary font-semibold hover:bg-primary/10"
                    : "text-foreground font-medium hover:bg-muted"
              )}
            >
              {d.getDate()}
            </button>
          );
        })}
      </div>
    </div>
  );
}
