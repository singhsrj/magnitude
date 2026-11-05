type KeyCapProps = {
  glyph: string;
  size?: "sm" | "md";
};

/** A keyboard hint. Mirrors the Figma component "KeyCap". */
export function KeyCap({ glyph, size = "md" }: KeyCapProps) {
  const dims = size === "md" ? "h-11 w-11 text-base" : "h-8 w-8 text-sm";
  return (
    <kbd
      aria-hidden="true"
      className={`${dims} inline-flex items-center justify-center rounded-key border border-line-strong bg-bg-raised font-mono font-medium text-ink-primary`}
    >
      {glyph}
    </kbd>
  );
}
