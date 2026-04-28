import { useAnalyticsSummary } from "@/hooks/use-analytics-summary";

export function DashboardPage() {
  const { data, isLoading, error } = useAnalyticsSummary();

  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-bold tracking-tight">Dashboard</h1>

      {isLoading && (
        <p className="text-muted-foreground">Loading analytics...</p>
      )}

      {error && (
        <div className="rounded-md border border-destructive/50 bg-destructive/10 p-4">
          <p className="text-sm text-destructive">
            Failed to load analytics summary. Make sure the backend is running.
          </p>
        </div>
      )}

      {data && (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          <StatCard label="Total Accounts" value={data.total_accounts} />
          <StatCard label="Active Accounts" value={data.active_accounts} />
          <StatCard label="Total Proxies" value={data.total_proxies} />
          <StatCard label="Warming Active" value={data.warming_active} />
          <StatCard label="Parser Jobs" value={data.parser_jobs} />
          <StatCard label="Commenting Campaigns" value={data.commenting_campaigns} />
          <StatCard label="Reaction Campaigns" value={data.reaction_campaigns} />
        </div>
      )}
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
