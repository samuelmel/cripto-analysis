import {
  CheckCircle,
  Clock,
  Eye,
  Fire,
  HandCoins,
  LockKey,
  ShieldWarning,
  Target,
  WarningCircle,
  type Icon,
} from "@phosphor-icons/react";
import type { Tone } from "../data/analytics";
import type { ExitReason, Stage } from "../types/signals";

/* Ícones com significado fixo — o mesmo ícone sempre quer dizer a mesma coisa no painel. */

export const REASON_ICON: Record<ExitReason, Icon> = {
  STOP: ShieldWarning,
  "PROTEGER LUCRO": LockKey,
  ALVO: Target,
  SOBRECOMPRADO: Fire,
  TEMPO: Clock,
};

export const STAGE_ICON: Record<Stage, Icon | null> = {
  COMPRAR: HandCoins,
  PREPARAR: Eye,
  NEUTRO: null,
};

export const VERDICT_ICON: Record<Tone, Icon> = {
  critical: WarningCircle,
  signal: HandCoins,
  warning: Eye,
  good: CheckCircle,
  neutral: CheckCircle,
};
