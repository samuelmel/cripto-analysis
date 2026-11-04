import {
  BookOpen,
  ChartNoAxesCombined,
  FlaskConical,
  LayoutDashboard,
  ShieldCheck,
  WalletCards,
} from "lucide-react";
import type { ReactNode } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { cn } from "../../lib/cn";
import { dateShort, lagDays } from "../../lib/format";
import { useOverview } from "../../services/queries";
import { Badge } from "../ui/primitives";

const NAV = [
  { to: "/", label: "Visão geral", short: "Visão", icon: LayoutDashboard, end: true },
  { to: "/carteiras", label: "Carteiras", short: "Carteiras", icon: WalletCards, end: false },
  { to: "/pesquisa", label: "Pesquisa", short: "Pesquisa", icon: FlaskConical, end: false },
  { to: "/mercado", label: "Ativos e mercado", short: "Mercado", icon: ChartNoAxesCombined, end: false },
  { to: "/metodologia", label: "Metodologia", short: "Método", icon: BookOpen, end: false },
] as const;

function currentSection(pathname: string): string {
  const item = [...NAV].reverse().find((entry) => (entry.end ? pathname === entry.to : pathname.startsWith(entry.to)));
  return item?.label ?? "Visão geral";
}

function Brand(): ReactNode {
  return (
    <NavLink to="/" className="flex items-center gap-3" aria-label="Crypto Analyzer — início">
      <span className="grid size-9 place-items-center rounded-[5px] bg-ink text-[13px] font-semibold tracking-tight text-white">
        CA
      </span>
      <span className="min-w-0">
        <span className="block text-[14px] font-semibold tracking-tight text-ink">Crypto Analyzer</span>
        <span className="block text-[10px] uppercase tracking-[0.14em] text-faint">leitura quantitativa</span>
      </span>
    </NavLink>
  );
}

function Sidebar(): ReactNode {
  return (
    <aside className="fixed inset-y-0 left-0 z-30 hidden w-[236px] flex-col border-r border-hairline bg-surface px-3 py-4 lg:flex">
      <div className="px-2">
        <Brand />
      </div>
      <nav className="mt-8 flex flex-1 flex-col gap-1" aria-label="Navegação principal">
        {NAV.map((item) => {
          const Icon = item.icon;
          return (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                cn(
                  "group flex items-center gap-2.5 rounded-md px-2.5 py-2 text-[13px] font-medium text-muted transition-colors",
                  "hover:bg-sunken hover:text-ink",
                  isActive && "bg-signal-wash text-signal-deep",
                )
              }
            >
              <Icon size={16} strokeWidth={1.7} />
              {item.label}
            </NavLink>
          );
        })}
      </nav>
      <div className="border-t border-hairline px-2 pt-3">
        <div className="flex items-start gap-2 text-[11px] leading-relaxed text-faint">
          <ShieldCheck size={14} className="mt-0.5 shrink-0" />
          <span>Somente leitura. Nenhuma ordem real é enviada.</span>
        </div>
      </div>
    </aside>
  );
}

function MobileNav(): ReactNode {
  return (
    <nav
      className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-5 border-t border-hairline bg-surface/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden"
      aria-label="Navegação principal"
    >
      {NAV.map((item) => {
        const Icon = item.icon;
        return (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              cn(
                "flex min-h-14 flex-col items-center justify-center gap-1 px-1 text-[10px] font-medium text-faint",
                isActive && "text-signal",
              )
            }
          >
            {({ isActive }) => (
              <>
                <Icon size={18} strokeWidth={isActive ? 2 : 1.7} />
                <span>{item.short}</span>
              </>
            )}
          </NavLink>
        );
      })}
    </nav>
  );
}

export function AppShell(): ReactNode {
  const location = useLocation();
  const overview = useOverview();
  const dataDay = overview.data?.recommendation.data_day ?? null;
  const system = overview.data?.system;
  const lag = lagDays(dataDay);
  const degraded = overview.isError || (lag !== null && lag > 1);
  const section = currentSection(location.pathname);

  return (
    <div className="min-h-dvh bg-ground">
      <Sidebar />
      <div className="min-h-dvh lg:pl-[236px]">
        <header className="sticky top-0 z-20 border-b border-hairline bg-ground/90 backdrop-blur">
          <div className="flex h-12 items-center justify-between gap-3 px-4 sm:px-6 xl:px-10">
            <div className="flex min-w-0 items-center gap-2">
              <span className="lg:hidden">
                <Brand />
              </span>
              <span className="hidden text-[12px] font-medium text-muted lg:inline">{section}</span>
              <span className="hidden text-faint lg:inline">/</span>
              <span className="hidden text-[12px] text-faint lg:inline">painel público</span>
            </div>
            <div className="flex items-center gap-2">
              {degraded ? (
                <Badge tone="warning" dot>
                  Dados defasados
                </Badge>
              ) : (
                <Badge tone="positive" dot>
                  Atualizado
                </Badge>
              )}
              <span className="hidden text-[11px] text-faint sm:inline">
                {dataDay ? `Dados de ${dateShort(dataDay)}` : "Sem leitura"}
              </span>
              <span className="hidden text-[11px] text-faint md:inline">API v{system?.api_version ?? "1"}</span>
            </div>
          </div>
        </header>
        <main className="px-4 pb-24 pt-6 sm:px-6 sm:pt-8 xl:px-10 xl:pt-10 lg:pb-12">
          <Outlet />
        </main>
        <footer className="hidden border-t border-hairline px-6 py-4 text-[11px] text-faint lg:block xl:px-10">
          Crypto Analyzer · dados fictícios e pesquisa aberta · nenhuma recomendação individual de investimento
        </footer>
      </div>
      <MobileNav />
    </div>
  );
}
