import {
  CurrencyBtc,
  Eye,
  HandCoins,
  Prohibit,
  ShieldWarning,
  TrendDown,
  WarningCircle,
  type Icon,
} from "@phosphor-icons/react";
import type { ExitReason, Stage } from "../types/signals";

/* Ícones com significado fixo — o mesmo ícone sempre quer dizer a mesma coisa no painel. */

export const REASON_ICON: Record<ExitReason, Icon> = {
  STOP: ShieldWarning,
  TENDENCIA: TrendDown,
  MERCADO: CurrencyBtc,
  DESLISTAGEM: Prohibit,
};

export const STAGE_ICON: Record<Stage, Icon | null> = {
  COMPRAR: HandCoins,
  PREPARAR: Eye,
  NEUTRO: null,
  INDISPONÍVEL: WarningCircle,
};
