import { useEffect, useState } from "react";
import { apiFetch } from "../lib/api";
import { useAuth } from "../context/AuthContext";

// Prva reč iz polja "Naziv" (Podešavanja → Osnovni podaci agencije).
// Keš je na nivou modula: učitava se jednom, a čuvanje u Osnovnim podacima
// ga osvežava kroz postaviNazivAgencije().

let prviNaziv = "";
let ucitano = false;
let ucitavanje: Promise<void> | null = null;
const pretplatnici = new Set<(v: string) => void>();

function prvaReč(naziv: string | null | undefined): string {
  return (naziv ?? "").trim().split(/\s+/)[0] ?? "";
}

function obavesti() {
  pretplatnici.forEach((f) => f(prviNaziv));
}

export function postaviNazivAgencije(naziv: string | null | undefined) {
  prviNaziv = prvaReč(naziv);
  ucitano = true;
  obavesti();
}

function ucitajNaziv(): Promise<void> {
  if (ucitano) return Promise.resolve();
  if (!ucitavanje) {
    ucitavanje = apiFetch<{ naziv?: string | null }>("/agencija")
      .then((data) => postaviNazivAgencije(data?.naziv))
      .catch(() => {
        // Greška: ostaje prazno, a sledeći mount pokušava ponovo.
      })
      .finally(() => {
        ucitavanje = null;
      });
  }
  return ucitavanje;
}

/** Vraća prvu reč iz naziva agencije ("" dok se ne učita ili ako je polje prazno). */
export function useAgencijaPrviNaziv(): string {
  const { user } = useAuth();
  const [vrednost, setVrednost] = useState(prviNaziv);

  useEffect(() => {
    pretplatnici.add(setVrednost);
    return () => {
      pretplatnici.delete(setVrednost);
    };
  }, []);

  useEffect(() => {
    if (user) void ucitajNaziv();
  }, [user]);

  return vrednost;
}
