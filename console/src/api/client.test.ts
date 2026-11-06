import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchStatus, onRateLimited } from "./client";

const answering = (status: number, body: unknown) =>
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status })));

afterEach(() => vi.unstubAllGlobals());

describe("a call the server limits", () => {
  it("is told to whoever listens, with what the server said, and still refuses the call", async () => {
    answering(429, { message: "Rate limit: too many calls. Slow down and try again in 3 seconds.", retry_after_seconds: 3 });
    const heard: string[] = [];
    const stop = onRateLimited((message) => heard.push(message));

    await expect(fetchStatus()).rejects.toThrow("try again in 3 seconds");

    expect(heard).toEqual(["Rate limit: too many calls. Slow down and try again in 3 seconds."]);
    stop();
  });

  it("is not told to a listener that has stopped", async () => {
    answering(429, { message: "Slow down." });
    const heard: string[] = [];
    onRateLimited((message) => heard.push(message))();

    await expect(fetchStatus()).rejects.toThrow();

    expect(heard).toEqual([]);
  });

  it("is the only refusal that is told", async () => {
    answering(403, { message: "No." });
    const heard: string[] = [];
    const stop = onRateLimited((message) => heard.push(message));

    await expect(fetchStatus()).rejects.toThrow("No.");

    expect(heard).toEqual([]);
    stop();
  });
});
