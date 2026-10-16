import type { AlertColor } from "@mui/material/Alert";

export interface SignInNotice {
  severity: AlertColor;
  message: string;
}

/** Why Discord sign-in came back without a session. dashboard.py puts the reason in ?signin=. */
export const SIGN_IN_ERRORS: Record<string, SignInNotice> = {
  cancelled: { severity: "info", message: "You cancelled on Discord, so you are not signed in." },
  state: { severity: "warning", message: "This sign-in expired, or it was started in another browser or tab. Start again from this page." },
  not_member: { severity: "error", message: "Your Discord account is not in any server this bot is in. Ask a server admin to invite you, or sign in with another account." },
  discord_unavailable: { severity: "error", message: "The dashboard couldn't reach Discord to check your access. Try again in a minute." },
  discord_error: { severity: "error", message: "Discord didn't accept the sign-in. Try again." },
  rate_limited: { severity: "error", message: "Too many sign-in attempts. Try again in a minute." },
  cookie: { severity: "error", message: "Your browser didn't keep the dashboard's sign-in cookie. Allow cookies for this site and try again." },
};

export const ACCESS_REVOKED: SignInNotice = {
  severity: "warning",
  message: "You are no longer in a server this bot is in, so you were signed out.",
};

export function signInNotice(reason: string): SignInNotice {
  return SIGN_IN_ERRORS[reason] ?? { severity: "error", message: "Signing in didn't work. Try again." };
}

/** The sign-in reason in the address, if any. */
export function readSignInReason(): string | null {
  return new URLSearchParams(window.location.search).get("signin");
}

/** Removes the reason from the address, so a reload does not show it again. */
export function clearSignInReason() {
  const params = new URLSearchParams(window.location.search);
  if (!params.has("signin")) return;
  params.delete("signin");
  const search = params.toString();
  window.history.replaceState(window.history.state, "", `${window.location.pathname}${search ? `?${search}` : ""}`);
}

/** Discord sign-in, coming back to the search and tab on screen. */
export function discordSignInHref(): string {
  const params = new URLSearchParams(window.location.search);
  params.delete("signin");
  const search = params.toString();
  return `/auth/discord?${new URLSearchParams({ next: `/${search ? `?${search}` : ""}` }).toString()}`;
}
