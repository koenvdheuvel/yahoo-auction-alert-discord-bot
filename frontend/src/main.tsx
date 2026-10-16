import "@fontsource-variable/archivo/wdth.css";

import createCache from "@emotion/cache";
import { CacheProvider } from "@emotion/react";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { moveOldKeys } from "./lib/storage";

// dashboard.py puts a new nonce on this tag for every page view. MUI writes its styles into
// <style> tags at runtime, and the Content-Security-Policy only accepts tags with that nonce.
const nonce = document.querySelector<HTMLMetaElement>('meta[property="csp-nonce"]')?.nonce || undefined;
const cache = createCache({ key: "dash", nonce, prepend: true });

moveOldKeys();

const root = document.getElementById("root");
if (!root) throw new Error("index.html has no #root element");

createRoot(root).render(
  <StrictMode>
    <CacheProvider value={cache}>
      <App />
    </CacheProvider>
  </StrictMode>,
);
