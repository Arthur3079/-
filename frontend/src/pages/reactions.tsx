import { useState } from "react";
import { Loader2, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Modal } from "@/components/ui/modal";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { EmptyState, ErrorState, Loading } from "@/components/state";
import { ApiError } from "@/api";
import {
  useCreateReactionCampaign,
  useDeleteReactionCampaign,
  useReactionCampaigns,
} from "@/hooks/use-reactions";
import type { ReactionCampaignOut, ReactionCampaignStatus } from "@/api";

const STATUS_VARIANT: Record<
  ReactionCampaignStatus,
  "secondary" | "warning" | "success" | "destructive" | "outline"
> = {
  draft: "secondary",
  running: "success",
  paused: "warning",
  archived: "outline",
};

function parseList(s: string): string[] {
  return s
    .split(/[,\n]/)
    .map((x) => x.trim())
    .filter(Boolean);
}

function parseIdList(s: string): number[] {
  return parseList(s)
    .map((x) => Number(x))
    .filter((n) => Number.isFinite(n) && n > 0);
}

export function ReactionsPage() {
  const campaigns = useReactionCampaigns();
  const [open, setOpen] = useState(false);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Reactions</h1>
          <p className="text-muted-foreground">
            Mass reactions: pick channels, an emoji set, and a pool of accounts.
          </p>
        </div>
        <Button onClick={() => setOpen(true)}>New campaign</Button>
      </div>

      {campaigns.isLoading && <Loading />}
      {campaigns.isError && (
        <ErrorState
          error={campaigns.error}
          onRetry={() => campaigns.refetch()}
        />
      )}
      {campaigns.isSuccess && campaigns.data.length === 0 && (
        <EmptyState
          title="No campaigns yet"
          description="Click 'New campaign' to set one up."
          action={
            <Button onClick={() => setOpen(true)}>
              <Plus className="h-4 w-4" />
              New campaign
            </Button>
          }
        />
      )}
      {campaigns.isSuccess && campaigns.data.length > 0 && (
        <ReactionsTable campaigns={campaigns.data} />
      )}

      <CreateReactionModal open={open} onClose={() => setOpen(false)} />
    </div>
  );
}

function ReactionsTable({
  campaigns,
}: {
  campaigns: ReactionCampaignOut[];
}) {
  const del = useDeleteReactionCampaign();
  return (
    <div className="rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-12">#</TableHead>
            <TableHead>Name</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Channels</TableHead>
            <TableHead>Accounts</TableHead>
            <TableHead>Emojis</TableHead>
            <TableHead>Limits</TableHead>
            <TableHead className="text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {campaigns.map((c) => (
            <TableRow key={c.id}>
              <TableCell className="text-muted-foreground">{c.id}</TableCell>
              <TableCell className="font-medium">
                {c.name}
                {c.note && (
                  <p className="max-w-xs truncate text-xs text-muted-foreground">
                    {c.note}
                  </p>
                )}
              </TableCell>
              <TableCell>
                <Badge variant={STATUS_VARIANT[c.status]}>{c.status}</Badge>
              </TableCell>
              <TableCell className="font-mono text-xs">
                {c.target_channels.length}
              </TableCell>
              <TableCell className="font-mono text-xs">
                {c.account_ids.length}
              </TableCell>
              <TableCell className="text-base">
                {c.emojis.slice(0, 6).join(" ")}
                {c.emojis.length > 6 && (
                  <span className="ml-1 text-xs text-muted-foreground">
                    +{c.emojis.length - 6}
                  </span>
                )}
              </TableCell>
              <TableCell className="font-mono text-xs text-muted-foreground">
                {c.accounts_per_post}/post · ≤ {c.max_reactions_per_day}/day
              </TableCell>
              <TableCell className="text-right">
                <Button
                  size="icon"
                  variant="ghost"
                  onClick={() => {
                    if (window.confirm(`Delete campaign "${c.name}"?`)) {
                      del.mutate(c.id);
                    }
                  }}
                  disabled={del.isPending}
                  title="Delete"
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function CreateReactionModal({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const create = useCreateReactionCampaign();
  const [name, setName] = useState("");
  const [channels, setChannels] = useState("");
  const [accounts, setAccounts] = useState("");
  const [emojis, setEmojis] = useState("");
  const [perPost, setPerPost] = useState("3");
  const [maxPerDay, setMaxPerDay] = useState("200");
  const [note, setNote] = useState("");

  function reset() {
    setName("");
    setChannels("");
    setAccounts("");
    setEmojis("");
    setPerPost("3");
    setMaxPerDay("200");
    setNote("");
    create.reset();
  }
  function close() {
    reset();
    onClose();
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    create.mutate(
      {
        name: name.trim(),
        target_channels: parseList(channels),
        account_ids: parseIdList(accounts),
        emojis: parseList(emojis),
        accounts_per_post: Number(perPost) || 3,
        max_reactions_per_day: Number(maxPerDay) || 200,
        note: note || null,
      },
      { onSuccess: close },
    );
  }

  return (
    <Modal
      open={open}
      onClose={close}
      title="New reaction campaign"
      description="Channels, emoji set and an account pool. Lists accept comma- or newline-separated values."
    >
      <form className="space-y-4" onSubmit={submit}>
        <div className="space-y-2">
          <Label htmlFor="rc-name">Name</Label>
          <Input
            id="rc-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="rc-channels">Target channels</Label>
          <Textarea
            id="rc-channels"
            value={channels}
            onChange={(e) => setChannels(e.target.value)}
            rows={2}
            placeholder="@channel_one, @channel_two"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="rc-accounts">Account IDs</Label>
          <Input
            id="rc-accounts"
            value={accounts}
            onChange={(e) => setAccounts(e.target.value)}
            placeholder="1, 2, 3"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="rc-emojis">Emojis</Label>
          <Input
            id="rc-emojis"
            value={emojis}
            onChange={(e) => setEmojis(e.target.value)}
            placeholder="👍, ❤️, 🔥"
          />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div className="space-y-2">
            <Label htmlFor="rc-per-post">Accounts per post</Label>
            <Input
              id="rc-per-post"
              type="number"
              min={1}
              value={perPost}
              onChange={(e) => setPerPost(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="rc-max">Max reactions/day</Label>
            <Input
              id="rc-max"
              type="number"
              min={0}
              value={maxPerDay}
              onChange={(e) => setMaxPerDay(e.target.value)}
            />
          </div>
        </div>
        <div className="space-y-2">
          <Label htmlFor="rc-note">Note (optional)</Label>
          <Input
            id="rc-note"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </div>
        {create.error && (
          <p className="text-sm text-destructive">
            {create.error instanceof ApiError
              ? create.error.message
              : String(create.error)}
          </p>
        )}
        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="ghost" onClick={close}>
            Cancel
          </Button>
          <Button type="submit" disabled={create.isPending}>
            {create.isPending && (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            )}
            Create
          </Button>
        </div>
      </form>
    </Modal>
  );
}
