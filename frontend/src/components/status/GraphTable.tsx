import Box from "@mui/material/Box";
import Link from "@mui/material/Link";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Typography from "@mui/material/Typography";

import type { TablePanel } from "../../api/types";
import { failureTone, formatTableValue, friendlyLabel } from "../../lib/graphs";
import { figures } from "../../theme";

interface Props {
  panel: TablePanel;
  /** The channel of each search whose text another search has too, by alert ID. */
  channels: Record<string, string>;
  onOpenSearch: (alertId: string) => void;
}

/** A Grafana table: a search opens its page, outcomes are coloured, the number column lines up on the right. */
export function GraphTable({ panel, channels, onOpenSearch }: Props) {
  return (
    <Box sx={{ maxHeight: 320, overflow: "auto" }}>
      <Table size="small" stickyHeader aria-label={panel.title}>
        <TableHead>
          <TableRow>
            {panel.columns.map((column) => (
              <TableCell key={column.key} align={column.key === "value" ? "right" : "left"}>{column.title}</TableCell>
            ))}
          </TableRow>
        </TableHead>
        <TableBody>
          {panel.rows.map((row, index) => (
            <TableRow key={index} hover>
              {panel.columns.map((column) => {
                if (column.key === "value") {
                  return <TableCell key={column.key} align="right" sx={figures}>{formatTableValue(row.value, panel.decimals)}</TableCell>;
                }
                const raw = row.labels[column.key] ?? "";
                const alertId = row.labels.alert_id;
                if (column.key === "search_query" && alertId) {
                  const channel = channels[alertId];
                  return (
                    <TableCell key={column.key}>
                      <Link component="button" onClick={() => onOpenSearch(alertId)} sx={{ fontWeight: 600, color: "text.primary", textAlign: "left" }}>
                        {raw}
                      </Link>
                      {channel && <Typography component="span" variant="body2" color="text.secondary" sx={{ display: "block", whiteSpace: "nowrap" }}>{channel}</Typography>}
                    </TableCell>
                  );
                }
                const tone = column.key === "outcome" ? failureTone(raw) ?? (raw === "success" ? "success" : null) : null;
                return (
                  <TableCell key={column.key} sx={{ color: tone ? `${tone}.main` : undefined }}>
                    {friendlyLabel(column.key, raw)}
                  </TableCell>
                );
              })}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Box>
  );
}
