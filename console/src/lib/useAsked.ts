import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Ask the server for something whenever what it depends on changes, and say so when it refuses.
 * Asking again for the same thing keeps what is on screen until the new answer arrives; asking for
 * something else clears it, so an old memory never shows under a new address.
 */
export function useAsked<T>(load: (signal: AbortSignal) => Promise<T>, on: unknown[]) {
  const [answer, setAnswer] = useState<T | null>(null);
  const [refused, setRefused] = useState<string | null>(null);
  const [asked, setAsked] = useState(0);
  const key = JSON.stringify(on);
  const shown = useRef(key);

  useEffect(() => {
    const attempt = new AbortController();
    if (shown.current !== key) {
      shown.current = key;
      setAnswer(null);
    }
    setRefused(null);
    load(attempt.signal)
      .then(setAnswer)
      .catch((problem: Error) => {
        if (!attempt.signal.aborted) {
          setAnswer(null);
          setRefused(problem.message);
        }
      });
    return () => attempt.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, asked]);

  const reload = useCallback(() => setAsked((times) => times + 1), []);
  return { answer, refused, reload, setAnswer };
}
