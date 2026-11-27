import { FC } from "react";
import { WarningIcon } from "./icons";
import { core, tint } from "../theme/coreTokens";

interface WarningCardProps {
  title: string;
  message: string;
  /** Compact mode for narrow contexts (QAM panel). */
  compact?: boolean;
}

/** Shared warning card layout: amber-bordered panel with icon, title and message. */
export const WarningCard: FC<WarningCardProps> = ({ title, message, compact = false }) => {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: compact ? "24px 16px" : "40px 32px",
        gap: "14px",
        textAlign: "center",
        background: tint(core.gunmetal, 0.75),
        border: `1px solid ${tint(core.warning, 0.35)}`,
        borderRadius: "6px",
        margin: compact ? "8px 4px" : "24px 2.8vw",
      }}
    >
      <WarningIcon style={{ color: core.warning, fontSize: compact ? "28px" : "42px" }} />
      <div
        style={{
          fontSize: compact ? "15px" : "19px",
          fontWeight: 600,
          color: core.text,
        }}
      >
        {title}
      </div>
      <div
        style={{
          fontSize: compact ? "12px" : "14px",
          color: core.text,
          maxWidth: compact ? "100%" : "680px",
          lineHeight: 1.5,
        }}
      >
        {message}
      </div>
    </div>
  );
};
