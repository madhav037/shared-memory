// The console's lint: JavaScript's and TypeScript's recommended rules, React's rules of hooks, and one security rule.
// Types are tsc's job (`npm run build`); this catches the bug patterns tsc lets through.
import js from "@eslint/js";
import { defineConfig } from "eslint/config";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

const RAW_HTML = "Raw HTML skips React's escaping; render the text, or say why nothing a member wrote reaches it.";

export default defineConfig(
  { ignores: ["dist", "playwright-report", "test-results", "src/api/schema*.d.ts"] },
  js.configs.recommended,
  tseslint.configs.recommended,
  reactHooks.configs.flat["recommended-latest"],
  {
    languageOptions: { globals: { ...globals.browser, ...globals.node } },
    rules: {
      // Text a member wrote reaches the page through React, which escapes it. Raw HTML skips that, so each use is
      // deliberate and says why nothing a member wrote can reach it.
      "no-restricted-syntax": [
        "error",
        { selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']", message: RAW_HTML },
        { selector: "AssignmentExpression[left.property.name=/^(innerHTML|outerHTML)$/]", message: RAW_HTML },
      ],
      // A warning until the effects that set state are reworked (#383); then an error.
      "react-hooks/set-state-in-effect": "warn",
    },
  },
);
