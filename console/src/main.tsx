import { MantineProvider } from "@mantine/core";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";

import { App } from "./App";
import { Guarded } from "./components/Guarded";
import { theme } from "./theme";

import "@fontsource/charis-sil/400.css";
import "@fontsource/charis-sil/400-italic.css";
import "@fontsource/charis-sil/700.css";
import "@fontsource/charis-sil/700-italic.css";
import "@fontsource/cooper-hewitt/400.css";
import "@fontsource/cooper-hewitt/400-italic.css";
import "@fontsource/cooper-hewitt/500.css";
import "@fontsource/cooper-hewitt/500-italic.css";
import "@fontsource/cooper-hewitt/600.css";
import "@fontsource/cooper-hewitt/700.css";
import "@fontsource/cooper-hewitt/700-italic.css";
import "@fontsource-variable/source-code-pro";
import "@mantine/core/styles.css";
import "./styles.css";

const root = document.getElementById("root");
if (!root) throw new Error("the page has no root element");
createRoot(root).render(
  <StrictMode>
    <MantineProvider theme={theme} defaultColorScheme="auto">
      <BrowserRouter>
        <Guarded fallback={<p role="alert">Something on this page couldn't be shown. Go back, or reload the page.</p>}>
          <App />
        </Guarded>
      </BrowserRouter>
    </MantineProvider>
  </StrictMode>,
);
