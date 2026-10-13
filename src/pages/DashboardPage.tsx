import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import type { UgovorRow, UgovoriResponse } from "../types";
import { apiFetch } from "../lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Globe, Users, ShieldCheck, Search, Loader2, FileText, User } from "lucide-react";

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
                      onClick={() => navigate(`/knjigovodstvo/ugovor?u=${encodeURIComponent(r.kljuc)}`)}
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
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
              <Globe className="w-4 h-4" /> Sistem
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">Aktivan</p>
            <p className="text-xs text-muted-foreground mt-1">Sve usluge rade normalno</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
              <Users className="w-4 h-4" /> Tipovi korisnika
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">7</p>
            <p className="text-xs text-muted-foreground mt-1">Konfigurisani tipovi</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
              <ShieldCheck className="w-4 h-4" /> Pristup
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">{user?.is_superadmin ? "Super Admin" : "Ograničen"}</p>
            <p className="text-xs text-muted-foreground mt-1">Nivo pristupa</p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Brzi pristup</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          Koristite navigaciju sa leve strane za upravljanje tipovima korisnika i nalozima.
        </CardContent>
      </Card>
    </div>
  );
}
