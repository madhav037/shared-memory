import { createTheme } from "@mantine/core";

/** Quiet and readable: memory is the thing worth looking at, not the console. */
export const theme = createTheme({
  primaryColor: "indigo",
  defaultRadius: "md",
  fontFamily: 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif',
  headings: { fontWeight: "600" },
});
