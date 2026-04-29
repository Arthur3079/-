import { useAnalyticsSummary } from "@/hooks/use-analytics-summary";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ErrorState, Loading } from "@/components/state";
import type {
  AccountTopRow,
  AccountsSummary,
  CommentingCampaignTopRow,
  CommentingSummary,
  KindCount,
  KindStatusCount,
  ParsersSummary,
  ReactionCampaignTopRow,
  ReactionsSummary,
  StatusCount,
  TrustBucket,
  WarmingSummary,
} from "@/api";

export function AnalyticsPage() {
  const { data, isLoading, error, refetch } = useAnalyticsSummary();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Analytics</h1>
        <p className="text-muted-foreground">
          Per-module breakdowns: status counts, top items, and trust-score
          distribution.
        </p>
      </div>

      {isLoading && <Loading />}
      {error && <ErrorState error={error} onRetry={() => refetch()} />}
      {data && (
        <div className="space-y-6">
          <AccountsSection summary={data.accounts} />
          <WarmingSection summary={data.warming} />
          <ParsersSection summary={data.parsers} />
          <CommentingSection summary={data.commenting} />
          <ReactionsSection summary={data.reactions} />
        </div>
      )}
    </div>
  );
}

function Section({
  title,
  total,
  children,
}: {
  title: string;
  total: number;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-lg border bg-card p-6 text-card-foreground shadow-sm">
      <div className="flex items-baseline justify-between">
        <h2 className="text-xl font-semibold">{title}</h2>
        <span className="text-sm text-muted-foreground">total: {total}</span>
      </div>
      <div className="mt-4 space-y-4">{children}</div>
    </section>
  );
}

function StatusBadges({ rows }: { rows: StatusCount[] }) {
  if (rows.length === 0) {
    return <p className="text-sm text-muted-foreground">no data</p>;
  }
  return (
    <div className="flex flex-wrap gap-1">
      {rows.map((r) => (
        <Badge key={r.status} variant="secondary">
          {r.status}: {r.count}
        </Badge>
      ))}
    </div>
  );
}

function KindCounts({ rows }: { rows: KindCount[] }) {
  if (rows.length === 0) {
    return <p className="text-sm text-muted-foreground">no data</p>;
  }
  return (
    <div className="flex flex-wrap gap-1">
      {rows.map((r) => (
        <Badge key={r.kind} variant="outline">
          {r.kind}: {r.count}
        </Badge>
      ))}
    </div>
  );
}

