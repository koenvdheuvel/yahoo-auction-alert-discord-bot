import ArrowDownward from "@mui/icons-material/ArrowDownward";
import ArrowUpward from "@mui/icons-material/ArrowUpward";
import DeleteOutlined from "@mui/icons-material/DeleteOutlined";
import SearchOutlined from "@mui/icons-material/SearchOutlined";
import Tag from "@mui/icons-material/Tag";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import IconButton from "@mui/material/IconButton";
import Link from "@mui/material/Link";
import MenuItem from "@mui/material/MenuItem";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TablePagination from "@mui/material/TablePagination";
import TableRow from "@mui/material/TableRow";
import TableSortLabel from "@mui/material/TableSortLabel";
import TextField from "@mui/material/TextField";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import { useContext, useMemo, useRef, useState } from "react";

import type { AlertSummary } from "../../api/types";
import { visuallyHidden } from "../../lib/a11y";
import { channelLabel } from "../../lib/channels";
import { formatCount, formatDateTime, formatRelative, plural } from "../../lib/format";
import { SEARCH_FILTERS, type SearchFilter } from "../../lib/hooks";
import { useCompact, usePhone } from "../../lib/responsive";
import {
  filterRows, LIVE_FILTERS, matchesFilter, SEARCH_FILTER_NAMES, sortRows,
  type Direction, type InventoryRow, type SortKey,
} from "../../lib/searchInventory";
import { SearchUnreadContext } from "../../lib/unreadCounts";
import { figures } from "../../theme";
import { ActionSheet, type SheetAction } from "../common/Sheet";
import { backlogText, oldestText, type LiveStatus } from "./liveStatus";
import { CheckLines, CheckSummary } from "./SearchChecks";
import { SearchCard, SearchCards } from "./SearchCard";
import { SearchUnread } from "./SearchUnread";

interface Props {
  alerts: AlertSummary[];
  /** Whether you may unregister the search: you need Manage Channels in its channel. */
  canChange: (alert: AlertSummary) => boolean;
  /** Adds the channel column and the channel filter, for lists that span channels. */
  showChannel?: boolean;
  /** The bot's checks and queues; leave out where they are not known, so no column pretends they are zero. */
  live?: LiveStatus;
  /** The quick filter, when the page keeps it in its address. Without `onFilterChange` the list keeps it itself. */
  filter?: SearchFilter | null;
  onFilterChange?: (filter: SearchFilter | null) => void;
  onOpen: (alert: AlertSummary) => void;
  onOpenChannel?: (channelId: string) => void;
  /** Leave out to list searches without an Unregister button. */
  onUnregister?: (alert: AlertSummary) => void;
}

interface Column {
  key: SortKey;
  label: string;
  /** Numbers and times start with the biggest or newest; names start from A. */
  first: Direction;
  align?: "right";
}

// The order of the table's columns. The channel column needs a list across channels; the last three need live status.
const COLUMNS: Column[] = [
  { key: "search", label: "Search", first: "asc" },
  { key: "channel", label: "Channel", first: "asc" },
  { key: "listings", label: "Listings", first: "desc", align: "right" },
  { key: "unread", label: "Unread", first: "desc", align: "right" },
  { key: "review", label: "Needs review", first: "desc", align: "right" },
  { key: "seen", label: "Last listing seen", first: "desc" },
  { key: "rules", label: "Rules", first: "desc" },
  { key: "checked", label: "Last checks", first: "desc" },
  { key: "waiting", label: "Pending deliveries", first: "desc", align: "right" },
  { key: "failed", label: "Failed deliveries", first: "desc", align: "right" },
];
const LIVE_COLUMNS: SortKey[] = ["checked", "waiting", "failed"];

const SIZES = [10, 25, 50, 100] as const;
const ALL_CHANNELS = "all";

/** Why a filter cannot be answered yet, or null when the list can say which searches match it. */
function unanswerable(filter: SearchFilter, live: LiveStatus | undefined): string | null {
  if (!LIVE_FILTERS.includes(filter) || !live) return null;
  if (live.kind === "loading") return "Loading the live status…";
  if (live.kind === "unavailable") {
    return `The live status could not be loaded, so searches with ${SEARCH_FILTER_NAMES[filter].toLowerCase()} cannot be listed yet. It retries on its own.`;
  }
  return filter === "errors" && !live.botRunning ? "The bot does not run with this dashboard, so check errors are not known here." : null;
}

