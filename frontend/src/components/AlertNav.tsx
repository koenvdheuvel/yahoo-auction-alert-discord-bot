import Search from "@mui/icons-material/Search";
import Box from "@mui/material/Box";
import InputAdornment from "@mui/material/InputAdornment";
import List from "@mui/material/List";
import ListItemButton from "@mui/material/ListItemButton";
import ListSubheader from "@mui/material/ListSubheader";
import Skeleton from "@mui/material/Skeleton";
import TextField from "@mui/material/TextField";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import type { UseQueryResult } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import type { AlertSummary, AlertsResponse } from "../api/types";
import { formatCount } from "../lib/format";
import { channelName } from "../lib/vocabulary";
import { figures } from "../theme";
import { LoadError } from "./common/Feedback";

interface Props {
  alerts: UseQueryResult<AlertsResponse>;
  selectedId: string | null;
  onSelect: (alertId: string | null) => void;
}

function Count({ value, review }: { value: number; review?: number }) {
  return (
    <Box component="span" sx={{ display: "inline-flex", alignItems: "baseline", gap: 1, ml: "auto", pl: 1.5, ...figures }}>
      {review ? (
        <Tooltip title={`${formatCount(review)} need review`}>
          <Box component="span" sx={{ color: "warning.main", fontWeight: 650, fontSize: "0.75rem" }}>
            {formatCount(review)}
          </Box>
        </Tooltip>
      ) : null}
      <Box component="span" sx={{ color: "text.secondary", fontSize: "0.8125rem" }}>{formatCount(value)}</Box>
    </Box>
  );
}

export function AlertNav({ alerts, selectedId, onSelect }: Props) {
  const [filter, setFilter] = useState("");
  const channels = useMemo(() => {
    const needle = filter.trim().toLocaleLowerCase();
    const groups = new Map<string, AlertSummary[]>();
    for (const alert of alerts.data?.alerts ?? []) {
      const haystack = `${alert.search_query} ${alert.channel_name ?? ""} ${alert.channel_id}`.toLocaleLowerCase();
      if (needle && !haystack.includes(needle)) continue;
      const items = groups.get(alert.channel_id) ?? [];
      items.push(alert);
      groups.set(alert.channel_id, items);
    }
    return [...groups.values()]
      .map((items) => items.sort((left, right) => left.search_query.localeCompare(right.search_query)))
      .sort((left, right) => channelName(left[0]!).localeCompare(channelName(right[0]!)));
  }, [alerts.data, filter]);
  const total = alerts.data?.alerts.length ?? 0;

  return (
    <Box sx={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      <Box sx={{ px: 2, pt: 2, pb: 1.5 }}>
        <Typography variant="h3" component="h2" sx={{ mb: 1.25 }}>Searches</Typography>
        <TextField
          fullWidth
          placeholder="Find a search or channel"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          slotProps={{
            htmlInput: { "aria-label": "Find a search or channel" },
            input: { startAdornment: <InputAdornment position="start"><Search fontSize="small" /></InputAdornment> },
          }}
        />
      </Box>
      <List dense subheader={<li />} sx={{ flex: 1, overflowY: "auto", pt: 0, "& ul": { p: 0 } }}>
        <ListItemButton selected={selectedId === null} onClick={() => onSelect(null)} aria-current={selectedId === null ? "page" : undefined}
          sx={{ mx: 1, borderRadius: 1 }}>
          <Typography variant="body1" sx={{ fontWeight: 600 }}>All listings</Typography>
          {alerts.data && <Count value={alerts.data.totals.archived_count} />}
        </ListItemButton>
        {alerts.isPending && Array.from({ length: 5 }, (_, index) => (
          <Skeleton key={index} variant="text" sx={{ mx: 2, my: 1 }} />
        ))}
        {alerts.isError && (
          <Box sx={{ p: 2 }}><LoadError error={alerts.error} what="Searches" onRetry={() => void alerts.refetch()} /></Box>
        )}
        {alerts.isSuccess && total === 0 && (
          <Typography variant="body2" color="text.secondary" sx={{ p: 2 }}>
            No searches yet. Register one in Discord with /register; its listings appear here after the next check.
          </Typography>
        )}
        {alerts.isSuccess && total > 0 && channels.length === 0 && (
          <Typography variant="body2" color="text.secondary" sx={{ p: 2 }}>No search matches “{filter}”.</Typography>
        )}
        {channels.map((items) => (
          <li key={items[0]!.channel_id}>
            <ul>
              <ListSubheader title={`Discord channel ${items[0]!.channel_id}`} sx={{ bgcolor: "background.default",
                lineHeight: "32px", mt: 1, fontWeight: 600, color: "text.secondary", fontSize: "0.75rem" }}>
                {channelName(items[0]!)}
              </ListSubheader>
              {items.map((alert) => (
                <ListItemButton key={alert.id} selected={alert.id === selectedId} onClick={() => onSelect(alert.id)}
                  aria-current={alert.id === selectedId ? "page" : undefined} sx={{ mx: 1, borderRadius: 1, minHeight: 36 }}>
                  <Typography variant="body1" noWrap title={alert.search_query} sx={{ minWidth: 0 }}>
                    {alert.search_query}
                  </Typography>
                  <Count value={alert.listing_count} review={alert.review_count} />
                </ListItemButton>
              ))}
            </ul>
          </li>
        ))}
      </List>
    </Box>
  );
}
