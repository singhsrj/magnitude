import Link from "next/link";

export function Logo() {
  return (
    <Link href="/" className="inline-flex items-center gap-3 rounded-key focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent">
      <span aria-hidden="true" className="h-3 w-3 rounded-full bg-accent" />
      <span className="text-xl font-semibold tracking-[-0.02em]">magnitude</span>
    </Link>
  );
}
