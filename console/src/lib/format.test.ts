import { describe, expect, it } from "vitest";

import { curled, readableNotice } from "./format";

const names = new Map([["emp-raj", "Raj Raiser"]]);
const memberName = (memberId: string) => names.get(memberId);

describe("a notice as a person reads it", () => {
  it("names a member without their member ID, and a project by its name", () => {
    expect(
      readableNotice(
        'Raj Raiser (emp-raj) commented on your card 1 "Retry failed webhooks" in billing-00f655: "Done."',
        memberName,
        [["billing-00f655", "Billing"]],
      ),
    ).toBe("Raj Raiser commented on your card 1 “Retry failed webhooks” in Billing: “Done.”");
  });

  it("keeps an ID it can't put a name to", () => {
    expect(readableNotice("Gone Member (emp-gone) can no longer reach billing-00f655.", memberName, [])).toBe(
      "Gone Member (emp-gone) can no longer reach billing-00f655.",
    );
  });

  it("leaves a project ID inside a longer word alone", () => {
    expect(readableNotice("see billing-00f655-old", memberName, [["billing-00f655", "Billing"]])).toBe(
      "see billing-00f655-old",
    );
  });
});

describe("curled quotes", () => {
  it("opens and closes double and single quotes, and turns apostrophes", () => {
    expect(curled(`It's "done" ('mostly')`)).toBe("It’s “done” (‘mostly’)");
  });
});
