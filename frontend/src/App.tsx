import Box from "@mui/material/Box";
import CircularProgress from "@mui/material/CircularProgress";
import CssBaseline from "@mui/material/CssBaseline";
import { ThemeProvider, useColorScheme } from "@mui/material/styles";
import { MutationCache, QueryCache, QueryClient, QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { ApiError, onSessionEnded } from "./api/client";
import { draftOwner, keys, refreshAccess, useSession } from "./api/hooks";
import type { Session } from "./api/types";
import { Login, type SessionEnd } from "./components/Login";
import { Shell } from "./components/shell/Shell";
import { NoticeProvider } from "./components/common/Notices";
import { claimDrafts } from "./lib/drafts";
import { pageColor, theme } from "./theme";

const queryClient: QueryClient = new QueryClient({
  queryCache: new QueryCache({ onError: (error) => refreshAccess(queryClient, error) }),
  mutationCache: new MutationCache({ onError: (error) => refreshAccess(queryClient, error) }),
  defaultOptions: {
    queries: {
      // Retry network blips and server errors, not answers such as 400, 401 or 404.
      retry: (failures, error) => failures < 2 && !(error instanceof ApiError && error.status >= 400 && error.status < 500),
    },
    mutations: { retry: false },
  },
});

// The browser's own bars, such as the address bar on Android, take the page's color in the chosen mode.
function BrowserColor() {
  const { mode, systemMode } = useColorScheme();
  const scheme = mode === "system" ? systemMode : mode;
  const color = scheme ? pageColor[scheme] : undefined;
  useEffect(() => {
    if (!color) return;
    for (const meta of document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]')) meta.content = color;
  }, [color]);
  return null;
}

export function App() {
  return (
    <ThemeProvider theme={theme} defaultMode="system" noSsr>
      <CssBaseline enableColorScheme />
      <BrowserColor />
      <QueryClientProvider client={queryClient}>
        <NoticeProvider>
          <SessionGate />
        </NoticeProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}

function SessionGate() {
  const client = useQueryClient();
  const session = useSession();
  const [ended, setEnded] = useState<SessionEnd | null>(null);

  useEffect(() => onSessionEnded((error) => {
    // After signing out on purpose, requests that were still on their way come back 401.
    const current = client.getQueryData<Session>(keys.session);
    if (current?.authenticated === false) return;
    setEnded(error.code === "access_revoked" ? "revoked" : "ended");
    client.setQueryData<Session>(keys.session, { authenticated: false, method: current?.method, title: current?.title,
      bot: current?.bot, bot_running: current?.bot_running });
  }), [client]);

  if (session.isPending) {
    return (
      <Box sx={{ minHeight: "100dvh", display: "grid", placeItems: "center" }}>
        <CircularProgress aria-label={`Opening ${document.title}`} />
      </Box>
    );
  }
  if (!session.data?.authenticated) {
    return (
      <Login
        method={session.data?.method}
        title={session.data?.title}
        bot={session.data?.bot}
        ended={session.data?.reason === "access_revoked" ? "revoked" : ended}
        unreachable={session.isError ? session.error : null}
        onRetry={() => void session.refetch()}
        onSignedIn={(data) => {
          setEnded(null);
          claimDrafts(draftOwner(data));
          client.setQueryData<Session>(keys.session, data);
        }}
      />
    );
  }
  return <Shell />;
}
