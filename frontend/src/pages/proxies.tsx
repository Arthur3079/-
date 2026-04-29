import { useState } from "react";
import { Plus, Trash2, ZapOff, Zap, Activity } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Modal } from "@/components/ui/modal";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { Loading, ErrorState, EmptyState } from "@/components/state";
import {
  useProxies,
  useCreateProxy,
  useDeleteProxy,
  useCheckProxy,
  type ProxyInput,
} from "@/hooks/use-proxies";
import type { ProxyHealth, ProxyOut, ProxyType } from "@/api";

const HEALTH_VARIANT: Record<ProxyHealth, BadgeProps["variant"]> = {
  unknown: "secondary",
  ok: "success",
  slow: "warning",
  dead: "destructive",
};

const PROXY_TYPES: ProxyType[] = ["socks5", "http", "mtproto"];

function ProxyTypeBadge({ type }: { type: ProxyType }) {
  return (
    <Badge variant="outline" className="uppercase tracking-wider">
      {type}
    </Badge>
  );
}

function ProxyHealthBadge({ proxy }: { proxy: ProxyOut }) {
  return (
    <div className="flex items-center gap-2">
      <Badge variant={HEALTH_VARIANT[proxy.health]}>{proxy.health}</Badge>
      {proxy.latency_ms != null && (
        <span className="text-xs text-muted-foreground">
          {proxy.latency_ms}ms
        </span>
      )}
    </div>
  );
}

interface CreateProxyModalProps {
  open: boolean;
  onClose: () => void;
}

