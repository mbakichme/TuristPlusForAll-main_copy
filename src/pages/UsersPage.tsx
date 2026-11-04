import { useState, useEffect } from "react";
import type { User, UserType } from "../types";
import { apiFetch } from "../lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow
} from "@/components/ui/table";
import {
  Sheet, SheetContent, SheetHeader, SheetTitle, SheetFooter
} from "@/components/ui/sheet";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle
} from "@/components/ui/alert-dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue
} from "@/components/ui/select";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Plus, Pencil, Trash2, Loader2, UserPlus, ShieldCheck } from "lucide-react";
import { toast } from "sonner";

interface UserForm {
  first_name: string;
  last_name: string;
  email: string;
  phone: string;
  address: string;
  city: string;
  status: string;
  username: string;
  password: string;
  user_type_id: string;
  poslovnica_id: string;
}

const emptyForm: UserForm = {
  first_name: "", last_name: "", email: "", phone: "",
  address: "", city: "", status: "aktivan", username: "",
  password: "", user_type_id: "", poslovnica_id: "",
};

interface PoslovnicaOpcija { id: number; naziv: string; }

const NEMA_POSLOVNICE = "nema";

export default function UsersPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [userTypes, setUserTypes] = useState<UserType[]>([]);
  const [poslovnice, setPoslovnice] = useState<PoslovnicaOpcija[]>([]);
  const [loading, setLoading] = useState(true);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [deleteId, setDeleteId] = useState<number | null>(null);
  const [editing, setEditing] = useState<User | null>(null);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState<UserForm>(emptyForm);

  async function load() {
    try {
      const [usersData, typesData, posData] = await Promise.all([
        apiFetch<User[]>("/users"),
        apiFetch<UserType[]>("/user-types"),
        apiFetch<{ poslovnice: PoslovnicaOpcija[] }>("/poslovnice"),
      ]);
      setUsers(usersData);
      setUserTypes(typesData);
      setPoslovnice(posData.poslovnice);
    } catch {
      toast.error("Greška pri učitavanju");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  function setField(key: keyof UserForm, value: string) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  function openAdd() {
    setEditing(null);
    setForm(emptyForm);
    setSheetOpen(true);
  }

  function openEdit(u: User) {
    setEditing(u);
    setForm({
      first_name: u.first_name, last_name: u.last_name,
      email: u.email, phone: u.phone || "",
      address: u.address || "", city: u.city || "",
      status: u.status, username: u.username,
      password: "", user_type_id: u.user_type_id?.toString() || "",
      poslovnica_id: u.poslovnica_id?.toString() || "",
    });
    setSheetOpen(true);
  }

  async function handleSave() {
    if (!form.first_name || !form.last_name || !form.email || !form.username) {
      toast.error("Ime, prezime, email i korisničko ime su obavezni");
      return;
    }
    if (!editing && !form.password) {
      toast.error("Lozinka je obavezna");
      return;
    }
    setSaving(true);
    try {
      const body: Record<string, unknown> = {
        first_name: form.first_name,
        last_name: form.last_name,
        email: form.email,
        phone: form.phone || null,
        address: form.address || null,
        city: form.city || null,
        status: form.status,
        username: form.username,
        user_type_id: form.user_type_id ? parseInt(form.user_type_id) : null,
        poslovnica_id: form.poslovnica_id ? parseInt(form.poslovnica_id) : null,
      };
      if (form.password) body.password = form.password;
      if (!editing) body.password = form.password;

      if (editing) {
        await apiFetch(`/users/${editing.id}`, { method: "PUT", body: JSON.stringify(body) });
        toast.success("Korisnik je ažuriran");
      } else {
        await apiFetch("/users", { method: "POST", body: JSON.stringify(body) });
        toast.success("Korisnik je dodat");
      }
      setSheetOpen(false);
      load();
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Greška");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!deleteId) return;
    try {
      await apiFetch(`/users/${deleteId}`, { method: "DELETE" });
      toast.success("Korisnik je obrisan");
      setDeleteId(null);
      load();
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Greška pri brisanju");
    }
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Korisnici</h1>
          <p className="text-muted-foreground mt-1">Upravljanje korisničkim nalozima</p>
        </div>
        <Button onClick={openAdd} className="gap-2">
          <Plus className="w-4 h-4" /> Dodaj korisnika
        </Button>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <UserPlus className="w-4 h-4" /> Svi korisnici
          </CardTitle>
          <CardDescription>{users.length} korisnika</CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex justify-center py-12">
              <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Korisnik</TableHead>
                  <TableHead>Email / Korisničko ime</TableHead>
                  <TableHead>Tip</TableHead>
                  <TableHead>Kontakt</TableHead>
                  <TableHead>Poslovnica</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="w-24 text-right">Akcije</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {users.map((u) => (
                  <TableRow key={u.id}>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0">
                          {u.is_superadmin
                            ? <ShieldCheck className="w-4 h-4 text-primary" />
                            : <span className="text-xs font-bold text-primary">{u.first_name[0]}{u.last_name[0]}</span>
                          }
                        </div>
                        <div>
                          <p className="font-medium text-sm">{u.first_name} {u.last_name}</p>
                          {u.city && <p className="text-xs text-muted-foreground">{u.city}</p>}
                        </div>
                      </div>
                    </TableCell>
                    <TableCell>
                      <p className="text-sm">{u.email}</p>
                      <p className="text-xs text-muted-foreground font-mono">@{u.username}</p>
                    </TableCell>
                    <TableCell>
                      {u.is_superadmin ? (
                        <Badge className="bg-primary/10 text-primary border-primary/20 text-xs">Super Admin</Badge>
                      ) : u.user_type_name ? (
                        <Badge variant="secondary" className="text-xs">{u.user_type_name}</Badge>
                      ) : (
                        <span className="text-muted-foreground text-sm">—</span>
                      )}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {u.phone || "—"}
                    </TableCell>
                    <TableCell className="text-sm">
                      {u.poslovnica_naziv || <span className="text-muted-foreground">—</span>}
                    </TableCell>
                    <TableCell>
                      <Badge variant={u.status === "aktivan" ? "default" : "secondary"} className="text-xs">
                        {u.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      {!u.is_superadmin && (
                        <div className="flex items-center justify-end gap-1">
                          <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => openEdit(u)}>
                            <Pencil className="w-3.5 h-3.5" />
                          </Button>
                          <Button
                            variant="ghost" size="icon"
                            className="h-8 w-8 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
                            onClick={() => setDeleteId(u.id)}
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </Button>
                        </div>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Add/Edit Sheet */}
      <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
        <SheetContent className="w-full sm:max-w-lg overflow-y-auto">
          <SheetHeader>
            <SheetTitle>{editing ? "Izmeni korisnika" : "Dodaj korisnika"}</SheetTitle>
          </SheetHeader>
          <div className="space-y-4 py-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>Ime *</Label>
                <Input value={form.first_name} onChange={(e) => setField("first_name", e.target.value)} placeholder="Ime" />
              </div>
              <div className="space-y-2">
                <Label>Prezime *</Label>
                <Input value={form.last_name} onChange={(e) => setField("last_name", e.target.value)} placeholder="Prezime" />
              </div>
            </div>
            <div className="space-y-2">
              <Label>Email *</Label>
              <Input type="email" value={form.email} onChange={(e) => setField("email", e.target.value)} placeholder="email@primer.rs" />
            </div>
            <div className="space-y-2">
              <Label>Telefon</Label>
              <Input value={form.phone} onChange={(e) => setField("phone", e.target.value)} placeholder="+381 60 123 4567" />
            </div>
            <div className="space-y-2">
              <Label>Adresa</Label>
              <Input value={form.address} onChange={(e) => setField("address", e.target.value)} placeholder="Ulica i broj" />
            </div>
            <div className="space-y-2">
              <Label>Grad</Label>
              <Input value={form.city} onChange={(e) => setField("city", e.target.value)} placeholder="Beograd" />
            </div>
            <div className="space-y-2">
              <Label>Tip korisnika</Label>
              <Select value={form.user_type_id} onValueChange={(v) => setField("user_type_id", v)}>
                <SelectTrigger>
                  <SelectValue placeholder="Izaberi tip..." />
                </SelectTrigger>
                <SelectContent>
                  {userTypes.map((t) => (
                    <SelectItem key={t.id} value={t.id.toString()}>{t.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Poslovnica</Label>
              <Select
                value={form.poslovnica_id || NEMA_POSLOVNICE}
                onValueChange={(v) => setField("poslovnica_id", v === NEMA_POSLOVNICE ? "" : v)}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Izaberi poslovnicu..." />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NEMA_POSLOVNICE}>— Bez poslovnice —</SelectItem>
                  {poslovnice.map((p) => (
                    <SelectItem key={p.id} value={p.id.toString()}>{p.naziv}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Status</Label>
              <Select value={form.status} onValueChange={(v) => setField("status", v)}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="aktivan">Aktivan</SelectItem>
                  <SelectItem value="neaktivan">Neaktivan</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Korisničko ime *</Label>
              <Input value={form.username} onChange={(e) => setField("username", e.target.value)} placeholder="korisnik123" />
            </div>
            <div className="space-y-2">
              <Label>{editing ? "Nova lozinka (ostavite prazno da zadržite)" : "Lozinka *"}</Label>
              <Input
                type="password"
                value={form.password}
                onChange={(e) => setField("password", e.target.value)}
                placeholder={editing ? "••••••••" : "Minimalno 6 karaktera"}
              />
            </div>
          </div>
          <SheetFooter>
            <Button variant="outline" onClick={() => setSheetOpen(false)}>Otkaži</Button>
            <Button onClick={handleSave} disabled={saving}>
              {saving ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : null}
              {editing ? "Sačuvaj izmene" : "Dodaj korisnika"}
            </Button>
          </SheetFooter>
        </SheetContent>
      </Sheet>

      {/* Delete Confirm */}
      <AlertDialog open={deleteId !== null} onOpenChange={() => setDeleteId(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Obriši korisnika?</AlertDialogTitle>
            <AlertDialogDescription>
              Ova akcija ne može biti poništena. Korisnički nalog će biti trajno obrisan.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Otkaži</AlertDialogCancel>
            <AlertDialogAction onClick={handleDelete} className="bg-destructive text-destructive-foreground hover:bg-destructive/90">
              Obriši
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
