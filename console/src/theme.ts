import { Button, createTheme, type MantineColorsTuple } from "@mantine/core";

/**
 * A modern public register: white paper, near-black ink, and one signal green for what is in force,
 * the current place and the action to take. Buttons are solid, with a darker edge beneath them.
 */
const signal: MantineColorsTuple = [
  "#e7f3ec",
  "#c6e5d2",
  "#93d0ad",
  "#4cc38a",
  "#26a766",
  "#118a4f",
  "#00703c",
  "#005a30",
  "#004526",
  "#002d18",
];

export const theme = createTheme({
  primaryColor: "signal",
  primaryShade: { light: 6, dark: 3 },
  colors: { signal },
  fontFamily: '"Cooper Hewitt", "Helvetica Neue", Arial, sans-serif',
  fontFamilyMonospace: '"Source Code Pro Variable", "Source Code Pro", ui-monospace, Menlo, Consolas, monospace',
  headings: {
    fontFamily: '"Cooper Hewitt", "Helvetica Neue", Arial, sans-serif',
    fontWeight: "700",
  },
  defaultRadius: 0,
  radius: { xs: "0px", sm: "0px", md: "0px", lg: "0px", xl: "0px" },
  fontSizes: { xs: "0.8125rem", sm: "0.9375rem", md: "1rem", lg: "1.125rem", xl: "1.375rem" },
  focusRing: "auto",
  cursorType: "pointer",
  components: {
    // Filled buttons take the signal colour with its own ink; the edge beneath them is drawn in styles.css.
    Button: Button.extend({
      defaultProps: { radius: 0 },
      vars: (_theme, props) => {
        if (props.variant === "default")
          return {
            root: {
              "--button-bg": "var(--paper-3)",
              "--button-hover": "var(--rule-soft)",
              "--button-color": "var(--ink)",
              "--button-bd": "1px solid transparent",
            },
          };
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
      // The edge each button stands on: darker than its face, the way GOV.UK draws them.
      styles: (_theme, props) => ({
        root: {
          "--edge":
            props.variant === "default"
              ? "var(--field-edge)"
              : props.color === "red"
                ? "var(--danger-edge)"
                : "var(--accent-edge)",
        } as React.CSSProperties,
      }),
    }),
    // What a field is missing is said between its label and the field, so the field stays level with its button.
    TextInput: { defaultProps: { radius: 0, inputWrapperOrder: ["label", "description", "error", "input"] } },
    Textarea: { defaultProps: { inputWrapperOrder: ["label", "description", "error", "input"] } },
    Select: { defaultProps: { radius: 0, inputWrapperOrder: ["label", "description", "error", "input"] } },
    Menu: { defaultProps: { radius: 0, shadow: "md" } },
    Drawer: { defaultProps: { radius: 0 } },
    Tooltip: { defaultProps: { radius: 0, withArrow: false, openDelay: 250 } },
    Switch: { defaultProps: { radius: 0 } },
    Slider: { defaultProps: { radius: 0 } },
  },
});
