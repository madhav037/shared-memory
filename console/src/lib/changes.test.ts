import { describe, expect, it } from "vitest";

import { whatChanges } from "./changes";

const STACK = "- Language: Go\n- Database: Postgres\n- Queue: RabbitMQ";

describe("what one memory would change about another", () => {
  it("says nothing about two memories written as prose", () => {
    expect(whatChanges("We use pnpm for every package.", "We use bun for every package.")).toBeNull();
  });

  it("names the part that changes, and the parts that stay as they are", () => {
    const changes = whatChanges(STACK, "- Language: Go\n- Database: Postgres\n- Queue: Kafka");

    expect(changes?.differences).toEqual([{ kind: "changed", label: "Queue", from: "RabbitMQ", to: "Kafka" }]);
    expect(changes?.unchanged).toEqual(["Language", "Database"]);
  });

  it("notices a part added and a part dropped", () => {
    const changes = whatChanges(STACK, "- Language: Go\n- Database: Postgres\n- Cache: Redis");

    expect(changes?.differences).toEqual([
      { kind: "removed", label: "Queue", from: "RabbitMQ" },
      { kind: "added", label: "Cache", to: "Redis" },
    ]);
  });

  it("compares when only one side is a list, so an offer of prose is still answered", () => {
    const changes = whatChanges(STACK, "We moved the queue to Kafka and left the rest alone.");

    expect(changes?.differences.map((difference) => difference.label)).toEqual(["Language", "Database", "Queue"]);
  });

  it("reads a label once, however often it is repeated", () => {
    const changes = whatChanges("- Queue: RabbitMQ\n- Queue: Kafka\n- Language: Go", "- Queue: RabbitMQ\n- Language: Go");

    expect(changes?.differences).toEqual([]);
    expect(changes?.unchanged).toEqual(["Queue", "Language"]);
  });
});
