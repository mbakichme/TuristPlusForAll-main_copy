import { useEffect, useRef } from "react";
import { toast } from "sonner";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import type { Notifikacija, NotifikacijeNoviji } from "../types";
import { apiFetch } from "../lib/api";

// Događaj koji se šalje kad stignu nove poruke; naslovna ga sluša i ažurira listu
export const NOTIFIKACIJE_NOVE_EVENT = "notifikacije:nove";
const INTERVAL_MS = 5000;

// Prati nove notifikacije u pozadini (polling): prikazuje obaveštenje
// za poruke drugih korisnika i šalje događaj naslovnoj za živo ažuriranje.
export default function NotifikacijeLive() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const posle = useRef<number | null>(null);

  useEffect(() => {
    if (!user) return;
    let aktivan = true;
    let tajmer: ReturnType<typeof setTimeout> | undefined;

    const proveri = async () => {
      try {
        const url = posle.current === null
          ? "/notifikacije/novije"
          : `/notifikacije/novije?posle=${posle.current}`;
        const d = await apiFetch<NotifikacijeNoviji>(url);
        if (!aktivan) return;
        if (posle.current === null) {
          posle.current = d.max_id;
        } else if (d.rows.length > 0) {
          posle.current = d.rows[d.rows.length - 1].id;
          const tudje = d.rows.filter((p: Notifikacija) => p.autor_id !== user.id);
          window.dispatchEvent(new CustomEvent(NOTIFIKACIJE_NOVE_EVENT, { detail: d.rows }));
          if (tudje.length > 0) {
            const p = tudje[tudje.length - 1];
            const autor = p.autor_ime || p.autor_username || "Korisnik";
            const tekst = tudje.length === 1
              ? `${autor}: ${p.poruka}`
              : `Novih poruka: ${tudje.length}. Poslednja od ${autor}`;
            toast.info("Nova notifikacija", {
              description: tekst.length > 160 ? tekst.slice(0, 160) + "…" : tekst,
              action: { label: "Otvori", onClick: () => navigate("/") },
              duration: 8000,
            });
          }
        }
      } catch {
        // mrežna greška — pokušaj ponovo na sledećem ciklusu
      }
      if (aktivan) tajmer = setTimeout(proveri, INTERVAL_MS);
    };

    proveri();
    return () => {
      aktivan = false;
      if (tajmer) clearTimeout(tajmer);
    };
  }, [user, navigate]);

  return null;
}
