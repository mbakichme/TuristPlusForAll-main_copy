import { Loader2 } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";

export default function PlaceholderPage({ title }: { title: string }) {
  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold">{title}</h1>
        <p className="text-muted-foreground text-sm">Knjigovodstvo</p>
      </div>
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-16 gap-3">
          <Loader2 className="w-8 h-8 text-muted-foreground/40" />
          <p className="text-muted-foreground">Ova stranica je u pripremi.</p>
        </CardContent>
      </Card>
    </div>
  );
}
