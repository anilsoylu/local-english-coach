import {
  BadgeDollarSign,
  Briefcase,
  Clock,
  Coffee,
  Handshake,
  type LucideIcon,
  MessageCircleHeart,
  MessageSquare,
  Plane,
  Presentation,
  Users,
} from "lucide-react";

// Scenario ids come from scenarios.yaml; unknown ids fall back to a plain chat icon.
const ICONS: Record<string, LucideIcon> = {
  smalltalk: Coffee,
  "upwork-discovery": Handshake,
  "upwork-price": BadgeDollarSign,
  "upwork-delay": Clock,
  standup: Users,
  interview: Briefcase,
  "project-explain": Presentation,
  travel: Plane,
  "friend-chat": MessageCircleHeart,
};

export function ScenarioIcon({
  id,
  className,
}: {
  id: string;
  className?: string;
}) {
  const Icon = ICONS[id] ?? MessageSquare;
  return <Icon aria-hidden className={className} />;
}
