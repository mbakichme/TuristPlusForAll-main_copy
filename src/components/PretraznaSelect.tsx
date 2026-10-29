import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";

/**
 * Select sa pretragom. `prazno` = dodaje opciju „Prazno (bez izbora)“ (Radix Select ne dozvoljava value="").
 * `onPretraga` = server-side pretraga: roditelj puni `opcije` prema upitu, komponenta ne filtrira lokalno.
 */
export default function PretraznaSelect({ value, opcije, placeholder, label, ariaLabel, onChange, disabled, prazno, className, onPretraga }: {
  value: string;
  opcije: { value: string; label: string }[];
  placeholder: string;
  label?: string;
  ariaLabel: string;
  onChange: (v: string) => void;
  disabled?: boolean;
  prazno?: boolean;
  className?: string;
  onPretraga?: (q: string) => void;
}) {
  const [otvoreno, setOtvoreno] = useState(false);
  const [upit, setUpit] = useState("");
  const izabrana = opcije.find((o) => o.value === value);
  const izbor = (v: string) => { onChange(v); setOtvoreno(false); };
  const promeniOtvoreno = (o: boolean) => {
    setOtvoreno(o);
    if (!o) { setUpit(""); onPretraga?.(""); }
  };
  return (
    <Popover open={otvoreno} onOpenChange={promeniOtvoreno}>
      <PopoverTrigger asChild>
        <Button type="button" variant="outline" disabled={disabled} aria-label={ariaLabel}
          className={cn("w-full h-9 justify-between font-normal text-sm", className)}>
          <span className={cn("truncate", !value && "text-muted-foreground")}>
            {value ? (izabrana?.label ?? value) : placeholder}
          </span>
          <ChevronDown className="size-3.5 opacity-50 shrink-0" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[--radix-popover-trigger-width] p-0 bg-card" align="start">
        <Command shouldFilter={!onPretraga}>
          {label && <div className="px-3 pt-2.5 pb-0.5 text-xs font-medium text-muted-foreground">{label}</div>}
          <CommandInput
            placeholder="Pretraga…"
            value={upit}
            onValueChange={(q) => { setUpit(q); onPretraga?.(q); }}
          />
          <CommandList>
            <CommandEmpty>Nema rezultata za zadatu pretragu.</CommandEmpty>
            <CommandGroup>
              {prazno && (
                <CommandItem value="prazno bez izbora" onSelect={() => izbor("")}>
                  <span className="italic text-muted-foreground">Prazno (bez izbora)</span>
                </CommandItem>
              )}
              {opcije.map((o) => (
                <CommandItem key={o.value} value={o.label} onSelect={() => izbor(o.value)}>
                  {o.label}
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
