import { useState, useEffect, useRef } from "react";
import type { ChangeEvent } from "react";
import type { Dokument } from "../types";
import { apiFetch } from "../lib/api";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Upload, Trash2, Loader2, FileImage, ImagePlus } from "lucide-react";
import { toast } from "sonner";

const MAX_SIZE = 4 * 1024 * 1024; // 4 MB

function PreviewBox({ slika, className }: { slika: string | null; className?: string }) {
  return (
    <div
      className={
        "flex items-center justify-center overflow-hidden rounded-lg border border-dashed bg-muted/40 " +
        (className || "h-36")
      }
    >
      {slika ? (
        <img src={slika} alt="Dokument" className="max-h-full max-w-full object-contain" />
      ) : (
        <div className="flex flex-col items-center gap-1 text-muted-foreground">
          <ImagePlus className="w-6 h-6" />
          <span className="text-xs">Slika nije otpremljena</span>
        </div>
      )}
    </div>
  );
}

export default function DokumentiPage() {
  const [rows, setRows] = useState<Dokument[]>([]);
  const [loading, setLoading] = useState(true);
  const [napomene, setNapomene] = useState<Record<string, string>>({});
  const [savingNapomena, setSavingNapomena] = useState<string | null>(null);
  const [uploading, setUploading] = useState<string | null>(null);
  const [uploadTip, setUploadTip] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  async function load() {
    try {
      const data = await apiFetch<Dokument[]>("/dokumenti");
      setRows(data);
      setNapomene(Object.fromEntries(data.map((r) => [r.tip, r.napomena ?? ""])));
    } catch {
      toast.error("Greška pri učitavanju dokumenata");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  function applyRow(upd: Dokument) {
    setRows((prev) => prev.map((r) => (r.tip === upd.tip ? upd : r)));
    setNapomene((prev) => ({ ...prev, [upd.tip]: upd.napomena ?? "" }));
  }

  function pokreniUpload(tip: string) {
    setUploadTip(tip);
    requestAnimationFrame(() => fileRef.current?.click());
  }

  async function onFilePicked(e: ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    e.target.value = "";
    const tip = uploadTip;
    setUploadTip(null);
    if (!f || !tip) return;
    if (!f.type.startsWith("image/")) { toast.error("Izaberite sliku (PNG, JPG...)"); return; }
    if (f.size > MAX_SIZE) { toast.error("Slika je veća od 4 MB"); return; }
    const reader = new FileReader();
    reader.onload = async () => {
      setUploading(tip);
      try {
        const upd = await apiFetch<Dokument>(`/dokumenti/${tip}/slika`, {
          method: "POST",
          body: JSON.stringify({ data_url: String(reader.result) }),
        });
        applyRow(upd);
        toast.success("Slika je sačuvana");
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "Greška pri otpremanju");
      } finally {
        setUploading(null);
      }
    };
    reader.readAsDataURL(f);
  }

  async function ukloniSliku(tip: string) {
    try {
      const upd = await apiFetch<Dokument>(`/dokumenti/${tip}/slika`, { method: "DELETE" });
      applyRow(upd);
      toast.success("Slika je uklonjena");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Greška");
    }
  }

  async function sacuvajNapomenu(tip: string) {
    setSavingNapomena(tip);
    try {
      const upd = await apiFetch<Dokument>(`/dokumenti/${tip}/napomena`, {
        method: "PUT",
        body: JSON.stringify({ napomena: napomene[tip] ?? "" }),
      });
      applyRow(upd);
      toast.success("Napomena sačuvana");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Greška");
    } finally {
      setSavingNapomena(null);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const logo = rows.find((r) => r.tip === "logo");
  const dokumenti = rows.filter((r) => r.tip !== "logo");

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Dokumenti</h1>
        <p className="text-muted-foreground text-sm">
          Logo, headeri i napomene za štampane dokumente (predračun, ugovor, faktura, vaučer...)
        </p>
      </div>

      <input
        ref={fileRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={onFilePicked}
      />

      {/* Logo */}
      {logo && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><FileImage className="w-5 h-5" />{logo.naziv}</CardTitle>
            <CardDescription>Koristi se na dokumentima i PDF izveštajima</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4 sm:flex-row sm:items-center">
            <PreviewBox slika={logo.slika} className="h-32 w-full sm:w-48" />
            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                onClick={() => pokreniUpload("logo")}
                disabled={uploading === "logo"}
              >
                {uploading === "logo"
                  ? <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  : <Upload className="w-4 h-4 mr-2" />}
                Otpremi logo
              </Button>
              {logo.slika && (
                <Button variant="outline" className="text-destructive hover:text-destructive" onClick={() => ukloniSliku("logo")}>
                  <Trash2 className="w-4 h-4 mr-2" />Ukloni
                </Button>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Dokumenti po tipu */}
      <div className="grid gap-4 md:grid-cols-2">
        {dokumenti.map((d) => {
          const dirrt = napomene[d.tip] ?? "";
          const izmenjena = dirrt !== (d.napomena ?? "");
          return (
            <Card key={d.tip}>
              <CardHeader>
                <CardTitle className="flex items-center gap-2"><FileImage className="w-5 h-5" />{d.naziv}</CardTitle>
                <CardDescription>Header se štampa u vrhu dokumenta</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <PreviewBox slika={d.slika} />
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => pokreniUpload(d.tip)}
                    disabled={uploading === d.tip}
                  >
                    {uploading === d.tip
                      ? <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                      : <Upload className="w-4 h-4 mr-2" />}
                    {d.slika ? "Zameni header" : "Otpremi header"}
                  </Button>
                  {d.slika && (
                    <Button
                      variant="outline"
                      size="sm"
                      className="text-destructive hover:text-destructive"
                      onClick={() => ukloniSliku(d.tip)}
                    >
                      <Trash2 className="w-4 h-4 mr-2" />Ukloni
                    </Button>
                  )}
                </div>
                <div className="space-y-2">
                  <Label>Napomena</Label>
                  <Textarea
                    rows={4}
                    value={dirrt}
                    onChange={(e) => setNapomene((prev) => ({ ...prev, [d.tip]: e.target.value }))}
                    placeholder={`Tekst napomene na ${d.naziv.toLowerCase()}u...`}
                  />
                  <div className="flex justify-end">
                    <Button
                      size="sm"
                      onClick={() => sacuvajNapomenu(d.tip)}
                      disabled={!izmenjena || savingNapomena === d.tip}
                    >
                      {savingNapomena === d.tip && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
                      Sačuvaj napomenu
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
