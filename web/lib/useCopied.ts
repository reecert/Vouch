"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Copy to the clipboard, and remember which thing was copied for long enough to say so.
 *
 * Six buttons had grown their own copy of this — four in the viewer, two on the site — with
 * two different flash durations, which is what a copy-pasted five-liner turns into. The key
 * is whatever distinguishes the buttons in a list (`i`, a sha, a job id); a lone button
 * passes nothing and reads `copied`.
 *
 * The timer is cancelled on unmount: revoking a job unmounts its row while the flash is
 * still pending, and a `setState` after that is a React warning nobody will chase down.
 */
export function useCopied<K = never>(ms = 1800) {
  const [copied, setCopied] = useState<K | true | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  const copy = useCallback(
    (text: string, key?: K) => {
      navigator.clipboard.writeText(text);
      setCopied(key ?? true);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(null), ms);
    },
    [ms],
  );

  return [copied, copy] as const;
}
