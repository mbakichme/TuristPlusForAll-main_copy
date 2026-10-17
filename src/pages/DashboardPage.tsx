import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import type { UgovorRow, UgovoriResponse, Notifikacija, NotifikacijeResponse } from "../types";
import { apiFetch } from "../lib/api";
import { NOTIFIKACIJE_NOVE_EVENT } from "../components/NotifikacijeLive";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Search, Loader2, FileText, User, CalendarDays, CalendarCheck, Bell } from "lucide-react";

// Backend prima max 200 po stranici — prikaz svih rezultata u skrolu
const FETCH_LIMIT = 200;

export default function DashboardPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [searchInput, setSearchInput] = useState("");
  const [query, setQuery] = useState("");
  const [rows, setRows] = useState<UgovorRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const reqId = useRef(0);
  const [poruke, setPoruke] = useState<Notifikacija[]>([]);

  useEffect(() => {
    apiFetch<NotifikacijeResponse>("/notifikacije?limit=10")
      .then((d) => setPoruke(d.rows))
      .catch(() => setPoruke([]));
  }, []);

  // Živo ažuriranje: nove poruke iz NotifikacijeLive (polling) ulaze na vrh liste
  useEffect(() => {
    const onNove = (e: Event) => {
      const nove = (e as CustomEvent<Notifikacija[]>).detail;
      setPoruke((prev) => {
        const postojeci = new Set(prev.map((p) => p.id));
        const dodaj = nove.filter((p) => !postojeci.has(p.id)).reverse();
        return [...dodaj, ...prev].slice(0, 10);
      });
    };
    window.addEventListener(NOTIFIKACIJE_NOVE_EVENT, onNove);
    return () => window.removeEventListener(NOTIFIKACIJE_NOVE_EVENT, onNove);
  }, []);

  // Debounce — pretraga se pokreće nakon 3 uneta karaktera
  useEffect(() => {
    const t = setTimeout(() => setQuery(searchInput.trim()), 400);
    return () => clearTimeout(t);
  }, [searchInput]);

  useEffect(() => {
    if (query.length < 3) {
      setRows([]); setTotal(0); setLoading(false);
      return;
    }
    const rid = ++reqId.current;
    setLoading(true);
    const params = new URLSearchParams({
      search: query,
      search_in: "putnik,kljuc",
      page_size: String(FETCH_LIMIT),
      sort: "kljuc",
      dir: "asc",
    });
    apiFetch<UgovoriResponse>(`/ugovori?${params}`)
      .then((d) => {
        if (rid !== reqId.current) return;
        setRows(d.rows); setTotal(d.total);
      })
      .catch(() => {
        if (rid !== reqId.current) return;
        setRows([]); setTotal(0);
      })
      .finally(() => {
        if (rid === reqId.current) setLoading(false);
      });
  }, [query]);

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-foreground">
          Korisnik: {user?.first_name}!
        </h1>
        <p className="text-muted-foreground mt-1">
          {user?.is_superadmin ? "Super Administrator" : user?.user_type_name} &middot; TuristPlus Admin Panel
        </p>
      </div>

      {/* Pretraga ugovora — prvi card */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Search className="w-5 h-5" />Pretraga ugovora
          </CardTitle>
          <CardDescription>
            Pretraga po broju ugovora ili imenu putnika (najmanje 3 karaktera)
          </CardDescription>
          <div className="relative mt-2">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Broj ugovora (npr. 10038) ili ime putnika..."
              className="pl-9"
            />
            {loading && <Loader2 className="absolute right-2.5 top-1/2 -translate-y-1/2 w-4 h-4 animate-spin text-muted-foreground" />}
          </div>
        </CardHeader>
        {query.length >= 3 && (
          <CardContent>
            {rows.length === 0 && !loading ? (
              <div className="text-sm text-muted-foreground py-3 text-center">
                Nema rezultata za „{query}”
              </div>
            ) : (
              <>
                <div className="divide-y rounded-md border max-h-80 overflow-y-auto">
                  {rows.map((r) => (
                    <button
                      key={r.kljuc}
                      onClick={() => navigate(`/prodaja/rezervacije?u=${encodeURIComponent(r.kljuc)}`)}
                      className="w-full text-left px-3 py-2 hover:bg-muted/60 transition-colors flex items-center justify-between gap-3"
                    >
                      <div className="flex items-center gap-3 min-w-0">
                        <FileText className="w-4 h-4 text-muted-foreground shrink-0" />
                        <span className="font-mono font-medium text-sm shrink-0">{r.kljuc}</span>
                        <span className="text-sm font-medium truncate">{r.putnik || "—"}</span>
                        {(r.putnici?.length ?? 0) > 1 && (
                          <span
                            className="inline-flex items-center gap-0.5 text-muted-foreground shrink-0"
                            title={r.putnici!.slice(1).join(", ")}
                          >
                            <span className="text-sm font-medium">+</span>
                            {r.putnici!.slice(1).map((_, i) => (
                              <User key={i} className="w-3.5 h-3.5" />
                            ))}
                          </span>
                        )}
                        <span className="text-xs text-muted-foreground truncate hidden sm:inline">{r.mesto || ""}</span>
                      </div>
                      <span className="text-xs text-muted-foreground whitespace-nowrap shrink-0">
                        {r.datumod}{r.datumdo ? ` – ${r.datumdo}` : ""}
                      </span>
                    </button>
                  ))}
                </div>
                {total > 0 && (
                  <p className="text-xs text-muted-foreground mt-2">
                    Pronađeno {total.toLocaleString("sr-RS")} ugovora{total > rows.length ? ` — prikazujem prvih ${rows.length}` : ""}
                  </p>
                )}
              </>
            )}
          </CardContent>
        )}
      </Card>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <button
          type="button"
          onClick={() => navigate("/prodaja/pretraga")}
          className="text-left rounded-xl border border-blue-200 bg-blue-50 p-5 hover:bg-blue-100 transition-colors"
        >
          <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-600 text-white">
            <Search className="w-5 h-5" />
          </span>
          <p className="mt-3 text-lg font-semibold text-blue-800">Pretraga</p>
          <p className="text-xs text-blue-700/80 mt-1">Slobodne sobe i cene po terminu</p>
        </button>
        <button
          type="button"
          onClick={() => navigate("/agencija/grafik")}
          className="text-left rounded-xl border border-emerald-200 bg-emerald-50 p-5 hover:bg-emerald-100 transition-colors"
        >
          <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-emerald-600 text-white">
            <CalendarDays className="w-5 h-5" />
          </span>
          <p className="mt-3 text-lg font-semibold text-emerald-800">Grafik</p>
          <p className="text-xs text-emerald-700/80 mt-1">Zauzeće smeštaja po danima</p>
        </button>
        <button
          type="button"
          onClick={() => navigate("/prodaja/rezervacije")}
          className="text-left rounded-xl border border-orange-200 bg-orange-50 p-5 hover:bg-orange-100 transition-colors"
        >
          <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-orange-500 text-white">
            <CalendarCheck className="w-5 h-5" />
          </span>
          <p className="mt-3 text-lg font-semibold text-orange-800">Rezervacije</p>
          <p className="text-xs text-orange-700/80 mt-1">Nova rezervacija ili izmena postojeće</p>
        </button>
      </div>

      <Card className="border-violet-200 bg-violet-50/50">
        <CardHeader className="flex flex-row items-center justify-between space-y-0">
          <CardTitle className="text-base flex items-center gap-2 text-violet-800">
            <Bell className="w-4 h-4" /> Notifikacije
          </CardTitle>
          <Button
            variant="outline"
            size="sm"
            onClick={() => navigate("/prodaja/notifikacije")}
            className="border-violet-300 text-violet-700 hover:bg-violet-100 hover:text-violet-800"
          >
            Pročitaj sve
          </Button>
        </CardHeader>
        <CardContent>
          {poruke.length === 0 ? (
            <p className="text-sm text-muted-foreground">Nema novih poruka.</p>
          ) : (
            <ul className="divide-y divide-violet-200">
              {poruke.map((p) => (
                <li key={p.id} className="py-2 first:pt-0 last:pb-0">
                  <p className="text-sm text-foreground whitespace-pre-wrap break-words">{p.poruka}</p>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {p.autor_ime || p.autor_username} · {new Date(p.created_at ?? "").toLocaleString("sr-RS", { dateStyle: "short", timeStyle: "short" })}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
