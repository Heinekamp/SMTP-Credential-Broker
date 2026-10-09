import { type ReactNode, useEffect, useId, useRef } from "react";

import { Card } from "../design-system/components";

const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export interface ModalFrameProps {
  title: ReactNode;
  onClose: () => void;
  maxWidth?: number;
  children: ReactNode;
}

// The shared scrim + card for every modal (#211): a real dialog for
// assistive tech (role="dialog", aria-modal, labelled by its title),
// Escape closes it, focus moves into it on open (unless a field has
// autoFocus), Tab/Shift+Tab stay inside it, and focus returns to whatever
// opened it on close. The modals used to be plain divs: no dialog
// semantics, no Escape, and Tab wandered off into the page behind.
export function ModalFrame({ title, onClose, maxWidth = 440, children }: ModalFrameProps) {
  const titleId = useId();
  const cardRef = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const card = cardRef.current;
    if (card && !card.contains(document.activeElement)) {
      card.querySelector<HTMLElement>(FOCUSABLE)?.focus();
    }

    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onCloseRef.current();
        return;
      }
      if (e.key !== "Tab" || !card) return;
      const focusable = Array.from(card.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      opener?.focus?.();
    };
  }, []);

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.7)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 100,
      }}
    >
      <div ref={cardRef} role="dialog" aria-modal="true" aria-labelledby={titleId} style={{ width: "100%", maxWidth }}>
        <Card style={{ width: "100%", padding: 24 }}>
          <h2 id={titleId} style={{ margin: "0 0 12px", fontSize: "var(--text-md)", fontWeight: 600 }}>
            {title}
          </h2>
          {children}
        </Card>
      </div>
    </div>
  );
}
