import ArrowDownward from "@mui/icons-material/ArrowDownward";
import ArrowUpward from "@mui/icons-material/ArrowUpward";
import SearchOutlined from "@mui/icons-material/SearchOutlined";
import Tag from "@mui/icons-material/Tag";
import Box from "@mui/material/Box";
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
import { useMemo, useRef, useState } from "react";

import type { CheckResult, SearchStatus } from "../../api/types";
import { channelLabel } from "../../lib/channels";
import { formatCount, formatDateTime, formatRelative, plural } from "../../lib/format";
import { useCompact, usePhone } from "../../lib/responsive";
import { sourceName } from "../../lib/vocabulary";
import { figures } from "../../theme";
import { HelpTip } from "../common/HelpTip";
import { ActionSheet } from "../common/Sheet";
import { SearchCard, SearchCards } from "../searches/SearchCard";
import { SearchUnread } from "../searches/SearchUnread";

const HELP = "Each search in this server: the result of its last check on each marketplace (hover a chip for when, how long and why), "
  + "how many listings it has found, and how many of its posts and DMs are waiting or failed. "
  + "Select a column heading to sort by it. "
  + "Last checks are kept in memory, so they are empty for a while after the bot restarts.";

const fromSeconds = (value: number | null | undefined) => (value ? new Date(value * 1000).toISOString() : null);

const OUTCOMES = { success: ["OK", "success"], error: ["Error", "error"], timeout: ["Timed out", "warning"] } as const;

function chipLabel(check: CheckResult): string {
  return `${sourceName(check.source)} ${check.outcome === "success" ? "✓" : OUTCOMES[check.outcome][0]}`;
}

function CheckChip({ check }: { check: CheckResult }) {
  const [label, color] = OUTCOMES[check.outcome];
  const finished = fromSeconds(check.finished_at);
  const detail = [`${sourceName(check.source)}: ${label.toLowerCase()} ${formatRelative(finished)}`,
    `took ${check.duration_seconds.toFixed(1)} s`, check.error && `(${check.error})`].filter(Boolean).join(", ");
  return (
    <Tooltip title={`${detail}. Finished ${formatDateTime(finished)}.`}>
      <Chip variant="outlined" color={color} label={chipLabel(check)} sx={{ mr: 0.5, mb: 0.5 }} />
    </Tooltip>
  );
}

/** A card's last checks. What the desktop shows on hover is written out, since a finger cannot hover. */
function CheckLines({ checks }: { checks: CheckResult[] | null }) {
  if (checks === null) return null;
  if (checks.length === 0) {
    return <Typography variant="body2" color="textSecondary" sx={{ mt: 0.5 }}>Not checked since the bot started</Typography>;
  }
  const latest = fromSeconds(Math.max(...checks.map((check) => check.finished_at)));
  return (
    <Box sx={{ mt: 1 }}>
      <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5 }}>
        {checks.map((check) => (
          <Chip key={check.source} variant="outlined" color={OUTCOMES[check.outcome][1]} label={chipLabel(check)} />
        ))}
      </Box>
      {checks.filter((check) => check.outcome !== "success").map((check) => (
        <Typography key={check.source} variant="body2" sx={{ mt: 0.5, color: `${OUTCOMES[check.outcome][1]}.main`, overflowWrap: "anywhere" }}>
          {sourceName(check.source)}: {check.outcome === "timeout"
            ? `timed out after ${check.duration_seconds.toFixed(1)} s`
            : check.error ?? "the check failed"}
        </Typography>
      ))}
      <Typography variant="caption" component="p" color="textSecondary" sx={{ mt: 0.5 }}>Checked {formatRelative(latest)}</Typography>
    </Box>
  );
}

const oldestText = (search: SearchStatus) => {
  const oldest = search.backlog.oldest_pending_seconds;
  return oldest ? `oldest ${Math.round(oldest / 60)} min` : null;
};

function backlogText(search: SearchStatus): string | null {
  const { pending, failed } = search.backlog;
  if (!pending && !failed) return null;
  const oldest = oldestText(search);
  return [pending && `${formatCount(pending)} waiting`, failed && `${formatCount(failed)} failed`].filter(Boolean).join(", ")
    + (oldest ? `, ${oldest}` : "");
}

type SortKey = "search" | "channel" | "checked" | "listings" | "waiting" | "failed";
type Direction = "asc" | "desc";

interface Column {
  key: SortKey;
  label: string;
  /** Numbers and times start with the biggest or newest; names start from A. */
  first: Direction;
  align?: "right";
}

