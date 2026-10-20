import Box from "@mui/material/Box";
import Link from "@mui/material/Link";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TablePagination from "@mui/material/TablePagination";
import TableRow from "@mui/material/TableRow";
import Typography from "@mui/material/Typography";
import { useRef } from "react";

import type { Decision, ReplayCandidate, ReplayItem } from "../../api/types";
import { formatCount, formatDateTime, formatPrice, safeUrl } from "../../lib/format";
import { usePhone } from "../../lib/responsive";
import { CHANGES, VERDICTS, sourceName } from "../../lib/vocabulary";
import { figures } from "../../theme";
import { DecisionButton } from "../common/Decision";
import { ListingImage } from "../common/ListingImage";

const PER_PAGE = 50;
// Decisions and their headings stay on one line, so "Needs review" never breaks in two.
const oneLine = { whiteSpace: "nowrap" } as const;

interface Column {
  /** The name on a phone, where the three decisions share one row. */
  short: string;
  /** The full name, which the reasons show. */
  label: string;
  decision: Decision;
}

function columns(item: ReplayItem): [Column, Column, Column] {
  return [
    { short: "Recorded", label: `Recorded ${formatDateTime(item.candidate.observed_at)}`, decision: item.original_decision },
    { short: "Published", label: "Published rules", decision: item.active_decision },
    { short: "Draft", label: "Your draft", decision: item.draft_decision },
  ];
}

/** "Newly filtered, was allowed", or nothing when the draft decides the same as the published rules. */
function changeText(item: ReplayItem): string | null {
  if (item.change === "unchanged") return null;
  return `${CHANGES[item.change]}, was ${VERDICTS[item.active_decision.verdict].toLowerCase()}`;
}

function Listing({ candidate }: { candidate: ReplayCandidate }) {
  const url = safeUrl(candidate.url);
  const title = candidate.title || "Untitled listing";
  return (
    <Stack direction="row" spacing={1.5}>
      {/* The photo opens the listing too, a bigger target for a finger than a line of title. Keyboards and
          screen readers use the title's link. */}
      {url ? (
        <Box component="a" href={url} target="_blank" rel="noopener noreferrer" tabIndex={-1} aria-hidden="true"
          sx={{ display: "flex", flex: "none" }}>
          <ListingImage src={candidate.image_url} size={56} />
        </Box>
      ) : <ListingImage src={candidate.image_url} size={56} />}
      <Box sx={{ minWidth: 0 }}>
        <Typography variant="body2" sx={{ fontWeight: 500, overflowWrap: "anywhere" }}>
          {url ? <Link href={url} target="_blank" rel="noopener noreferrer">{title}</Link> : title}
        </Typography>
        <Typography variant="caption" color="textSecondary" sx={figures}>
          {sourceName(candidate.source)} {formatPrice(candidate.price)}
        </Typography>
      </Box>
    </Stack>
  );
}

function Row({ item }: { item: ReplayItem }) {
  const [recorded, published, draft] = columns(item);
  const change = changeText(item);
  return (
    <TableRow hover sx={{ "& td": { verticalAlign: "top" } }}>
      <TableCell sx={{ minWidth: 280 }}><Listing candidate={item.candidate} /></TableCell>
      <TableCell sx={oneLine}><DecisionButton decision={recorded.decision} label={recorded.label} /></TableCell>
      <TableCell sx={oneLine}><DecisionButton decision={published.decision} label={published.label} /></TableCell>
      <TableCell sx={oneLine}>
        <DecisionButton decision={draft.decision} label={draft.label} />
        {change && <Typography variant="caption" color="textSecondary" component="p">{change}</Typography>}
      </TableCell>
    </TableRow>
  );
}

/** One listing on a phone: the listing on top, then its three decisions side by side. */
function Card({ item }: { item: ReplayItem }) {
  const change = changeText(item);
  return (
    <Box component="li" sx={{ px: 1.5, py: 1.25, borderBottom: 1, borderColor: "divider", "&:last-of-type": { borderBottom: 0 } }}>
      <Listing candidate={item.candidate} />
      <Box sx={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", columnGap: 1, mt: 0.75 }}>
        {columns(item).map((column) => (
          // The short name is for the eye; the decision's button says the full name to screen readers.
          <Box key={column.short} sx={{ minWidth: 0, display: "flex", flexDirection: "column", alignItems: "flex-start" }}>
            <Typography variant="caption" color="textSecondary" aria-hidden="true">{column.short}</Typography>
            <DecisionButton decision={column.decision} label={column.label} />
          </Box>
        ))}
      </Box>
      {change && <Typography variant="caption" color="textSecondary" component="p" sx={{ mt: 0.5 }}>{change}</Typography>}
    </Box>
  );
}

interface Props {
  items: ReplayItem[];
  page: number;
  onPage: (page: number) => void;
}

/** The replayed listings of one view: a table on larger screens, a card for each listing on phones. */
export function ReplayResults({ items, page, onPage }: Props) {
  const phone = usePhone();
  const top = useRef<HTMLDivElement>(null);
  const shown = items.slice(page * PER_PAGE, (page + 1) * PER_PAGE);

  const changePage = (next: number) => {
    onPage(next);
    // The page buttons are under the list, so scroll back up to where the new page starts.
    const node = top.current;
    if (node && node.getBoundingClientRect().top < 0) node.scrollIntoView({ block: "start" });
  };

  return (
    <Box ref={top} sx={{ border: 1, borderColor: "divider", borderRadius: 1, bgcolor: "background.paper", scrollMarginTop: 120 }}>
      {phone ? (
        <Box component="ul" aria-label="Replay results" sx={{ listStyle: "none", m: 0, p: 0 }}>
          {shown.map((item) => <Card key={item.candidate.id} item={item} />)}
        </Box>
      ) : (
        <TableContainer>
          <Table size="small" aria-label="Replay results">
            <TableHead>
              <TableRow>
                <TableCell>Listing</TableCell>
                <TableCell sx={oneLine}>Recorded then</TableCell>
                <TableCell sx={oneLine}>Published rules</TableCell>
                <TableCell sx={oneLine}>Your draft</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {shown.map((item) => <Row key={item.candidate.id} item={item} />)}
            </TableBody>
          </Table>
        </TableContainer>
      )}
      <TablePagination component="div" count={items.length} page={page} rowsPerPage={PER_PAGE}
        rowsPerPageOptions={[PER_PAGE]} onPageChange={(_, next) => changePage(next)}
        labelDisplayedRows={({ from, to, count }) => `${formatCount(from)} to ${formatCount(to)} of ${formatCount(count)}`}
        sx={phone ? { borderTop: 1, borderColor: "divider" } : undefined} />
    </Box>
  );
}
