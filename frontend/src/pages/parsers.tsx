import { useState } from "react";
import { Loader2, Play, Plus, Trash2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Modal } from "@/components/ui/modal";
import { Select } from "@/components/ui/select";
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
  useCancelParser,
  useCreateParserJob,
  useDeleteParser,
  useParserJobs,
  useRunParserStub,
} from "@/hooks/use-parsers";
import type { ParserJobOut, ParserJobStatus, ParserKind } from "@/api";

const STATUS_VARIANT: Record<
  ParserJobStatus,
  "secondary" | "warning" | "success" | "destructive" | "outline"
> = {
  pending: "secondary",
  running: "warning",
  completed: "success",
  failed: "destructive",
  cancelled: "outline",
};

const PARSER_KINDS: ParserKind[] = [
  "users_in_chat",
  "channels_of_user",
  "chat_history",
  "users_by_message",
];

export function ParsersPage() {
  const jobs = useParserJobs();
  const [open, setOpen] = useState(false);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Parsers</h1>
          <p className="text-muted-foreground">
            Run parsing jobs against chats, channels, and messages. Use{" "}
            <span className="font-mono">run-stub</span> for deterministic dev
            data.
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
          title="No parser jobs yet"
          description="Click 'New job' to start collecting data."
          action={
            <Button onClick={() => setOpen(true)}>
              <Plus className="h-4 w-4" />
              New job
            </Button>
          }
        />
      )}
      {jobs.isSuccess && jobs.data.length > 0 && (
        <ParsersTable jobs={jobs.data} />
      )}

      <CreateParserModal open={open} onClose={() => setOpen(false)} />
    </div>
  );
}

function ParsersTable({ jobs }: { jobs: ParserJobOut[] }) {
  const cancel = useCancelParser();
  const stub = useRunParserStub();
  const del = useDeleteParser();

  return (
    <div className="rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-12">#</TableHead>
            <TableHead>Account</TableHead>
            <TableHead>Kind</TableHead>
            <TableHead>Target</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Results</TableHead>
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
                <Badge variant="outline">{job.kind}</Badge>
              </TableCell>
              <TableCell className="max-w-[14rem] truncate font-mono text-xs">
                {job.target}
              </TableCell>
              <TableCell>
                <Badge variant={STATUS_VARIANT[job.status]}>{job.status}</Badge>
                {job.error && (
                  <p className="mt-1 max-w-[14rem] truncate text-xs text-destructive">
                    {job.error}
                  </p>
                )}
              </TableCell>
              <TableCell className="font-mono text-xs">
                {job.result_count}
              </TableCell>
              <TableCell className="text-right">
                <div className="flex justify-end gap-1">
                  {(job.status === "pending" || job.status === "running") && (
                    <>
                      <Button
                        size="icon"
                        variant="ghost"
                        onClick={() => stub.mutate(job.id)}
                        disabled={stub.isPending}
                        title="Run stub executor"
                      >
                        <Play className="h-4 w-4" />
                      </Button>
                      <Button
                        size="icon"
                        variant="ghost"
                        onClick={() => cancel.mutate(job.id)}
                        disabled={cancel.isPending}
                        title="Cancel"
                      >
                        <X className="h-4 w-4" />
                      </Button>
                    </>
                  )}
                  <Button
                    size="icon"
                    variant="ghost"
                    onClick={() => {
                      if (window.confirm(`Delete parser job #${job.id}?`)) {
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

function CreateParserModal({
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

  function reset() {
    setAccountId("");
    setKind("users_in_chat");
    setTarget("");
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
        kind,
        target: target.trim(),
        note: note || null,
      },
      { onSuccess: close },
    );
  }

  return (
    <Modal
      open={open}
      onClose={close}
      title="New parser job"
      description="Choose what to parse and pick a target (channel @username, chat ID, etc.)."
    >
      <form className="space-y-4" onSubmit={submit}>
        <div className="space-y-2">
          <Label htmlFor="parser-account">Account ID</Label>
          <Input
            id="parser-account"
            type="number"
            value={accountId}
            onChange={(e) => setAccountId(e.target.value)}
            required
            min={1}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="parser-kind">Kind</Label>
          <Select
            id="parser-kind"
            value={kind}
            onChange={(e) => setKind(e.target.value as ParserKind)}
          >
            {PARSER_KINDS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </Select>
        </div>
        <div className="space-y-2">
          <Label htmlFor="parser-target">Target</Label>
          <Input
            id="parser-target"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            required
            placeholder="@channel or numeric chat id"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="parser-note">Note (optional)</Label>
          <Input
            id="parser-note"
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
