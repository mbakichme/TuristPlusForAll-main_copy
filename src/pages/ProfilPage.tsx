import { useEffect, useState } from "react";
import { toast } from "sonner";
import { CalendarDays, FileText, IdCard, KeyRound, Loader2, Phone, UserRound, type LucideIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiFetch } from "../lib/api";

type Profil = {
  id: number;
  first_name: string;
  last_name: string;
  email: string;
  username: string;
  phone: string | null;
  jmbg: string | null;
  is_superadmin: boolean;
  user_type_name: string | null;
  statistika: { ukupno_ugovora: number; danas_ugovora: number };
};

const TELEFON_RE = /^[0-9+()/.\- ]{5,50}$/;
const JMBG_RE = /^\d{13}$/;
const nf = new Intl.NumberFormat("sr-RS");

function StatKarta({ ikona: Ikona, naslov, vrednost, opis }: {
  ikona: LucideIcon; naslov: string; vrednost: number; opis: string;
}) {
  return (
    <Card className="rounded-2xl shadow-sm">
      <CardContent className="flex items-center gap-4 p-5">
        <div className="flex size-12 shrink-0 items-center justify-center rounded-2xl bg-primary/10">
          <Ikona className="size-6 text-primary" />
        </div>
        <div className="min-w-0">
          <p className="text-sm text-muted-foreground">{naslov}</p>
          <p className="text-3xl font-semibold tabular-nums tracking-tight">{nf.format(vrednost)}</p>
          <p className="text-xs text-muted-foreground">{opis}</p>
        </div>
      </CardContent>
    </Card>
  );
}

