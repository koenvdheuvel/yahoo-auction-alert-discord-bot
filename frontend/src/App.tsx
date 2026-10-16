import Box from "@mui/material/Box";
import CircularProgress from "@mui/material/CircularProgress";
import CssBaseline from "@mui/material/CssBaseline";
import { ThemeProvider } from "@mui/material/styles";
import { QueryClient, QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { ApiError, onSessionEnded } from "./api/client";
import { keys, useSession } from "./api/hooks";
import type { Session } from "./api/types";
import { Login } from "./components/Login";
import { Workspace } from "./components/Workspace";
import { NoticeProvider } from "./components/common/Notices";
import { theme } from "./theme";

const queryClient = new QueryClient({
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
  const [ended, setEnded] = useState(false);

  useEffect(() => onSessionEnded(() => {
    // After signing out on purpose, requests that were still on their way come back 401.
    if (client.getQueryData<Session>(keys.session)?.authenticated === false) return;
    setEnded(true);
    client.setQueryData<Session>(keys.session, { authenticated: false });
  }), [client]);

  if (session.isPending) {
    return (
      <Box sx={{ minHeight: "100vh", display: "grid", placeItems: "center" }}>
        <CircularProgress aria-label="Opening Filter Lab" />
      </Box>
    );
  }
  if (!session.data?.authenticated) {
    return (
      <Login
        sessionEnded={ended}
        unreachable={session.isError ? session.error : null}
        onSignedIn={(data) => {
          setEnded(false);
          client.setQueryData<Session>(keys.session, data);
        }}
      />
    );
  }
  return <Workspace />;
}
