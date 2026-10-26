import { useState, useEffect } from "react";
import { apiFetch } from "../lib/api";
import { postaviNazivAgencije } from "../hooks/useAgencijaPrviNaziv";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Loader2, Save, Building } from "lucide-react";
import { toast } from "sonner";

interface AgencijaData {
  naziv?: string;
  poslovno_ime?: string;
  email1?: string;
  email2?: string;
  telefon1?: string;
  telefon2?: string;
  ulica?: string;
  broj?: string;
  post_broj?: string;
  mesto?: string;
  drzava?: string;
  opstina_rgz?: string;
  opstina_naziv?: string;
  mesto_rgz?: string;
  mesto_naziv?: string;
  ulica_rgz?: string;
  ulica_naziv?: string;
  api_kljuc_efakture?: string;
  api_kljuc_cis?: string;
  pib?: string;
  mb?: string;
  jbkjs?: string;
  jmbg?: string;
  tekuci_racun1?: string;
  banka1?: string;
  tekuci_racun2?: string;
  banka2?: string;
  tekuci_racun3?: string;
  banka3?: string;
  tekuci_racun4?: string;
  banka4?: string;
}

const empty: AgencijaData = {
  naziv: "", poslovno_ime: "", email1: "", email2: "",
  telefon1: "", telefon2: "", ulica: "", broj: "", post_broj: "",
  mesto: "", drzava: "", opstina_rgz: "", opstina_naziv: "",
  mesto_rgz: "", mesto_naziv: "", ulica_rgz: "", ulica_naziv: "",
  api_kljuc_efakture: "", api_kljuc_cis: "",
  pib: "", mb: "", jbkjs: "", jmbg: "",
  tekuci_racun1: "", banka1: "", tekuci_racun2: "", banka2: "",
  tekuci_racun3: "", banka3: "", tekuci_racun4: "", banka4: "",
};

function Field({ label, name, value, onChange, type = "text" }: {
  label: string;
  name: keyof AgencijaData;
  value: string;
  onChange: (name: keyof AgencijaData, val: string) => void;
  type?: string;
}) {
  return (
    <div className="space-y-1.5">
      <Label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">{label}</Label>
      <Input
        type={type}
        value={value}
        onChange={(e) => onChange(name, e.target.value)}
        className="h-9"
      />
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-4 pt-2">
      <div>
        <h3 className="text-sm font-semibold text-foreground">{title}</h3>
        <Separator className="mt-2" />
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {children}
      </div>
    </div>
  );
}

export default function AgencijaPage() {
  const [form, setForm] = useState<AgencijaData>(empty);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    apiFetch<AgencijaData>("/agencija")
      .then((data) => setForm({ ...empty, ...data }))
      .catch(() => toast.error("Greška pri učitavanju podataka"))
      .finally(() => setLoading(false));
  }, []);

  function setField(name: keyof AgencijaData, val: string) {
    setForm((f) => ({ ...f, [name]: val }));
  }

  async function handleSave() {
    setSaving(true);
    try {
      await apiFetch("/agencija", { method: "PUT", body: JSON.stringify(form) });
      postaviNazivAgencije(form.naziv);
      toast.success("Podaci su sačuvani");
    } catch {
      toast.error("Greška pri čuvanju podataka");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
            <Building className="w-6 h-6" /> Osnovni podaci agencije
          </h1>
          <p className="text-muted-foreground mt-1 text-sm">Opšte informacije, kontakti i finansijski podaci</p>
        </div>
        <Button onClick={handleSave} disabled={saving} className="gap-2">
          {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
          Sačuvaj
        </Button>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Podaci o agenciji</CardTitle>
          <CardDescription>Popunite sve relevantne podatke o agenciji</CardDescription>
        </CardHeader>
        <CardContent className="space-y-10 pt-6">

          <Section title="Opšti podaci">
            <Field label="Naziv" name="naziv" value={form.naziv || ""} onChange={setField} />
            <Field label="Poslovno ime" name="poslovno_ime" value={form.poslovno_ime || ""} onChange={setField} />
            <Field label="PIB" name="pib" value={form.pib || ""} onChange={setField} />
            <Field label="Matični broj" name="mb" value={form.mb || ""} onChange={setField} />
            <Field label="JBKJS" name="jbkjs" value={form.jbkjs || ""} onChange={setField} />
            <Field label="JMBG" name="jmbg" value={form.jmbg || ""} onChange={setField} />
          </Section>

          <Section title="Kontakt">
            <Field label="Email 1" name="email1" value={form.email1 || ""} onChange={setField} type="email" />
            <Field label="Email 2" name="email2" value={form.email2 || ""} onChange={setField} type="email" />
            <Field label="Telefon 1" name="telefon1" value={form.telefon1 || ""} onChange={setField} />
            <Field label="Telefon 2" name="telefon2" value={form.telefon2 || ""} onChange={setField} />
          </Section>

          <Section title="Adresa">
            <Field label="Ulica" name="ulica" value={form.ulica || ""} onChange={setField} />
            <Field label="Broj" name="broj" value={form.broj || ""} onChange={setField} />
            <Field label="Poštanski broj" name="post_broj" value={form.post_broj || ""} onChange={setField} />
            <Field label="Mesto" name="mesto" value={form.mesto || ""} onChange={setField} />
            <Field label="Država" name="drzava" value={form.drzava || ""} onChange={setField} />
          </Section>

          <Section title="RGZ podaci">
            <Field label="Opština RGZ" name="opstina_rgz" value={form.opstina_rgz || ""} onChange={setField} />
            <Field label="Opština naziv" name="opstina_naziv" value={form.opstina_naziv || ""} onChange={setField} />
            <Field label="Mesto RGZ" name="mesto_rgz" value={form.mesto_rgz || ""} onChange={setField} />
            <Field label="Mesto naziv" name="mesto_naziv" value={form.mesto_naziv || ""} onChange={setField} />
            <Field label="Ulica RGZ" name="ulica_rgz" value={form.ulica_rgz || ""} onChange={setField} />
            <Field label="Ulica naziv" name="ulica_naziv" value={form.ulica_naziv || ""} onChange={setField} />
          </Section>

          <Section title="API ključevi">
            <Field label="API ključ eFakture" name="api_kljuc_efakture" value={form.api_kljuc_efakture || ""} onChange={setField} />
            <Field label="API ključ CIS" name="api_kljuc_cis" value={form.api_kljuc_cis || ""} onChange={setField} />
          </Section>

          <div className="space-y-4 pt-2">
            <div>
              <h3 className="text-sm font-semibold text-foreground">Tekući računi</h3>
              <Separator className="mt-2" />
            </div>
            <div className="space-y-3">
              {([1, 2, 3, 4] as const).map((n) => (
                <div key={n} className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <Field
                    label={`Tekući račun ${n}`}
                    name={`tekuci_racun${n}` as keyof AgencijaData}
                    value={form[`tekuci_racun${n}` as keyof AgencijaData] || ""}
                    onChange={setField}
                  />
                  <Field
                    label={`Banka ${n}`}
                    name={`banka${n}` as keyof AgencijaData}
                    value={form[`banka${n}` as keyof AgencijaData] || ""}
                    onChange={setField}
                  />
                </div>
              ))}
            </div>
          </div>

        </CardContent>
      </Card>

      {/* Bottom save button */}
      <div className="flex justify-end">
        <Button onClick={handleSave} disabled={saving} className="gap-2">
          {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
          Sačuvaj izmene
        </Button>
      </div>
    </div>
  );
}
