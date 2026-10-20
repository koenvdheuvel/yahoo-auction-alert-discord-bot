import Check from "@mui/icons-material/Check";
import KeyboardOutlined from "@mui/icons-material/KeyboardOutlined";
import KeyOutlined from "@mui/icons-material/KeyOutlined";
import Logout from "@mui/icons-material/Logout";
import SettingsOutlined from "@mui/icons-material/SettingsOutlined";
import UploadFileOutlined from "@mui/icons-material/UploadFileOutlined";
import Avatar from "@mui/material/Avatar";
import Box from "@mui/material/Box";
import ButtonBase from "@mui/material/ButtonBase";
import Divider from "@mui/material/Divider";
import IconButton from "@mui/material/IconButton";
import ListItemIcon from "@mui/material/ListItemIcon";
import ListItemText from "@mui/material/ListItemText";
import ListSubheader from "@mui/material/ListSubheader";
import Menu from "@mui/material/Menu";
import MenuItem from "@mui/material/MenuItem";
import { useColorScheme } from "@mui/material/styles";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../../api/client";
import { keys, useSession } from "../../api/hooks";
import type { Session } from "../../api/types";
import { clearAllDrafts, countDrafts } from "../../lib/drafts";
import { errorMessage } from "../../lib/errors";
import { plural } from "../../lib/format";
import { ImportHistoryDialog } from "../ImportHistoryDialog";
import { ConfirmDialog } from "../common/Feedback";
import { useNotify } from "../common/notify";

const MODES = [["light", "Light"], ["dark", "Dark"], ["system", "Same as the system"]] as const;

/** Who is signed in, at the bottom of the channel list as in Discord, with the settings and sign-out. */
export function UserPanel({ onHelp }: { onHelp: () => void }) {
  const client = useQueryClient();
  const notify = useNotify();
  const { mode, setMode } = useColorScheme();
  const user = useSession().data?.user ?? null;
  const [accountAnchor, setAccountAnchor] = useState<HTMLElement | null>(null);
  const [settingsAnchor, setSettingsAnchor] = useState<HTMLElement | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [draftsToRemove, setDraftsToRemove] = useState(0);
  const [confirmSignOut, setConfirmSignOut] = useState(false);

  const signOut = useMutation({
    mutationFn: api.logout,
    onSuccess: (session) => {
      // Leave the workspace first, so clearing the drafts does not make it fetch again.
      client.setQueryData<Session>(keys.session, session);
      clearAllDrafts();
      client.removeQueries({ predicate: (query) => query.queryKey[0] !== keys.session[0] });
    },
    onError: (error) => notify(`Signing out failed: ${errorMessage(error)}`, "error"),
  });

  const requestSignOut = () => {
    setAccountAnchor(null);
    const drafts = countDrafts();
    if (drafts) {
      setDraftsToRemove(drafts);
      setConfirmSignOut(true);
    } else {
      signOut.mutate();
    }
  };
  const closeSettings = () => setSettingsAnchor(null);
  const name = user ? user.name : "Access key";

  return (
    <Box sx={{ flex: "none", height: 52, px: 1, display: "flex", alignItems: "center", gap: 0.5, bgcolor: "surface.panel" }}>
      <ButtonBase aria-haspopup="menu" aria-expanded={accountAnchor !== null} aria-label={`${name}: account`}
        onClick={(event) => setAccountAnchor(event.currentTarget)}
        sx={{ flex: 1, minWidth: 0, display: "flex", justifyContent: "flex-start", gap: 1, px: 0.5, py: 0.5, borderRadius: 1,
          textAlign: "left", "&:hover": { bgcolor: "surface.hover" } }}>
        <Avatar src={user?.avatar_url} alt="" sx={{ width: 32, height: 32, fontSize: "0.875rem" }}>
          {user ? user.name.slice(0, 1).toUpperCase() : <KeyOutlined fontSize="small" />}
        </Avatar>
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="body2" noWrap sx={{ fontWeight: 600, color: "text.primary" }}>{name}</Typography>
          <Typography variant="caption" noWrap component="p" color="textSecondary">
            {user ? user.username : "Every server"}
          </Typography>
        </Box>
      </ButtonBase>
      <Tooltip title="Settings">
        <IconButton aria-label="Settings" aria-haspopup="menu" aria-expanded={settingsAnchor !== null} size="small"
          onClick={(event) => setSettingsAnchor(event.currentTarget)}>
          <SettingsOutlined fontSize="small" />
        </IconButton>
      </Tooltip>
      <Menu anchorEl={accountAnchor} open={accountAnchor !== null} onClose={() => setAccountAnchor(null)}
        anchorOrigin={{ vertical: "top", horizontal: "left" }} transformOrigin={{ vertical: "bottom", horizontal: "left" }}>
        <Box sx={{ px: 2, pt: 1, pb: 1.5, maxWidth: 280 }}>
          <Typography variant="subtitle1" noWrap>{user ? user.name : "Signed in with the access key"}</Typography>
          <Typography variant="body2" color="textSecondary" noWrap>
            {user ? `@${user.username} on Discord` : "It can see every server's searches."}
          </Typography>
        </Box>
        <Divider />
        <MenuItem onClick={requestSignOut} disabled={signOut.isPending}>
          <ListItemIcon><Logout fontSize="small" /></ListItemIcon>
          <ListItemText>Sign out</ListItemText>
        </MenuItem>
      </Menu>
      <Menu anchorEl={settingsAnchor} open={settingsAnchor !== null} onClose={closeSettings}
        anchorOrigin={{ vertical: "top", horizontal: "right" }} transformOrigin={{ vertical: "bottom", horizontal: "right" }}>
        <MenuItem onClick={() => { closeSettings(); setImportOpen(true); }}>
          <ListItemIcon><UploadFileOutlined fontSize="small" /></ListItemIcon>
          <ListItemText>Import saved history…</ListItemText>
        </MenuItem>
        <MenuItem onClick={() => { closeSettings(); onHelp(); }}>
          <ListItemIcon><KeyboardOutlined fontSize="small" /></ListItemIcon>
          <ListItemText>Keyboard shortcuts</ListItemText>
        </MenuItem>
        <Divider />
        <ListSubheader sx={{ lineHeight: 2.5, bgcolor: "transparent" }}>Appearance</ListSubheader>
        {MODES.map(([value, label]) => (
          <MenuItem key={value} selected={mode === value} role="menuitemradio" aria-checked={mode === value}
            onClick={() => { setMode(value); closeSettings(); }}>
            <ListItemIcon>{mode === value && <Check fontSize="small" />}</ListItemIcon>
            <ListItemText>{label}</ListItemText>
          </MenuItem>
        ))}
      </Menu>
      <ImportHistoryDialog open={importOpen} onClose={() => setImportOpen(false)} />
      <ConfirmDialog open={confirmSignOut} title="Sign out and remove drafts?" confirm="Sign out"
        busy={signOut.isPending} onClose={() => setConfirmSignOut(false)}
        onConfirm={() => { setConfirmSignOut(false); signOut.mutate(); }}>
        <Typography variant="body2">
          Signing out removes {plural(draftsToRemove, "unpublished draft")} from this browser. Publish a draft first to keep it.
        </Typography>
      </ConfirmDialog>
    </Box>
  );
}
