import { Button, createTheme, type MantineColorsTuple } from "@mantine/core";

/**
 * The Consolidated Code: the team's memory published like a code of practice.
 * Buckram green is the binding colour of the volume; everything else is paper and ink.
 */
const buckram: MantineColorsTuple = [
  "#e8f2ed",
  "#d2e5db",
  "#a6cbb8",
  "#7cc4a0",
  "#509874",
  "#3a8a63",
  "#2c7353",
  "#1e5b46",
  "#154a39",
  "#0a3a2b",
];

export const theme = createTheme({
  primaryColor: "buckram",
  primaryShade: { light: 7, dark: 3 },
  colors: { buckram },
  fontFamily: '"Public Sans Variable", "Public Sans", ui-sans-serif, system-ui, sans-serif',
  fontFamilyMonospace: 'ui-monospace, "Cascadia Mono", "SF Mono", Menlo, Consolas, monospace',
  headings: {
    fontFamily: '"Source Serif 4 Variable", "Source Serif 4", Georgia, serif',
    fontWeight: "600",
  },
  defaultRadius: 0,
  radius: { xs: "0px", sm: "1px", md: "2px", lg: "2px", xl: "2px" },
  fontSizes: { xs: "0.8125rem", sm: "0.875rem", md: "1rem", lg: "1.125rem", xl: "1.375rem" },
  focusRing: "auto",
  cursorType: "pointer",
  components: {
    // Filled buttons take the binding colour with its own ink, so they read in both themes.
    Button: Button.extend({
      defaultProps: { radius: 0 },
      vars: (_theme, props) => {
        if (props.variant && props.variant !== "filled") return { root: {} };
        const danger = props.color === "red";
        return {
          root: {
            "--button-bg": danger ? "var(--danger)" : "var(--accent)",
            "--button-hover": danger ? "var(--danger-hover)" : "var(--accent-hover)",
            "--button-color": "var(--accent-ink)",
          },
        };
      },
    }),
    TextInput: { defaultProps: { radius: 0 } },
    Select: { defaultProps: { radius: 0 } },
    Menu: { defaultProps: { radius: 0, shadow: "sm" } },
    Drawer: { defaultProps: { radius: 0 } },
    Tooltip: { defaultProps: { radius: 0, withArrow: false, openDelay: 250 } },
    Switch: { defaultProps: { radius: 0 } },
    Slider: { defaultProps: { radius: 0 } },
  },
});