const COLUMNS: Column[] = [
  { key: "search", label: "Search", first: "asc" },
  { key: "channel", label: "Channel", first: "asc" },
  { key: "checked", label: "Last checks", first: "desc" },
  { key: "listings", label: "Listings", first: "desc", align: "right" },
  { key: "waiting", label: "Waiting", first: "desc", align: "right" },
  { key: "failed", label: "Failed", first: "desc", align: "right" },
];

const SIZES = [10, 25, 50, 100] as const;
const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

/** What a search is sorted by; null when it is unknown or has not run, which sorts last in either direction. */
function sortValue(search: SearchStatus, key: SortKey): string | number | null {
  switch (key) {
    case "search": return search.search_query;
    case "channel": return channelLabel(search.channel_id, search.channel_name);
    case "checked": {
      if (!search.checks?.length) return null;
      let latest = search.checks[0]!.finished_at;
      for (const check of search.checks) latest = Math.max(latest, check.finished_at);
      return latest;
    }
    case "listings": return search.listing_count;
    case "waiting": return search.backlog.pending;
    case "failed": return search.backlog.failed;
  }
}

/** The order of searches that are equal in the chosen column, so the list never shuffles between refreshes. */
function tieOrder(a: SearchStatus, b: SearchStatus): number {
  return collator.compare(a.search_query, b.search_query)
    || collator.compare(channelLabel(a.channel_id, a.channel_name), channelLabel(b.channel_id, b.channel_name))
    || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
}

function sortSearches(searches: SearchStatus[], key: SortKey, direction: Direction): SearchStatus[] {
  const sign = direction === "asc" ? 1 : -1;
  return [...searches].sort((a, b) => {
    const x = sortValue(a, key);
    const y = sortValue(b, key);
    if (x === null || y === null) {
      if (x !== y) return x === null ? 1 : -1;
    } else {
      const order = typeof x === "string" ? collator.compare(x, y as string) : x - (y as number);
      if (order) return order * sign;
    }
    return tieOrder(a, b);
  });
}

interface Props {
  searches: SearchStatus[];
  onOpenSearch: (alertId: string) => void;
  onOpenChannel: (channelId: string) => void;
}

interface CardsProps extends Props {
  sort: SortKey;
  direction: Direction;
  onSort: (key: SortKey) => void;
  onDirection: () => void;
}

/** On phones and tablets each search is a card that opens it; a long press also offers its channel. */
function SearchStatusCards({ searches, sort, direction, onSort, onDirection, onOpenSearch, onOpenChannel }: CardsProps) {
  const phone = usePhone();
  // The search stays while the sheet slides away, so its title does not go blank.
  const [menu, setMenu] = useState<{ search: SearchStatus; open: boolean } | null>(null);
  const picked = menu?.search;
  const ascending = direction === "asc";
  return (
    <>
      <Box sx={{ display: "flex", alignItems: "center", gap: 1, mb: 1 }}>
        {/* On phones a select opens the phone's own picker instead of a menu that floats over the page. */}
        <TextField select size="small" label="Sort by" value={sort} onChange={(event) => onSort(event.target.value as SortKey)}
          slotProps={{ select: { native: phone } }} sx={{ flex: 1, minWidth: 0 }}>
          {COLUMNS.map((column) => phone
            ? <option key={column.key} value={column.key}>{column.label}</option>
            : <MenuItem key={column.key} value={column.key}>{column.label}</MenuItem>)}
        </TextField>
        <IconButton onClick={onDirection} aria-label={ascending ? "Ascending, switch to descending" : "Descending, switch to ascending"}
          sx={{ border: 1, borderColor: "divider", borderRadius: 1 }}>
          {ascending ? <ArrowUpward fontSize="small" /> : <ArrowDownward fontSize="small" />}
        </IconButton>
      </Box>
      <SearchCards label="Search status">
        {searches.map((search) => {
          const backlog = backlogText(search);
          return (
            <SearchCard key={search.id} name={search.search_query} onOpen={() => onOpenSearch(search.id)}
              onMenu={() => setMenu({ search, open: true })}>
              <Typography variant="body2" color="textSecondary" sx={{ ...figures, mt: 0.25 }}>
                {channelLabel(search.channel_id, search.channel_name)} · {plural(search.listing_count, "listing")}
                <SearchUnread alert={search} />
              </Typography>
              <CheckLines checks={search.checks} />
              {backlog && (
                <Typography variant="body2" sx={{ mt: 0.5, color: search.backlog.failed ? "error.main" : "text.primary", ...figures }}>
                  Posts and DMs: {backlog}
                </Typography>
              )}
            </SearchCard>
          );
        })}
      </SearchCards>
      <ActionSheet open={menu?.open ?? false} onClose={() => setMenu((current) => current && { ...current, open: false })}
        title={picked?.search_query ?? ""} actions={picked ? [
          { label: "Open the search", icon: <SearchOutlined />, onSelect: () => onOpenSearch(picked.id) },
          { label: `Open ${channelLabel(picked.channel_id, picked.channel_name)}`, icon: <Tag />,
            onSelect: () => onOpenChannel(picked.channel_id) },
        ] : []} />
    </>
  );
}

