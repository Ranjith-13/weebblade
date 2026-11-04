import * as React from "react";
import { Input as InputPrimitive } from "@base-ui/react/input";
import { cn } from "cn";

/* Pulled from the shadcn registry, then restyled onto this project's tokens.
 * Stock shipped `rounded-lg`, a ring-offset focus glow and a dark-mode branch  - 
 * all three fight the design (zero radius everywhere, focus is a flat outline,
 * and there is no dark mode by choice). What is kept is the base-ui primitive
 * underneath, which handles the input semantics properly.
 *
 * Deliberately borderless: the field sits under a 2px rule drawn by its form,
 * so the input itself must not draw a competing box. */
function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <InputPrimitive
      type={type}
      data-slot="input"
      className={cn(
        "min-w-0 flex-1 rounded-none border-0 bg-transparent p-0 text-ink outline-none",
        "placeholder:text-ink-soft/55",
        "disabled:pointer-events-none disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
}

export { Input };
