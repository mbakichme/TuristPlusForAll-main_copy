import { useState, useEffect } from "react";
import type { Dispatch, SetStateAction } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { cn } from "@/lib/utils";
import { BrandMark } from "@/components/BrandMark";
import { useAuth } from "../context/AuthContext";
import { useAgencijaPrviNaziv } from "../hooks/useAgencijaPrviNaziv";
import {
  LayoutDashboard, Users, UserPlus,
  ChevronLeft, ChevronRight, ChevronDown, LogOut, ShieldCheck, Settings,
  Building2, Tag, Flag, MapPin, Map, Hotel, BedDouble, DoorOpen, Bus, ChartGantt, X, Building, CalendarDays, TrendingUp, Search, CalendarPlus,
  FileText, Receipt, ReceiptText, FilePlus, FileMinus, FileX, Handshake, Landmark, NotebookPen, FileImage,
  Eye, ShoppingBag, Banknote, Palette, Sigma, Bell, Store, ArrowRightLeft, Ban, Calculator, Armchair
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { Separator } from "@/components/ui/separator";

interface SidebarProps {
  mobileOpen: boolean;
  setMobileOpen: (v: boolean) => void;
}

interface NavItemProps {
  to: string;
  icon: React.ElementType;
  label: string;
  collapsed: boolean;
  onClick?: () => void;
}

function NavItem({ to, icon: Icon, label, collapsed, onClick }: NavItemProps) {
  const item = (
    <NavLink
      to={to}
      onClick={onClick}
      className={({ isActive }) =>
        cn(
          "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors w-full",
          "hover:bg-accent hover:text-accent-foreground",
          isActive
            ? "bg-primary text-primary-foreground hover:bg-primary hover:text-primary-foreground"
            : "text-muted-foreground"
        )
      }
    >
      <Icon className="w-5 h-5 flex-shrink-0" />
      {!collapsed && <span className="truncate">{label}</span>}
    </NavLink>
  );

  if (collapsed) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>{item}</TooltipTrigger>
        <TooltipContent side="right">{label}</TooltipContent>
      </Tooltip>
    );
  }
  return item;
}