function CreateProxyModal({ open, onClose }: CreateProxyModalProps) {
  const create = useCreateProxy();
  const [type, setType] = useState<ProxyType>("socks5");
  const [host, setHost] = useState("");
  const [port, setPort] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [secret, setSecret] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setType("socks5");
    setHost("");
    setPort("");
    setUsername("");
    setPassword("");
    setSecret("");
    setNote("");
    setError(null);
  };

  const handleClose = () => {
    if (create.isPending) return;
    reset();
    onClose();
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const portNum = Number(port);
    if (!host.trim() || !Number.isFinite(portNum) || portNum < 1 || portNum > 65535) {
      setError("Host and port (1-65535) are required.");
      return;
    }
    const input: ProxyInput = {
      type,
      host: host.trim(),
      port: portNum,
      username: username.trim() || null,
      password: password || null,
      mtproto_secret: type === "mtproto" ? secret.trim() || null : null,
      note: note.trim() || null,
    };
    try {
      await create.mutateAsync(input);
      reset();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="Add proxy"
      description="Stored credentials are write-only — once saved, they're never returned by the API."
    >
      <form onSubmit={onSubmit} className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="proxy-type">Type</Label>
          <Select
            id="proxy-type"
            value={type}
            onChange={(e) => setType(e.target.value as ProxyType)}
            disabled={create.isPending}
          >
            {PROXY_TYPES.map((t) => (
              <option key={t} value={t}>
                {t.toUpperCase()}
              </option>
            ))}
          </Select>
        </div>

        <div className="grid grid-cols-3 gap-3">
          <div className="col-span-2 space-y-2">
            <Label htmlFor="proxy-host">Host</Label>
            <Input
              id="proxy-host"
              value={host}
              onChange={(e) => setHost(e.target.value)}
              placeholder="proxy.example.com"
              disabled={create.isPending}
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="proxy-port">Port</Label>
            <Input
              id="proxy-port"
              type="number"
              value={port}
              onChange={(e) => setPort(e.target.value)}
              placeholder="1080"
              min={1}
              max={65535}
              disabled={create.isPending}
              required
            />
          </div>
        </div>

        {type !== "mtproto" && (
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label htmlFor="proxy-username">Username</Label>
              <Input
                id="proxy-username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                disabled={create.isPending}
                autoComplete="off"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="proxy-password">Password</Label>
              <Input
                id="proxy-password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={create.isPending}
                autoComplete="off"
              />
            </div>
          </div>
        )}

        {type === "mtproto" && (
          <div className="space-y-2">
            <Label htmlFor="proxy-secret">MTProto secret</Label>
            <Input
              id="proxy-secret"
              value={secret}
              onChange={(e) => setSecret(e.target.value)}
              disabled={create.isPending}
              placeholder="ee…"
              autoComplete="off"
            />
          </div>
        )}

        <div className="space-y-2">
          <Label htmlFor="proxy-note">Note</Label>
          <Textarea
            id="proxy-note"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            disabled={create.isPending}
            placeholder="Optional human-readable label."
          />
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}

        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="outline" onClick={handleClose} disabled={create.isPending}>
            Cancel
          </Button>
          <Button type="submit" disabled={create.isPending}>
            {create.isPending ? "Saving…" : "Save proxy"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function ProxiesTable({ proxies }: { proxies: ProxyOut[] }) {
  const del = useDeleteProxy();
  const check = useCheckProxy();

  return (
    <div className="rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-16">ID</TableHead>
            <TableHead>Type</TableHead>
            <TableHead>Host:Port</TableHead>
            <TableHead>Auth</TableHead>
            <TableHead>Health</TableHead>
            <TableHead>Note</TableHead>
            <TableHead className="text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {proxies.map((p) => (
            <TableRow key={p.id}>
              <TableCell className="font-mono text-xs">{p.id}</TableCell>
              <TableCell>
                <ProxyTypeBadge type={p.type} />
              </TableCell>
              <TableCell className="font-mono">
                {p.host}:{p.port}
              </TableCell>
              <TableCell className="text-xs text-muted-foreground">
                {p.username && <span>user: {p.username}</span>}
                {p.has_password && <span className="ml-2">🔑</span>}
                {p.has_mtproto_secret && <span className="ml-2">secret</span>}
                {!p.username && !p.has_password && !p.has_mtproto_secret && (
                  <span>—</span>
                )}
              </TableCell>
              <TableCell>
                <ProxyHealthBadge proxy={p} />
              </TableCell>
              <TableCell className="max-w-[200px] truncate text-sm text-muted-foreground">
                {p.note ?? "—"}
              </TableCell>
              <TableCell className="text-right">
                <div className="flex justify-end gap-1">
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    onClick={() => check.mutate(p.id)}
                    disabled={check.isPending && check.variables === p.id}
                    title="Run health check"
                  >
                    {check.isPending && check.variables === p.id ? (
                      <Activity className="h-4 w-4 animate-pulse" />
                    ) : p.health === "ok" ? (
                      <Zap className="h-4 w-4" />
                    ) : (
                      <ZapOff className="h-4 w-4" />
                    )}
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    onClick={() => {
                      if (confirm(`Delete proxy ${p.host}:${p.port}?`)) {
                        del.mutate(p.id);
                      }
                    }}
                    disabled={del.isPending && del.variables === p.id}
                    title="Delete proxy"
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

export function ProxiesPage() {
  const [createOpen, setCreateOpen] = useState(false);
  const proxies = useProxies();

  return (
    <div className="flex flex-1 flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Proxies</h1>
          <p className="text-sm text-muted-foreground">
            Network endpoints used by managed accounts to reach Telegram.
          </p>
        </div>
        <Button onClick={() => setCreateOpen(true)}>
          <Plus className="h-4 w-4" />
          Add proxy
        </Button>
      </div>

      {proxies.isLoading && <Loading />}
      {proxies.isError && (
        <ErrorState error={proxies.error} onRetry={() => proxies.refetch()} />
      )}
      {proxies.isSuccess && proxies.data.length === 0 && (
        <EmptyState
          title="No proxies yet"
          description="Add a proxy to start binding accounts to it."
          action={
            <Button onClick={() => setCreateOpen(true)}>
              <Plus className="h-4 w-4" />
              Add proxy
            </Button>
          }
        />
      )}
      {proxies.isSuccess && proxies.data.length > 0 && (
        <ProxiesTable proxies={proxies.data} />
      )}

      <CreateProxyModal open={createOpen} onClose={() => setCreateOpen(false)} />
    </div>
  );
}
