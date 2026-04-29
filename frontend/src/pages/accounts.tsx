import { useState } from "react";
import { Plus, Trash2, LogIn, LogOut, Activity, Power } from "lucide-react";
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
  useAccounts,
  useCreateAccount,
  useDeleteAccount,
  useHealthCheck,
  useLogout,
  useLoginStart,
  useLoginCode,
  useLoginPassword,
  type AccountInput,
} from "@/hooks/use-accounts";
import { useProxies } from "@/hooks/use-proxies";
import type { AccountOut, AccountRole, AccountStatus } from "@/api";

const STATUS_VARIANT: Record<AccountStatus, BadgeProps["variant"]> = {
  new: "secondary",
  warming: "warning",
  active: "success",
  flood: "warning",
  spam_block: "destructive",
  banned: "destructive",
  retired: "outline",
};

const ROLES: AccountRole[] = [
  "multi",
  "commenter",
  "chatter",
  "reactor",
  "parser",
];

function StatusBadge({ status }: { status: AccountStatus }) {
  return <Badge variant={STATUS_VARIANT[status]}>{status}</Badge>;
}

interface CreateAccountModalProps {
  open: boolean;
  onClose: () => void;
}

function CreateAccountModal({ open, onClose }: CreateAccountModalProps) {
  const create = useCreateAccount();
  const proxies = useProxies();
  const [phone, setPhone] = useState("");
  const [role, setRole] = useState<AccountRole>("multi");
  const [proxyId, setProxyId] = useState("");
  const [apiId, setApiId] = useState("");
  const [apiHash, setApiHash] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setPhone("");
    setRole("multi");
    setProxyId("");
    setApiId("");
    setApiHash("");
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
    if (!phone.trim()) {
      setError("Phone is required.");
      return;
    }
    const input: AccountInput = {
      phone: phone.trim(),
      role,
      proxy_id: proxyId ? Number(proxyId) : null,
      api_id: apiId ? Number(apiId) : null,
      api_hash: apiHash.trim() || null,
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
      title="Add account"
      description="Creates an empty account row. Use the Login action afterwards to attach a Telegram session."
    >
      <form onSubmit={onSubmit} className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="acc-phone">Phone</Label>
          <Input
            id="acc-phone"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="+1 555 0100"
            disabled={create.isPending}
            required
          />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-2">
            <Label htmlFor="acc-role">Role</Label>
            <Select
              id="acc-role"
              value={role}
              onChange={(e) => setRole(e.target.value as AccountRole)}
              disabled={create.isPending}
            >
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="acc-proxy">Proxy</Label>
            <Select
              id="acc-proxy"
              value={proxyId}
              onChange={(e) => setProxyId(e.target.value)}
              disabled={create.isPending || proxies.isLoading}
            >
              <option value="">— none —</option>
              {proxies.data?.map((p) => (
                <option key={p.id} value={p.id}>
                  #{p.id} {p.type}://{p.host}:{p.port}
                </option>
              ))}
            </Select>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-2">
            <Label htmlFor="acc-apiid">API ID (optional)</Label>
            <Input
              id="acc-apiid"
              type="number"
              value={apiId}
              onChange={(e) => setApiId(e.target.value)}
              disabled={create.isPending}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="acc-apihash">API hash (optional)</Label>
            <Input
              id="acc-apihash"
              value={apiHash}
              onChange={(e) => setApiHash(e.target.value)}
              disabled={create.isPending}
              autoComplete="off"
            />
          </div>
        </div>

        <div className="space-y-2">
          <Label htmlFor="acc-note">Note</Label>
          <Textarea
            id="acc-note"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            disabled={create.isPending}
          />
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}

        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="outline" onClick={handleClose} disabled={create.isPending}>
            Cancel
          </Button>
          <Button type="submit" disabled={create.isPending}>
            {create.isPending ? "Saving…" : "Save account"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

interface LoginModalProps {
  account: AccountOut | null;
  onClose: () => void;
}

type LoginStep = "start" | "code" | "password" | "done";

function LoginModal({ account, onClose }: LoginModalProps) {
  const [step, setStep] = useState<LoginStep>("start");
  const [token, setToken] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [doneMessage, setDoneMessage] = useState<string | null>(null);

  const start = useLoginStart();
  const sendCode = useLoginCode();
  const sendPassword = useLoginPassword();

  const reset = () => {
    setStep("start");
    setToken(null);
    setCode("");
    setPassword("");
    setError(null);
    setDoneMessage(null);
  };

  const close = () => {
    if (start.isPending || sendCode.isPending || sendPassword.isPending) return;
    reset();
    onClose();
  };

  if (!account) return null;

  const onStart = async () => {
    setError(null);
    try {
      const res = await start.mutateAsync({ account_id: account.id });
      setToken(res.login_token);
      setStep("code");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const onCode = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!token) return;
    try {
      const res = await sendCode.mutateAsync({
        account_id: account.id,
        login_token: token,
        code: code.trim(),
      });
      if (res.status === "password_required") {
        setStep("password");
      } else {
        setDoneMessage("Logged in successfully.");
        setStep("done");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const onPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!token) return;
    try {
      await sendPassword.mutateAsync({
        account_id: account.id,
        login_token: token,
        password,
      });
      setDoneMessage("Logged in successfully (2FA).");
      setStep("done");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <Modal
      open={account != null}
      onClose={close}
      title={`Login: ${account.phone}`}
      description="Telegram will send a login code to this phone number; enter it below."
    >
      {step === "start" && (
        <div className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Press “Send code” to receive a login code in your Telegram app or via SMS.
          </p>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={close}>
              Cancel
            </Button>
            <Button onClick={onStart} disabled={start.isPending}>
              {start.isPending ? "Requesting…" : "Send code"}
            </Button>
          </div>
        </div>
      )}

      {step === "code" && (
        <form onSubmit={onCode} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="login-code">Login code</Label>
            <Input
              id="login-code"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              autoComplete="one-time-code"
              required
              autoFocus
            />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={close} disabled={sendCode.isPending}>
              Cancel
            </Button>
            <Button type="submit" disabled={sendCode.isPending}>
              {sendCode.isPending ? "Verifying…" : "Verify code"}
            </Button>
          </div>
        </form>
      )}

      {step === "password" && (
        <form onSubmit={onPassword} className="space-y-4">
          <p className="text-sm text-muted-foreground">
            This account has 2FA enabled. Enter the cloud password.
          </p>
          <div className="space-y-2">
            <Label htmlFor="login-pass">2FA password</Label>
            <Input
              id="login-pass"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoFocus
              autoComplete="current-password"
            />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={close} disabled={sendPassword.isPending}>
              Cancel
            </Button>
            <Button type="submit" disabled={sendPassword.isPending}>
              {sendPassword.isPending ? "Verifying…" : "Submit"}
            </Button>
          </div>
        </form>
      )}

      {step === "done" && (
        <div className="space-y-4">
          <p className="text-sm text-emerald-500">{doneMessage}</p>
          <div className="flex justify-end">
            <Button onClick={close}>Close</Button>
          </div>
        </div>
      )}
    </Modal>
  );
}

function AccountsTable({ accounts }: { accounts: AccountOut[] }) {
  const [loginAccount, setLoginAccount] = useState<AccountOut | null>(null);
  const del = useDeleteAccount();
  const health = useHealthCheck();
  const logout = useLogout();

  return (
    <>
      <div className="rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-16">ID</TableHead>
              <TableHead>Phone</TableHead>
              <TableHead>Username</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Role</TableHead>
              <TableHead>Trust</TableHead>
              <TableHead>Session</TableHead>
              <TableHead>Proxy</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {accounts.map((a) => (
              <TableRow key={a.id}>
                <TableCell className="font-mono text-xs">{a.id}</TableCell>
                <TableCell className="font-mono">{a.phone}</TableCell>
                <TableCell>
                  {a.username ? (
                    <span className="font-mono">@{a.username}</span>
                  ) : (
                    <span className="text-muted-foreground">—</span>
                  )}
                </TableCell>
                <TableCell>
                  <StatusBadge status={a.status} />
                  {!a.is_enabled && (
                    <Badge variant="outline" className="ml-1">
                      <Power className="mr-1 h-3 w-3" /> off
                    </Badge>
                  )}
                </TableCell>
                <TableCell className="text-sm">{a.role}</TableCell>
                <TableCell>
                  <span className="font-mono text-sm">{a.trust_score}</span>
                </TableCell>
                <TableCell>
                  {a.has_session ? (
                    <Badge variant="success">yes</Badge>
                  ) : (
                    <Badge variant="secondary">none</Badge>
                  )}
                </TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {a.proxy_id != null ? `#${a.proxy_id}` : "—"}
                </TableCell>
                <TableCell className="text-right">
                  <div className="flex justify-end gap-1">
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      onClick={() => setLoginAccount(a)}
                      title="Login flow"
                    >
                      <LogIn className="h-4 w-4" />
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      onClick={() => health.mutate(a.id)}
                      disabled={health.isPending && health.variables === a.id}
                      title="Run health check"
                    >
                      <Activity
                        className={
                          health.isPending && health.variables === a.id
                            ? "h-4 w-4 animate-pulse"
                            : "h-4 w-4"
                        }
                      />
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      onClick={() => {
                        if (confirm(`Log out account ${a.phone}?`)) {
                          logout.mutate(a.id);
                        }
                      }}
                      disabled={!a.has_session || (logout.isPending && logout.variables === a.id)}
                      title="Logout (drops session)"
                    >
                      <LogOut className="h-4 w-4" />
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      onClick={() => {
                        if (confirm(`Delete account ${a.phone}?`)) {
                          del.mutate(a.id);
                        }
                      }}
                      disabled={del.isPending && del.variables === a.id}
                      title="Delete"
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

      <LoginModal account={loginAccount} onClose={() => setLoginAccount(null)} />
    </>
  );
}

export function AccountsPage() {
  const [createOpen, setCreateOpen] = useState(false);
  const accounts = useAccounts();

  return (
    <div className="flex flex-1 flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Accounts</h1>
          <p className="text-sm text-muted-foreground">
            Managed Telegram accounts. Login flow attaches a Telethon session.
          </p>
        </div>
        <Button onClick={() => setCreateOpen(true)}>
          <Plus className="h-4 w-4" />
          Add account
        </Button>
      </div>

      {accounts.isLoading && <Loading />}
      {accounts.isError && (
        <ErrorState error={accounts.error} onRetry={() => accounts.refetch()} />
      )}
      {accounts.isSuccess && accounts.data.length === 0 && (
        <EmptyState
          title="No accounts yet"
          description="Add an account to start the warming / parsing / commenting workflows."
          action={
            <Button onClick={() => setCreateOpen(true)}>
              <Plus className="h-4 w-4" />
              Add account
            </Button>
          }
        />
      )}
      {accounts.isSuccess && accounts.data.length > 0 && (
        <AccountsTable accounts={accounts.data} />
      )}

      <CreateAccountModal open={createOpen} onClose={() => setCreateOpen(false)} />
    </div>
  );
}
