import { useState } from "react";
import { Plus, Trash2, Eye } from "lucide-react";
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
import { Loading, ErrorState, EmptyState } from "@/components/state";
import {
  useReactionCampaigns,
  useCreateReactionCampaign,
  useDeleteReactionCampaign,
  useReactionTargets,
  useTargetReactions,
  type ReactionCampaignInput,
} from "@/hooks/use-reactions";
import type {
  ReactionCampaignOut,
  ReactionCampaignStatus,
} from "@/api";

const STATUS_VARIANT: Record<ReactionCampaignStatus, BadgeProps["variant"]> = {
  draft: "secondary",
  running: "success",
  paused: "warning",
  archived: "outline",
};

function CreateCampaignModal({
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
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setName("");
    setChannels("");
    setAccounts("");
    setEmojis("");
    setPerPost("3");
    setMaxPerDay("200");
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
    if (!name.trim()) {
      setError("Name is required.");
      return;
    }
    const input: ReactionCampaignInput = {
      name: name.trim(),
      target_channels: channels
        .split(",")
        .map((c) => c.trim())
        .filter(Boolean),
      account_ids: accounts
        .split(",")
        .map((c) => c.trim())
        .filter(Boolean)
        .map(Number)
        .filter((n) => !Number.isNaN(n)),
      emojis: emojis
        .split(",")
        .map((e) => e.trim())
        .filter(Boolean),
      accounts_per_post: Number(perPost) || 3,
      max_reactions_per_day: Number(maxPerDay) || 200,
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
    <Modal open={open} onClose={handleClose} title="New reaction campaign">
      <form onSubmit={onSubmit} className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="r-name">Name</Label>
          <Input
            id="r-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="r-channels">Target channels (comma-separated)</Label>
          <Input
            id="r-channels"
            value={channels}
            onChange={(e) => setChannels(e.target.value)}
            placeholder="@channel1, @channel2"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="r-accounts">Account IDs (comma-separated)</Label>
          <Input
            id="r-accounts"
            value={accounts}
            onChange={(e) => setAccounts(e.target.value)}
            placeholder="1, 2, 3"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="r-emojis">Emojis (comma-separated)</Label>
          <Input
            id="r-emojis"
            value={emojis}
            onChange={(e) => setEmojis(e.target.value)}
            placeholder="👍, ❤️, 🔥"
          />
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label htmlFor="r-per-post">Accounts per post</Label>
            <Input
              id="r-per-post"
              type="number"
              min={1}
              value={perPost}
              onChange={(e) => setPerPost(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="r-max">Max reactions/day</Label>
            <Input
              id="r-max"
              type="number"
              min={0}
              value={maxPerDay}
              onChange={(e) => setMaxPerDay(e.target.value)}
            />
          </div>
        </div>
        {error && <p className="text-sm text-destructive">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button
            type="button"
            variant="ghost"
            onClick={handleClose}
            disabled={create.isPending}
          >
            Cancel
          </Button>
          <Button type="submit" disabled={create.isPending}>
            {create.isPending ? "Creating…" : "Create"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function TargetsModal({
  campaignId,
  onClose,
}: {
  campaignId: number | null;
  onClose: () => void;
}) {
  const { data, isLoading, error } = useReactionTargets(campaignId);
  const [targetId, setTargetId] = useState<number | null>(null);
  return (
    <>
      <Modal
        open={campaignId !== null}
        onClose={() => {
          setTargetId(null);
          onClose();
        }}
        title={`Targets for campaign #${campaignId ?? ""}`}
        className="max-w-4xl"
      >
        {isLoading && <Loading />}
        {error && <ErrorState error={error} />}
        {data && data.length === 0 && <EmptyState title="No targets" />}
        {data && data.length > 0 && (
          <div className="max-h-[60vh] overflow-auto rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>ID</TableHead>
                  <TableHead>Channel</TableHead>
                  <TableHead>TG msg</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Reactions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.map((t) => (
                  <TableRow key={t.id}>
                    <TableCell>{t.id}</TableCell>
                    <TableCell>{t.channel}</TableCell>
                    <TableCell>{t.tg_message_id}</TableCell>
                    <TableCell>
                      <Badge variant="secondary">{t.status}</Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        size="icon"
                        variant="ghost"
                        onClick={() => setTargetId(t.id)}
                        title="Show reactions"
                      >
                        <Eye className="h-4 w-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </Modal>
      <ReactionsModal
        campaignId={campaignId}
        targetId={targetId}
        onClose={() => setTargetId(null)}
      />
    </>
  );
}

function ReactionsModal({
  campaignId,
  targetId,
  onClose,
}: {
  campaignId: number | null;
  targetId: number | null;
  onClose: () => void;
}) {
  const { data, isLoading, error } = useTargetReactions(campaignId, targetId);
  return (
    <Modal
      open={targetId !== null}
      onClose={onClose}
      title={`Reactions for target #${targetId ?? ""}`}
      className="max-w-3xl"
    >
      {isLoading && <Loading />}
      {error && <ErrorState error={error} />}
      {data && data.length === 0 && <EmptyState title="No planned reactions" />}
      {data && data.length > 0 && (
        <div className="max-h-[60vh] overflow-auto rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Account</TableHead>
                <TableHead>Emoji</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Posted at</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.map((r) => (
                <TableRow key={r.id}>
                  <TableCell>{r.account_id}</TableCell>
                  <TableCell>{r.emoji}</TableCell>
                  <TableCell>{r.status}</TableCell>
                  <TableCell>{r.posted_at ?? "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </Modal>
  );
}

function CampaignRow({
  campaign,
  onShowTargets,
}: {
  campaign: ReactionCampaignOut;
  onShowTargets: (id: number) => void;
}) {
  const del = useDeleteReactionCampaign();
  return (
    <TableRow>
      <TableCell>{campaign.id}</TableCell>
      <TableCell>{campaign.name}</TableCell>
      <TableCell>
        <Badge variant={STATUS_VARIANT[campaign.status]}>
          {campaign.status}
        </Badge>
      </TableCell>
      <TableCell>{campaign.target_channels.length}</TableCell>
      <TableCell>{campaign.account_ids.length}</TableCell>
      <TableCell>{campaign.emojis.join(" ")}</TableCell>
      <TableCell>{campaign.accounts_per_post}</TableCell>
      <TableCell className="text-right">
        <div className="flex justify-end gap-1">
          <Button
            size="icon"
            variant="ghost"
            onClick={() => onShowTargets(campaign.id)}
            title="Targets"
          >
            <Eye className="h-4 w-4" />
          </Button>
          <Button
            size="icon"
            variant="ghost"
            onClick={() => {
              if (confirm(`Delete campaign #${campaign.id}?`))
                del.mutate(campaign.id);
            }}
            disabled={del.isPending}
            title="Delete"
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      </TableCell>
    </TableRow>
  );
}

export function ReactionsPage() {
  const { data, isLoading, error, refetch } = useReactionCampaigns();
  const [open, setOpen] = useState(false);
  const [targetsCampaign, setTargetsCampaign] = useState<number | null>(null);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold tracking-tight">Reactions</h1>
        <Button onClick={() => setOpen(true)}>
          <Plus className="mr-2 h-4 w-4" />
          New campaign
        </Button>
      </div>

      {isLoading && <Loading />}
      {error && <ErrorState error={error} onRetry={() => refetch()} />}
      {data && data.length === 0 && (
        <EmptyState
          title="No reaction campaigns"
          description="Create a campaign to mass-react to posts on target channels."
        />
      )}
      {data && data.length > 0 && (
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>ID</TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Channels</TableHead>
                <TableHead>Accounts</TableHead>
                <TableHead>Emojis</TableHead>
                <TableHead>Per post</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.map((c) => (
                <CampaignRow
                  key={c.id}
                  campaign={c}
                  onShowTargets={setTargetsCampaign}
                />
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <CreateCampaignModal open={open} onClose={() => setOpen(false)} />
      <TargetsModal
        campaignId={targetsCampaign}
        onClose={() => setTargetsCampaign(null)}
      />
    </div>
  );
}
