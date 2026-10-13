import { useState, useEffect } from "react";
import type { ReactNode } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import type { UgovorDetail } from "../types";
import { apiFetch } from "../lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Loader2, ArrowLeft, FileText, User } from "lucide-react";
import { toast } from "sonner";

const fmtEur = (v: number | null | undefined) =>
  v == null ? "—" : new Intl.NumberFormat("sr-RS", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(v) + " €";

// Nosilac + ikonice saputnika (hover = imena saputnika)
function PutniciVrednost({ detail }: { detail: UgovorDetail }) {
  const saputnici = (detail.putnici || []).slice(1);
  return (
    <span className="inline-flex items-center justify-end gap-1.5 flex-wrap">
      <span>{detail.putnik || "—"}</span>
      {saputnici.length > 0 && (
        <span
          className="inline-flex items-center gap-0.5 text-muted-foreground"
          title={saputnici.join(", ")}
        >
          <span className="text-sm font-medium">+</span>
          {saputnici.map((_, i) => (
            <User key={i} className="w-3.5 h-3.5" />
          ))}
        </span>
      )}
    </span>
  );
}

function Pf({ label, value, mono }: { label: string; value: ReactNode; mono?: boolean }) {
  return (
    <div className="flex justify-between gap-4 border-b py-1.5 last:border-0">
      <span className="text-xs text-muted-foreground shrink-0">{label}</span>
      <span className={`text-sm font-medium text-right min-w-0 break-words ${mono ? "font-mono" : ""}`}>{value}</span>
    </div>
  );
}

export default function UgovorDetaljPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const kljuc = searchParams.get("u") || "";
  const [detail, setDetail] = useState<UgovorDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!kljuc) { setLoading(false); return; }
    setLoading(true);
    setDetail(null);
    apiFetch<UgovorDetail>(`/ugovori/${kljuc}`)
      .then(setDetail)
      .catch(() => toast.error("Greška pri učitavanju ugovora"))
      .finally(() => setLoading(false));
  }, [kljuc]);

  const period = detail?.datumod
    ? `${detail.datumod}${detail.datumdo ? ` - ${detail.datumdo}` : ""}`
    : null;

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <FileText className="w-6 h-6" />
            {detail ? `Ugovor ${detail.kljuc}` : "Ugovor"}
          </h1>
          {detail?.putnik && (
            <p className="text-muted-foreground text-sm truncate">{detail.putnik}</p>
          )}
        </div>
        <Button variant="outline" onClick={() => navigate(-1)}>
          <ArrowLeft className="w-4 h-4 mr-2" />Nazad
        </Button>
      </div>

      {loading ? (
        <div className="py-16 text-center">
          <Loader2 className="w-6 h-6 animate-spin mx-auto text-muted-foreground" />
        </div>
      ) : !detail ? (
        <Card>
          <CardContent className="py-10 text-center text-muted-foreground text-sm">
            {kljuc ? `Ugovor ${kljuc} nije pronađen` : "Ugovor nije specificiran"}
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Podaci o ugovoru</CardTitle>
            </CardHeader>
            <CardContent>
              <Pf label="Broj ugovora" value={detail.kljuc} mono />
              <Pf label="Datum ugovora" value={detail.danas || "—"} />
              <Pf label="Nosilac" value={<PutniciVrednost detail={detail} />} />
              <Pf
                label="Saputnici"
                value={
                  (detail.putnici?.length ?? 0) > 1
                    ? detail.putnici!.slice(1).join(", ")
                    : "—"
                }
              />
              <Pf label="Broj putnika" value={detail.putnici?.length || 1} mono />
              <Pf label="Mesto" value={detail.mesto || "—"} />
              <Pf label="Destinacija" value={detail.destinacija || "—"} />
              <Pf label="Smeštaj" value={detail.naziv || "—"} />
              <Pf label="Period" value={period || "—"} />
            </CardContent>
          </Card>

          <div className="space-y-4">
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Finansijski podaci</CardTitle>
              </CardHeader>
              <CardContent>
                <Pf label="Vrednost aranžmana" value={fmtEur(detail.ukupna_vrednost)} mono />
                <Pf label="Naplata" value={fmtEur(detail.naplata)} mono />
                <Pf label="Provizija" value={fmtEur(detail.provizija)} mono />
                <Pf label="Uplaćeno" value={fmtEur(detail.uplaceno)} mono />
                <Pf label="Saldo" value={fmtEur(detail.saldo)} mono />
                <Pf label="Kurs (EUR)" value={detail.kurs != null ? detail.kurs.toLocaleString("sr-RS") : "—"} mono />
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Subagent</CardTitle>
              </CardHeader>
              <CardContent>
                {detail.subagent_info ? (
                  <>
                    <Pf label="Naziv" value={detail.subagent_info.naziv || "—"} />
                    <Pf label="Telefon" value={detail.subagent_info.tel || "—"} />
                    <Pf label="Kontakt" value={detail.subagent_info.kontakt || "—"} />
                    <Pf label="Provizija" value={detail.subagent_info.provizija != null ? `${detail.subagent_info.provizija} %` : "—"} />
                    <Pf label="Račun" value={detail.subagent_info.racun || "—"} mono />
                  </>
                ) : (
                  <div className="text-sm text-muted-foreground py-1">Ugovor nije zaključen preko subagenta</div>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
