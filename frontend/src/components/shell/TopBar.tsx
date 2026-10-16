import HelpOutlineOutlined from "@mui/icons-material/HelpOutlineOutlined";
import MenuIcon from "@mui/icons-material/Menu";
import Box from "@mui/material/Box";
import Divider from "@mui/material/Divider";
import IconButton from "@mui/material/IconButton";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import type { ReactNode } from "react";

import { TOPBAR_HEIGHT } from "../../theme";

interface Props {
  icon: ReactNode;
  title: string;
  /** Shown after the title, like a channel's topic in Discord. */
  detail?: string | null;
  showMenu: boolean;
  onMenu: () => void;
  onHelp: () => void;
  actions?: ReactNode;
}

/** The bar over the main area: what is open, and the actions for it. */
export function TopBar({ icon, title, detail, showMenu, onMenu, onHelp, actions }: Props) {
  return (
    <Box component="header" sx={{ height: TOPBAR_HEIGHT, flex: "none", display: "flex", alignItems: "center", gap: 1,
      px: { xs: 1, md: 2 }, bgcolor: "background.default", boxShadow: "0 1px 0 rgba(0,0,0,0.2)", position: "sticky",
      top: 0, zIndex: 4 }}>
      {showMenu && (
        <IconButton edge="start" aria-label="Open the server and channel lists" onClick={onMenu}><MenuIcon /></IconButton>
      )}
      <Box sx={{ display: "flex", color: "text.secondary" }}>{icon}</Box>
      <Typography variant="h2" component="h1" noWrap sx={{ minWidth: 0, flexShrink: 1 }}>{title}</Typography>
      {detail && (
        <>
          <Divider orientation="vertical" flexItem sx={{ my: 1.5, display: { xs: "none", sm: "block" } }} />
          <Typography variant="body2" color="text.secondary" noWrap sx={{ minWidth: 0, display: { xs: "none", sm: "block" } }}>
            {detail}
          </Typography>
        </>
      )}
      <Box sx={{ flex: 1 }} />
      {actions}
      <Tooltip title="Keyboard shortcuts">
        <IconButton aria-label="Keyboard shortcuts" onClick={onHelp} size="small"><HelpOutlineOutlined fontSize="small" /></IconButton>
      </Tooltip>
    </Box>
  );
}
