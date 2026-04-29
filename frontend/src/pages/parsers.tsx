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
import { Select } from "@/components/ui/select";
import { Loading, ErrorState, EmptyState } from "@/components/state";
import {
  useParserJobs,
  useCreateParserJob,
  useDeleteParserJob,
  useParserResults,
  type ParserJobInput,
} from "@/hooks/use-parsers";
import type { ParserJobOut, ParserJobStatus, ParserKind } from "@/api";

const KINDS: ParserKind[] = [
  "users_in_chat",
  "channels_of_user",
  "chat_history",
  "users_by_message",
];

const STATUS_VARIANT: Record<ParserJobStatus, BadgeProps["variant"]> = {
  pending: "secondary",
  running: "success",
  completed: "outline",
  failed: "destructive",
  cancelled: "destructive",
};

function CreateParserJobModal({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const create = useCreateParserJob();
  const [accountId, setAccountId] = useState("");
  const [kind, setKind] = useState<ParserKind>("users_in_chat");
  const [target, setTarget] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setAccountId("");
    setKind("users_in_chat");
    setTarget("");
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
    const idNum = Number(accountId);
    if (!idNum || Number.isNaN(idNum)) {
      setError("Account ID is required.");
      return;
    }
    if (!target.trim()) {
      setError("Target is required.");
      return;
    }
    const input: ParserJobInput = {
      account_id: idNum,
      kind,
      target: target.trim(),
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
    <Modal open={open} onClose={handleClose} title="New parser job">
      <form onSubmit={onSubmit} className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="p-account">Account ID</Label>
          <Input
            id="p-account"
            type="number"
            value={accountId}
            onChange={(e) => setAccountId(e.target.value)}
            required
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="p-kind">Kind</Label>
          <Select
            id="p-kind"
            value={kind}
            onChange={(e) => setKind(e.target.value as ParserKind)}
          >
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </Select>
        </div>
        <div className="space-y-2">
          <Label htmlFor="p-target">Target</Label>
          <Input
            id="p-target"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            required
            maxLength={255}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="p-note">Note</Label>
          <Input
            id="p-note"
            value={note}
            onChange={(e) => setNote(e.target.value)}
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

function ResultsModal({
  jobId,
  onClose,
}: {
  jobId: number | null;
  onClose: () => void;
}) {
  const { data, isLoading, error } = useParserResults(jobId);
  return (
    <Modal
      open={jobId !== null}
      onClose={onClose}
      title={`Results for job #${jobId ?? ""}`}
      className="max-w-3xl"
    >
      {isLoading && <Loading />}
      {error && <ErrorState error={error} />}
      {data && data.items.length === 0 && (
        <EmptyState title="No results yet" />
      )}
      {data && data.items.length > 0 && (
        <div className="max-h-[60vh] overflow-auto rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Kind</TableHead>
                <TableHead>TG ID</TableHead>
                <TableHead>Username</TableHead>
                <TableHead>Title</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.items.map((r) => (
                <TableRow key={r.id}>
                  <TableCell>{r.kind}</TableCell>
                  <TableCell>{r.tg_id ?? "—"}</TableCell>
                  <TableCell>{r.username ?? "—"}</TableCell>
                  <TableCell>{r.title ?? "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </Modal>
  );
}

function JobRow({
  job,
  onShowResults,
}: {
  job: ParserJobOut;
  onShowResults: (id: number) => void;
}) {
  const del = useDeleteParserJob();
  return (
    <TableRow>
      <TableCell>{job.id}</TableCell>
      <TableCell>{job.account_id}</TableCell>
      <TableCell>{job.kind}</TableCell>
      <TableCell className="max-w-[240px] truncate">{job.target}</TableCell>
      <TableCell>
        <Badge variant={STATUS_VARIANT[job.status]}>{job.status}</Badge>
      </TableCell>
      <TableCell>{job.result_count}</TableCell>
      <TableCell className="text-right">
        <div className="flex justify-end gap-1">
          <Button
            size="icon"
            variant="ghost"
            onClick={() => onShowResults(job.id)}
            title="Results"
          >
            <Eye className="h-4 w-4" />
          </Button>
          <Button
            size="icon"
            variant="ghost"
            onClick={() => {
              if (confirm(`Delete parser job #${job.id}?`)) del.mutate(job.id);
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

export function ParsersPage() {
  const { data, isLoading, error, refetch } = useParserJobs();
  const [open, setOpen] = useState(false);
  const [resultsJob, setResultsJob] = useState<number | null>(null);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold tracking-tight">Parsers</h1>
        <Button onClick={() => setOpen(true)}>
          <Plus className="mr-2 h-4 w-4" />
          New job
        </Button>
      </div>

      {isLoading && <Loading />}
      {error && <ErrorState error={error} onRetry={() => refetch()} />}
      {data && data.length === 0 && (
        <EmptyState
          title="No parser jobs"
          description="Create a parser job to fetch users, channels, or messages."
        />
      )}
      {data && data.length > 0 && (
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>ID</TableHead>
                <TableHead>Account</TableHead>
                <TableHead>Kind</TableHead>
                <TableHead>Target</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Results</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.map((job) => (
                <JobRow
                  key={job.id}
                  job={job}
                  onShowResults={setResultsJob}
                />
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <CreateParserJobModal open={open} onClose={() => setOpen(false)} />
      <ResultsModal jobId={resultsJob} onClose={() => setResultsJob(null)} />
    </div>
  );
}
