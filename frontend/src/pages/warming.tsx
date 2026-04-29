import { useState } from "react";
import { Plus, Pause, Play, Ban, Trash2 } from "lucide-react";
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
  useWarmingJobs,
  useCreateWarmingJob,
  usePauseWarmingJob,
  useResumeWarmingJob,
  useCancelWarmingJob,
  useDeleteWarmingJob,
  type WarmingJobInput,
} from "@/hooks/use-warming";
import type { WarmingJobOut, WarmingJobStatus } from "@/api";

const STATUS_VARIANT: Record<WarmingJobStatus, BadgeProps["variant"]> = {
  pending: "secondary",
  running: "success",
  paused: "warning",
  completed: "outline",
  cancelled: "destructive",
};

function StatusBadge({ status }: { status: WarmingJobStatus }) {
  return <Badge variant={STATUS_VARIANT[status]}>{status}</Badge>;
}

interface CreateModalProps {
  open: boolean;
  onClose: () => void;
}

function CreateWarmingJobModal({ open, onClose }: CreateModalProps) {
  const create = useCreateWarmingJob();
  const [accountId, setAccountId] = useState("");
  const [note, setNote] = useState("");
  const [targetTrust, setTargetTrust] = useState("");
  const [seed, setSeed] = useState("");
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setAccountId("");
    setNote("");
    setTargetTrust("");
    setSeed("");
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
    const idNum = Number(accountId);
    if (!idNum || Number.isNaN(idNum)) {
      setError("Account ID is required.");
      return;
    }
    const input: WarmingJobInput = {
      account_id: idNum,
      note: note.trim() || null,
      seed: seed ? Number(seed) : null,
      plan: targetTrust
        ? { target_trust_score: Number(targetTrust) }
        : null,
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
      title="New warming job"
      description="Schedules a warm-up plan for the given account."
    >
      <form onSubmit={onSubmit} className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="w-account">Account ID</Label>
          <Input
            id="w-account"
            type="number"
            value={accountId}
            onChange={(e) => setAccountId(e.target.value)}
            required
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="w-trust">Target trust (optional, 0–100)</Label>
          <Input
            id="w-trust"
            type="number"
            min={0}
            max={100}
            value={targetTrust}
            onChange={(e) => setTargetTrust(e.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="w-seed">Seed (optional, for reproducible plan)</Label>
          <Input
            id="w-seed"
            type="number"
            value={seed}
            onChange={(e) => setSeed(e.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="w-note">Note</Label>
          <Textarea
            id="w-note"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={3}
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

function JobRow({ job }: { job: WarmingJobOut }) {
  const pause = usePauseWarmingJob();
  const resume = useResumeWarmingJob();
  const cancel = useCancelWarmingJob();
  const del = useDeleteWarmingJob();

  return (
    <TableRow>
      <TableCell>{job.id}</TableCell>
      <TableCell>{job.account_id}</TableCell>
      <TableCell>
        <StatusBadge status={job.status} />
      </TableCell>
      <TableCell>
        {job.actions_done}/{job.total_actions}
      </TableCell>
      <TableCell>{job.actions_failed}</TableCell>
      <TableCell>{job.target_trust_score}</TableCell>
      <TableCell className="text-right">
        <div className="flex justify-end gap-1">
          {job.status === "running" && (
            <Button
              size="icon"
              variant="ghost"
              onClick={() => pause.mutate(job.id)}
              disabled={pause.isPending}
              title="Pause"
            >
              <Pause className="h-4 w-4" />
            </Button>
          )}
          {job.status === "paused" && (
            <Button
              size="icon"
              variant="ghost"
              onClick={() => resume.mutate(job.id)}
              disabled={resume.isPending}
              title="Resume"
            >
              <Play className="h-4 w-4" />
            </Button>
          )}
          {(job.status === "running" ||
            job.status === "paused" ||
            job.status === "pending") && (
            <Button
              size="icon"
              variant="ghost"
              onClick={() => cancel.mutate(job.id)}
              disabled={cancel.isPending}
              title="Cancel"
            >
              <Ban className="h-4 w-4" />
            </Button>
          )}
          <Button
            size="icon"
            variant="ghost"
            onClick={() => {
              if (confirm(`Delete warming job #${job.id}?`)) del.mutate(job.id);
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

export function WarmingPage() {
  const { data, isLoading, error, refetch } = useWarmingJobs();
  const [open, setOpen] = useState(false);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold tracking-tight">Warming</h1>
        <Button onClick={() => setOpen(true)}>
          <Plus className="mr-2 h-4 w-4" />
          New job
        </Button>
      </div>

      {isLoading && <Loading />}
      {error && <ErrorState error={error} onRetry={() => refetch()} />}
      {data && data.length === 0 && (
        <EmptyState
          title="No warming jobs"
          description="Create a warming job to schedule a warm-up plan for an account."
        />
      )}
      {data && data.length > 0 && (
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>ID</TableHead>
                <TableHead>Account</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Progress</TableHead>
                <TableHead>Failed</TableHead>
                <TableHead>Target trust</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.map((job) => (
                <JobRow key={job.id} job={job} />
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <CreateWarmingJobModal open={open} onClose={() => setOpen(false)} />
    </div>
  );
}