export default function ProfilPage() {
  const [profil, setProfil] = useState<Profil | null>(null);
  const [ucitava, setUcitava] = useState(true);

  const [telefon, setTelefon] = useState("");
  const [jmbg, setJmbg] = useState("");
  const [cuvaPodatke, setCuvaPodatke] = useState(false);

  const [trenutna, setTrenutna] = useState("");
  const [nova, setNova] = useState("");
  const [potvrda, setPotvrda] = useState("");
  const [cuvaLozinku, setCuvaLozinku] = useState(false);

  useEffect(() => {
    let aktivno = true;
    apiFetch<Profil>("/profil")
      .then((d) => {
        if (!aktivno) return;
        setProfil(d);
        setTelefon(d.phone ?? "");
        setJmbg(d.jmbg ?? "");
      })
      .catch(() => { if (aktivno) toast.error("Profil nije učitan"); })
      .finally(() => { if (aktivno) setUcitava(false); });
    return () => { aktivno = false; };
  }, []);

  const podaciIzmenjeni = !!profil
    && (telefon.trim() !== (profil.phone ?? "") || jmbg.trim() !== (profil.jmbg ?? ""));

  async function sacuvajPodatke() {
    const t = telefon.trim();
    const j = jmbg.trim();
    if (t && !TELEFON_RE.test(t)) { toast.error("Neispravan broj telefona"); return; }
    if (j && !JMBG_RE.test(j)) { toast.error("JMBG mora imati tačno 13 cifara"); return; }
    setCuvaPodatke(true);
    try {
      const r = await apiFetch<{ phone: string | null; jmbg: string | null }>("/profil", {
        method: "PUT",
        body: JSON.stringify({ phone: t, jmbg: j }),
      });
      setProfil((p) => (p ? { ...p, phone: r.phone, jmbg: r.jmbg } : p));
      setTelefon(r.phone ?? "");
      setJmbg(r.jmbg ?? "");
      toast.success("Podaci su sačuvani");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Greška");
    } finally {
      setCuvaPodatke(false);
    }
  }

  async function promeniLozinku() {
    if (!trenutna) { toast.error("Unesite trenutnu lozinku"); return; }
    if (nova.length < 8) { toast.error("Nova lozinka mora imati najmanje 8 karaktera"); return; }
    if (nova !== potvrda) { toast.error("Lozinke se ne poklapaju"); return; }
    setCuvaLozinku(true);
    try {
      await apiFetch("/profil/lozinka", {
        method: "POST",
        body: JSON.stringify({ trenutna, nova }),
      });
      setTrenutna("");
      setNova("");
      setPotvrda("");
      toast.success("Lozinka je promenjena");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Greška");
    } finally {
      setCuvaLozinku(false);
    }
  }

  if (ucitava) {
    return (
      <div className="flex justify-center py-24">
        <Loader2 className="size-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!profil) {
    return <div className="py-24 text-center text-sm text-muted-foreground">Profil nije dostupan.</div>;
  }

  const inicijali = `${profil.first_name[0] ?? ""}${profil.last_name[0] ?? ""}`.toUpperCase();
  const uloga = profil.is_superadmin ? "Super Admin" : profil.user_type_name ?? "Korisnik";

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6">
      <div className="flex items-center gap-4">
        <div className="flex size-16 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xl font-semibold text-primary">
          {inicijali}
        </div>
        <div className="min-w-0">
          <h1 className="truncate text-2xl font-semibold tracking-tight">{profil.first_name} {profil.last_name}</h1>
          <p className="truncate text-sm text-muted-foreground">{profil.email}</p>
          <Badge variant="secondary" className="mt-1">{uloga}</Badge>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <StatKarta
          ikona={FileText}
          naslov="Ukupno ugovora"
          vrednost={profil.statistika.ukupno_ugovora}
          opis="Ugovori koje ste kreirali"
        />
        <StatKarta
          ikona={CalendarDays}
          naslov="Danas"
          vrednost={profil.statistika.danas_ugovora}
          opis="Ugovori kreirani danas"
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="rounded-2xl shadow-sm">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <IdCard className="size-4 text-primary" />Lični podaci
            </CardTitle>
            <CardDescription>Telefon i JMBG su vidljivi samo vama i administratorima.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="profil-telefon">Telefon</Label>
              <div className="relative">
                <Phone className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  id="profil-telefon"
                  className="pl-9"
                  placeholder="npr. +381 64 123 4567"
                  value={telefon}
                  maxLength={50}
                  onChange={(e) => setTelefon(e.target.value)}
                />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="profil-jmbg">JMBG</Label>
              <Input
                id="profil-jmbg"
                inputMode="numeric"
                placeholder="13 cifara"
                value={jmbg}
                maxLength={13}
                onChange={(e) => setJmbg(e.target.value.replace(/\D/g, ""))}
              />
            </div>
            <div className="flex justify-end pt-2">
              <Button disabled={!podaciIzmenjeni || cuvaPodatke} onClick={() => void sacuvajPodatke()}>
                {cuvaPodatke && <Loader2 className="mr-1.5 size-4 animate-spin" />}
                Sačuvaj podatke
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card className="rounded-2xl shadow-sm">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <KeyRound className="size-4 text-primary" />Lozinka
            </CardTitle>
            <CardDescription>Najmanje 8 karaktera. Nova lozinka mora biti različita od trenutne.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="profil-trenutna">Trenutna lozinka</Label>
              <Input id="profil-trenutna" type="password" autoComplete="current-password"
                value={trenutna} onChange={(e) => setTrenutna(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="profil-nova">Nova lozinka</Label>
              <Input id="profil-nova" type="password" autoComplete="new-password"
                value={nova} onChange={(e) => setNova(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="profil-potvrda">Potvrda nove lozinke</Label>
              <Input id="profil-potvrda" type="password" autoComplete="new-password"
                value={potvrda} onChange={(e) => setPotvrda(e.target.value)} />
            </div>
            <div className="flex justify-end pt-2">
              <Button
                disabled={cuvaLozinku || !trenutna || !nova || !potvrda}
                onClick={() => void promeniLozinku()}
              >
                {cuvaLozinku && <Loader2 className="mr-1.5 size-4 animate-spin" />}
                Promeni lozinku
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>

      <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <UserRound className="size-3.5" />Korisničko ime: {profil.username}
      </p>
    </div>
  );
}
