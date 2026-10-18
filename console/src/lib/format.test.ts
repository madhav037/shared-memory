import { describe, expect, it } from "vitest";

import { curled, folderName, isTopic, noticeMemory, readableNotice } from "./format";

const names = new Map([
  ["emp-raj", "Raj Raiser"],
  ["E1001", "Olive Owner"],
]);
const memberName = (memberId: string) => names.get(memberId);

/** A notice's parts as one line, a memory it names shown as [its title](its path). */
const read = (...asked: Parameters<typeof readableNotice>) =>
  readableNotice(...asked)
    .map((part) => (typeof part === "string" ? part : `[${part.title}](${part.path})`))
    .join("");

describe("a notice as a person reads it", () => {
  it("names a member without their member ID, and a project by its name", () => {
    expect(
      read(
        'Raj Raiser (emp-raj) commented on your card 1 "Retry failed webhooks" in billing-00f655: "Done."',
        memberName,
        [["billing-00f655", "Billing"]],
      ),
    ).toBe("Raj Raiser commented on your card 1 “Retry failed webhooks” in Billing: “Done.”");
  });

  it("keeps an ID it can't put a name to", () => {
    expect(read("Gone Member (emp-gone) can no longer reach billing-00f655.", memberName, [])).toBe(
      "Gone Member (emp-gone) can no longer reach billing-00f655.",
    );
  });

  it("leaves a project ID inside a longer word alone", () => {
    expect(read("see billing-00f655-old", memberName, [["billing-00f655", "Billing"]])).toBe(
      "see billing-00f655-old",
    );
  });

  it("names a member the notice opens with by their ID alone", () => {
    expect(read("E1001 retired a memory you wrote.", memberName, [])).toBe("Olive Owner retired a memory you wrote.");
    expect(read("emp-gone retired a memory you wrote.", memberName, [])).toBe("emp-gone retired a memory you wrote.");
  });

  it("only looks for a bare ID at the very start", () => {
    expect(read("Retired by E1001 today.", memberName, [])).toBe("Retired by E1001 today.");
  });

  it("sets a memory it cites by title and path apart, to be linked by its title", () => {
    const parts = readableNotice(
      'E1001 promoted a memory in your name: "Use pnpm, not npm" (projects/billing-00f655/shared/conventions/use-pnpm.md), imported from billing-api:CLAUDE.md, is now project memory and you are its author.',
      memberName,
      [["billing-00f655", "Billing"]],
    );

    expect(parts).toEqual([
      "Olive Owner promoted a memory in your name: ",
      { title: "Use pnpm, not npm", path: "projects/billing-00f655/shared/conventions/use-pnpm.md" },
      ", imported from billing-api:CLAUDE.md, is now project memory and you are its author.",
    ]);
    expect(noticeMemory(parts)?.path).toBe("projects/billing-00f655/shared/conventions/use-pnpm.md");
  });

  it("names no memory when the notice cites none", () => {
    expect(noticeMemory(readableNotice("Raj Raiser (emp-raj) commented.", memberName, []))).toBeUndefined();
  });
});

describe("a folder's name as the console shows it", () => {
  it("knows a topic from the folders around it", () => {
    expect(isTopic("team/conventions/invoicing")).toBe(true);
    expect(isTopic("team/conventions")).toBe(false);
    expect(isTopic("projects/billing-1/shared/conventions/invoicing")).toBe(true);
    expect(isTopic("projects/billing-1/shared/conventions")).toBe(false);
    expect(isTopic("projects/billing-1/people/E1001/gotchas")).toBe(false);
    expect(isTopic("projects/billing-1/people/E1001/gotchas/webhooks")).toBe(true);
  });

  it("puts a topic in sentence case and leaves every other name as the server gives it", () => {
    expect(folderName("projects/billing-1/shared/conventions/invoicing", "invoicing")).toBe("Invoicing");
    expect(folderName("projects/billing-1", "iOS app")).toBe("iOS app");
  });
});

describe("curled quotes", () => {
  it("opens and closes double and single quotes, and turns apostrophes", () => {
    expect(curled(`It's "done" ('mostly')`)).toBe("It’s “done” (‘mostly’)");
  });
});
