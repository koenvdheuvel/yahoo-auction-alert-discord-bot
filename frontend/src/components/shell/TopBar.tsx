import ExpandMore from "@mui/icons-material/ExpandMore";
import HelpOutlineOutlined from "@mui/icons-material/HelpOutlineOutlined";
import MenuIcon from "@mui/icons-material/Menu";
import Box from "@mui/material/Box";
import ButtonBase from "@mui/material/ButtonBase";
import Divider from "@mui/material/Divider";
import IconButton from "@mui/material/IconButton";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import type { ReactNode } from "react";

import { useTouch } from "../../lib/responsive";
import { TOPBAR_HEIGHT } from "../../theme";

interface Props {
  icon: ReactNode;
  title: string;
  /** Shown after the title, like a channel's topic in Discord. */
  detail?: string | null;
  showMenu: boolean;
  onMenu: () => void;
  onHelp: () => void;
  /** Opens what the title is about, as tapping a channel's name does in Discord's app. */
  onTitle?: () => void;
  actions?: ReactNode;
}

/** The bar over the main area: what is open, and the actions for it. */
export function TopBar({ icon, title, detail, showMenu, onMenu, onHelp, onTitle, actions }: Props) {
  // Keyboard shortcuts mean nothing without a keyboard.
  const touch = useTouch();
  return (
    <Box component="header" sx={{ height: `calc(${TOPBAR_HEIGHT}px + env(safe-area-inset-top, 0px))`,
      pt: "env(safe-area-inset-top, 0px)", flex: "none", display: "flex", alignItems: "center", gap: 1,
      px: { xs: 1, md: 2 }, bgcolor: "background.default", boxShadow: "0 1px 0 rgba(0,0,0,0.2)", position: "sticky",
      top: 0, zIndex: 4 }}>
      {showMenu && (
        <IconButton edge="start" aria-label="Open the server and channel lists" onClick={onMenu}><MenuIcon /></IconButton>
      )}
      <Box sx={{ display: "flex", color: "text.secondary" }}>{icon}</Box>
      <Typography variant="h2" component="h1" noWrap sx={{ minWidth: 0, flexShrink: 1 }}>
        {onTitle ? (
          <ButtonBase onClick={onTitle} aria-haspopup="dialog" aria-label={`${title}: show the details`}
            sx={{ maxWidth: "100%", minHeight: 44, gap: 0.25, px: 0.5, mx: -0.5, borderRadius: 1, font: "inherit" }}>
            <Box component="span" sx={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{title}</Box>
            <ExpandMore fontSize="small" sx={{ color: "text.secondary", flex: "none" }} />
          </ButtonBase>
        ) : title}
      </Typography>
      {detail && (
        <>
          <Divider orientation="vertical" flexItem sx={{ my: 1.5, display: { xs: "none", sm: "block" } }} />
          <Typography variant="body2" color="textSecondary" noWrap sx={{ minWidth: 0, display: { xs: "none", sm: "block" } }}>
            {detail}
          </Typography>
        </>
      )}
      <Box sx={{ flex: 1 }} />
      {actions}
      {!touch && (
        <Tooltip title="Keyboard shortcuts">
          <IconButton aria-label="Keyboard shortcuts" onClick={onHelp} size="small"><HelpOutlineOutlined fontSize="small" /></IconButton>
        </Tooltip>
      )}
    </Box>
  );
}
