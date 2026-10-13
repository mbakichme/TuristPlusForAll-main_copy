import { useEffect, useState } from "react";
import { useNavigate, useParams, useLocation, Link } from "react-router-dom";
import type { PredracunPripremi, Predracun } from "../types";
import { apiFetch } from "../lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue
} from "@/components/ui/select";
import { Loader2, FileText, ArrowLeft } from "lucide-react";
import { toast } from "sonner";

const fmtNum = (v: number | null | undefined, suffix = "") =>
  v == null ? "—" : new Intl.NumberFormat("sr-RS", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(v) + suffix;

function ReadOnly({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div>
      <div className="text-muted-foreground text-[11px]">{label}</div>
      <div className="text-xs">{value || "—"}</div>
    </div>
  );
}

export default function PredracunFormPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const params = useParams();
  const isEdit = !location.pathname.includes("/novi/");
  const editId = isEdit ? Number(params.id) : null;
  const ugovor = !isEdit ? (params["*"] || "").trim() : "";

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [pripremi, setPripremi] = useState<PredracunPripremi | null>(null);
  const [existing, setExisting] = useState<Predracun | null>(null);
  const [racun, setRacun] = useState("");
  const [nacin, setNacin] = useState("");
  const [napomena, setNapomena] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        if (isEdit) {
          const d = await apiFetch<Predracun>(`/predracuni/${editId}`);
          if (cancelled) return;
          setExisting(d);
          setRacun(d.racun || "");
          setNacin(d.nacin || "");
          setNapomena(d.napomena || "");
        } else {
          const d = await apiFetch<PredracunPripremi>(`/predracuni/pripremi/${ugovor}`);
          if (cancelled) return;
          setPripremi(d);
          setRacun(d.racuni[0]?.racun || "");
          setNacin(d.nacini[0] || "");
        }
      } catch {
        if (!cancelled) toast.error("Greška pri učitavanju podataka za predracun");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [isEdit, editId, ugovor]);

  async function save() {
    setSaving(true);
    try {
      if (isEdit) {
        await apiFetch(`/predracuni/${editId}`, {
          method: "PUT",
          body: JSON.stringify({ racun, nacin, napomena }),
        });
        toast.success("Predračun je sačuvan");
      } else {
        await apiFetch("/predracuni", {
          method: "POST",
          body: JSON.stringify({ ugovor, racun, nacin, napomena }),
        });
        toast.success("Predračun je kreiran");
      }
      navigate("/knjigovodstvo/predracuni");
    } catch {
      toast.error("Greška pri čuvanju predračuna");
    } finally {
      setSaving(false);
    }
  }

  const broj = isEdit ? existing?.broj_predracuna : pripremi?.broj_predracuna;
  const datum = isEdit ? existing?.datum_fmt : pripremi?.datum;
  const nosilac = isEdit ? existing?.nosilac : pripremi?.nosilac;
  const saputnik = isEdit ? existing?.saputnik : pripremi?.saputnik;
  const destinacija = isEdit ? existing?.destinacija : pripremi?.destinacija;
  const period = isEdit ? existing?.period : pripremi?.period;
  const provizija = isEdit ? existing?.provizija : pripremi?.provizija;
  const zaduzenje = isEdit ? existing?.zaduzenje : pripremi?.zaduzenje;
  const subagent = isEdit ? existing?.subagent : pripremi?.subagent;
  const adresa = isEdit ? existing?.adresa : pripremi?.adresa;
  const mesto = isEdit ? existing?.mesto : pripremi?.mesto;
  const ugovorVal = isEdit ? existing?.ugovor : pripremi?.ugovor;
  const organizator = isEdit ? existing?.organizator : pripremi?.organizator;
  const poslovnica = isEdit ? existing?.poslovnica : pripremi?.poslovnica;

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Button variant="outline" size="icon" onClick={() => navigate(-1)}>
            <ArrowLeft className="w-4 h-4" />
          </Button>
          <div>
            <h1 className="text-2xl font-bold">{isEdit ? "Predračun" : "Kreiraj predracun"}</h1>
            <p className="text-muted-foreground text-sm">Broj: {broj || "..."}</p>
          </div>
        </div>
        <Button onClick={save} disabled={saving || loading}>
          {saving && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
          Sačuvaj predracun
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <FileText className="w-4 h-4" />Predračun {broj}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="py-10 text-center">
              <Loader2 className="w-6 h-6 animate-spin mx-auto text-muted-foreground" />
            </div>
          ) : (
            <div className="space-y-5">
              <div className="grid grid-cols-2 md:grid-cols-3 gap-x-4 gap-y-2">
                <ReadOnly label="Broj predracuna" value={broj} />
                <ReadOnly label="Datum" value={datum} />
                <ReadOnly label="Ugovor" value={ugovorVal} />
                <ReadOnly label="Nosilac" value={nosilac} />
                <ReadOnly label="Saputnik" value={saputnik} />
                <ReadOnly label="Destinacija" value={destinacija} />
                <ReadOnly label="Period" value={period} />
                <ReadOnly label="Organizator" value={organizator} />
                <ReadOnly label="Poslovnica" value={poslovnica} />
                <ReadOnly label="Subagent" value={subagent} />
                <ReadOnly label="Adresa subagenta" value={adresa} />
                <ReadOnly label="Mesto subagenta" value={mesto} />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-md border bg-muted/30 p-3 text-xs space-y-1">
                  <div className="font-semibold mb-1.5">Obračun</div>
                  <div className="flex justify-between"><span className="text-muted-foreground">Provizija</span><span>{fmtNum(provizija, " RSD")}</span></div>
                  <div className="flex justify-between border-t pt-1.5"><span className="font-semibold">Zaduženje</span><span className="font-bold">{fmtNum(zaduzenje, " RSD")}</span></div>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-x-4 gap-y-2.5">
                <div>
                  <Label className="text-[11px]">Račun</Label>
                  <Select value={racun} onValueChange={setRacun}>
                    <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="Izaberi račun" /></SelectTrigger>
                    <SelectContent>
                      {(isEdit
                        ? [{ label: racun || "—", racun: racun || "", banka: "" }]
                        : (pripremi?.racuni || [])
                      ).map((r) => (
                        <SelectItem key={r.racun} value={r.racun} className="text-xs">
                          {r.label}{r.banka ? ` — ${r.banka}` : ""}{r.racun ? ` · ${r.racun}` : ""}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {isEdit && <p className="text-[10px] text-muted-foreground mt-0.5">{racun || "—"}</p>}
                </div>
                <div>
                  <Label className="text-[11px]">Način</Label>
                  <Select value={nacin} onValueChange={setNacin}>
                    <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="Izaberi način" /></SelectTrigger>
                    <SelectContent>
                      {(isEdit
                        ? [nacin]
                        : (pripremi?.nacini || [])
                      ).filter(Boolean).map((n) => (
                        <SelectItem key={n} value={n} className="text-xs">{n}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="md:col-span-2">
                  <Label className="text-[11px]">Napomena</Label>
                  <Textarea
                    value={napomena}
                    onChange={(e) => setNapomena(e.target.value)}
                    className="min-h-16 text-xs"
                    placeholder="Napomena..."
                  />
                </div>
              </div>

              {!isEdit && (
                <p className="text-[11px] text-muted-foreground">
                  Kreiranjem predračuna broj se dodeljuje automatski: prvi nosi broj ugovora, sledeći{" "}
                  <span className="font-mono">-1</span>, <span className="font-mono">-2</span>... Pogledajte sve predracune u{" "}
                  <Link to="/knjigovodstvo/predracuni" className="underline">Predračuni</Link>.
                </p>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
