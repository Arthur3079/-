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
  useCommentingCampaigns,
  useCreateCommentingCampaign,
  useDeleteCommentingCampaign,
} from "@/hooks/use-commenting";
import type {
  CommentingCampaignOut,
  CommentingCampaignStatus,
} from "@/api";

const STATUS_VARIANT: Record<
  CommentingCampaignStatus,
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

export function CommentingPage() {
  const campaigns = useCommentingCampaigns();
  const [open, setOpen] = useState(false);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Commenting</h1>
          <p className="text-muted-foreground">
            LLM-driven commenting campaigns: pick channels to watch and a pool
            of accounts to post from.
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
        <CommentingTable campaigns={campaigns.data} />
      )}

      <CreateCommentingModal open={open} onClose={() => setOpen(false)} />
    </div>
  );
}

function CommentingTable({
  campaigns,
}: {
  campaigns: CommentingCampaignOut[];
}) {
  const del = useDeleteCommentingCampaign();
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
              <TableCell className="font-mono text-xs text-muted-foreground">
                {c.min_delay_seconds}-{c.max_delay_seconds}s · ≤{" "}
                {c.max_comments_per_day}/day
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

function CreateCommentingModal({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const create = useCreateCommentingCampaign();
  const [name, setName] = useState("");
  const [prompt, setPrompt] = useState("");
  const [channels, setChannels] = useState("");
  const [accounts, setAccounts] = useState("");
  const [minDelay, setMinDelay] = useState("60");
  const [maxDelay, setMaxDelay] = useState("300");
  const [maxPerDay, setMaxPerDay] = useState("20");
  const [note, setNote] = useState("");

  function reset() {
    setName("");
    setPrompt("");
    setChannels("");
    setAccounts("");
    setMinDelay("60");
    setMaxDelay("300");
    setMaxPerDay("20");
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
        prompt_template: prompt,
        target_channels: parseList(channels),
        account_ids: parseIdList(accounts),
        min_delay_seconds: Number(minDelay) || 60,
        max_delay_seconds: Number(maxDelay) || 300,
        max_comments_per_day: Number(maxPerDay) || 20,
        note: note || null,
      },
      { onSuccess: close },
    );
  }

  return (
    <Modal
      open={open}
      onClose={close}
      title="New commenting campaign"
      description="Channels, prompt template and an account pool. Lists accept comma- or newline-separated values."
    >
      <form className="space-y-4" onSubmit={submit}>
        <div className="space-y-2">
          <Label htmlFor="cc-name">Name</Label>
          <Input
            id="cc-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="cc-prompt">Prompt template</Label>
          <Textarea
            id="cc-prompt"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            required
            rows={4}
            placeholder="You are a Telegram commenter. Reply to the post: {{post}}"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="cc-channels">Target channels</Label>
          <Textarea
            id="cc-channels"
            value={channels}
            onChange={(e) => setChannels(e.target.value)}
            rows={2}
            placeholder="@channel_one, @channel_two"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="cc-accounts">Account IDs</Label>
          <Input
            id="cc-accounts"
            value={accounts}
            onChange={(e) => setAccounts(e.target.value)}
            placeholder="1, 2, 3"
          />
        </div>
        <div className="grid grid-cols-3 gap-2">
          <div className="space-y-2">
            <Label htmlFor="cc-min">Min delay (s)</Label>
            <Input
              id="cc-min"
              type="number"
              min={0}
              value={minDelay}
              onChange={(e) => setMinDelay(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="cc-max">Max delay (s)</Label>
            <Input
              id="cc-max"
              type="number"
              min={0}
              value={maxDelay}
              onChange={(e) => setMaxDelay(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="cc-day">Max/day</Label>
            <Input
              id="cc-day"
              type="number"
              min={0}
              value={maxPerDay}
              onChange={(e) => setMaxPerDay(e.target.value)}
            />
          </div>
        </div>
        <div className="space-y-2">
          <Label htmlFor="cc-note">Note (optional)</Label>
          <Input
            id="cc-note"
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
