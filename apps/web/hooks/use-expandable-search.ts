/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useEffect, useRef, useState } from "react";

type UseExpandableSearchOptions = {
  onClose?: () => void;
};

/**
 * Custom hook for expandable search input behavior
 * Handles focus management to prevent unwanted opening on programmatic focus restoration
 * Opens on click, typing, or keyboard shortcut (via PowerK Cmd+F)
 */
export const useExpandableSearch = (options?: UseExpandableSearchOptions) => {
  const { onClose } = options || {};

  // states
  const [isOpen, setIsOpen] = useState(false);

  // refs
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const wasClickedRef = useRef<boolean>(false);
  const wasKeyboardTriggeredRef = useRef<boolean>(false);

  // Handle close
  const handleClose = useCallback(() => {
    setIsOpen(false);
    inputRef.current?.blur();
    onClose?.();
  }, [onClose]);

  // Outside click handler - memoized to prevent unnecessary re-registrations
  const handleOutsideClick = useCallback(() => {
    if (isOpen) {
      handleClose();
    }
  }, [isOpen, handleClose]);

  // Outside click detection. Not `useOutsideClickDetector`: it skips clicks inside a `data-prevent-outside-click`
  // container (the sidebar, the page content) that the search is not in, so the panel stayed open there.
  useEffect(() => {
    if (!isOpen) return undefined;
    const handlePointerDownOutside = (event: PointerEvent) => {
      const container = containerRef.current;
      const path = event.composedPath();
      if (!container || path.includes(container)) return;
      // a popup opened from the panel renders in a portal on <body> — a press there is not outside
      if (path.some((node) => node instanceof Element && node.hasAttribute("data-base-ui-portal"))) return;
      handleOutsideClick();
    };
    // `pointerdown` in the capture phase: draggable list rows cancel the press before any `mousedown` fires, and a
    // press there must close the panel too
    document.addEventListener("pointerdown", handlePointerDownOutside, true);
    return () => document.removeEventListener("pointerdown", handlePointerDownOutside, true);
  }, [isOpen, handleOutsideClick]);

  // Track keyboard shortcuts that trigger focus (Cmd+F / Ctrl+F)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "f") {
        // Mark as keyboard triggered so handleFocus knows to open
        wasKeyboardTriggeredRef.current = true;
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, []);

  // Track explicit clicks
  const handleMouseDown = useCallback(() => {
    wasClickedRef.current = true;
  }, []);

  // Open on explicit clicks or keyboard shortcut, not programmatic focus restoration
  const handleFocus = useCallback(() => {
    if (wasClickedRef.current || wasKeyboardTriggeredRef.current) {
      setIsOpen(true);
      wasClickedRef.current = false;
      wasKeyboardTriggeredRef.current = false;
    }
  }, []);

  // Helper to open panel (for typing/onChange)
  const openPanel = useCallback(() => {
    if (!isOpen) {
      setIsOpen(true);
    }
  }, [isOpen]);

  return {
    // State
    isOpen,
    setIsOpen,

    // Refs
    containerRef,
    inputRef,

    // Handlers
    handleClose,
    handleMouseDown,
    handleFocus,
    openPanel,
  };
};
