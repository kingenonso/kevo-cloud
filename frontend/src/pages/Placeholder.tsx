export function PlaceholderPage({ title }: { title: string }) {
  return (
    <div className="flex h-full flex-col items-center justify-center rounded-2xl border border-dashed border-border bg-card/50 text-center">
      <p className="font-heading text-xl text-foreground">{title}</p>
      <p className="mt-2 max-w-sm text-sm text-muted-foreground">
        This page hasn't been rebuilt in the new interface yet.
      </p>
    </div>
  )
}
