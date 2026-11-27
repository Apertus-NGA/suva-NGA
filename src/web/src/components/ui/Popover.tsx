import * as RadixPopover from "@radix-ui/react-popover";
import type { ReactNode } from "react";

type Props = { trigger: ReactNode; children: ReactNode; width?: number; align?: "start" | "end" };

/** A panel anchored to its trigger. All filter menus use this one, so they look and behave alike. */
export function Popover({ trigger, children, width = 280, align = "start" }: Props) {
  return (
    <RadixPopover.Root>
      <RadixPopover.Trigger asChild>{trigger}</RadixPopover.Trigger>
      <RadixPopover.Portal>
        <RadixPopover.Content
          align={align}
          sideOffset={6}
          collisionPadding={12}
          style={{ width }}
          className="z-50 rounded-lg border border-line bg-surface shadow-popover outline-none"
        >
          {children}
        </RadixPopover.Content>
      </RadixPopover.Portal>
    </RadixPopover.Root>
  );
}
