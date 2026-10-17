import { useState, type ReactNode } from "react";
import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { Toaster } from "@/components/ui/sonner";
import Sidebar from "./components/Sidebar";
import NotifikacijeLive from "./components/NotifikacijeLive";
import LoginPage from "./pages/LoginPage";
import DashboardPage from "./pages/DashboardPage";
import UserTypesPage from "./pages/UserTypesPage";
import UsersPage from "./pages/UsersPage";
import TipPonudePage from "./pages/TipPonudePage";
import DrzavaPage from "./pages/DrzavaPage";
import DestinacijaPage from "./pages/DestinacijaPage";
import MestoPage from "./pages/MestoPage";
import TipSmestajPage from "./pages/TipSmestajPage";
import SmestajPage from "./pages/SmestajPage";
import SobePage from "./pages/SobePage";
import PrevozPage from "./pages/PrevozPage";
import KursPage from "./pages/KursPage";
import GrafikPage from "./pages/GrafikPage";
import PretragaPage from "./pages/PretragaPage";
import RezervacijePage from "./pages/RezervacijePage";
import PeriodiPage from "./pages/PeriodiPage";
import CenovniciPage from "./pages/CenovniciPage";
import KoeficijentiPage from "./pages/KoeficijentiPage";
import AgencijaPage from "./pages/AgencijaPage";
import DokumentiPage from "./pages/DokumentiPage";
import BojeGrafikPage from "./pages/BojeGrafikPage";
import UgovoriPage from "./pages/UgovoriPage";
import UgovorDetaljPage from "./pages/UgovorDetaljPage";
import IzvodiPage from "./pages/IzvodiPage";
import KnjizenjePage from "./pages/KnjizenjePage";
import SubagentiPage from "./pages/SubagentiPage";
import PredracuniPage from "./pages/PredracuniPage";
import PredracunFormPage from "./pages/PredracunFormPage";
import PreuzimanjePage from "./pages/PreuzimanjePage";
import PregledProdajaAranzmanaPage from "./pages/PregledProdajaAranzmanaPage";
import NotifikacijePage from "./pages/NotifikacijePage";
import ProfilPage from "./pages/ProfilPage";
import PlaceholderPage from "./pages/PlaceholderPage";
import { Loader2, Menu } from "lucide-react";

