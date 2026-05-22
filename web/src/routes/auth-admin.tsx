/**
 * Auth Diagnostics page — visible only to users with canAdminAuth capability.
 * Route: /auth-admin  (wrapped in <RequireCapability> in App.tsx)
 */

import { AlertCircle, ShieldCheck, KeyRound, Database, Lock, Users, RefreshCw } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuthDiagnostics } from "@/lib/queries";

export default function AuthAdmin() {
  const { data, isLoading, isError, error, refetch, isRefetching } = useAuthDiagnostics();

  return (
    <div className="flex-1 space-y-6 p-8 pt-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-3xl font-bold tracking-tight flex items-center gap-2">
            <ShieldCheck className="h-8 w-8 text-primary" />
            Auth Diagnostics
          </h2>
          <p className="text-muted-foreground">
            Auth subsystem configuration, group/role mappings, cache status, and recent denial log.
            Visible to <code className="text-xs bg-muted rounded px-1 py-0.5">sg_sec_admin</code> only.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => refetch()}
          disabled={isLoading || isRefetching}
        >
          <RefreshCw className={`h-4 w-4 mr-2 ${isRefetching ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      {/* Loading skeleton */}
      {isLoading && (
        <div className="space-y-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-32 w-full rounded-xl" />
          ))}
        </div>
      )}

      {/* Error state */}
      {isError && (
        <div className="rounded-xl border border-destructive/20 bg-destructive/5 p-6 flex flex-col items-center justify-center text-center max-w-xl mx-auto">
          <AlertCircle className="h-10 w-10 text-destructive mb-3" />
          <h4 className="font-semibold text-lg text-destructive">Failed to load auth diagnostics</h4>
          <p className="text-muted-foreground text-sm mt-1">
            The diagnostics endpoint returned an error. Check that you hold the{" "}
            <code className="text-xs bg-muted rounded px-1">canAdminAuth</code> capability.
          </p>
          <pre className="mt-4 p-2 bg-sidebar rounded font-mono text-[11px] text-sidebar-foreground max-w-full overflow-x-auto">
            {error instanceof Error ? error.message : String(error)}
          </pre>
          <Button variant="outline" size="sm" className="mt-4" onClick={() => refetch()}>
            Retry
          </Button>
        </div>
      )}

      {/* Data panels */}
      {data && (
        <div className="space-y-6">
          {/* Current Mode panel */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-lg">
                <Lock className="h-5 w-5 text-primary" />
                Current Auth Mode
              </CardTitle>
              <CardDescription>
                Active authentication mode and global flags.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="flex flex-wrap gap-3 items-center">
                <div className="flex items-center gap-2">
                  <span className="text-sm text-muted-foreground">Mode:</span>
                  <Badge variant="outline" className="font-mono text-sm uppercase">
                    {data.auth_mode}
                  </Badge>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-sm text-muted-foreground">SSO required:</span>
                  <Badge variant={data.sso_required ? "default" : "outline"}>
                    {data.sso_required ? "Yes" : "No"}
                  </Badge>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-sm text-muted-foreground">Dev headers:</span>
                  <Badge variant={data.dev_headers_enabled ? "destructive" : "outline"}>
                    {data.dev_headers_enabled ? "Enabled" : "Disabled"}
                  </Badge>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Group → Role mapping */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-lg">
                <Users className="h-5 w-5 text-primary" />
                Group → Role Mapping
              </CardTitle>
              <CardDescription>
                LDAP/SSO groups and the role each group is mapped to.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {Object.keys(data.groups).length === 0 ? (
                <p className="text-sm text-muted-foreground">No group mappings configured.</p>
              ) : (
                <div className="overflow-x-auto rounded border">
                  <table className="w-full text-left text-xs border-collapse">
                    <thead>
                      <tr className="bg-muted border-b text-muted-foreground font-semibold">
                        <th className="p-3">Group</th>
                        <th className="p-3">Role</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {Object.entries(data.groups).map(([group, role]) => (
                        <tr key={group} className="hover:bg-muted/50 transition-colors">
                          <td className="p-3 font-mono">{group}</td>
                          <td className="p-3">
                            <Badge variant="outline" className="font-mono text-[11px]">
                              {role}
                            </Badge>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Role → Capabilities matrix */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-lg">
                <KeyRound className="h-5 w-5 text-primary" />
                Role → Capabilities
              </CardTitle>
              <CardDescription>
                Capability set granted to each role.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {Object.keys(data.role_capabilities).length === 0 ? (
                <p className="text-sm text-muted-foreground">No role capabilities defined.</p>
              ) : (
                <div className="overflow-x-auto rounded border">
                  <table className="w-full text-left text-xs border-collapse">
                    <thead>
                      <tr className="bg-muted border-b text-muted-foreground font-semibold">
                        <th className="p-3">Role</th>
                        <th className="p-3">Capabilities</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {Object.entries(data.role_capabilities).map(([role, caps]) => (
                        <tr key={role} className="hover:bg-muted/50 transition-colors">
                          <td className="p-3 font-mono align-top">{role}</td>
                          <td className="p-3">
                            <div className="flex flex-wrap gap-1">
                              {caps.map((cap) => (
                                <Badge
                                  key={cap}
                                  variant="outline"
                                  className="font-mono text-[10px] py-0 px-1"
                                >
                                  {cap}
                                </Badge>
                              ))}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Cache status + LDAP adapter — side by side */}
          <div className="grid gap-6 md:grid-cols-2">
            {/* Cache status */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-lg">
                  <Database className="h-5 w-5 text-primary" />
                  Cache Status
                </CardTitle>
                <CardDescription>User-cache file configuration and state.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                <div className="flex justify-between border-b pb-1">
                  <span className="text-muted-foreground">File path</span>
                  <span className="font-mono text-[11px] max-w-[60%] truncate text-right" title={data.cache.file_path}>
                    {data.cache.file_path}
                  </span>
                </div>
                <div className="flex justify-between border-b pb-1">
                  <span className="text-muted-foreground">Loaded</span>
                  <Badge variant={data.cache.loaded ? "default" : "outline"}>
                    {data.cache.loaded ? "Yes" : "No"}
                  </Badge>
                </div>
                <div className="flex justify-between border-b pb-1">
                  <span className="text-muted-foreground">User count</span>
                  <span className="font-mono">{data.cache.user_count}</span>
                </div>
                <div className="flex justify-between border-b pb-1">
                  <span className="text-muted-foreground">TTL</span>
                  <span className="font-mono">{data.cache.ttl_seconds}s</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Last load age</span>
                  <span className="font-mono">
                    {data.cache.last_load_age_seconds !== null
                      ? `${data.cache.last_load_age_seconds}s ago`
                      : "never"}
                  </span>
                </div>
              </CardContent>
            </Card>

            {/* LDAP adapter */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-lg">
                  <ShieldCheck className="h-5 w-5 text-primary" />
                  LDAP Adapter
                </CardTitle>
                <CardDescription>Active LDAP/fixture adapter details.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                <div className="flex justify-between border-b pb-1">
                  <span className="text-muted-foreground">Adapter class</span>
                  <span className="font-mono text-[11px]">{data.ldap.adapter_class}</span>
                </div>
                <div className="flex justify-between border-b pb-1">
                  <span className="text-muted-foreground">Fixture mode</span>
                  <Badge variant={data.ldap.is_fixture ? "destructive" : "outline"}>
                    {data.ldap.is_fixture ? "Fixture" : "Live"}
                  </Badge>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">LDAP URL configured</span>
                  <Badge variant={data.ldap.ldap_url_configured ? "default" : "outline"}>
                    {data.ldap.ldap_url_configured ? "Yes" : "No"}
                  </Badge>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Seeded identity hints — only in basic/dev mode */}
          {data.seeded_users.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-lg">
                  <Users className="h-5 w-5 text-primary" />
                  Seeded Identity Hints
                </CardTitle>
                <CardDescription>
                  Hard-coded fixture users (basic / dev auth mode only).
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="overflow-x-auto rounded border">
                  <table className="w-full text-left text-xs border-collapse">
                    <thead>
                      <tr className="bg-muted border-b text-muted-foreground font-semibold">
                        <th className="p-3">Username</th>
                        <th className="p-3">Display Name</th>
                        <th className="p-3">Groups</th>
                        <th className="p-3">Roles</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {data.seeded_users.map((u) => (
                        <tr key={u.username} className="hover:bg-muted/50 transition-colors">
                          <td className="p-3 font-mono">{u.username}</td>
                          <td className="p-3">{u.display_name}</td>
                          <td className="p-3">
                            <div className="flex flex-wrap gap-1">
                              {u.groups.map((g) => (
                                <Badge key={g} variant="outline" className="font-mono text-[10px] py-0 px-1">
                                  {g}
                                </Badge>
                              ))}
                            </div>
                          </td>
                          <td className="p-3">
                            <div className="flex flex-wrap gap-1">
                              {u.roles.map((r) => (
                                <Badge key={r} variant="outline" className="font-mono text-[10px] py-0 px-1">
                                  {r}
                                </Badge>
                              ))}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Recent denies */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-lg">
                <AlertCircle className="h-5 w-5 text-destructive" />
                Recent Denials
              </CardTitle>
              <CardDescription>
                Last authorization failures recorded by the auth subsystem.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {data.recent_denies.length === 0 ? (
                <p className="text-sm text-muted-foreground">No recent denials — all clear.</p>
              ) : (
                <div className="overflow-x-auto rounded border">
                  <table className="w-full text-left text-xs border-collapse">
                    <thead>
                      <tr className="bg-muted border-b text-muted-foreground font-semibold">
                        <th className="p-3">Username</th>
                        <th className="p-3">Capability</th>
                        <th className="p-3">Reason</th>
                        <th className="p-3">Timestamp</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {data.recent_denies.map((d, idx) => (
                        <tr key={idx} className="hover:bg-muted/50 transition-colors">
                          <td className="p-3 font-mono">{d.username}</td>
                          <td className="p-3">
                            <Badge variant="destructive" className="font-mono text-[10px] py-0 px-1">
                              {d.capability}
                            </Badge>
                          </td>
                          <td className="p-3 text-muted-foreground">{d.reason}</td>
                          <td className="p-3 font-mono text-[11px] whitespace-nowrap">{d.ts}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
