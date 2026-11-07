import * as React from "react";

import { cn } from "@/lib/utils";

/** Grey pulsing block shown while data loads. */
function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return <div aria-hidden="true" className={cn("animate-pulse rounded-lg bg-muted", className)} {...props} />;
}

export { Skeleton };
