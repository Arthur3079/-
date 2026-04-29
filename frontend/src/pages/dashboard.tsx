import { useOverallSummary } from "@/hooks/use-overall-summary";
import { Loading, ErrorState } from "@/components/state";

export function DashboardPage() {
  const { data, isLoading, error, refetch } = useOverallSummary();

  if (isLoading) return <Loading />;
  if (error) return <ErrorState error={error} onRetry={() => refetch()} />;
  if (!data) return null;

  const activeAccounts =
    data.accounts.by_status.find((s) => s.status === "active")?.count ?? 0;
  const runningWarming =
    data.warming.jobs_by_status.find((s) => s.status === "running")?.count ?? 0;
  const runningCommenting =
    data.commenting.campaigns_by_status.find((s) => s.status === "running")
      ?.count ?? 0;
  const runningReactions =
    data.reactions.campaigns_by_status.find((s) => s.status === "running")
      ?.count ?? 0;

  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-bold tracking-tight">Dashboard</h1>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Total Accounts" value={data.accounts.total} />
        <StatCard label="Active Accounts" value={activeAccounts} />
        <StatCard label="Total Proxies" value={data.accounts.proxies_total} />
        <StatCard label="Warming Jobs" value={data.warming.jobs_total} />
        <StatCard label="Warming Running" value={runningWarming} />
        <StatCard label="Parser Jobs" value={data.parsers.jobs_total} />
        <StatCard
          label="Commenting Campaigns"
          value={data.commenting.campaigns_total}
        />
        <StatCard
          label="Commenting Running"
          value={runningCommenting}
        />
        <StatCard
          label="Reaction Campaigns"
          value={data.reactions.campaigns_total}
        />
        <StatCard label="Reactions Running" value={runningReactions} />
        <StatCard
          label="Comments Posted"
          value={
            data.commenting.comments_by_status.find((s) => s.status === "posted")
              ?.count ?? 0
          }
        />
        <StatCard
          label="Reactions Posted"
          value={
            data.reactions.reactions_by_status.find((s) => s.status === "posted")
              ?.count ?? 0
          }
        />
      </div>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border bg-card p-6 text-card-foreground shadow-sm">
      <p className="text-sm font-medium text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-bold">{value}</p>
    </div>
  );
}
