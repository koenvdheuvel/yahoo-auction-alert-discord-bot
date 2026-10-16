import Check from "@mui/icons-material/Check";
import KeyboardOutlined from "@mui/icons-material/KeyboardOutlined";
import KeyOutlined from "@mui/icons-material/KeyOutlined";
import Logout from "@mui/icons-material/Logout";
import MenuIcon from "@mui/icons-material/Menu";
import MoreVert from "@mui/icons-material/MoreVert";
import ScienceOutlined from "@mui/icons-material/ScienceOutlined";
import UploadFileOutlined from "@mui/icons-material/UploadFileOutlined";
import AppBar from "@mui/material/AppBar";
import Avatar from "@mui/material/Avatar";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Divider from "@mui/material/Divider";
import IconButton from "@mui/material/IconButton";
import ListItemIcon from "@mui/material/ListItemIcon";
import ListItemText from "@mui/material/ListItemText";
import ListSubheader from "@mui/material/ListSubheader";
import Menu from "@mui/material/Menu";
import MenuItem from "@mui/material/MenuItem";
import { useColorScheme } from "@mui/material/styles";
import Toolbar from "@mui/material/Toolbar";
import Typography from "@mui/material/Typography";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import { keys, useSession } from "../api/hooks";
import type { Session } from "../api/types";
import { clearAllDrafts, countDrafts } from "../lib/drafts";
import { errorMessage } from "../lib/errors";
import { plural } from "../lib/format";
import { ImportHistoryDialog } from "./ImportHistoryDialog";
import { ConfirmDialog } from "./common/Feedback";
import { LogoMark } from "./common/Logo";
import { useNotify } from "./common/notify";

export const HEADER_HEIGHT = 56;

const MODES = [["light", "Light"], ["dark", "Dark"], ["system", "Same as the system"]] as const;

interface Props {
  showMenu: boolean;
  onMenu: () => void;
  onTestTitle: () => void;
  onHelp: () => void;
}

export function AppHeader({ showMenu, onMenu, onTestTitle, onHelp }: Props) {
  const client = useQueryClient();
  const notify = useNotify();
  const { mode, setMode } = useColorScheme();
  const user = useSession().data?.user ?? null;
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const [accountAnchor, setAccountAnchor] = useState<HTMLElement | null>(null);
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

  const close = () => setAnchor(null);
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

  return (
    <AppBar position="fixed" sx={{ height: HEADER_HEIGHT, borderBottom: 1, borderColor: "divider",
      bgcolor: "background.paper", zIndex: (theme) => theme.zIndex.drawer + 1 }}>
      <Toolbar sx={{ minHeight: `${HEADER_HEIGHT}px !important`, gap: 1, px: { xs: 1.5, md: 2.5 } }}>
        {showMenu && (
          <IconButton edge="start" aria-label="Open the list of searches" onClick={onMenu}><MenuIcon /></IconButton>
        )}
        <LogoMark size={26} />
        <Typography variant="h2" component="p" sx={{ fontSize: "1.05rem" }}>Filter Lab</Typography>
        <Box sx={{ flex: 1 }} />
        <Button startIcon={<ScienceOutlined />} onClick={onTestTitle} color="inherit" aria-keyshortcuts="t">
          Test a title
        </Button>
        <IconButton aria-label="More actions" aria-haspopup="menu" aria-expanded={anchor !== null}
          onClick={(event) => setAnchor(event.currentTarget)}>
          <MoreVert />
        </IconButton>
        <Button color="inherit" aria-haspopup="menu" aria-expanded={accountAnchor !== null}
          aria-label={`${user ? user.name : "Access key"}: account`} onClick={(event) => setAccountAnchor(event.currentTarget)}
          sx={{ minWidth: 0, px: { xs: 0.5, sm: 1 } }}
          startIcon={
            <Avatar src={user?.avatar_url} alt="" sx={{ width: 28, height: 28, fontSize: "0.875rem" }}>
              {user ? user.name.slice(0, 1).toUpperCase() : <KeyOutlined fontSize="small" />}
            </Avatar>
          }>
          <Box component="span" sx={{ display: { xs: "none", sm: "inline" }, maxWidth: 160, overflow: "hidden",
            textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {user ? user.name : "Access key"}
          </Box>
        </Button>
        <Menu anchorEl={accountAnchor} open={accountAnchor !== null} onClose={() => setAccountAnchor(null)}
          anchorOrigin={{ vertical: "bottom", horizontal: "right" }} transformOrigin={{ vertical: "top", horizontal: "right" }}>
          <Box sx={{ px: 2, pt: 1, pb: 1.5, maxWidth: 280 }}>
            <Typography variant="subtitle1" noWrap>{user ? user.name : "Signed in with the access key"}</Typography>
            <Typography variant="body2" color="text.secondary" noWrap>
              {user ? `@${user.username} on Discord` : "It can see every server's searches."}
            </Typography>
          </Box>
          <Divider />
          <MenuItem onClick={requestSignOut} disabled={signOut.isPending}>
            <ListItemIcon><Logout fontSize="small" /></ListItemIcon>
            <ListItemText>Sign out</ListItemText>
          </MenuItem>
        </Menu>
        <Menu anchorEl={anchor} open={anchor !== null} onClose={close}
          anchorOrigin={{ vertical: "bottom", horizontal: "right" }} transformOrigin={{ vertical: "top", horizontal: "right" }}>
          <MenuItem onClick={() => { close(); setImportOpen(true); }}>
            <ListItemIcon><UploadFileOutlined fontSize="small" /></ListItemIcon>
            <ListItemText>Import saved history…</ListItemText>
          </MenuItem>
          <MenuItem onClick={() => { close(); onHelp(); }}>
            <ListItemIcon><KeyboardOutlined fontSize="small" /></ListItemIcon>
            <ListItemText>Keyboard shortcuts</ListItemText>
          </MenuItem>
          <Divider />
          <ListSubheader sx={{ lineHeight: 2.5 }}>Appearance</ListSubheader>
          {MODES.map(([value, name]) => (
            <MenuItem key={value} selected={mode === value} role="menuitemradio" aria-checked={mode === value}
              onClick={() => { setMode(value); close(); }}>
              <ListItemIcon>{mode === value && <Check fontSize="small" />}</ListItemIcon>
              <ListItemText>{name}</ListItemText>
            </MenuItem>
          ))}
        </Menu>
      </Toolbar>
      <ImportHistoryDialog open={importOpen} onClose={() => setImportOpen(false)} />
      <ConfirmDialog open={confirmSignOut} title="Sign out and remove drafts?" confirm="Sign out"
        busy={signOut.isPending} onClose={() => setConfirmSignOut(false)}
        onConfirm={() => { setConfirmSignOut(false); signOut.mutate(); }}>
        <Typography variant="body2">
          Signing out removes {plural(draftsToRemove, "unpublished draft")} from this browser. Publish a draft first to keep it.
        </Typography>
      </ConfirmDialog>
    </AppBar>
  );
}
