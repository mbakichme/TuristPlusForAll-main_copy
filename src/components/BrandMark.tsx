import { cn } from "@/lib/utils";

// Logo aplikacije (public/logo.png).
export function BrandMark({ className }: { className?: string }) {
  return (
    <img
      src="/logo.png"
      alt="TuristPlus"
      className={cn("flex-shrink-0 object-contain", className)}
    />
  );
}
