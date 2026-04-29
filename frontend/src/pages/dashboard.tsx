import { useAnalyticsSummary } from "@/hooks/use-analytics-summary";
import { Badge } from "@/components/ui/badge";
import { ErrorState, Loading } from "@/components/state";
import type { OverallSummary, StatusCount } from "@/api";

export function DashboardPage() {
  const { data, isLoading, error, refetch } = useAnalyticsSummary();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Dashboard</h1>
        <p className="text-muted-foreground">
          Combine analytics — counters and per-status breakdown across all
          modules.
        </p>
      </div>

      {isLoading && <Loading />}
      {error && <ErrorState error={error} onRetry={() => refetch()} />}
      {data && <SummaryGrid summary={data} />}
    </div>
  );
}

function SummaryGrid({ summary }: { summary: OverallSummary }) {
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      <StatCard
        title="Accounts"
        value={summary.accounts.total}
        sub={`avg trust ${summary.accounts.avg_trust.toFixed(1)} · ${summary.accounts.proxies_total} proxies`}
        breakdown={summary.accounts.by_status}
      />
      <StatCard
        title="Warming"
        value={summary.warming.jobs_total}
        sub={`${summary.warming.actions_total} actions`}
        breakdown={summary.warming.jobs_by_status}
      />
      <StatCard
        title="Parsers"
        value={summary.parsers.jobs_total}
        sub={`${summary.parsers.results_total} results`}
        breakdown={summary.parsers.jobs_by_status}
      />
      <StatCard
        title="Commenting"
        value={summary.commenting.campaigns_total}
        sub={`${summary.commenting.posts_total} posts · ${summary.commenting.comments_total} comments`}
        breakdown={summary.commenting.campaigns_by_status}
      />
      <StatCard
        title="Reactions"
        value={summary.reactions.campaigns_total}
        sub={`${summary.reactions.targets_total} targets · ${summary.reactions.reactions_total} reactions`}
        breakdown={summary.reactions.campaigns_by_status}
      />
      <ProxiesCard summary={summary} />
    </div>
  );
}

function StatCard({
  title,
  value,
  sub,
  breakdown,
}: {
  title: string;
  value: number;
  sub: string;
  breakdown: StatusCount[];
}) {
  return (
    <div className="rounded-lg border bg-card p-6 text-card-foreground shadow-sm">
      <p className="text-sm font-medium text-muted-foreground">{title}</p>
      <p className="mt-1 text-3xl font-bold">{value}</p>
      <p className="mt-1 text-xs text-muted-foreground">{sub}</p>
      {breakdown.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1">
          {breakdown.map((row) => (
            <Badge key={row.status} variant="secondary">
              {row.status}: {row.count}
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}

function ProxiesCard({ summary }: { summary: OverallSummary }) {
  return (
    <div className="rounded-lg border bg-card p-6 text-card-foreground shadow-sm">
      <p className="text-sm font-medium text-muted-foreground">Proxies</p>
      <p className="mt-1 text-3xl font-bold">{summary.accounts.proxies_total}</p>
      <p className="mt-1 text-xs text-muted-foreground">by health</p>
      <div className="mt-3 flex flex-wrap gap-1">
        {summary.accounts.proxies_by_health.map((row) => (
          <Badge
            key={row.status}
            variant={
              row.status === "ok"
                ? "success"
                : row.status === "slow"
                  ? "warning"
                  : row.status === "dead"
                    ? "destructive"
                    : "secondary"
            }
          >
            {row.status}: {row.count}
          </Badge>
        ))}
      </div>
    </div>
  );
}
