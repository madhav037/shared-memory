// Fails when the committed API types no longer match the ones generated from the API's description.
import { readFileSync, rmSync } from "node:fs";

const committed = "src/api/schema.d.ts";
const regenerated = "src/api/schema.generated.check.d.ts";
const matches = readFileSync(committed, "utf8") === readFileSync(regenerated, "utf8");
rmSync(regenerated);
if (!matches) {
  console.error(`${committed} is out of date. Run: npm run api:types`);
  process.exit(1);
}
console.log(`${committed} matches the API's description.`);