/** Every search of the server: how its checks went and what waits to be posted, sortable and in pages. */
export function StatusSearches({ searches, onOpenSearch, onOpenChannel }: Props) {
  const compact = useCompact();
  const top = useRef<HTMLDivElement>(null);
  const [order, setOrder] = useState<{ key: SortKey; direction: Direction }>({ key: "search", direction: "asc" });
  const [pageIndex, setPageIndex] = useState(0);
  const [pageSize, setPageSize] = useState(25);
  const sorted = useMemo(() => sortSearches(searches, order.key, order.direction), [searches, order]);
  // The list can shrink while a later page is open; show the last page that still exists.
  const page = Math.min(pageIndex, Math.max(0, Math.ceil(sorted.length / pageSize) - 1));
  if (page !== pageIndex) setPageIndex(page);
  const shown = sorted.slice(page * pageSize, (page + 1) * pageSize);

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

  return (
    <Box ref={top} sx={{ scrollMarginTop: 120 }}>
      <Typography variant="h3" component="h2" sx={{ mb: 1 }}>
        Searches
        <HelpTip title="Searches" text={HELP} />
      </Typography>
      {searches.length === 0 ? (
        <Typography variant="body2" color="textSecondary">No searches in this server yet.</Typography>
      ) : (
        <>
          {compact ? (
            <SearchStatusCards searches={shown} sort={order.key} direction={order.direction} onSort={pick} onDirection={flip}
              onOpenSearch={onOpenSearch} onOpenChannel={onOpenChannel} />
          ) : (
            <Box sx={{ overflowX: "auto" }}>
              <Table size="small" aria-label="Search status">
                <TableHead>
                  <TableRow>
                    {COLUMNS.map((column) => {
                      const active = order.key === column.key;
                      return (
                        <TableCell key={column.key} align={column.align} sortDirection={active ? order.direction : false}>
                          <TableSortLabel active={active} direction={active ? order.direction : column.first}
                            onClick={() => sortBy(column.key)}>
                            {column.label}
                          </TableSortLabel>
                        </TableCell>
                      );
                    })}
                  </TableRow>
                </TableHead>
                <TableBody>
                  {shown.map((search) => {
                    const oldest = search.backlog.pending ? oldestText(search) : null;
                    return (
                      <TableRow key={search.id} hover>
                        <TableCell>
                          <Link component="button" onClick={() => onOpenSearch(search.id)} sx={{ fontWeight: 600, color: "text.primary" }}>
                            {search.search_query}
                          </Link>
                          <SearchUnread alert={search} />
                        </TableCell>
                        <TableCell>
                          <Link component="button" color="inherit" onClick={() => onOpenChannel(search.channel_id)}>
                            {channelLabel(search.channel_id, search.channel_name)}
                          </Link>
                        </TableCell>
                        <TableCell>
                          {search.checks === null ? <Typography variant="body2" color="textSecondary">Unknown here</Typography>
                            : search.checks.length === 0 ? <Typography variant="body2" color="textSecondary">Not checked since the bot started</Typography>
                              : search.checks.map((check) => <CheckChip key={check.source} check={check} />)}
                        </TableCell>
                        <TableCell align="right" sx={figures}>{formatCount(search.listing_count)}</TableCell>
                        <TableCell align="right" sx={figures}>
                          {formatCount(search.backlog.pending)}
                          {oldest && <Typography variant="caption" component="p" color="textSecondary">{oldest}</Typography>}
                        </TableCell>
                        <TableCell align="right" sx={{ ...figures, color: search.backlog.failed ? "error.main" : undefined }}>
                          {formatCount(search.backlog.failed)}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </Box>
          )}
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
