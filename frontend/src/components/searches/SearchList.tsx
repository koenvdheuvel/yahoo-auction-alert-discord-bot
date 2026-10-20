import DeleteOutlined from "@mui/icons-material/DeleteOutlined";
import SearchOutlined from "@mui/icons-material/SearchOutlined";
import Tag from "@mui/icons-material/Tag";
import Box from "@mui/material/Box";
import IconButton from "@mui/material/IconButton";
import Link from "@mui/material/Link";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import { useState } from "react";

import type { AlertSummary } from "../../api/types";
import { visuallyHidden } from "../../lib/a11y";
import { channelLabel } from "../../lib/channels";
import { formatCount, formatDateTime, formatRelative, plural } from "../../lib/format";
import { useCompact } from "../../lib/responsive";
import { figures } from "../../theme";
import { ActionSheet, type SheetAction } from "../common/Sheet";
import { SearchCard, SearchCards } from "./SearchCard";
import { SearchUnread } from "./SearchUnread";

interface Props {
  alerts: AlertSummary[];
  /** Whether you may unregister the search: you need Manage Channels in its channel. */
  canChange: (alert: AlertSummary) => boolean;
  showChannel?: boolean;
  onOpen: (alert: AlertSummary) => void;
  onOpenChannel?: (channelId: string) => void;
  /** Leave out to list searches without an Unregister button. */
  onUnregister?: (alert: AlertSummary) => void;
}

// Columns a phone leaves out, so the search's name and count stay readable.
const WIDE = { display: { xs: "none", md: "table-cell" } } as const;

/** Searches as /alerts and /allalerts list them, with their counts and a way to unregister. */
export function SearchList({ alerts, canChange, showChannel = false, onOpen, onOpenChannel, onUnregister }: Props) {
  const compact = useCompact();
  // The search stays while the sheet slides away, so its title does not go blank.
  const [menu, setMenu] = useState<{ alert: AlertSummary; open: boolean } | null>(null);

  if (compact) {
    const picked = menu?.alert;
    const actions: SheetAction[] = picked ? [
      { label: "Open the search", icon: <SearchOutlined />, onSelect: () => onOpen(picked) },
      ...(onOpenChannel ? [{ label: `Open ${channelLabel(picked.channel_id, picked.channel_name)}`, icon: <Tag />,
        onSelect: () => onOpenChannel(picked.channel_id) }] : []),
      ...(onUnregister ? [{ label: "Unregister", icon: <DeleteOutlined />, onSelect: () => onUnregister(picked),
        disabled: !canChange(picked) }] : []),
    ] : [];
    return (
      <>
        <SearchCards label="Searches">
          {alerts.map((alert) => {
            const changeable = canChange(alert);
            return (
              <SearchCard key={alert.id} name={alert.search_query} onOpen={() => onOpen(alert)}
                onMenu={() => setMenu({ alert, open: true })}
                end={onUnregister && changeable && (
                  <IconButton aria-label={`Unregister ${alert.search_query}`} onClick={() => onUnregister(alert)}>
                    <DeleteOutlined />
                  </IconButton>
                )}>
                <Typography variant="body2" color="textSecondary" sx={{ ...figures, mt: 0.25 }}>
                  {showChannel && `${channelLabel(alert.channel_id, alert.channel_name)} · `}
                  {plural(alert.listing_count, "listing")}
                  <SearchUnread alertId={alert.id} />
                  {alert.review_count > 0 && (
                    <> · <Box component="span" sx={{ color: "warning.main" }}>{formatCount(alert.review_count)} need review</Box></>
                  )}
                </Typography>
                <Typography variant="caption" component="p" color="textSecondary">
                  {alert.last_seen_at ? `Last seen ${formatRelative(alert.last_seen_at)}` : "Not seen yet"}
                  {` · ${alert.active_version_id ? "Published rules" : "Discord filters only"}`}
                </Typography>
                {onUnregister && !changeable && (
                  <Typography variant="caption" component="p" color="textSecondary" sx={{ mt: 0.5 }}>
                    You need Manage Channels in its channel to unregister it.
                  </Typography>
                )}
              </SearchCard>
            );
          })}
        </SearchCards>
        <ActionSheet open={menu?.open ?? false} onClose={() => setMenu((current) => current && { ...current, open: false })}
          title={picked?.search_query ?? ""} actions={actions}>
          {picked && (
            <Typography variant="body2" color="textSecondary" sx={figures}>
              {channelLabel(picked.channel_id, picked.channel_name)} · {plural(picked.listing_count, "listing")}
            </Typography>
          )}
          {picked && onUnregister && !canChange(picked) && (
            <Typography variant="caption" component="p" color="textSecondary" sx={{ mt: 0.5 }}>
              You need Manage Channels in its channel to unregister it.
            </Typography>
          )}
        </ActionSheet>
      </>
    );
  }

  return (
    <Box sx={{ overflowX: "auto" }}>
      <Table size="small" aria-label="Searches">
        <TableHead>
          <TableRow>
            <TableCell>Search</TableCell>
            {showChannel && <TableCell>Channel</TableCell>}
            <TableCell align="right">Listings</TableCell>
            <TableCell align="right" sx={WIDE}>Need review</TableCell>
            <TableCell sx={WIDE}>Last seen</TableCell>
            <TableCell sx={WIDE}>Rules</TableCell>
            {onUnregister && <TableCell padding="checkbox"><Box component="span" sx={visuallyHidden}>Actions</Box></TableCell>}
          </TableRow>
        </TableHead>
        <TableBody>
          {alerts.map((alert) => (
            <TableRow key={alert.id} hover>
              <TableCell sx={{ maxWidth: 320 }}>
                <Link component="button" onClick={() => onOpen(alert)} sx={{ fontWeight: 600, textAlign: "left", color: "text.primary" }}>
                  {alert.search_query}
                </Link>
                <SearchUnread alertId={alert.id} />
              </TableCell>
              {showChannel && (
                <TableCell>
                  {onOpenChannel ? (
                    <Link component="button" onClick={() => onOpenChannel(alert.channel_id)} color="inherit">
                      {channelLabel(alert.channel_id, alert.channel_name)}
                    </Link>
                  ) : channelLabel(alert.channel_id, alert.channel_name)}
                </TableCell>
              )}
              <TableCell align="right" sx={figures}>{formatCount(alert.listing_count)}</TableCell>
              <TableCell align="right" sx={{ ...figures, ...WIDE, color: alert.review_count ? "warning.main" : undefined }}>
                {formatCount(alert.review_count)}
              </TableCell>
              <TableCell sx={WIDE}>
                {alert.last_seen_at ? (
                  <Tooltip title={formatDateTime(alert.last_seen_at)}><span>{formatRelative(alert.last_seen_at)}</span></Tooltip>
                ) : <Typography variant="body2" color="textSecondary">Not yet</Typography>}
              </TableCell>
              <TableCell sx={WIDE}>{alert.active_version_id ? "Published" : <Typography variant="body2" color="textSecondary">Discord filters only</Typography>}</TableCell>
              {onUnregister && (
                <TableCell padding="checkbox">
                  <Tooltip title={canChange(alert) ? "Unregister" : "You need Manage Channels in this channel to unregister it"}>
                    <span>
                      <IconButton size="small" aria-label={`Unregister ${alert.search_query}`} disabled={!canChange(alert)}
                        onClick={() => onUnregister(alert)}>
                        <DeleteOutlined fontSize="small" />
                      </IconButton>
                    </span>
                  </Tooltip>
                </TableCell>
              )}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Box>
  );
}