function SidebarContent({ collapsed, settingsOpen, setSettingsOpen, agencijaOpen, setAgencijaOpen, prodajaOpen, setProdajaOpen, knjigovodstvoOpen, setKnjigovodstvoOpen, preglediOpen, setPreglediOpen, dnevniOpen, setDnevniOpen, handleLogout, user, onNavClick }: {
  collapsed: boolean;
  settingsOpen: boolean;
  setSettingsOpen: Dispatch<SetStateAction<boolean>>;
  agencijaOpen: boolean;
  setAgencijaOpen: Dispatch<SetStateAction<boolean>>;
  prodajaOpen: boolean;
  setProdajaOpen: Dispatch<SetStateAction<boolean>>;
  knjigovodstvoOpen: boolean;
  setKnjigovodstvoOpen: Dispatch<SetStateAction<boolean>>;
  preglediOpen: boolean;
  setPreglediOpen: Dispatch<SetStateAction<boolean>>;
  dnevniOpen: boolean;
  setDnevniOpen: Dispatch<SetStateAction<boolean>>;
  handleLogout: () => void;
  user: ReturnType<typeof useAuth>["user"];
  onNavClick?: () => void;
}) {
  // Tip "prodaja" vidi samo sekciju Prodaja
  const jeProdaja = !!user && !user.is_superadmin && user.user_type_slug === "prodaja";
  const prviNaziv = useAgencijaPrviNaziv();
  return (
    <>
      {/* Header */}
      <div className={cn("flex items-center gap-3 px-4 py-5 border-b border-border", collapsed && "justify-center px-2")}>
        <BrandMark className="w-9 h-9" />
        {!collapsed && (
          <div className="overflow-hidden">
            <p className="text-sm font-bold text-foreground leading-tight truncate">TuristPlus</p>
            <p className="text-xs text-muted-foreground truncate">{prviNaziv || "Admin Panel"}</p>
          </div>
        )}
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto py-4 px-2 space-y-1">
        <NavItem to="/" icon={LayoutDashboard} label="Naslovna" collapsed={collapsed} onClick={onNavClick} />

        {/* Agencija section */}
        {!jeProdaja && (
        <>
        <div className="pt-4">
          {!collapsed && (
            <button
              onClick={() => setAgencijaOpen((o) => !o)}
              className="w-full flex items-center justify-between px-3 mb-1 group"
            >
              <div className="flex items-center gap-2">
                <Building2 className="w-4 h-4 text-foreground" />
                <span className="text-sm font-bold text-foreground uppercase tracking-wider">
                  Agencija
                </span>
              </div>
              <ChevronDown
                className={cn(
                  "w-3.5 h-3.5 text-muted-foreground transition-transform duration-200",
                  !agencijaOpen && "-rotate-90"
                )}
              />
            </button>
          )}
          {collapsed && <Separator className="my-2" />}
          <div
            className={cn(
              "space-y-1 overflow-hidden transition-all duration-200",
              !collapsed && !agencijaOpen ? "max-h-0 opacity-0" : "max-h-[720px] opacity-100"
            )}
          >
            <NavItem to="/agencija/tip-ponude" icon={Tag} label="Tipovi ponude" collapsed={collapsed} onClick={onNavClick} />
            <NavItem to="/agencija/tip-smestaja" icon={Hotel} label="Tipovi smeštaja" collapsed={collapsed} onClick={onNavClick} />
            <NavItem to="/agencija/drzava" icon={Flag} label="Države" collapsed={collapsed} onClick={onNavClick} />
            <NavItem to="/agencija/destinacija" icon={MapPin} label="Destinacije" collapsed={collapsed} onClick={onNavClick} />
            <NavItem to="/agencija/mesto" icon={Map} label="Mesta" collapsed={collapsed} onClick={onNavClick} />
            <NavItem to="/agencija/smestaj" icon={BedDouble} label="Smeštaj" collapsed={collapsed} onClick={onNavClick} />
            <NavItem to="/agencija/sobe" icon={DoorOpen} label="Sobe" collapsed={collapsed} onClick={onNavClick} />
            <NavItem to="/agencija/dodatne-usluge" icon={Receipt} label="Dodatne usluge" collapsed={collapsed} onClick={onNavClick} />
            <NavItem to="/agencija/koeficijenti" icon={Sigma} label="Koeficijenti prodaje" collapsed={collapsed} onClick={onNavClick} />
            <NavItem to="/agencija/periodi" icon={CalendarDays} label="Periodi" collapsed={collapsed} onClick={onNavClick} />
            <NavItem to="/agencija/cenovnici" icon={Tag} label="Cenovnici" collapsed={collapsed} onClick={onNavClick} />
            <NavItem to="/agencija/prevoz" icon={Bus} label="Prevoz" collapsed={collapsed} onClick={onNavClick} />
            <NavItem to="/agencija/destinacija-prevoz" icon={Bus} label="Destinacija prevoz" collapsed={collapsed} onClick={onNavClick} />
            <NavItem to="/agencija/prevoz-limit" icon={Armchair} label="Limiti prevoz" collapsed={collapsed} onClick={onNavClick} />
            <NavItem to="/agencija/kurs" icon={Banknote} label="Kurs" collapsed={collapsed} onClick={onNavClick} />
            <NavItem to="/knjigovodstvo/subagenti" icon={Handshake} label="Subagenti" collapsed={collapsed} onClick={onNavClick} />
          </div>
        </div>
        </>
        )}

        {/* Prodaja section */}
        <div className="pt-4">
          {!collapsed && (
            <button
              onClick={() => setProdajaOpen((o) => !o)}
              className="w-full flex items-center justify-between px-3 mb-1 group"
            >
              <div className="flex items-center gap-2">
                <TrendingUp className="w-4 h-4 text-foreground" />
                <span className="text-sm font-bold text-foreground uppercase tracking-wider">
                  Prodaja
                </span>
              </div>
              <ChevronDown
                className={cn(
                  "w-3.5 h-3.5 text-muted-foreground transition-transform duration-200",
                  !prodajaOpen && "-rotate-90"
                )}
              />
            </button>
          )}
          {collapsed && <Separator className="my-2" />}
          <div
            className={cn(
              "space-y-1 overflow-hidden transition-all duration-200",
              !collapsed && !prodajaOpen ? "max-h-0 opacity-0" : "max-h-64 opacity-100"
            )}
          >
            <NavItem to="/prodaja/pretraga" icon={Search} label="Pretraga" collapsed={collapsed} onClick={onNavClick} />
            <NavItem to="/prodaja/rezervacije" icon={CalendarPlus} label="Rezervacije" collapsed={collapsed} onClick={onNavClick} />
            <NavItem to="/knjigovodstvo/ugovori" icon={FileText} label="Ugovori" collapsed={collapsed} onClick={onNavClick} />
            <NavItem to="/agencija/grafik" icon={ChartGantt} label="Grafik" collapsed={collapsed} onClick={onNavClick} />
            <NavItem to="/prodaja/notifikacije" icon={Bell} label="Notifikacije" collapsed={collapsed} onClick={onNavClick} />
          </div>
        </div>

        {/* Knjigovodstvo section */}
        {!jeProdaja && (
        <>
        <div className="pt-4">
          {!collapsed && (
            <button
              onClick={() => setKnjigovodstvoOpen((o) => !o)}
              className="w-full flex items-center justify-between px-3 mb-1 group"
            >
              <div className="flex items-center gap-2">
                <FileText className="w-4 h-4 text-foreground" />
                <span className="text-sm font-bold text-foreground uppercase tracking-wider">
                  Knjigovodstvo
                </span>
              </div>
              <ChevronDown
                className={cn(
                  "w-3.5 h-3.5 text-muted-foreground transition-transform duration-200",
                  !knjigovodstvoOpen && "-rotate-90"
                )}
              />
            </button>
          )}
          {collapsed && <Separator className="my-2" />}
          <div
            className={cn(
              "space-y-1 overflow-hidden transition-all duration-200",
              !collapsed && !knjigovodstvoOpen ? "max-h-0 opacity-0" : "max-h-[640px] opacity-100"
            )}
          >
            <NavItem to="/knjigovodstvo/ugovori" icon={FileText} label="Ugovori" collapsed={collapsed} onClick={onNavClick} />
            <NavItem to="/knjigovodstvo/izvodi" icon={Landmark} label="Izvodi" collapsed={collapsed} onClick={onNavClick} />
            <NavItem to="/knjigovodstvo/knjizenje" icon={NotebookPen} label="Knjiženje" collapsed={collapsed} onClick={onNavClick} />
            <NavItem to="/knjigovodstvo/prebacivanja" icon={ArrowRightLeft} label="Prebacivanja" collapsed={collapsed} onClick={onNavClick} />
            <NavItem to="/knjigovodstvo/zabrane" icon={Ban} label="Administrativne zabrane" collapsed={collapsed} onClick={onNavClick} />
            <NavItem to="/knjigovodstvo/predracuni" icon={Receipt} label="Predračuni" collapsed={collapsed} onClick={onNavClick} />
            <NavItem to="/knjigovodstvo/avansne-fakture" icon={ReceiptText} label="Avansne fakture" collapsed={collapsed} onClick={onNavClick} />
            <NavItem to="/knjigovodstvo/fakture" icon={FileText} label="Fakture" collapsed={collapsed} onClick={onNavClick} />
            <NavItem to="/knjigovodstvo/dok-smanjenju" icon={FileMinus} label="Dok. o smanjenju" collapsed={collapsed} onClick={onNavClick} />
            <NavItem to="/knjigovodstvo/dok-smanjenju-avansnih" icon={FileX} label="Dok. o smanjenju avansnih" collapsed={collapsed} onClick={onNavClick} />
            <NavItem to="/knjigovodstvo/dok-povecanju" icon={FilePlus} label="Dok. o povećanju" collapsed={collapsed} onClick={onNavClick} />
            <NavItem to="/knjigovodstvo/subagenti" icon={Handshake} label="Subagenti" collapsed={collapsed} onClick={onNavClick} />
            <NavItem to="/knjigovodstvo/dobavljaci" icon={Store} label="Dobavljači" collapsed={collapsed} onClick={onNavClick} />
            <NavItem to="/knjigovodstvo/banke" icon={Landmark} label="Banke" collapsed={collapsed} onClick={onNavClick} />
          </div>
        </div>
        </>
        )}

        {/* Pregledi section */}
        {!jeProdaja && (
        <>
        <div className="pt-4">
          {!collapsed && (
            <button
              onClick={() => setPreglediOpen((o) => !o)}
              className="w-full flex items-center justify-between px-3 mb-1 group"
            >
              <div className="flex items-center gap-2">
                <Eye className="w-4 h-4 text-foreground" />
                <span className="text-sm font-bold text-foreground uppercase tracking-wider">
                  Pregledi
                </span>
              </div>
              <ChevronDown
                className={cn(
                  "w-3.5 h-3.5 text-muted-foreground transition-transform duration-200",
                  !preglediOpen && "-rotate-90"
                )}
              />
            </button>
          )}
          {collapsed && <Separator className="my-2" />}
          <div
            className={cn(
              "space-y-1 overflow-hidden transition-all duration-200",
              !collapsed && !preglediOpen ? "max-h-0 opacity-0" : "max-h-56 opacity-100"
            )}
          >
            {!collapsed ? (
              <>
                <button
                  onClick={() => setDnevniOpen((o) => !o)}
                  className="w-full flex items-center justify-between px-3 pt-2 pb-1 rounded-md hover:bg-accent/60 transition-colors"
                >
                  <div className="flex items-center gap-2">
                    <CalendarDays className="w-3.5 h-3.5 text-muted-foreground" />
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                      Dnevni izveštaji
                    </span>
                  </div>
                  <ChevronDown
                    className={cn(
                      "w-3 h-3 text-muted-foreground transition-transform duration-200",
                      !dnevniOpen && "-rotate-90"
                    )}
                  />
                </button>
                <div
                  className={cn(
                    "overflow-hidden transition-all duration-200",
                    !dnevniOpen ? "max-h-0 opacity-0" : "max-h-24 opacity-100"
                  )}
                >
                  <div className="pl-6">
                    <NavItem to="/pregledi/dnevni-izvestaji/prodaja-aranzmana" icon={ShoppingBag} label="Prodaja aranžmana" collapsed={collapsed} onClick={onNavClick} />
                  </div>
                </div>
              </>
            ) : (
              <NavItem to="/pregledi/dnevni-izvestaji/prodaja-aranzmana" icon={ShoppingBag} label="Prodaja aranžmana" collapsed={collapsed} onClick={onNavClick} />
            )}
          </div>
        </div>
        </>
        )}

        {/* Podešavanja section */}
        {!jeProdaja && (
        <>
        <div className="pt-4">
          {!collapsed && (
            <button
              onClick={() => setSettingsOpen((o) => !o)}
              className="w-full flex items-center justify-between px-3 mb-1 group"
            >
              <div className="flex items-center gap-2">
                <Settings className="w-4 h-4 text-foreground" />
                <span className="text-sm font-bold text-foreground uppercase tracking-wider">
                  Podešavanja
                </span>
              </div>
              <ChevronDown
                className={cn(
                  "w-3.5 h-3.5 text-muted-foreground transition-transform duration-200",
                  !settingsOpen && "-rotate-90"
                )}
              />
            </button>
          )}
          {collapsed && <Separator className="my-2" />}
          <div
            className={cn(
              "space-y-1 overflow-hidden transition-all duration-200",
              !collapsed && !settingsOpen ? "max-h-0 opacity-0" : "max-h-96 opacity-100"
            )}
          >
            <NavItem to="/podesavanja/agencija" icon={Building} label="Osnovni podaci" collapsed={collapsed} onClick={onNavClick} />
            <NavItem to="/podesavanja/poslovnice" icon={Store} label="Poslovnice" collapsed={collapsed} onClick={onNavClick} />
            <NavItem to="/podesavanja/dokumenti" icon={FileImage} label="Dokumenti" collapsed={collapsed} onClick={onNavClick} />
            <NavItem to="/podesavanja/boje-grafik" icon={Palette} label="Boje grafik" collapsed={collapsed} onClick={onNavClick} />
            <NavItem to="/podesavanja/parametri-obracuna" icon={Calculator} label="Parametri obračuna" collapsed={collapsed} onClick={onNavClick} />
            <NavItem to="/podesavanja/tipovi-korisnika" icon={Users} label="Tipovi korisnika" collapsed={collapsed} onClick={onNavClick} />
            <NavItem to="/podesavanja/korisnici" icon={UserPlus} label="Dodaj korisnika" collapsed={collapsed} onClick={onNavClick} />
          </div>
        </div>
        </>
        )}
      </nav>

      {/* Footer / user */}
      <div className={cn("border-t border-border p-2", collapsed ? "flex flex-col items-center gap-1" : "space-y-1")}>
        {user && (
          <NavLink
            to="/profil"
            onClick={onNavClick}
            title="Moj profil"
            className={({ isActive }) => cn("flex items-center gap-2 px-2 py-2 rounded-lg bg-muted/50 hover:bg-muted transition-colors", collapsed && "justify-center w-full", isActive && "ring-1 ring-primary/40")}
          >
            <div className="w-8 h-8 rounded-full bg-primary/20 flex items-center justify-center flex-shrink-0">
              {user.is_superadmin
                ? <ShieldCheck className="w-4 h-4 text-primary" />
                : <span className="text-xs font-bold text-primary">{user.first_name[0]}{user.last_name[0]}</span>
              }
            </div>
            {!collapsed && (
              <div className="overflow-hidden flex-1">
                <p className="text-xs font-semibold text-foreground truncate">{user.first_name} {user.last_name}</p>
                <p className="text-xs text-muted-foreground truncate">{user.is_superadmin ? "Super Admin" : user.user_type_name}</p>
              </div>
            )}
          </NavLink>
        )}
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              onClick={handleLogout}
              className={cn("w-full text-muted-foreground hover:text-destructive hover:bg-destructive/10", collapsed ? "justify-center px-2" : "justify-start gap-2")}
            >
              <LogOut className="w-4 h-4 flex-shrink-0" />
              {!collapsed && <span>Odjavi se</span>}
            </Button>
          </TooltipTrigger>
          {collapsed && <TooltipContent side="right">Odjavi se</TooltipContent>}
        </Tooltip>
      </div>
    </>
  );
}

