import { cn } from "@/lib/utils";

interface PageLoaderProps {
  text?: string;
  className?: string;
}

/** Centralni preloader za celu stranicu: dvostruki prsten + skeleton redovi. */
export function PageLoader({ text = "Molimo sačekajte učitavanje podataka u toku.", className }: PageLoaderProps) {
  return (
    <div
      role="status"
      aria-live="polite"
      className={cn("flex min-h-[70vh] w-full flex-col items-center justify-center gap-8 p-6", className)}
    >
      <div className="relative size-16" aria-hidden="true">
        <span className="absolute inset-0 rounded-full border-[3px] border-primary/15" />
        <span className="absolute inset-0 animate-spin rounded-full border-[3px] border-transparent border-t-primary motion-reduce:animate-none" />
        <span className="absolute inset-3 animate-spin rounded-full border-[3px] border-transparent border-b-primary/60 [animation-direction:reverse] [animation-duration:1.4s] motion-reduce:animate-none" />
        <span className="absolute inset-[26px] animate-pulse rounded-full bg-primary motion-reduce:animate-none" />
      </div>

      <p className="max-w-sm text-center text-sm font-medium text-muted-foreground">{text}</p>

      <div className="w-full max-w-md space-y-3" aria-hidden="true">
        <div className="h-3 w-3/4 animate-pulse rounded-full bg-muted motion-reduce:animate-none" />
        <div className="h-3 w-full animate-pulse rounded-full bg-muted [animation-delay:150ms] motion-reduce:animate-none" />
        <div className="h-3 w-5/6 animate-pulse rounded-full bg-muted [animation-delay:300ms] motion-reduce:animate-none" />
      </div>
    </div>
  );
}
