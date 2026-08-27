import {
  CalendarDays,
  Database,
  FileText,
  FolderOpen,
  GitBranch,
  Globe2,
  HardDrive,
  Mail,
  MessageCircle,
  MessagesSquare,
  UserRound,
  Video,
  type LucideIcon
} from "lucide-react";
import type { SourceEntity } from "../types";

function iconFor(source: Pick<SourceEntity, "platform" | "source_kind" | "title">): LucideIcon {
  const identity = `${source.platform} ${source.title}`.toLowerCase();
  if (/whatsapp|slack/.test(identity)) return MessageCircle;
  if (/gchat|google[ _-]?chat/.test(identity)) return MessagesSquare;
  if (/gmail|email|outlook/.test(identity)) return Mail;
  if (/drive|dropbox|box/.test(identity)) return HardDrive;
  if (/github|gitlab|\brepo\b/.test(identity) || source.source_kind === "repository") return GitBranch;
  if (/zoom|meet|video/.test(identity)) return Video;
  if (/calendar|agenda/.test(identity)) return CalendarDays;
  if (/web|http|browser|gcp/.test(identity) || source.source_kind === "endpoint") return Globe2;
  if (source.source_kind === "collection") return FolderOpen;
  if (source.source_kind === "account") return UserRound;
  if (source.source_kind === "item" || /file|arquivo|manual/.test(identity)) return FileText;
  return Database;
}

export function SourcePlatformIcon({
  source,
  size = 16
}: {
  source: Pick<SourceEntity, "platform" | "source_kind" | "title">;
  size?: number;
}) {
  const Icon = iconFor(source);
  return <Icon size={size} aria-hidden />;
}
