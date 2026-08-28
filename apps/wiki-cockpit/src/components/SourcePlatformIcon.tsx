import { useState } from "react";
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

type SourceIconInput = Pick<SourceEntity, "platform" | "source_kind" | "title" | "visual_identity">;
type SourceBrandIdentity = NonNullable<SourceEntity["visual_identity"]>;

const GOOGLE_DRIVE_IDENTITY: SourceBrandIdentity = {
  key: "google-drive",
  label: "Google Drive",
  asset_path: "/source-icons/google-drive.png",
  background: "transparent"
};

const BUNDLED_BRANDS: Record<string, SourceBrandIdentity> = {
  "google-cloud": { key: "google-cloud", label: "Google Cloud", asset_path: "/source-icons/google-cloud.svg", background: "light" },
  gmail: { key: "gmail", label: "Gmail", asset_path: "/source-icons/gmail.svg", background: "light" },
  "google-chat": { key: "google-chat", label: "Google Chat", asset_path: "/source-icons/google-chat.svg", background: "light" },
  github: { key: "github", label: "GitHub", asset_path: "/source-icons/github.svg", background: "light" },
  whatsapp: { key: "whatsapp", label: "WhatsApp", asset_path: "/source-icons/whatsapp.svg", background: "light" },
  zoom: { key: "zoom", label: "Zoom", asset_path: "/source-icons/zoom.svg", background: "light" },
  "google-calendar": { key: "google-calendar", label: "Google Calendar", asset_path: "/source-icons/google-calendar.svg", background: "light" }
};

/** Source-declared brand -> bundled platform brand -> semantic fallback. */
export function resolveSourceBrand(source: SourceIconInput): SourceBrandIdentity | null {
  if (source.visual_identity) return source.visual_identity;
  const platform = source.platform.trim().toLowerCase().replace(/[ _]+/g, "-");
  const identity = `${source.platform} ${source.title}`.toLowerCase();
  if (platform === "drive" || platform === "google-drive" || /google[ _-]?drive/.test(identity)) {
    return GOOGLE_DRIVE_IDENTITY;
  }
  if (platform === "gmail") return BUNDLED_BRANDS.gmail;
  if (platform === "gchat" || platform === "google-chat") return BUNDLED_BRANDS["google-chat"];
  if (platform === "whatsapp") return BUNDLED_BRANDS.whatsapp;
  if (platform === "calendar" || platform === "google-calendar") return BUNDLED_BRANDS["google-calendar"];
  if (/\bgcp\b|google[ _-]?cloud/.test(identity)) return BUNDLED_BRANDS["google-cloud"];
  if (/\bgithub\b/.test(identity)) return BUNDLED_BRANDS.github;
  if (/\bzoom\b/.test(identity)) return BUNDLED_BRANDS.zoom;
  return null;
}

function iconFor(source: SourceIconInput): LucideIcon {
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
  source: SourceIconInput;
  size?: number;
}) {
  const brand = resolveSourceBrand(source);
  const [failedAsset, setFailedAsset] = useState("");
  if (brand && failedAsset !== brand.asset_path) {
    return (
      <img
        className={`sourcePlatformBrandIcon sourcePlatformBrandIcon-${brand.background}`}
        src={brand.asset_path}
        alt=""
        aria-hidden="true"
        title={brand.label}
        width={size}
        height={size}
        onError={() => setFailedAsset(brand.asset_path)}
      />
    );
  }
  const Icon = iconFor(source);
  return <Icon className="sourcePlatformSemanticIcon" size={size} aria-hidden />;
}
