import { useCallback, useEffect, useState } from "react";

/**
 * Ask the server for something whenever what it depends on changes, and say so when it refuses.
 * Asking again for the same thing keeps what is on screen until the new answer arrives; asking for
 * something else clears it, so an old memory never shows under a new address.
 */
export function useAsked<T>(load: (signal: AbortSignal) => Promise<T>, on: unknown[]) {
  const [answer, setAnswer] = useState<T | null>(null);
  const [refusal, setRefusal] = useState<{ message: string; ask: string } | null>(null);
  const [asked, setAsked] = useState(0);
  const key = JSON.stringify(on);
  const ask = `${key}#${asked}`;
  const [shown, setShown] = useState(key);
  if (shown !== key) {
    setShown(key);
    setAnswer(null);
  }
  // A refusal belongs to the ask that drew it: asking again clears it.
  const refused = refusal?.ask === ask ? refusal.message : null;

  useEffect(() => {
    const attempt = new AbortController();
    load(attempt.signal)
      .then(setAnswer)
      .catch((problem: Error) => {
        if (!attempt.signal.aborted) {
          setAnswer(null);
          setRefusal({ message: problem.message, ask });
        }
      });
    return () => attempt.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, asked]);

  const reload = useCallback(() => setAsked((times) => times + 1), []);
  return { answer, refused, reload, setAnswer };
}
