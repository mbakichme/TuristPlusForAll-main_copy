import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import type { UgovorRow, UgovoriResponse, Notifikacija, NotifikacijeResponse } from "../types";
import { apiFetch } from "../lib/api";
import { NOTIFIKACIJE_NOVE_EVENT } from "../components/NotifikacijeLive";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Search, Loader2, FileText, User, CalendarDays, CalendarCheck, Bell } from "lucide-react";

// Backend prima max 200 po stranici — prikaz svih rezultata u skrolu
const FETCH_LIMIT = 200;

type UgovorDanas = {
  kljuc: string;
  nosioc: string | null;
  mesto: string | null;
  smestaj: string | null;
  datumod: string | null;
  datumdo: string | null;
  soba: string | null;
  struktura: string | null;
  obradio: string | null;
};

type UgovoriDanasResponse = { datum: string; ukupno: number; rows: UgovorDanas[] };

// "25.05.2026" + "04.06.2026" → "25.05-04.06.2026"; različite godine → pun zapis
function formatTermin(od: string | null, doD: string | null): string {
  if (!od) return "—";
  if (!doD) return od;
  const [d1, m1, y1] = od.split(".");
  const [d2, m2, y2] = doD.split(".");
  if (y1 && y1 === y2) return `${d1}.${m1}-${d2}.${m2}.${y2}`;
  return `${od}-${doD}`;
}

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
  const [danas, setDanas] = useState<UgovorDanas[]>([]);
  const [danasDatum, setDanasDatum] = useState("");

  useEffect(() => {
    apiFetch<UgovoriDanasResponse>("/ugovori-danas")
      .then((d) => { setDanas(d.rows); setDanasDatum(d.datum); })
      .catch(() => setDanas([]));
  }, []);

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

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <button
          type="button"
          onClick={() => navigate("/prodaja/pretraga")}
          className="text-left rounded-xl border border-blue-200 bg-blue-50 p-5 hover:bg-blue-100 transition-colors"
        >
          <span className="flex items-center gap-3">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-blue-600 text-white">
              <Search className="w-5 h-5" />
            </span>
            <span className="text-lg font-semibold text-blue-800">Pretraga</span>
          </span>
          <p className="text-xs text-blue-700/80 mt-2">Pregled raspoloživih aranžmana</p>
        </button>
        <button
          type="button"
          onClick={() => navigate("/agencija/grafik")}
          className="text-left rounded-xl border border-emerald-200 bg-emerald-50 p-5 hover:bg-emerald-100 transition-colors"
        >
          <span className="flex items-center gap-3">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-emerald-600 text-white">
              <CalendarDays className="w-5 h-5" />
            </span>
            <span className="text-lg font-semibold text-emerald-800">Grafik</span>
          </span>
          <p className="text-xs text-emerald-700/80 mt-2">Grafički pregled raspoloživosti</p>
        </button>
        <button
          type="button"
          onClick={() => navigate("/prodaja/rezervacije")}
          className="text-left rounded-xl border border-orange-200 bg-orange-50 p-5 hover:bg-orange-100 transition-colors"
        >
          <span className="flex items-center gap-3">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-orange-500 text-white">
              <CalendarCheck className="w-5 h-5" />
            </span>
            <span className="text-lg font-semibold text-orange-800">Rezervacije</span>
          </span>
          <p className="text-xs text-orange-700/80 mt-2">Nova rezervacija ili izmena postojeće</p>
        </button>
        <button
          type="button"
          onClick={() => navigate("/knjigovodstvo/ugovori")}
          className="text-left rounded-xl border border-violet-200 bg-violet-50 p-5 hover:bg-violet-100 transition-colors"
        >
          <span className="flex items-center gap-3">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-violet-600 text-white">
              <FileText className="w-5 h-5" />
            </span>
            <span className="text-lg font-semibold text-violet-800">Ugovori</span>
          </span>
          <p className="text-xs text-violet-700/80 mt-2">Rezervacije, predrezervacije i storno</p>
        </button>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[3fr_2fr] gap-4 items-start">
      <Card className="border-sky-200 bg-sky-50/50">
        <CardHeader className="flex flex-row items-center justify-between space-y-0">
          <CardTitle className="text-base flex items-center gap-2 text-sky-800">
            <FileText className="w-4 h-4" /> Ugovori kreirani danas
          </CardTitle>
          <span className="text-xs text-sky-800/80 font-medium">
            {danasDatum} · {danas.length}
          </span>
        </CardHeader>
        <CardContent>
          {danas.length === 0 ? (
            <p className="text-sm text-muted-foreground">Danas još nema kreiranih ugovora.</p>
          ) : (
            <div className="rounded-md border border-sky-200 bg-card max-h-96 overflow-auto">
              <Table className="text-xs">
                <TableHeader className="sticky top-0 bg-card z-10">
                  <TableRow className="h-7">
                    <TableHead className="h-7 px-2 py-1 whitespace-nowrap">Broj ugovora</TableHead>
                    <TableHead className="h-7 px-2 py-1 whitespace-nowrap">Nosioc</TableHead>
                    <TableHead className="h-7 px-2 py-1 whitespace-nowrap">Mesto</TableHead>
                    <TableHead className="h-7 px-2 py-1 whitespace-nowrap">Smeštaj</TableHead>
                    <TableHead className="h-7 px-2 py-1 whitespace-nowrap">Termin</TableHead>
                    <TableHead className="h-7 px-2 py-1 whitespace-nowrap">Soba</TableHead>
                    <TableHead className="h-7 px-2 py-1 whitespace-nowrap">Obradio</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {danas.map((u) => (
                    <TableRow
                      key={u.kljuc}
                      onClick={() => navigate(`/prodaja/rezervacije?u=${encodeURIComponent(u.kljuc)}`)}
                      className="cursor-pointer h-7"
                    >
                      <TableCell className="px-2 py-1 font-mono font-medium whitespace-nowrap">{u.kljuc}</TableCell>
                      <TableCell className="px-2 py-1 max-w-[7.5rem] truncate" title={u.nosioc ?? ""}>{u.nosioc || "—"}</TableCell>
                      <TableCell className="px-2 py-1 max-w-[6rem] truncate" title={u.mesto ?? ""}>{u.mesto || "—"}</TableCell>
                      <TableCell className="px-2 py-1 max-w-[7rem] truncate" title={u.smestaj ?? ""}>{u.smestaj || "—"}</TableCell>
                      <TableCell className="px-2 py-1 whitespace-nowrap">
                        {formatTermin(u.datumod, u.datumdo)}
                      </TableCell>
                      <TableCell className="px-2 py-1 whitespace-nowrap">
                        {u.soba ? `${u.soba.trim()}${u.struktura?.trim() ? ` (${u.struktura.trim()})` : ""}` : "—"}
                      </TableCell>
                      <TableCell className="px-2 py-1 max-w-[7.5rem] truncate" title={u.obradio ?? ""}>{u.obradio || "—"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

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
    </div>
  );
}
