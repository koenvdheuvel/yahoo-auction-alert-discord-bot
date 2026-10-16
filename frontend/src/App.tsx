import Box from "@mui/material/Box";
import CircularProgress from "@mui/material/CircularProgress";
import CssBaseline from "@mui/material/CssBaseline";
import { ThemeProvider } from "@mui/material/styles";
import { MutationCache, QueryCache, QueryClient, QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { ApiError, onSessionEnded } from "./api/client";
import { draftOwner, keys, refreshAccess, useSession } from "./api/hooks";
import type { Session } from "./api/types";
import { Login, type SessionEnd } from "./components/Login";
import { Workspace } from "./components/Workspace";
import { NoticeProvider } from "./components/common/Notices";
import { claimDrafts } from "./lib/drafts";
import { theme } from "./theme";

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

export function App() {
  return (
    <ThemeProvider theme={theme} defaultMode="system" noSsr>
      <CssBaseline enableColorScheme />
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
    client.setQueryData<Session>(keys.session, { authenticated: false, method: current?.method });
  }), [client]);

  if (session.isPending) {
    return (
      <Box sx={{ minHeight: "100vh", display: "grid", placeItems: "center" }}>
        <CircularProgress aria-label="Opening the dashboard" />
      </Box>
    );
  }
  if (!session.data?.authenticated) {
    return (
      <Login
        method={session.data?.method}
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
  return <Workspace />;
}
