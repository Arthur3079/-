interface PlaceholderProps {
  title: string;
}

export function Placeholder({ title }: PlaceholderProps) {
  return (
    <div className="flex flex-1 items-center justify-center">
      <div className="text-center">
        <h1 className="text-3xl font-bold tracking-tight">{title}</h1>
        <p className="mt-2 text-muted-foreground">
          This module will be implemented in a future sprint.
        </p>
      </div>
    </div>
  );
}
