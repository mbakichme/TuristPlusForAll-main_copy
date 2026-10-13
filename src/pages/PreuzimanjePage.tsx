import { useState, useEffect } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { apiFetch } from "../lib/api";
import { Loader2, CheckCircle2, XCircle } from "lucide-react";
import { toast } from "sonner";

export default function PreuzimanjePage() {
  const params = useParams();
  const wildcard = params["*"] || "";
  const broj = decodeURIComponent(wildcard).replace(/^\/+|\/+$/g, "");
  const navigate = useNavigate();
  const [status, setStatus] = useState<"loading" | "done" | "error">("loading");
  const [message, setMessage] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function run() {
      if (!broj) {
        setStatus("error");
        setMessage("Broj ugovora nije zadat.");
        return;
      }
      try {
        const res = await apiFetch<{ ok: boolean; aranzman: number; uplate: number }>(
          `/preuzimanje_podataka/${encodeURIComponent(broj)}`
        );
        if (cancelled) return;
        setStatus("done");
        setMessage(
          `Ugovor ${broj} je uspešno preuzet — aranžman: ${res.aranzman}, uplate: ${res.uplate}.`
        );
        toast.success("Podaci su uspešno preuzeti");
        setTimeout(() => {
          if (!cancelled) navigate("/knjigovodstvo/ugovori");
        }, 1500);
      } catch (e) {
        if (cancelled) return;
        setStatus("error");
        setMessage(e instanceof Error ? e.message : "Greška pri preuzimanju ugovora");
      }
    }
    run();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [broj]);

  return (
    <div className="flex items-center justify-center min-h-[60vh] p-6">
      <div className="flex flex-col items-center gap-4 text-center max-w-md">
        {status === "loading" && (
          <>
            <Loader2 className="w-10 h-10 animate-spin text-primary" />
            <p className="text-lg font-semibold">Preuzimanje ugovora {broj}...</p>
            <p className="text-sm text-muted-foreground">Podaci se učitavaju sa glavnog sistema.</p>
          </>
        )}
        {status === "done" && (
          <>
            <CheckCircle2 className="w-10 h-10 text-green-600" />
            <p className="text-lg font-semibold">{message}</p>
            <p className="text-sm text-muted-foreground">Preusmeravanje na ugovore...</p>
          </>
        )}
        {status === "error" && (
          <>
            <XCircle className="w-10 h-10 text-destructive" />
            <p className="text-lg font-semibold">Preuzimanje nije uspelo</p>
            <p className="text-sm text-muted-foreground">{message}</p>
          </>
        )}
      </div>
    </div>
  );
}
