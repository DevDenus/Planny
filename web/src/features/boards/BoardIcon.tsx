import {
  BriefcaseBusiness,
  GraduationCap,
  Heart,
  House,
  Inbox,
  ListChecks,
  Plane,
  ShoppingCart,
  type LucideIcon,
} from "lucide-react";

export const BOARD_ICONS: { key: string; label: string; Icon: LucideIcon }[] = [
  { key: "list-checks", label: "Список", Icon: ListChecks },
  { key: "inbox", label: "Входящие", Icon: Inbox },
  { key: "shopping-cart", label: "Покупки", Icon: ShoppingCart },
  { key: "house", label: "Дом", Icon: House },
  { key: "briefcase", label: "Работа", Icon: BriefcaseBusiness },
  { key: "graduation-cap", label: "Учёба", Icon: GraduationCap },
  { key: "heart", label: "Личное", Icon: Heart },
  { key: "plane", label: "Поездки", Icon: Plane },
];

export function BoardIcon({ icon, size = 20 }: { icon: string; size?: number }) {
  const Icon = BOARD_ICONS.find((item) => item.key === icon)?.Icon ?? ListChecks;
  return <Icon size={size} aria-hidden="true" />;
}
