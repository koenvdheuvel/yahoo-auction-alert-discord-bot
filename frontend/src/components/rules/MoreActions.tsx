import MoreVert from "@mui/icons-material/MoreVert";
import IconButton from "@mui/material/IconButton";
import ListItemIcon from "@mui/material/ListItemIcon";
import ListItemText from "@mui/material/ListItemText";
import Menu from "@mui/material/Menu";
import MenuItem from "@mui/material/MenuItem";
import type { SxProps, Theme } from "@mui/material/styles";
import { useState, type ReactNode } from "react";

import { usePhone } from "../../lib/responsive";
import { ActionSheet } from "../common/Sheet";

export interface MoreAction {
  label: string;
  icon?: ReactNode;
  onSelect: () => void;
  disabled?: boolean;
}

interface Props {
  /** Names the button for screen readers, such as "More actions for Brands". */
  label: string;
  /** The heading of the sheet on phones. */
  title: string;
  /** Shown under the sheet's heading on phones. */
  detail?: ReactNode;
  actions: MoreAction[];
  sx?: SxProps<Theme>;
}

/** A ⋮ button with a menu. On phones the menu opens as a sheet from the bottom, as in Discord's app. */
export function MoreActions({ label, title, detail, actions, sx }: Props) {
  const phone = usePhone();
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const close = () => setAnchor(null);
  return (
    <>
      <IconButton aria-label={label} aria-haspopup={phone ? "dialog" : "menu"} onClick={(event) => setAnchor(event.currentTarget)}
        sx={sx}>
        <MoreVert />
      </IconButton>
      {phone ? (
        <ActionSheet open={anchor !== null} onClose={close} title={title} actions={actions}>{detail}</ActionSheet>
      ) : (
        <Menu anchorEl={anchor} open={anchor !== null} onClose={close}>
          {actions.map((action) => (
            <MenuItem key={action.label} disabled={action.disabled} onClick={() => { close(); action.onSelect(); }}>
              {action.icon && <ListItemIcon>{action.icon}</ListItemIcon>}
              <ListItemText>{action.label}</ListItemText>
            </MenuItem>
          ))}
        </Menu>
      )}
    </>
  );
}
