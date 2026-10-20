import LoginIcon from "@mui/icons-material/Login";
import Visibility from "@mui/icons-material/Visibility";
import VisibilityOff from "@mui/icons-material/VisibilityOff";
import Alert from "@mui/material/Alert";
import Avatar from "@mui/material/Avatar";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import IconButton from "@mui/material/IconButton";
import InputAdornment from "@mui/material/InputAdornment";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useMutation } from "@tanstack/react-query";
import { useEffect, useState, type SubmitEvent } from "react";

import { api } from "../api/client";
import type { BotUser, Session, SignInMethod } from "../api/types";
import { errorMessage } from "../lib/errors";
import { ACCESS_REVOKED, clearSignInReason, discordSignInHref, readSignInReason, signInNotice } from "../lib/signin";
import { LogoMark } from "./common/Logo";

/** Why the person is back at sign-in: the session expired, or they lost access to every server. */
export type SessionEnd = "ended" | "revoked";

interface Props {
  method: SignInMethod | undefined;
  /** The dashboard's name and the bot, from the session answer; unknown when the server cannot be reached. */
  title?: string;
  bot?: BotUser | null;
  ended: SessionEnd | null;
  unreachable: Error | null;
  onRetry: () => void;
  onSignedIn: (session: Session) => void;
}

const ENDED = "Your session ended. Sign in again; your unpublished drafts are still here.";

export function Login({ method, title = "Dashboard", bot = null, ended, unreachable, onRetry, onSignedIn }: Props) {
  return (
    <Box component="main" sx={{ minHeight: "100vh", display: "grid", placeItems: "center", p: 3, bgcolor: "surface.rail" }}>
      <Box sx={{ width: "100%", maxWidth: 440, bgcolor: "background.default", borderRadius: 2, p: { xs: 3, sm: 4 },
        boxShadow: "0 8px 24px rgba(0,0,0,0.24)" }}>
        <Stack direction="row" spacing={1.5} sx={{ alignItems: "center", mb: 3 }}>
          <Avatar src={bot?.avatar_url} alt="" sx={{ width: 48, height: 48, bgcolor: "primary.main" }}>
            {bot ? bot.name.slice(0, 1) : <LogoMark size={28} />}
          </Avatar>
          <Typography variant="h1" component="h1">{title}</Typography>
        </Stack>
        <Typography variant="body1" color="textSecondary" sx={{ mb: 3 }}>
          Manage the bot's searches, channels and notifications, and tune the rules that decide what gets posted to
          Discord.
        </Typography>
        {method === "discord" ? (
          <DiscordSignIn ended={ended} />
        ) : method === "access_key" ? (
          <AccessKeySignIn ended={ended !== null} onSignedIn={onSignedIn} />
        ) : (
          <Stack spacing={2}>
            <Alert severity="error" role="alert">{unreachable ? errorMessage(unreachable) : "The dashboard can't be reached."}</Alert>
            <Button variant="outlined" color="inherit" onClick={onRetry}>Try again</Button>
          </Stack>
        )}
      </Box>
    </Box>
  );
}

function DiscordSignIn({ ended }: { ended: SessionEnd | null }) {
  // dashboard.py sends the person back with ?signin=<reason> when sign-in did not work.
  const [reason] = useState(readSignInReason);
  useEffect(() => clearSignInReason(), []);
  const notice = reason ? signInNotice(reason) : ended === "revoked" ? ACCESS_REVOKED : null;

  return (
    <Stack spacing={2}>
      {notice && <Alert severity={notice.severity} role="alert">{notice.message}</Alert>}
      {!notice && ended === "ended" && <Alert severity="info">{ENDED}</Alert>}
      <Button variant="contained" size="large" href={discordSignInHref()} startIcon={<LoginIcon />}>
        Sign in with Discord
      </Button>
      {!notice && (
        <Typography variant="body2" color="textSecondary">
          Anyone in a server this bot is in can sign in to manage their own 🔔 notifications. With Manage Channels in a
          server you manage its searches too. The dashboard only asks Discord who you are; the bot checks your servers
          itself.
        </Typography>
      )}
    </Stack>
  );
}

function AccessKeySignIn({ ended, onSignedIn }: { ended: boolean; onSignedIn: (session: Session) => void }) {
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
    <Stack component="form" spacing={2} onSubmit={submit} noValidate>
      {ended && !login.isError && <Alert severity="info">{ENDED}</Alert>}
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
        helperText="It is in the .dashboard-token file next to the bot's database, or in DASHBOARD_TOKEN."
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
  );
}