function KindStatus({ rows }: { rows: KindStatusCount[] }) {
  if (rows.length === 0) {
    return <p className="text-sm text-muted-foreground">no data</p>;
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Kind</TableHead>
          <TableHead>Status</TableHead>
          <TableHead className="text-right">Count</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r, i) => (
          <TableRow key={`${r.kind}-${r.status}-${i}`}>
            <TableCell className="font-mono text-xs">{r.kind}</TableCell>
            <TableCell>{r.status}</TableCell>
            <TableCell className="text-right font-mono text-xs">
              {r.count}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function AccountsSection({ summary }: { summary: AccountsSummary }) {
  return (
    <Section title="Accounts" total={summary.total}>
      <Field label="By status">
        <StatusBadges rows={summary.by_status} />
      </Field>
      <Field
        label={`Trust score: avg ${summary.avg_trust.toFixed(1)} · min ${summary.min_trust} · max ${summary.max_trust}`}
      >
        <TrustHistogram buckets={summary.trust_buckets} />
      </Field>
      {summary.top.length > 0 && (
        <Field label="Top by trust">
          <TopAccountsTable rows={summary.top} />
        </Field>
      )}
      <Field label={`Proxies (${summary.proxies_total})`}>
        <StatusBadges rows={summary.proxies_by_health} />
      </Field>
    </Section>
  );
}

function WarmingSection({ summary }: { summary: WarmingSummary }) {
  return (
    <Section title="Warming" total={summary.jobs_total}>
      <Field label="Jobs by status">
        <StatusBadges rows={summary.jobs_by_status} />
      </Field>
      <Field label={`Actions (${summary.actions_total}) by kind & status`}>
        <KindStatus rows={summary.actions_by_kind_status} />
      </Field>
    </Section>
  );
}

function ParsersSection({ summary }: { summary: ParsersSummary }) {
  return (
    <Section title="Parsers" total={summary.jobs_total}>
      <Field label="Jobs by status">
        <StatusBadges rows={summary.jobs_by_status} />
      </Field>
      <Field label="Jobs by kind">
        <KindCounts rows={summary.jobs_by_kind} />
      </Field>
      <Field label={`Results (${summary.results_total}) by kind`}>
        <KindCounts rows={summary.results_by_kind} />
      </Field>
      <Field label="Results by job kind">
        <KindCounts rows={summary.results_by_job_kind} />
      </Field>
    </Section>
  );
}

function CommentingSection({ summary }: { summary: CommentingSummary }) {
  return (
    <Section title="Commenting" total={summary.campaigns_total}>
      <Field label="Campaigns by status">
        <StatusBadges rows={summary.campaigns_by_status} />
      </Field>
      <Field label={`Posts (${summary.posts_total}) by status`}>
        <StatusBadges rows={summary.posts_by_status} />
      </Field>
      <Field label={`Comments (${summary.comments_total}) by status`}>
        <StatusBadges rows={summary.comments_by_status} />
      </Field>
      {summary.top.length > 0 && (
        <Field label="Top campaigns">
          <TopCommentingTable rows={summary.top} />
        </Field>
      )}
    </Section>
  );
}

function ReactionsSection({ summary }: { summary: ReactionsSummary }) {
  return (
    <Section title="Reactions" total={summary.campaigns_total}>
      <Field label="Campaigns by status">
        <StatusBadges rows={summary.campaigns_by_status} />
      </Field>
      <Field label={`Targets (${summary.targets_total}) by status`}>
        <StatusBadges rows={summary.targets_by_status} />
      </Field>
      <Field label={`Reactions (${summary.reactions_total}) by status`}>
        <StatusBadges rows={summary.reactions_by_status} />
      </Field>
      {summary.reactions_by_emoji_status.length > 0 && (
        <Field label="By emoji + status">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Emoji</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Count</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {summary.reactions_by_emoji_status.map((r, i) => (
                <TableRow key={`${r.emoji}-${r.status}-${i}`}>
                  <TableCell className="text-base">{r.emoji}</TableCell>
                  <TableCell>{r.status}</TableCell>
                  <TableCell className="text-right font-mono text-xs">
                    {r.count}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Field>
      )}
      {summary.top.length > 0 && (
        <Field label="Top campaigns">
          <TopReactionsTable rows={summary.top} />
        </Field>
      )}
    </Section>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <p className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      {children}
    </div>
  );
}

function TrustHistogram({ buckets }: { buckets: TrustBucket[] }) {
  if (buckets.length === 0) {
    return <p className="text-sm text-muted-foreground">no data</p>;
  }
  const max = Math.max(...buckets.map((b) => b.count), 1);
  return (
    <div className="space-y-1">
      {buckets.map((b, i) => (
        <div key={i} className="flex items-center gap-2 text-xs">
          <span className="w-16 font-mono text-muted-foreground">
            {b.lower}-{b.upper}
          </span>
          <div className="h-2 flex-1 rounded bg-muted">
            <div
              className="h-full rounded bg-primary"
              style={{ width: `${(b.count / max) * 100}%` }}
            />
          </div>
          <span className="w-12 text-right font-mono">{b.count}</span>
        </div>
      ))}
    </div>
  );
}

function TopAccountsTable({ rows }: { rows: AccountTopRow[] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-12">#</TableHead>
          <TableHead>Phone</TableHead>
          <TableHead>Status</TableHead>
          <TableHead className="text-right">Trust</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r) => (
          <TableRow key={r.id}>
            <TableCell className="text-muted-foreground">{r.id}</TableCell>
            <TableCell className="font-mono text-xs">{r.phone}</TableCell>
            <TableCell>{r.status}</TableCell>
            <TableCell className="text-right font-mono">
              {r.trust_score}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function TopCommentingTable({
  rows,
}: {
  rows: CommentingCampaignTopRow[];
}) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-12">#</TableHead>
          <TableHead>Name</TableHead>
          <TableHead>Status</TableHead>
          <TableHead className="text-right">Posted</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r) => (
          <TableRow key={r.id}>
            <TableCell className="text-muted-foreground">{r.id}</TableCell>
            <TableCell className="font-medium">{r.name}</TableCell>
            <TableCell>{r.status}</TableCell>
            <TableCell className="text-right font-mono">
              {r.posted_count}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function TopReactionsTable({ rows }: { rows: ReactionCampaignTopRow[] }) {
  return <TopCommentingTable rows={rows} />;
}