// Tip "prodaja": dozvoljene su naslovna i stranice sekcije Prodaja
// (Pretraga, Rezervacije, Ugovori + detalj ugovora, Grafik)
function ProdajaRouteGuard({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const location = useLocation();
  const jeProdaja = !!user && !user.is_superadmin && user.user_type_slug === "prodaja";
  if (!jeProdaja) return <>{children}</>;
  const p = location.pathname;
  const dozvoljeno =
    p === "/" ||
    p.startsWith("/prodaja") ||
    p.startsWith("/knjigovodstvo/ugovor") ||
    p.startsWith("/agencija/grafik") ||
    p === "/profil";
  if (dozvoljeno) return <>{children}</>;
  return <Navigate to="/prodaja/pretraga" replace />;
}

function ProtectedLayout() {
  const { user, loading } = useAuth();
  const [mobileOpen, setMobileOpen] = useState(false);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <Loader2 className="w-8 h-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!user) return <Navigate to="/login" replace />;

  return (
    <div className="flex h-screen bg-background overflow-hidden">
      {/* Mobile overlay */}
      {mobileOpen && (
        <div className="fixed inset-0 z-40 bg-black/50 md:hidden" onClick={() => setMobileOpen(false)} />
      )}
      <Sidebar mobileOpen={mobileOpen} setMobileOpen={setMobileOpen} />
      <NotifikacijeLive />
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Mobile header with hamburger */}
        <div className="md:hidden flex items-center gap-3 px-4 py-3 bg-card border-b border-border">
          <button onClick={() => setMobileOpen(true)} className="p-1 rounded-md hover:bg-accent transition-colors">
            <Menu className="w-6 h-6" />
          </button>
          <span className="font-semibold text-sm">Oktopod Travel</span>
        </div>
        <main className="flex-1 overflow-y-auto">
          <ProdajaRouteGuard>
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/profil" element={<ProfilPage />} />
            <Route path="/prodaja/pretraga" element={<PretragaPage />} />
            <Route path="/prodaja/rezervacije" element={<RezervacijePage />} />
            <Route path="/prodaja/notifikacije" element={<NotifikacijePage />} />
            <Route path="/agencija/tip-ponude" element={<TipPonudePage />} />
            <Route path="/agencija/drzava" element={<DrzavaPage />} />
            <Route path="/agencija/destinacija" element={<DestinacijaPage />} />
            <Route path="/agencija/mesto" element={<MestoPage />} />
            <Route path="/agencija/tip-smestaja" element={<TipSmestajPage />} />
            <Route path="/agencija/smestaj" element={<SmestajPage />} />
            <Route path="/agencija/sobe" element={<SobePage />} />
            <Route path="/agencija/prevoz" element={<PrevozPage />} />
            <Route path="/agencija/kurs" element={<KursPage />} />
            <Route path="/agencija/grafik" element={<GrafikPage />} />
            <Route path="/agencija/periodi" element={<PeriodiPage />} />
            <Route path="/agencija/cenovnici" element={<CenovniciPage />} />
            <Route path="/agencija/koeficijenti" element={<KoeficijentiPage />} />
            <Route path="/knjigovodstvo/ugovori" element={<UgovoriPage />} />
            <Route path="/knjigovodstvo/ugovor" element={<UgovorDetaljPage />} />
            <Route path="/knjigovodstvo/izvodi" element={<IzvodiPage />} />
            <Route path="/knjigovodstvo/knjizenje" element={<KnjizenjePage />} />
            <Route path="/knjigovodstvo/subagenti" element={<SubagentiPage />} />
            <Route path="/knjigovodstvo/predracuni" element={<PredracuniPage />} />
            <Route path="/knjigovodstvo/predracuni/novi/*" element={<PredracunFormPage />} />
            <Route path="/knjigovodstvo/predracuni/:id/edit" element={<PredracunFormPage />} />
            <Route path="/knjigovodstvo/avansne-fakture" element={<PlaceholderPage title="Avansne fakture" />} />
            <Route path="/knjigovodstvo/fakture" element={<PlaceholderPage title="Fakture" />} />
            <Route path="/knjigovodstvo/dok-smanjenju" element={<PlaceholderPage title="Dokumenti o smanjenju" />} />
            <Route path="/knjigovodstvo/dok-smanjenju-avansnih" element={<PlaceholderPage title="Dokumenti o smanjenju avansnih faktura" />} />
            <Route path="/knjigovodstvo/dok-povecanju" element={<PlaceholderPage title="Dokumenti o povećanju" />} />
            <Route path="/pregledi/dnevni-izvestaji/prodaja-aranzmana" element={<PregledProdajaAranzmanaPage />} />
            <Route path="/preuzimanje_podataka/*" element={<PreuzimanjePage />} />
            <Route path="/podesavanja/tipovi-korisnika" element={<UserTypesPage />} />
            <Route path="/podesavanja/korisnici" element={<UsersPage />} />
            <Route path="/podesavanja/agencija" element={<AgencijaPage />} />
            <Route path="/podesavanja/dokumenti" element={<DokumentiPage />} />
            <Route path="/podesavanja/boje-grafik" element={<BojeGrafikPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
          </ProdajaRouteGuard>
        </main>
      </div>
    </div>
  );
}

function LoginRoute() {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <Loader2 className="w-8 h-8 animate-spin text-muted-foreground" />
      </div>
    );
  }
  if (user) return <Navigate to="/" replace />;
  return <LoginPage />;
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginRoute />} />
          <Route path="/*" element={<ProtectedLayout />} />
        </Routes>
        <Toaster richColors closeButton position="top-right" />
      </AuthProvider>
    </BrowserRouter>
  );
}
