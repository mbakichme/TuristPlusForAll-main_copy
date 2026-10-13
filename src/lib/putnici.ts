// Pomoćne funkcije za prikaz putnika (saputnici iz aranzman_dopuna)
import type { PutnikDetalj } from "@/types"

/** CHD/INF oznake uzrasta prevodimo u čitljiv tekst; odrasli bez oznake */
export function uzrastOznaka(uzrast?: string | null): string | null {
  const u = (uzrast || "").trim().toUpperCase()
  if (u === "CHD") return "dete"
  if (u === "INF") return "beba"
  return null
}

/** Ime saputnika sa oznakom uzrasta kad postoji: "PERIC MARKA (dete)" */
export function fmtPutnik(p: PutnikDetalj): string {
  const ime = (p.saputnik || "").trim()
  const o = uzrastOznaka(p.uzrast)
  return o ? `${ime} (${o})` : ime
}

/** Spisak saputnika za prikaz (bez praznih imena) */
export function fmtPutnici(detalji?: PutnikDetalj[] | null): string[] {
  return (detalji || []).map(fmtPutnik).filter((ime) => ime.length > 0)
}