/** A count that is not there yet or could not be had; never a zero. */
function Unknown({ live, thing }: { live: LiveStatus | undefined; thing: string }) {
  const label = live?.kind === "loading" ? `Loading ${thing}` : live?.kind === "unavailable" ? `Could not load ${thing}` : `Not known yet: ${thing}`;
  return (
    <Box component="span" role="img" aria-label={label} title={label} sx={{ color: "text.secondary" }}>
      {live?.kind === "loading" ? "…" : "?"}
    </Box>
  );
}

/** The channel a search is in, as a link when the page can open it. */
function ChannelName({ alert, onOpenChannel }: { alert: AlertSummary; onOpenChannel: Props["onOpenChannel"] }) {
  const label = channelLabel(alert.channel_id, alert.channel_name);
  return onOpenChannel
    ? <Link component="button" onClick={() => onOpenChannel(alert.channel_id)} color="inherit" sx={{ textAlign: "left" }}>{label}</Link>
    : <>{label}</>;
}

interface Layout {
  columns: Column[];
  live: LiveStatus | undefined;
  canChange: Props["canChange"];
  onOpen: Props["onOpen"];
  onOpenChannel: Props["onOpenChannel"];
  onUnregister: Props["onUnregister"];
}

function UnregisterButton({ alert, layout }: { alert: AlertSummary; layout: Layout }) {
  const allowed = layout.canChange(alert);
  return (
    <Tooltip title={allowed ? "Unregister" : "You need Manage Channels in this channel to unregister it"}>
      <span>
        <IconButton size="small" aria-label={`Unregister ${alert.search_query}`} disabled={!allowed} onClick={() => layout.onUnregister?.(alert)}>
          <DeleteOutlined fontSize="small" />
        </IconButton>
      </span>
    </Tooltip>
  );
}

function SearchCell({ row, column, layout }: { row: InventoryRow; column: Column; layout: Layout }) {
  const { alert, status, unread } = row;
  const { live } = layout;
  switch (column.key) {
    case "search":
      return (
        <TableCell sx={{ minWidth: 160, maxWidth: 320 }}>
          <Link component="button" onClick={() => layout.onOpen(alert)} sx={{ fontWeight: 600, textAlign: "left", color: "text.primary" }}>
            {alert.search_query}
          </Link>
        </TableCell>
      );
    case "channel":
      return <TableCell><ChannelName alert={alert} onOpenChannel={layout.onOpenChannel} /></TableCell>;
    case "listings":
      return <TableCell align="right" sx={figures}>{formatCount(alert.listing_count)}</TableCell>;
    case "unread":
      // Nothing unread has no state; the pill shows a count, or says that the count is on its way or failed.
      return (
        <TableCell align="right" sx={figures}>
          {unread === null ? <Typography variant="body2" component="span" color="textSecondary">0</Typography> : <SearchUnread alertId={alert.id} />}
        </TableCell>
      );
    case "review":
      return <TableCell align="right" sx={{ ...figures, color: alert.review_count ? "warning.main" : undefined }}>{formatCount(alert.review_count)}</TableCell>;
    case "seen":
      return (
        <TableCell>
          {alert.last_seen_at
            ? <Tooltip title={formatDateTime(alert.last_seen_at)}><span>{formatRelative(alert.last_seen_at)}</span></Tooltip>
            : <Typography variant="body2" color="textSecondary">Not yet</Typography>}
        </TableCell>
      );
    case "rules":
      return <TableCell>{alert.active_version_id ? "Published" : <Typography variant="body2" color="textSecondary">Discord filters only</Typography>}</TableCell>;
    case "checked":
      return (
        <TableCell>
          {!status ? <Unknown live={live} thing="last checks" /> : <CheckSummary checks={status.checks} />}
        </TableCell>
      );
    case "waiting": {
      const oldest = status ? oldestText(status) : null;
      return (
        <TableCell align="right" sx={figures}>
          {status ? formatCount(status.backlog.pending) : <Unknown live={live} thing="pending deliveries" />}
          {oldest && <Typography variant="caption" component="p" color="textSecondary">{oldest}</Typography>}
        </TableCell>
      );
    }
    case "failed":
      return (
        <TableCell align="right" sx={{ ...figures, color: status?.backlog.failed ? "error.main" : undefined }}>
          {status ? formatCount(status.backlog.failed) : <Unknown live={live} thing="failed deliveries" />}
        </TableCell>
      );
  }
}

interface ViewProps {
  rows: InventoryRow[];
  layout: Layout;
  order: { key: SortKey; direction: Direction };
  onSort: (key: SortKey) => void;
}

