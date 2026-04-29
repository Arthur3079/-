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
import { Textarea } from "@/components/ui/textarea";
import { Loading, ErrorState, EmptyState } from "@/components/state";
import {
  useCommentingCampaigns,
  useCreateCommentingCampaign,
  useDeleteCommentingCampaign,
  useCampaignPosts,
  usePostComments,
  type CommentingCampaignInput,
} from "@/hooks/use-commenting";
import type {
  CommentingCampaignOut,
  CommentingCampaignStatus,
} from "@/api";

const STATUS_VARIANT: Record<CommentingCampaignStatus, BadgeProps["variant"]> = {
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
  const create = useCreateCommentingCampaign();
  const [name, setName] = useState("");
  const [prompt, setPrompt] = useState("");
  const [channels, setChannels] = useState("");
  const [accountIds, setAccountIds] = useState("");
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setName("");
    setPrompt("");
    setChannels("");
    setAccountIds("");
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
    if (!name.trim() || !prompt.trim()) {
      setError("Name and prompt are required.");
      return;
    }
    const input: CommentingCampaignInput = {
      name: name.trim(),
      prompt_template: prompt.trim(),
      target_channels: channels
        .split(",")
        .map((c) => c.trim())
        .filter(Boolean),
      account_ids: accountIds
        .split(",")
        .map((c) => c.trim())
        .filter(Boolean)
        .map(Number)
        .filter((n) => !Number.isNaN(n)),
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
    <Modal open={open} onClose={handleClose} title="New commenting campaign">
      <form onSubmit={onSubmit} className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="c-name">Name</Label>
          <Input
            id="c-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="c-prompt">Prompt template</Label>
          <Textarea
            id="c-prompt"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            required
            rows={4}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="c-channels">Target channels (comma-separated)</Label>
          <Input
            id="c-channels"
            value={channels}
            onChange={(e) => setChannels(e.target.value)}
            placeholder="@channel1, @channel2"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="c-accounts">
            Account IDs (comma-separated numbers)
          </Label>
          <Input
            id="c-accounts"
            value={accountIds}
            onChange={(e) => setAccountIds(e.target.value)}
            placeholder="1, 2, 3"
          />
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

function PostsModal({
  campaignId,
  onClose,
}: {
  campaignId: number | null;
  onClose: () => void;
}) {
  const { data, isLoading, error } = useCampaignPosts(campaignId);
  const [postId, setPostId] = useState<number | null>(null);
  return (
    <>
      <Modal
        open={campaignId !== null}
        onClose={() => {
          setPostId(null);
          onClose();
        }}
        title={`Posts for campaign #${campaignId ?? ""}`}
        className="max-w-4xl"
      >
        {isLoading && <Loading />}
        {error && <ErrorState error={error} />}
        {data && data.length === 0 && <EmptyState title="No observed posts" />}
        {data && data.length > 0 && (
          <div className="max-h-[60vh] overflow-auto rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>ID</TableHead>
                  <TableHead>Channel</TableHead>
                  <TableHead>TG msg</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Comments</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.map((p) => (
                  <TableRow key={p.id}>
                    <TableCell>{p.id}</TableCell>
                    <TableCell>{p.channel}</TableCell>
                    <TableCell>{p.tg_message_id}</TableCell>
                    <TableCell>
                      <Badge variant="secondary">{p.status}</Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        size="icon"
                        variant="ghost"
                        onClick={() => setPostId(p.id)}
                        title="Show comments"
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
      <CommentsModal
        campaignId={campaignId}
        postId={postId}
        onClose={() => setPostId(null)}
      />
    </>
  );
}

function CommentsModal({
  campaignId,
  postId,
  onClose,
}: {
  campaignId: number | null;
  postId: number | null;
  onClose: () => void;
}) {
  const { data, isLoading, error } = usePostComments(campaignId, postId);
  return (
    <Modal
      open={postId !== null}
      onClose={onClose}
      title={`Comments for post #${postId ?? ""}`}
      className="max-w-3xl"
    >
      {isLoading && <Loading />}
      {error && <ErrorState error={error} />}
      {data && data.length === 0 && <EmptyState title="No planned comments" />}
      {data && data.length > 0 && (
        <div className="max-h-[60vh] overflow-auto rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Account</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Text</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.map((c) => (
                <TableRow key={c.id}>
                  <TableCell>{c.account_id}</TableCell>
                  <TableCell>{c.status}</TableCell>
                  <TableCell className="max-w-[400px] truncate">
                    {c.text ?? "—"}
                  </TableCell>
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
  onShowPosts,
}: {
  campaign: CommentingCampaignOut;
  onShowPosts: (id: number) => void;
}) {
  const del = useDeleteCommentingCampaign();
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
      <TableCell>{campaign.max_comments_per_day}</TableCell>
      <TableCell className="text-right">
        <div className="flex justify-end gap-1">
          <Button
            size="icon"
            variant="ghost"
            onClick={() => onShowPosts(campaign.id)}
            title="Posts"
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

export function CommentingPage() {
  const { data, isLoading, error, refetch } = useCommentingCampaigns();
  const [open, setOpen] = useState(false);
  const [postsCampaign, setPostsCampaign] = useState<number | null>(null);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold tracking-tight">Commenting</h1>
        <Button onClick={() => setOpen(true)}>
          <Plus className="mr-2 h-4 w-4" />
          New campaign
        </Button>
      </div>

      {isLoading && <Loading />}
      {error && <ErrorState error={error} onRetry={() => refetch()} />}
      {data && data.length === 0 && (
        <EmptyState
          title="No commenting campaigns"
          description="Create a campaign to start auto-commenting on target channels."
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
                <TableHead>Max/day</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.map((c) => (
                <CampaignRow
                  key={c.id}
                  campaign={c}
                  onShowPosts={setPostsCampaign}
                />
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <CreateCampaignModal open={open} onClose={() => setOpen(false)} />
      <PostsModal
        campaignId={postsCampaign}
        onClose={() => setPostsCampaign(null)}
      />
    </div>
  );
}
