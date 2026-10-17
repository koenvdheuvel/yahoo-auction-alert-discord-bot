import Visibility from "@mui/icons-material/Visibility";
import VisibilityOff from "@mui/icons-material/VisibilityOff";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import IconButton from "@mui/material/IconButton";
import InputAdornment from "@mui/material/InputAdornment";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useMutation } from "@tanstack/react-query";
import { useState, type SubmitEvent } from "react";

import { api } from "../api/client";
import type { Session } from "../api/types";
import { errorMessage } from "../lib/errors";
import { LogoMark } from "./common/Logo";

interface Props {
  sessionEnded: boolean;
  unreachable: Error | null;
  onSignedIn: (session: Session) => void;
}

export function Login({ sessionEnded, unreachable, onSignedIn }: Props) {
  const [key, setKey] = useState("");
  const [visible, setVisible] = useState(false);
  const login = useMutation({
    mutationFn: api.login,
    onSuccess: (session) => {
      setKey("");
      onSignedIn(session);
    },
  });

  const submit = (event: SubmitEvent) => {
    event.preventDefault();
    if (key.trim()) login.mutate(key.trim());
  };

  return (
    <Box component="main" sx={{ minHeight: "100vh", display: "grid", placeItems: "center", p: 3 }}>
      <Box sx={{ width: "100%", maxWidth: 420 }}>
        <Stack direction="row" spacing={1.5} sx={{ alignItems: "center", mb: 4 }}>
          <LogoMark size={36} />
          <Typography variant="h1" component="h1">Filter Lab</Typography>
        </Stack>
        <Typography variant="body1" color="text.secondary" sx={{ mb: 3 }}>
          See what your searches find, and tune the rules that decide what gets posted to Discord.
        </Typography>
        <Stack component="form" spacing={2} onSubmit={submit} noValidate>
          {sessionEnded && !login.isError && (
            <Alert severity="info">Your session ended. Sign in again; your unpublished drafts are still here.</Alert>
          )}
          {unreachable && !login.isError && <Alert severity="error">{errorMessage(unreachable)}</Alert>}
          {login.isError && <Alert severity="error" role="alert">{errorMessage(login.error)}</Alert>}
          <TextField
            label="Access key"
            type={visible ? "text" : "password"}
            value={key}
            onChange={(event) => setKey(event.target.value)}
            autoComplete="current-password"
            autoFocus
            required
            fullWidth
            size="medium"
            helperText="It is in the .review-token file next to the bot's database, or in REVIEW_TOKEN."
            slotProps={{
              htmlInput: { maxLength: 512, spellCheck: false, autoCapitalize: "off" },
              input: {
                endAdornment: (
                  <InputAdornment position="end">
                    <IconButton onClick={() => setVisible((value) => !value)} edge="end"
                      aria-label={visible ? "Hide access key" : "Show access key"}>
                      {visible ? <VisibilityOff /> : <Visibility />}
                    </IconButton>
                  </InputAdornment>
                ),
              },
            }}
          />
          <Button type="submit" variant="contained" size="large" disabled={!key.trim() || login.isPending}>
            {login.isPending ? "Signing in" : "Sign in"}
          </Button>
        </Stack>
      </Box>
    </Box>
  );
}
