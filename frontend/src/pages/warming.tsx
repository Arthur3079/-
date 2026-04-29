import { useState } from "react";
import { Loader2, Pause, Plus, Play, Trash2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Modal } from "@/components/ui/modal";
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
  useCancelWarming,
  useCreateWarmingJob,
  useDeleteWarming,
  usePauseWarming,
  useResumeWarming,
  useWarmingJobs,
} from "@/hooks/use-warming";
import type { WarmingJobOut, WarmingJobStatus } from "@/api";

const STATUS_VARIANT: Record<
  WarmingJobStatus,
  "secondary" | "warning" | "success" | "destructive" | "outline"
> = {
  pending: "secondary",
  running: "success",
  paused: "warning",
  completed: "outline",
  cancelled: "destructive",
};

export function WarmingPage() {
  const jobs = useWarmingJobs();
  const [open, setOpen] = useState(false);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Warming</h1>
          <p className="text-muted-foreground">
            Schedule warm-up jobs that subscribe, read history, react to posts,
            and send idle messages on behalf of an account.
          </p>
        </div>
        <Button onClick={() => setOpen(true)}>New job</Button>
      </div>

      {jobs.isLoading && <Loading />}
      {jobs.isError && (
        <ErrorState error={jobs.error} onRetry={() => jobs.refetch()} />
      )}
      {jobs.isSuccess && jobs.data.length === 0 && (
        <EmptyState
          title="No warming jobs yet"
          description="Click 'New job' to plan a warm-up cycle for an account."
          action={
            <Button onClick={() => setOpen(true)}>
              <Plus className="h-4 w-4" />
              New job
            </Button>
          }
        />
      )}
      {jobs.isSuccess && jobs.data.length > 0 && (
        <WarmingTable jobs={jobs.data} />
      )}

      <CreateWarmingModal open={open} onClose={() => setOpen(false)} />
    </div>
  );
}

function WarmingTable({ jobs }: { jobs: WarmingJobOut[] }) {
  const pause = usePauseWarming();
  const resume = useResumeWarming();
  const cancel = useCancelWarming();
  const del = useDeleteWarming();

  return (
    <div className="rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-12">#</TableHead>
            <TableHead>Account</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Target trust</TableHead>
            <TableHead>Progress</TableHead>
            <TableHead>Note</TableHead>
            <TableHead className="text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {jobs.map((job) => (
            <TableRow key={job.id}>
              <TableCell className="text-muted-foreground">{job.id}</TableCell>
              <TableCell className="font-mono text-xs">
                #{job.account_id}
              </TableCell>
              <TableCell>
                <Badge variant={STATUS_VARIANT[job.status]}>{job.status}</Badge>
              </TableCell>
              <TableCell className="font-mono text-xs">
                {job.target_trust_score}
              </TableCell>
              <TableCell className="font-mono text-xs">
                {job.actions_done}/{job.total_actions}
                <span className="ml-2 text-muted-foreground">
                  (failed {job.actions_failed} · pending {job.actions_pending})
                </span>
              </TableCell>
              <TableCell className="max-w-xs truncate text-muted-foreground">
                {job.note || ""}
              </TableCell>
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
                  {(job.status === "paused" || job.status === "pending") && (
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
                  {job.status !== "completed" &&
                    job.status !== "cancelled" && (
                      <Button
                        size="icon"
                        variant="ghost"
                        onClick={() => cancel.mutate(job.id)}
                        disabled={cancel.isPending}
                        title="Cancel"
                      >
                        <X className="h-4 w-4" />
                      </Button>
                    )}
                  <Button
                    size="icon"
                    variant="ghost"
                    onClick={() => {
                      if (
                        window.confirm(`Delete warming job #${job.id}?`)
                      ) {
                        del.mutate(job.id);
                      }
                    }}
                    disabled={del.isPending}
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
  );
}

function CreateWarmingModal({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const create = useCreateWarmingJob();
  const [accountId, setAccountId] = useState("");
  const [seed, setSeed] = useState("");
  const [note, setNote] = useState("");

  function reset() {
    setAccountId("");
    setSeed("");
    setNote("");
    create.reset();
  }
  function close() {
    reset();
    onClose();
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const id = Number(accountId);
    if (!Number.isFinite(id) || id <= 0) return;
    create.mutate(
      {
        account_id: id,
        note: note || null,
        seed: seed ? Number(seed) : null,
      },
      { onSuccess: close },
    );
  }

  return (
    <Modal
      open={open}
      onClose={close}
      title="New warming job"
      description="Pick an existing account; the planner schedules subscribe / read / react / idle actions."
    >
      <form className="space-y-4" onSubmit={submit}>
        <div className="space-y-2">
          <Label htmlFor="warming-account">Account ID</Label>
          <Input
            id="warming-account"
            type="number"
            value={accountId}
            onChange={(e) => setAccountId(e.target.value)}
            required
            min={1}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="warming-seed">Seed (optional)</Label>
          <Input
            id="warming-seed"
            type="number"
            value={seed}
            onChange={(e) => setSeed(e.target.value)}
            placeholder="Reproducible plan if set"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="warming-note">Note (optional)</Label>
          <Input
            id="warming-note"
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

