import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

export function Loading({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "flex flex-1 items-center justify-center py-12 text-muted-foreground",
        className,
      )}
    >
      <Loader2 className="mr-2 h-5 w-5 animate-spin" />
      <span>Loading…</span>
    </div>
  );
}

export interface ErrorStateProps {
  error: unknown;
  onRetry?: () => void;
  className?: string;
}

export function ErrorState({ error, onRetry, className }: ErrorStateProps) {
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div
      className={cn(
        "flex flex-1 flex-col items-center justify-center py-12 text-center",
        className,
      )}
    >
      <p className="text-destructive">Failed to load: {message}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 text-sm text-primary underline"
        >
          Retry
        </button>
      )}
    </div>
  );
}

export interface EmptyStateProps {
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}

export function EmptyState({
  title,
  description,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-1 flex-col items-center justify-center rounded-lg border border-dashed py-12 text-center",
        className,
      )}
    >
      <h3 className="text-lg font-semibold">{title}</h3>
      {description && (
        <p className="mt-1 max-w-md text-sm text-muted-foreground">
          {description}
        </p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