function SearchTable({ rows, layout, order, onSort }: ViewProps) {
  return (
    <Box sx={{ position: "relative", overflowX: "auto" }}>
      <Table size="small" aria-label="Searches"
        sx={{ "& .MuiTableCell-root": { px: 1 }, "& .MuiTableCell-paddingCheckbox": { px: 0.5 } }}>
        <TableHead>
          <TableRow>
            {layout.columns.map((column) => {
              const active = order.key === column.key;
              return (
                <TableCell key={column.key} align={column.align} sortDirection={active ? order.direction : false}>
                  <TableSortLabel active={active} direction={active ? order.direction : column.first} onClick={() => onSort(column.key)}>
                    {column.label}
                  </TableSortLabel>
                </TableCell>
              );
            })}
            {layout.onUnregister && <TableCell padding="checkbox"><Box component="span" sx={visuallyHidden}>Actions</Box></TableCell>}
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.alert.id} hover>
              {layout.columns.map((column) => <SearchCell key={column.key} row={row} column={column} layout={layout} />)}
              {layout.onUnregister && <TableCell padding="checkbox"><UnregisterButton alert={row.alert} layout={layout} /></TableCell>}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Box>
  );
}

const NEED_MANAGE = "You need Manage Channels in its channel to unregister it.";

/** On phones and tablets each search is a card that opens it; a long press also offers its channel and Unregister. */
function SearchCardList({ rows, layout, showChannel }: { rows: InventoryRow[]; layout: Layout; showChannel: boolean }) {
  const { live, onOpen, onOpenChannel, onUnregister, canChange } = layout;
  // The search stays while the sheet slides away, so its title does not go blank.
  const [menu, setMenu] = useState<{ alert: AlertSummary; open: boolean } | null>(null);
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
        {rows.map(({ alert, status, unread }) => {
          const changeable = canChange(alert);
          const backlog = status ? backlogText(status) : null;
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
                <Box component="span" sx={{ whiteSpace: "nowrap" }}>{plural(alert.listing_count, "listing")}</Box>
                {unread !== null && (
                  <Box component="span" sx={{ whiteSpace: "nowrap" }}> · Unread<SearchUnread alertId={alert.id} /></Box>
                )}
                {alert.review_count > 0 && (
                  <Box component="span" sx={{ color: "warning.main", whiteSpace: "nowrap" }}> · {formatCount(alert.review_count)} need review</Box>
                )}
              </Typography>
              <Typography variant="caption" component="p" color="textSecondary">
                {alert.last_seen_at ? `Last listing seen ${formatRelative(alert.last_seen_at)}` : "No listing seen yet"}
                {` · ${alert.active_version_id ? "Published rules" : "Discord filters only"}`}
              </Typography>
              {live && (status ? <CheckLines checks={status.checks} /> : (
                <Typography variant="body2" color="textSecondary" sx={{ mt: 0.5 }}>
                  {live.kind === "loading" ? "Loading checks…" : live.kind === "unavailable" ? "Checks could not be loaded" : "Not in the live status yet"}
                </Typography>
              ))}
              {backlog && (
                <Typography variant="body2" sx={{ mt: 0.5, color: status?.backlog.failed ? "error.main" : "text.primary", ...figures }}>
                  Posts and DMs: {backlog}
                </Typography>
              )}
              {onUnregister && !changeable && (
                <Typography variant="caption" component="p" color="textSecondary" sx={{ mt: 0.5 }}>{NEED_MANAGE}</Typography>
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
          <Typography variant="caption" component="p" color="textSecondary" sx={{ mt: 0.5 }}>{NEED_MANAGE}</Typography>
        )}
      </ActionSheet>
    </>
  );
}

/**
 * Every search of a server or channel in one place: filter it by words, channel and quick filters, sort it, and open
 * or unregister what you find. The server's Searches page, a channel's searches and the all-servers page all use it.
 */
export function SearchList({
  alerts, canChange, showChannel = false, live, filter: controlled, onFilterChange, onOpen, onOpenChannel, onUnregister,
}: Props) {
  const compact = useCompact();
  const phone = usePhone();
  const unreadStates = useContext(SearchUnreadContext);
  const top = useRef<HTMLDivElement>(null);
  const [text, setText] = useState("");
  const [channel, setChannel] = useState(ALL_CHANNELS);
  const [ownFilter, setOwnFilter] = useState<SearchFilter | null>(null);
  const [order, setOrder] = useState<{ key: SortKey; direction: Direction }>({ key: showChannel ? "channel" : "search", direction: "asc" });
  const [pageIndex, setPageIndex] = useState(0);
  const [pageSize, setPageSize] = useState(25);

  const filters = SEARCH_FILTERS.filter((name) => live || !LIVE_FILTERS.includes(name));
  const requested = onFilterChange ? controlled ?? null : ownFilter;
  // Without live status there is no such filter, so an address that asks for one shows every search.
  const quick = requested && filters.includes(requested) ? requested : null;
  // The filter can change from outside, such as the back button; its results start on the first page.
  const [seenQuick, setSeenQuick] = useState(quick);
  if (seenQuick !== quick) {
    setSeenQuick(quick);
    setPageIndex(0);
  }

  const columns = COLUMNS.filter((column) => (showChannel || column.key !== "channel") && (live || !LIVE_COLUMNS.includes(column.key)));
  const rows = useMemo((): InventoryRow[] => alerts.map((alert) => ({
    alert,
    status: live?.kind === "ready" ? live.searches.get(alert.id) ?? null : null,
    unread: unreadStates.get(alert.id) ?? null,
  })), [alerts, live, unreadStates]);
  const channels = useMemo(() => {
    const labels = new Map<string, string>();
    for (const alert of alerts) labels.set(alert.channel_id, channelLabel(alert.channel_id, alert.channel_name));
    return [...labels].sort((a, b) => a[1].localeCompare(b[1], undefined, { numeric: true }));
  }, [alerts]);
  // A channel whose last search is gone cannot keep filtering.
  const channelId = channel !== ALL_CHANNELS && channels.some(([id]) => id === channel) ? channel : null;

  const blocked = quick ? unanswerable(quick, live) : null;
  const counts = useMemo(() => {
    const found: Partial<Record<SearchFilter, number>> = {};
    for (const name of SEARCH_FILTERS) {
      if (unanswerable(name, live) === null) found[name] = rows.filter((row) => matchesFilter(row, name)).length;
    }
    return found;
  }, [rows, live]);
  const unknownUnread = rows.filter((row) => row.unread !== null && row.unread.kind !== "count");
  const matching = useMemo(() => filterRows(rows, { text, channelId, quick }), [rows, text, channelId, quick]);
  const sorted = useMemo(() => sortRows(matching, order.key, order.direction), [matching, order]);
  // The list can shrink while a later page is open; show the last page that still exists.
  const page = Math.min(pageIndex, Math.max(0, Math.ceil(sorted.length / pageSize) - 1));
  if (page !== pageIndex) setPageIndex(page);
  const shown = sorted.slice(page * pageSize, (page + 1) * pageSize);
  const filtering = text.trim() !== "" || channelId !== null || quick !== null;

  const setQuick = (next: SearchFilter | null) => {
    if (onFilterChange) onFilterChange(next);
    else setOwnFilter(next);
    setPageIndex(0);
  };
  const clear = () => {
    setText("");
    setChannel(ALL_CHANNELS);
    setQuick(null);
  };
  const sortBy = (key: SortKey) => {
    const first = COLUMNS.find((column) => column.key === key)!.first;
    setOrder((current) => ({ key, direction: current.key === key ? (current.direction === "asc" ? "desc" : "asc") : first }));
    setPageIndex(0);
  };
  const pick = (key: SortKey) => {
    setOrder((current) => current.key === key ? current : { key, direction: COLUMNS.find((column) => column.key === key)!.first });
    setPageIndex(0);
  };
  const flip = () => {
    setOrder((current) => ({ ...current, direction: current.direction === "asc" ? "desc" : "asc" }));
    setPageIndex(0);
  };
  const changePage = (next: number) => {
    setPageIndex(next);
    // The page buttons are under the list, so scroll back up to where the new page starts.
    const node = top.current;
    if (node && node.getBoundingClientRect().top < 0) node.scrollIntoView({ block: "start" });
  };

  const layout: Layout = { columns, live, canChange, onOpen, onOpenChannel, onUnregister };
  const ascending = order.direction === "asc";
  return (
    <Box ref={top} sx={{ scrollMarginTop: 120 }}>
      <Box sx={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 1, mb: 1 }}>
        <TextField size="small" type="search" label={showChannel ? "Filter by name or channel" : "Filter by name"} value={text}
          onChange={(event) => { setText(event.target.value); setPageIndex(0); }} sx={{ flex: "1 1 220px", minWidth: 0 }} />
        {showChannel && channels.length > 1 && (
          <TextField select size="small" label="Channel" value={channelId ?? ALL_CHANNELS}
            onChange={(event) => { setChannel(event.target.value); setPageIndex(0); }}
            slotProps={{ select: { native: phone } }} sx={{ flex: "1 1 160px", minWidth: 0 }}>
            {phone ? <option value={ALL_CHANNELS}>All channels</option> : <MenuItem value={ALL_CHANNELS}>All channels</MenuItem>}
            {channels.map(([id, label]) => phone
              ? <option key={id} value={id}>{label}</option>
              : <MenuItem key={id} value={id}>{label}</MenuItem>)}
          </TextField>
        )}
        {compact && (
          <Box sx={{ display: "flex", alignItems: "center", gap: 1, flex: "1 1 160px", minWidth: 0 }}>
            {/* On phones a select opens the phone's own picker instead of a menu that floats over the page. */}
            <TextField select size="small" label="Sort by" value={order.key} onChange={(event) => pick(event.target.value as SortKey)}
              slotProps={{ select: { native: phone } }} sx={{ flex: 1, minWidth: 0 }}>
              {columns.map((column) => phone
                ? <option key={column.key} value={column.key}>{column.label}</option>
                : <MenuItem key={column.key} value={column.key}>{column.label}</MenuItem>)}
            </TextField>
            <IconButton onClick={flip} aria-label={ascending ? "Ascending, switch to descending" : "Descending, switch to ascending"}
              sx={{ flexShrink: 0, border: 1, borderColor: "divider", borderRadius: 1 }}>
              {ascending ? <ArrowUpward fontSize="small" /> : <ArrowDownward fontSize="small" />}
            </IconButton>
          </Box>
        )}
      </Box>
      <Typography variant="caption" component="p" color="textSecondary" sx={{ mb: 0.75 }}>
        Filters count searches. Unread counts new or changed saved listings for your account in this browser;
        review is a rule decision. Opening unfiltered Listings marks a search read.
      </Typography>
      <Box role="group" aria-label="Quick filters" sx={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 0.75, mb: 1 }}>
        {filters.map((name) => {
          const active = quick === name;
          const count = counts[name];
          return (
            <Chip key={name} clickable aria-pressed={active} color={active ? "primary" : "default"} variant={active ? "filled" : "outlined"}
              label={count === undefined ? SEARCH_FILTER_NAMES[name] : `${SEARCH_FILTER_NAMES[name]} ${formatCount(count)}`}
              onClick={() => setQuick(active ? null : name)} />
          );
        })}
        {filtering && <Button size="small" onClick={clear}>Clear filters</Button>}
      </Box>
      <Box sx={{ mb: 1 }}>
        {live?.kind === "unavailable" && (
          <Typography variant="caption" component="p" color="textSecondary">
            Last checks and queued posts could not be loaded. They are tried again on their own.
          </Typography>
        )}
        {live?.kind === "ready" && !live.botRunning && (
          <Typography variant="caption" component="p" color="textSecondary">
            The bot does not run with this dashboard, so last checks are not known here.
          </Typography>
        )}
        {unknownUnread.length > 0 && (
          <Typography variant="caption" component="p" color="textSecondary">
            {unknownUnread.some((row) => row.unread?.kind === "unavailable")
              ? `Unread counts could not be had for ${plural(unknownUnread.length, "search", "searches")}.`
              : `Counting unread listings for ${plural(unknownUnread.length, "search", "searches")}…`}
          </Typography>
        )}
        {filtering && !blocked && (
          <Typography variant="body2" color="textSecondary" role="status">
            {`Showing ${formatCount(sorted.length)} of ${plural(rows.length, "search", "searches")}`}
          </Typography>
        )}
      </Box>
      {blocked ? (
        <Typography variant="body2" color="textSecondary" role="status">{blocked}</Typography>
      ) : sorted.length === 0 ? (
        <Typography variant="body2" color="textSecondary" role="status">
          {filtering ? "No searches match these filters." : "No searches."}
        </Typography>
      ) : (
        <>
          {compact
            ? <SearchCardList rows={shown} layout={layout} showChannel={showChannel} />
            : <SearchTable rows={shown} layout={layout} order={order} onSort={sortBy} />}
          {sorted.length > SIZES[0] && (
            <TablePagination component="div" count={sorted.length} page={page} rowsPerPage={pageSize} rowsPerPageOptions={SIZES}
              onPageChange={(_, next) => changePage(next)}
              onRowsPerPageChange={(event) => { setPageSize(Number(event.target.value)); setPageIndex(0); }}
              labelRowsPerPage={compact ? "Rows:" : undefined}
              sx={compact ? { "& .MuiTablePagination-toolbar": { px: 0, flexWrap: "wrap" } } : undefined}
              labelDisplayedRows={({ from, to, count }) => `${formatCount(from)} to ${formatCount(to)} of ${formatCount(count)}`} />
          )}
        </>
      )}
    </Box>
  );
}
