import { addMonths, format } from "date-fns";

/** Koraci zaokruživanja rate u centima: 1000 din, 100 din, 10 din, 1 din, 1 cent. */
const KORACI_CENTI = [100000, 10000, 1000, 100, 1];

/**
 * Raspodela iznosa na n čekova (iznosi u RSD).
 * Pravilo: osnovna rata = količnik naviše zaokružen na 1000 din; poslednja = ostatak.
 * Primer: 43000 / 9 → 8 × 5000 + 3000. Ako ostatak ne bi bio pozitivan
 * (npr. 1000 / 3), korak se smanjuje na 100 → 10 → 1 din.
 */
export function podeliIznos(ukupno: number, n: number): number[] {
  if (!Number.isInteger(n) || n < 1) return [];
  const T = Math.round(ukupno * 100);
  for (const k of KORACI_CENTI) {
    const osnovna = Math.ceil(T / (n * k)) * k;
    if (osnovna * (n - 1) < T) {
      const poslednja = T - osnovna * (n - 1);
      return [...Array.from({ length: n - 1 }, () => osnovna / 100), poslednja / 100];
    }
  }
  return [];
}

/** Datumi čekova: prvi zadati, svaki sledeći +1 mesec. Format YYYY-MM-DD. */
export function generisiDatume(prvi: Date, n: number): string[] {
  return Array.from({ length: n }, (_, i) => format(addMonths(prvi, i), "yyyy-MM-dd"));
}

/** Zbir u centima — poređenje bez float grešaka. */
export function zbirCenti(iznosi: number[]): number {
  return iznosi.reduce((s, v) => s + Math.round(v * 100), 0);
}