export default function Sidebar({ mobileOpen, setMobileOpen }: SidebarProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [settingsOpen, settingsOpenRaw] = useState(false);
  const [agencijaOpen, agencijaOpenRaw] = useState(false);
  const [prodajaOpen, prodajaOpenRaw] = useState(false);
  const [knjigovodstvoOpen, knjigovodstvoOpenRaw] = useState(false);
  const [preglediOpen, preglediOpenRaw] = useState(false);
  const [dnevniOpen, setDnevniOpen] = useState(true);
  const { user, logout } = useAuth();

  // Glavne sekcije su međusobno isključive: otvaranje jedne zatvara ostale.
  // Dnevni izveštaji su podsekcija unutar Pregledi pa su van ove grupe.
  const stanjaSekcija = {
    settings: settingsOpen,
    agencija: agencijaOpen,
    prodaja: prodajaOpen,
    knjigovodstvo: knjigovodstvoOpen,
    pregledi: preglediOpen,
  };
  const postavkeSekcija = {
    settings: settingsOpenRaw,
    agencija: agencijaOpenRaw,
    prodaja: prodajaOpenRaw,
    knjigovodstvo: knjigovodstvoOpenRaw,
    pregledi: preglediOpenRaw,
  };
  function jedinstvena(kljuc: keyof typeof postavkeSekcija): Dispatch<SetStateAction<boolean>> {
    return (akcija) => {
      const sledece = typeof akcija === "function" ? akcija(stanjaSekcija[kljuc]) : akcija;
      if (sledece) {
        (Object.keys(postavkeSekcija) as (keyof typeof postavkeSekcija)[])
          .filter((k) => k !== kljuc)
          .forEach((k) => postavkeSekcija[k](false));
      }
      postavkeSekcija[kljuc](sledece);
    };
  }
  const setSettingsOpen = jedinstvena("settings");
  const setAgencijaOpen = jedinstvena("agencija");
  const setProdajaOpen = jedinstvena("prodaja");
  const setKnjigovodstvoOpen = jedinstvena("knjigovodstvo");
  const setPreglediOpen = jedinstvena("pregledi");
  const prviNaziv = useAgencijaPrviNaziv();
  const navigate = useNavigate();

  // Tip "prodaja" vidi samo sekciju Prodaja
  const jeProdaja = !!user && !user.is_superadmin && user.user_type_slug === "prodaja";

  useEffect(() => {
    if (jeProdaja) setProdajaOpen(true);
  }, [jeProdaja]);

  function handleLogout() {
    logout();
    navigate("/login");
  }

  function closeMobile() {
    setMobileOpen(false);
  }

  return (
    <TooltipProvider delayDuration={0}>
      {/* Desktop sidebar */}
      <aside
        className={cn(
          "hidden md:flex relative flex-col h-screen bg-card transition-all duration-300 ease-in-out flex-shrink-0",
          collapsed ? "w-0" : "w-64 border-r border-border"
        )}
      >
        {!collapsed && (
          <SidebarContent
            collapsed={collapsed}
            settingsOpen={settingsOpen}
            setSettingsOpen={setSettingsOpen}
            agencijaOpen={agencijaOpen}
            setAgencijaOpen={setAgencijaOpen}
            prodajaOpen={prodajaOpen}
            setProdajaOpen={setProdajaOpen}
            knjigovodstvoOpen={knjigovodstvoOpen}
            setKnjigovodstvoOpen={setKnjigovodstvoOpen}
            preglediOpen={preglediOpen}
            setPreglediOpen={setPreglediOpen}
            dnevniOpen={dnevniOpen}
            setDnevniOpen={setDnevniOpen}
            handleLogout={handleLogout}
            user={user}
          />
        )}

        {/* Toggle — ostaje vidljiv i kad je navigacija sklonjena */}
        <button
          onClick={() => setCollapsed(!collapsed)}
          aria-label={collapsed ? "Prikaži navigaciju" : "Sakrij navigaciju"}
          className={cn(
            "absolute top-16 z-10 w-8 h-8 rounded-full bg-background border border-border",
            "flex items-center justify-center shadow-sm hover:bg-accent transition-colors",
            collapsed ? "left-2" : "-right-4"
          )}
        >
          {collapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
        </button>
      </aside>


      {/* Mobile sidebar overlay */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 md:hidden">
          {/* Backdrop */}
          <div className="fixed inset-0 bg-black/50" onClick={closeMobile} />
          {/* Panel */}
          <aside className="fixed inset-y-0 left-0 w-64 bg-card border-r border-border flex flex-col z-50 animate-in slide-in-from-left duration-200">
            {/* Close button */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-border">
              <div className="flex items-center gap-3">
                <BrandMark className="w-9 h-9" />
                <div className="overflow-hidden">
                  <p className="text-sm font-bold text-foreground leading-tight truncate">TuristPlus</p>
                  <p className="text-xs text-muted-foreground truncate">{prviNaziv || "Admin Panel"}</p>
                </div>
              </div>
              <button onClick={closeMobile} className="p-1 rounded-md hover:bg-accent transition-colors">
                <X className="w-5 h-5 text-muted-foreground" />
              </button>
            </div>
            {/* Nav content — always expanded on mobile */}
            <nav className="flex-1 overflow-y-auto py-4 px-2 space-y-1">
              <NavItem to="/" icon={LayoutDashboard} label="Naslovna" collapsed={false} onClick={closeMobile} />

              {!jeProdaja && (
              <>
              <div className="pt-4">
                <button
                  onClick={() => setAgencijaOpen((o) => !o)}
                  className="w-full flex items-center justify-between px-3 mb-1 group"
                >
                  <div className="flex items-center gap-2">
                    <Building2 className="w-4 h-4 text-foreground" />
                    <span className="text-sm font-bold text-foreground uppercase tracking-wider">
                      Agencija
                    </span>
                  </div>
                  <ChevronDown
                    className={cn(
                      "w-3.5 h-3.5 text-muted-foreground transition-transform duration-200",
                      !agencijaOpen && "-rotate-90"
                    )}
                  />
                </button>
                <div
                  className={cn(
                    "space-y-1 overflow-hidden transition-all duration-200",
                    !agencijaOpen ? "max-h-0 opacity-0" : "max-h-[720px] opacity-100"
                  )}
                >
                  <NavItem to="/agencija/tip-ponude" icon={Tag} label="Tipovi ponude" collapsed={false} onClick={closeMobile} />
                  <NavItem to="/agencija/tip-smestaja" icon={Hotel} label="Tipovi smeštaja" collapsed={false} onClick={closeMobile} />
                  <NavItem to="/agencija/drzava" icon={Flag} label="Države" collapsed={false} onClick={closeMobile} />
                  <NavItem to="/agencija/destinacija" icon={MapPin} label="Destinacije" collapsed={false} onClick={closeMobile} />
                  <NavItem to="/agencija/mesto" icon={Map} label="Mesta" collapsed={false} onClick={closeMobile} />
                  <NavItem to="/agencija/smestaj" icon={BedDouble} label="Smeštaj" collapsed={false} onClick={closeMobile} />
                  <NavItem to="/agencija/sobe" icon={DoorOpen} label="Sobe" collapsed={false} onClick={closeMobile} />
                  <NavItem to="/agencija/dodatne-usluge" icon={Receipt} label="Dodatne usluge" collapsed={false} onClick={closeMobile} />
                  <NavItem to="/agencija/koeficijenti" icon={Sigma} label="Koeficijenti prodaje" collapsed={false} onClick={closeMobile} />
                  <NavItem to="/agencija/periodi" icon={CalendarDays} label="Periodi" collapsed={false} onClick={closeMobile} />
                  <NavItem to="/agencija/cenovnici" icon={Tag} label="Cenovnici" collapsed={false} onClick={closeMobile} />
                  <NavItem to="/agencija/prevoz" icon={Bus} label="Prevoz" collapsed={false} onClick={closeMobile} />
                  <NavItem to="/agencija/destinacija-prevoz" icon={Bus} label="Destinacija prevoz" collapsed={false} onClick={closeMobile} />
                  <NavItem to="/agencija/prevoz-limit" icon={Armchair} label="Limiti prevoz" collapsed={false} onClick={closeMobile} />
                  <NavItem to="/agencija/kurs" icon={Banknote} label="Kurs" collapsed={false} onClick={closeMobile} />
                  <NavItem to="/knjigovodstvo/subagenti" icon={Handshake} label="Subagenti" collapsed={false} onClick={closeMobile} />
                </div>
              </div>
              </>
              )}

              <div className="pt-4">
                <button
                  onClick={() => setProdajaOpen((o) => !o)}
                  className="w-full flex items-center justify-between px-3 mb-1 group"
                >
                  <div className="flex items-center gap-2">
                    <TrendingUp className="w-4 h-4 text-foreground" />
                    <span className="text-sm font-bold text-foreground uppercase tracking-wider">
                      Prodaja
                    </span>
                  </div>
                  <ChevronDown
                    className={cn(
                      "w-3.5 h-3.5 text-muted-foreground transition-transform duration-200",
                      !prodajaOpen && "-rotate-90"
                    )}
                  />
                </button>
                <div
                  className={cn(
                    "space-y-1 overflow-hidden transition-all duration-200",
                    !prodajaOpen ? "max-h-0 opacity-0" : "max-h-64 opacity-100"
                  )}
                >
                  <NavItem to="/prodaja/pretraga" icon={Search} label="Pretraga" collapsed={false} onClick={closeMobile} />
                  <NavItem to="/prodaja/rezervacije" icon={CalendarPlus} label="Rezervacije" collapsed={false} onClick={closeMobile} />
                  <NavItem to="/knjigovodstvo/ugovori" icon={FileText} label="Ugovori" collapsed={false} onClick={closeMobile} />
                  <NavItem to="/agencija/grafik" icon={ChartGantt} label="Grafik" collapsed={false} onClick={closeMobile} />
                  <NavItem to="/prodaja/notifikacije" icon={Bell} label="Notifikacije" collapsed={false} onClick={closeMobile} />
                </div>
              </div>

              {!jeProdaja && (
              <>
              <div className="pt-4">
                <button
                  onClick={() => setKnjigovodstvoOpen((o) => !o)}
                  className="w-full flex items-center justify-between px-3 mb-1 group"
                >
                  <div className="flex items-center gap-2">
                    <FileText className="w-4 h-4 text-foreground" />
                    <span className="text-sm font-bold text-foreground uppercase tracking-wider">
                      Knjigovodstvo
                    </span>
                  </div>
                  <ChevronDown
                    className={cn(
                      "w-3.5 h-3.5 text-muted-foreground transition-transform duration-200",
                      !knjigovodstvoOpen && "-rotate-90"
                    )}
                  />
                </button>
                <div
                  className={cn(
                    "space-y-1 overflow-hidden transition-all duration-200",
                    !knjigovodstvoOpen ? "max-h-0 opacity-0" : "max-h-[640px] opacity-100"
                  )}
                >
                  <NavItem to="/knjigovodstvo/ugovori" icon={FileText} label="Ugovori" collapsed={false} onClick={closeMobile} />
                  <NavItem to="/knjigovodstvo/izvodi" icon={Landmark} label="Izvodi" collapsed={false} onClick={closeMobile} />
                  <NavItem to="/knjigovodstvo/knjizenje" icon={NotebookPen} label="Knjiženje" collapsed={false} onClick={closeMobile} />
                  <NavItem to="/knjigovodstvo/prebacivanja" icon={ArrowRightLeft} label="Prebacivanja" collapsed={false} onClick={closeMobile} />
                  <NavItem to="/knjigovodstvo/zabrane" icon={Ban} label="Administrativne zabrane" collapsed={false} onClick={closeMobile} />
                  <NavItem to="/knjigovodstvo/predracuni" icon={Receipt} label="Predračuni" collapsed={false} onClick={closeMobile} />
                  <NavItem to="/knjigovodstvo/avansne-fakture" icon={ReceiptText} label="Avansne fakture" collapsed={false} onClick={closeMobile} />
                  <NavItem to="/knjigovodstvo/fakture" icon={FileText} label="Fakture" collapsed={false} onClick={closeMobile} />
                  <NavItem to="/knjigovodstvo/dok-smanjenju" icon={FileMinus} label="Dok. o smanjenju" collapsed={false} onClick={closeMobile} />
                  <NavItem to="/knjigovodstvo/dok-smanjenju-avansnih" icon={FileX} label="Dok. o smanjenju avansnih" collapsed={false} onClick={closeMobile} />
                  <NavItem to="/knjigovodstvo/dok-povecanju" icon={FilePlus} label="Dok. o povećanju" collapsed={false} onClick={closeMobile} />
                  <NavItem to="/knjigovodstvo/subagenti" icon={Handshake} label="Subagenti" collapsed={false} onClick={closeMobile} />
                  <NavItem to="/knjigovodstvo/dobavljaci" icon={Store} label="Dobavljači" collapsed={false} onClick={closeMobile} />
                  <NavItem to="/knjigovodstvo/banke" icon={Landmark} label="Banke" collapsed={false} onClick={closeMobile} />
                </div>
              </div>
              </>
              )}

              {!jeProdaja && (
              <>
              <div className="pt-4">
                <button
                  onClick={() => setPreglediOpen((o) => !o)}
                  className="w-full flex items-center justify-between px-3 mb-1 group"
                >
                  <div className="flex items-center gap-2">
                    <Eye className="w-4 h-4 text-foreground" />
                    <span className="text-sm font-bold text-foreground uppercase tracking-wider">
                      Pregledi
                    </span>
                  </div>
                  <ChevronDown
                    className={cn(
                      "w-3.5 h-3.5 text-muted-foreground transition-transform duration-200",
                      !preglediOpen && "-rotate-90"
                    )}
                  />
                </button>
                <div
                  className={cn(
                    "space-y-1 overflow-hidden transition-all duration-200",
                    !preglediOpen ? "max-h-0 opacity-0" : "max-h-56 opacity-100"
                  )}
                >
                  <button
                    onClick={() => setDnevniOpen((o) => !o)}
                    className="w-full flex items-center justify-between px-3 pt-2 pb-1 rounded-md hover:bg-accent/60 transition-colors"
                  >
                    <div className="flex items-center gap-2">
                      <CalendarDays className="w-3.5 h-3.5 text-muted-foreground" />
                      <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                        Dnevni izveštaji
                      </span>
                    </div>
                    <ChevronDown
                      className={cn(
                        "w-3 h-3 text-muted-foreground transition-transform duration-200",
                        !dnevniOpen && "-rotate-90"
                      )}
                    />
                  </button>
                  <div
                    className={cn(
                      "overflow-hidden transition-all duration-200",
                      !dnevniOpen ? "max-h-0 opacity-0" : "max-h-24 opacity-100"
                    )}
                  >
                    <div className="pl-6">
                      <NavItem to="/pregledi/dnevni-izvestaji/prodaja-aranzmana" icon={ShoppingBag} label="Prodaja aranžmana" collapsed={false} onClick={closeMobile} />
                    </div>
                  </div>
                </div>
              </div>
              </>
              )}

              {!jeProdaja && (
              <>
              <div className="pt-4">
                <button
                  onClick={() => setSettingsOpen((o) => !o)}
                  className="w-full flex items-center justify-between px-3 mb-1 group"
                >
                  <div className="flex items-center gap-2">
                    <Settings className="w-4 h-4 text-foreground" />
                    <span className="text-sm font-bold text-foreground uppercase tracking-wider">
                      Podešavanja
                    </span>
                  </div>
                  <ChevronDown
                    className={cn(
                      "w-3.5 h-3.5 text-muted-foreground transition-transform duration-200",
                      !settingsOpen && "-rotate-90"
                    )}
                  />
                </button>
                <div
                  className={cn(
                    "space-y-1 overflow-hidden transition-all duration-200",
                    !settingsOpen ? "max-h-0 opacity-0" : "max-h-96 opacity-100"
                  )}
                >
                  <NavItem to="/podesavanja/agencija" icon={Building} label="Osnovni podaci" collapsed={false} onClick={closeMobile} />
                  <NavItem to="/podesavanja/poslovnice" icon={Store} label="Poslovnice" collapsed={false} onClick={closeMobile} />
                  <NavItem to="/podesavanja/dokumenti" icon={FileImage} label="Dokumenti" collapsed={false} onClick={closeMobile} />
                  <NavItem to="/podesavanja/boje-grafik" icon={Palette} label="Boje grafik" collapsed={false} onClick={closeMobile} />
                  <NavItem to="/podesavanja/parametri-obracuna" icon={Calculator} label="Parametri obračuna" collapsed={false} onClick={closeMobile} />
                  <NavItem to="/podesavanja/tipovi-korisnika" icon={Users} label="Tipovi korisnika" collapsed={false} onClick={closeMobile} />
                  <NavItem to="/podesavanja/korisnici" icon={UserPlus} label="Dodaj korisnika" collapsed={false} onClick={closeMobile} />
                </div>
              </div>
              </>
              )}
            </nav>

            {/* Footer */}
            <div className="border-t border-border p-2 space-y-1">
              {user && (
                <NavLink
                  to="/profil"
                  onClick={() => setMobileOpen(false)}
                  title="Moj profil"
                  className={({ isActive }) => cn("flex items-center gap-2 px-2 py-2 rounded-lg bg-muted/50 hover:bg-muted transition-colors", isActive && "ring-1 ring-primary/40")}
                >
                  <div className="w-8 h-8 rounded-full bg-primary/20 flex items-center justify-center flex-shrink-0">
                    {user.is_superadmin
                      ? <ShieldCheck className="w-4 h-4 text-primary" />
                      : <span className="text-xs font-bold text-primary">{user.first_name[0]}{user.last_name[0]}</span>
                    }
                  </div>
                  <div className="overflow-hidden flex-1">
                    <p className="text-xs font-semibold text-foreground truncate">{user.first_name} {user.last_name}</p>
                    <p className="text-xs text-muted-foreground truncate">{user.is_superadmin ? "Super Admin" : user.user_type_name}</p>
                  </div>
                </NavLink>
              )}
              <Button
                variant="ghost"
                size="sm"
                onClick={handleLogout}
                className="w-full text-muted-foreground hover:text-destructive hover:bg-destructive/10 justify-start gap-2"
              >
                <LogOut className="w-4 h-4 flex-shrink-0" />
                <span>Odjavi se</span>
              </Button>
            </div>
          </aside>
        </div>
      )}
    </TooltipProvider>
  );
}
