import DeleteOutlined from "@mui/icons-material/DeleteOutlined";
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

import type { AlertSummary } from "../../api/types";
import { visuallyHidden } from "../../lib/a11y";
import { channelLabel } from "../../lib/channels";
import { formatCount, formatDateTime, formatRelative } from "../../lib/format";
import { figures } from "../../theme";

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
