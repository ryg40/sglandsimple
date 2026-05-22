/**
 * Stage-19 — 403 Forbidden page.
 *
 * Usable in two modes:
 *   1. Full route element: <Route path="/forbidden" element={<Forbidden />} />
 *   2. Inline fallback inside <RequireCapability>: rendered automatically when
 *      the capability check fails, with `requiredCapability` injected.
 *
 * Reads identity from useAuth() to show the signed-in user and effective roles.
 */

import { useAuth } from "@/components/auth-provider";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { ShieldOff } from "lucide-react";

interface ForbiddenProps {
  /** The capability that was required but not held. Optional. */
  requiredCapability?: string;
}

export function Forbidden({ requiredCapability }: ForbiddenProps = {}) {
  const { me, authenticated, roles, authMode } = useAuth();

  const displayName = me?.user?.display_name ?? me?.user?.username ?? "Unknown";
  const email = me?.user?.email;

  return (
    <div className="flex min-h-full items-center justify-center p-8">
      <Card className="w-full max-w-lg">
        <CardHeader className="space-y-3">
          <div className="flex items-center gap-3 text-destructive">
            <ShieldOff className="h-7 w-7 shrink-0" />
            <CardTitle className="text-2xl text-destructive">
              Access denied
            </CardTitle>
          </div>
          <CardDescription className="text-base">
            You do not have permission to view this page.
          </CardDescription>
        </CardHeader>

        <CardContent className="space-y-4 text-sm">
          {requiredCapability && (
            <div className="rounded-md bg-destructive/10 px-4 py-3">
              <p className="font-medium text-destructive">Required capability</p>
              <p className="font-mono text-xs text-muted-foreground mt-1">
                {requiredCapability}
              </p>
            </div>
          )}

          <div className="space-y-2 rounded-md border border-border bg-muted/40 px-4 py-3">
            <p className="font-medium text-foreground">Signed in as</p>
            {authenticated ? (
              <>
                <p className="text-muted-foreground">
                  {displayName}
                  {email ? (
                    <span className="ml-2 font-mono text-xs">({email})</span>
                  ) : null}
                </p>
                <p className="text-muted-foreground">
                  <span className="font-medium text-foreground">
                    Effective roles:{" "}
                  </span>
                  {roles.length > 0 ? (
                    <span className="font-mono text-xs">
                      {roles.join(", ")}
                    </span>
                  ) : (
                    <span className="italic text-xs">none</span>
                  )}
                </p>
              </>
            ) : (
              <p className="text-muted-foreground italic">Not authenticated</p>
            )}
            <p className="text-muted-foreground">
              <span className="font-medium text-foreground">Auth mode: </span>
              <span className="font-mono text-xs">{authMode || "unknown"}</span>
            </p>
          </div>

          <p className="text-muted-foreground">
            Contact your administrator if you believe this is an error.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
