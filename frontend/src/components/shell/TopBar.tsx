import ExpandMore from "@mui/icons-material/ExpandMore";
import HelpOutlineOutlined from "@mui/icons-material/HelpOutlineOutlined";
import MenuIcon from "@mui/icons-material/Menu";
import Box from "@mui/material/Box";
import ButtonBase from "@mui/material/ButtonBase";
import IconButton from "@mui/material/IconButton";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import type { ReactNode } from "react";

import { useTouch } from "../../lib/responsive";
import { TOPBAR_HEIGHT } from "../../theme";

interface Props {
  icon: ReactNode;
  title: string;
  /** Server/channel context stays visible below the title, including on phones. */
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
  const label = (
    <Box component="span" sx={{ display: "block", minWidth: 0, textAlign: "left" }}>
      <Box component="span" sx={{ display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{title}</Box>
      {detail && (
        <Typography component="span" variant="caption" color="textSecondary" title={detail}
          sx={{ display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden",
            whiteSpace: "normal", fontSize: { xs: "0.6875rem", sm: "0.75rem" }, lineHeight: 1.15, fontWeight: 400 }}>
          {detail}
        </Typography>
      )}
    </Box>
  );
  return (
    <Box component="header" sx={{ height: `calc(${TOPBAR_HEIGHT}px + env(safe-area-inset-top, 0px))`,
      pt: "env(safe-area-inset-top, 0px)", flex: "none", display: "flex", alignItems: "center", gap: 1,
      px: { xs: 1, md: 2 }, bgcolor: "background.default", boxShadow: "0 1px 0 rgba(0,0,0,0.2)", position: "sticky",
      top: 0, zIndex: 4 }}>
      {showMenu && (
        <IconButton edge="start" aria-label="Open the server and channel lists" onClick={onMenu}><MenuIcon /></IconButton>
      )}
      <Box sx={{ display: "flex", color: "text.secondary", flexShrink: 0 }}>{icon}</Box>
      <Typography variant="h2" component="h1" sx={{ minWidth: 0, flex: 1 }}>
        {onTitle ? (
          <ButtonBase onClick={onTitle} aria-haspopup="dialog" aria-label={`${title}: show the details`}
            sx={{ maxWidth: "100%", minHeight: 44, gap: 0.25, px: 0.5, mx: -0.5, borderRadius: 1, font: "inherit",
              "&.Mui-focusVisible": { outlineOffset: -2 } }}>
            {label}
            <ExpandMore fontSize="small" sx={{ color: "text.secondary", flex: "none" }} />
          </ButtonBase>
        ) : label}
      </Typography>
      {actions}
      {!touch && (
        <Tooltip title="Keyboard shortcuts">
          <IconButton aria-label="Keyboard shortcuts" onClick={onHelp} size="small"><HelpOutlineOutlined fontSize="small" /></IconButton>
        </Tooltip>
      )}
    </Box>
  );
}
