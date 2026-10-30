/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
// plane imports
import { Switch } from "@makeplane/propel/components/switch";
import { cn } from "@plane/utils";

/** Light or dark mode for the request form — on: dark. It starts from the system's mode and is remembered. */
export function ThemeSwitch() {
  const { resolvedTheme, setTheme } = useTheme();
  // the theme is known only in the browser — render the switch after mounting so it never shows the wrong mode
  const [isMounted, setIsMounted] = useState(false);
  useEffect(() => setIsMounted(true), []);
  if (!isMounted) return <div className="h-5 w-[72px]" />;

  const isDark = resolvedTheme === "dark";
  return (
    <div className="flex items-center gap-1.5">
      <Sun className={cn("size-4", isDark ? "text-placeholder" : "text-primary")} aria-hidden />
      <Switch
        size="sm"
        checked={isDark}
        onCheckedChange={(checked) => setTheme(checked ? "dark" : "light")}
        aria-label="Dark mode"
      />
      <Moon className={cn("size-4", isDark ? "text-primary" : "text-placeholder")} aria-hidden />
    </div>
  );
}
