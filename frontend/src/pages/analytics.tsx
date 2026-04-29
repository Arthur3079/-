import { useOverallSummary } from "@/hooks/use-overall-summary";
import { Loading, ErrorState } from "@/components/state";
import type { StatusCount } from "@/api";

export function AnalyticsPage() {
  const { data, isLoading, error, refetch } = useOverallSummary();

  if (isLoading) return <Loading />;
  if (error) return <ErrorState error={error} onRetry={() => refetch()} />;
  if (!data) return null;

  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-bold tracking-tight">Analytics</h1>

      <Section title="Accounts">
        <Metrics
          items={[
            ["Total", data.accounts.total],
            ["Proxies total", data.accounts.proxies_total],
            ["Avg trust", data.accounts.avg_trust.toFixed(1)],
            ["Min trust", data.accounts.min_trust],
            ["Max trust", data.accounts.max_trust],
          ]}
        />
        <Bucket title="By status" rows={data.accounts.by_status} />
        <Bucket
          title="Proxies by health"
          rows={data.accounts.proxies_by_health}
        />
        <Bucket
          title="Trust buckets"
          rows={data.accounts.trust_buckets.map((b) => ({
            status: b.bucket,
            count: b.count,
          }))}
        />
      </Section>

      <Section title="Warming">
        <Metrics
          items={[
            ["Jobs total", data.warming.jobs_total],
            ["Actions total", data.warming.actions_total],
          ]}
        />
        <Bucket title="Jobs by status" rows={data.warming.jobs_by_status} />
        {data.warming.actions_by_kind_status.length > 0 && (
          <div className="rounded-md border p-4">
            <h3 className="mb-2 text-sm font-semibold">Actions by kind × status</h3>
            <ul className="space-y-1 text-sm">
              {data.warming.actions_by_kind_status.map((r, i) => (
                <li key={i} className="flex justify-between">
                  <span className="text-muted-foreground">
                    {r.kind} / {r.status}
                  </span>
                  <span>{r.count}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </Section>

      <Section title="Parsers">
        <Metrics
          items={[
            ["Jobs total", data.parsers.jobs_total],
            ["Results total", data.parsers.results_total],
          ]}
        />
        <Bucket title="Jobs by status" rows={data.parsers.jobs_by_status} />
        <Bucket
          title="Jobs by kind"
          rows={data.parsers.jobs_by_kind.map((k) => ({
            status: k.kind,
            count: k.count,
          }))}
        />
        <Bucket
          title="Results by kind"
          rows={data.parsers.results_by_kind.map((k) => ({
            status: k.kind,
            count: k.count,
          }))}
        />
      </Section>

      <Section title="Commenting">
        <Metrics
          items={[
            ["Campaigns total", data.commenting.campaigns_total],
            ["Posts total", data.commenting.posts_total],
            ["Comments total", data.commenting.comments_total],
          ]}
        />
        <Bucket
          title="Campaigns by status"
          rows={data.commenting.campaigns_by_status}
        />
        <Bucket title="Posts by status" rows={data.commenting.posts_by_status} />
        <Bucket
          title="Comments by status"
          rows={data.commenting.comments_by_status}
        />
      </Section>

      <Section title="Reactions">
        <Metrics
          items={[
            ["Campaigns total", data.reactions.campaigns_total],
            ["Targets total", data.reactions.targets_total],
            ["Reactions total", data.reactions.reactions_total],
          ]}
        />
        <Bucket
          title="Campaigns by status"
          rows={data.reactions.campaigns_by_status}
        />
        <Bucket
          title="Targets by status"
          rows={data.reactions.targets_by_status}
        />
        <Bucket
          title="Reactions by status"
          rows={data.reactions.reactions_by_status}
        />
      </Section>
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-3">
      <h2 className="text-xl font-semibold">{title}</h2>
      <div className="grid gap-3 md:grid-cols-2">{children}</div>
    </section>
  );
}

function Metrics({ items }: { items: Array<[string, number | string]> }) {
  return (
    <div className="rounded-md border p-4">
      <ul className="space-y-1 text-sm">
        {items.map(([k, v]) => (
          <li key={k} className="flex justify-between">
            <span className="text-muted-foreground">{k}</span>
            <span className="font-medium">{v}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Bucket({ title, rows }: { title: string; rows: StatusCount[] }) {
  if (rows.length === 0) return null;
  return (
    <div className="rounded-md border p-4">
      <h3 className="mb-2 text-sm font-semibold">{title}</h3>
      <ul className="space-y-1 text-sm">
        {rows.map((r, i) => (
          <li key={i} className="flex justify-between">
            <span className="text-muted-foreground">{r.status}</span>
            <span>{r.count}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
