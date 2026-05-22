/**
 * Stage-19 auth context: AuthProvider, useAuth(), Capability constants,
 * and the <RequireCapability> route-guard component.
 *
 * Mirrors the Capability string constants from web/auth.py exactly so that
 * TypeScript consumers import symbols, not magic strings.
 */

import React, { createContext, useContext } from "react";
import { useMe } from "@/lib/queries";
import type { MeResponse } from "@/lib/types";
import { Forbidden } from "@/components/forbidden";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

// ---------------------------------------------------------------------------
// Capability constants  (mirror web/auth.py class Capability exactly)
// ---------------------------------------------------------------------------

export const Capability = {
  /** Workflow / connector mutations */
  CAN_RUN_WORKFLOW: "canRunWorkflow",
  CAN_APPLY_JIRA: "canApplyJira",
  CAN_UPDATE_ARCHER: "canUpdateArcher",

  /** Docs / knowledge base */
  CAN_MANAGE_DOCS: "canManageDocs",
  CAN_SYNC_DOCS: "canSyncDocs",

  /** Architecture inventory */
  CAN_EDIT_ARCHITECTURE_INVENTORY: "canEditArchitectureInventory",

  /** Auth/admin diagnostics */
  CAN_ADMIN_AUTH: "canAdminAuth",

  /** Data access / editing (sheet, wrangler write) */
  CAN_EDIT_DATA: "canEditData",

  /** Jira validate (audit users may validate/comment but not apply) */
  CAN_VALIDATE_JIRA: "canValidateJira",

  /** Read-level access to chat / Ask Data */
  CAN_READ_CHAT: "canReadChat",
} as const;

export type CapabilityValue = (typeof Capability)[keyof typeof Capability];

// ---------------------------------------------------------------------------
// Context shape
// ---------------------------------------------------------------------------

export interface AuthContextValue {
  /** Raw /api/me response; undefined while the query is in flight. */
  me: MeResponse | undefined;
  isLoading: boolean;
  authenticated: boolean;
  capabilities: string[];
  /** Returns true if the current user holds the given capability string. */
  hasCapability: (cap: string) => boolean;
  roles: string[];
  groups: string[];
  authMode: string;
}

// ---------------------------------------------------------------------------
// Context + Provider
// ---------------------------------------------------------------------------

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const { data: me, isLoading } = useMe();

  const authenticated = me?.authenticated ?? false;
  const capabilities: string[] = me?.capabilities ?? [];
  const roles: string[] = me?.roles ?? [];
  const groups: string[] = me?.groups ?? [];
  const authMode: string = me?.auth_mode ?? "";

  function hasCapability(cap: string): boolean {
    return capabilities.includes(cap);
  }

  const value: AuthContextValue = {
    me,
    isLoading,
    authenticated,
    capabilities,
    hasCapability,
    roles,
    groups,
    authMode,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// ---------------------------------------------------------------------------
// useAuth hook
// ---------------------------------------------------------------------------

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (ctx === undefined) {
    throw new Error("useAuth must be used within an <AuthProvider>");
  }
  return ctx;
}

// ---------------------------------------------------------------------------
// <RequireCapability> guard component
// ---------------------------------------------------------------------------

export interface RequireCapabilityProps {
  capability: string;
  /** Rendered when the capability check fails. Defaults to <Forbidden>. */
  fallback?: React.ReactNode;
  children: React.ReactNode;
}

/**
 * Renders `children` when the current user holds `capability`.
 * While auth is still loading, renders nothing (avoids flash of 403).
 * When the check fails, renders `fallback` (default: full <Forbidden> page).
 */
export function RequireCapability({
  capability,
  fallback,
  children,
}: RequireCapabilityProps) {
  const { isLoading, hasCapability } = useAuth();

  if (isLoading) {
    // Brief spinner-free blank; avoids flicker before identity resolves.
    return null;
  }

  if (!hasCapability(capability)) {
    return (
      <>
        {fallback !== undefined ? (
          fallback
        ) : (
          <Forbidden requiredCapability={capability} />
        )}
      </>
    );
  }

  return <>{children}</>;
}

// ---------------------------------------------------------------------------
// <DisabledWithTooltip> helper
// ---------------------------------------------------------------------------

export interface DisabledWithTooltipProps {
  /** When true the children render normally; when false they are visually disabled and show the tooltip. */
  enabled: boolean;
  /** Tooltip message shown to the user when the action is not available. */
  message: string;
  children: React.ReactElement;
}

/**
 * Wraps a single interactive element (typically a Button).
 * When `enabled` is false, renders the child with `disabled` prop set and
 * wraps it in a tooltip explaining why.
 *
 * Usage:
 *   <DisabledWithTooltip enabled={hasCapability(Capability.CAN_RUN_WORKFLOW)} message="Requires canRunWorkflow">
 *     <Button onClick={run}>Run</Button>
 *   </DisabledWithTooltip>
 */
export function DisabledWithTooltip({ enabled, message, children }: DisabledWithTooltipProps) {
  if (enabled) return <>{children}</>;

  // Clone the child with disabled=true so the button doesn't fire.
  const cloned = React.cloneElement(children, { disabled: true } as Record<string, unknown>);

  return (
    <Tooltip>
      {/* asChild not used because the child is already a real button element.
          Wrapping in a span makes the tooltip trigger work even on disabled buttons. */}
      <TooltipTrigger asChild>
        <span className="inline-flex">{cloned}</span>
      </TooltipTrigger>
      <TooltipContent>{message}</TooltipContent>
    </Tooltip>
  );
}
