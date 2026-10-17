import GridViewOutlined from "@mui/icons-material/GridViewOutlined";
import Search from "@mui/icons-material/Search";
import ViewListOutlined from "@mui/icons-material/ViewListOutlined";
import Box from "@mui/material/Box";
import FormControlLabel from "@mui/material/FormControlLabel";
import InputAdornment from "@mui/material/InputAdornment";
import MenuItem from "@mui/material/MenuItem";
import { useTheme } from "@mui/material/styles";
import Switch from "@mui/material/Switch";
import TextField from "@mui/material/TextField";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Tooltip from "@mui/material/Tooltip";
import useMediaQuery from "@mui/material/useMediaQuery";
import type { RefObject } from "react";

import type { Facets, Source, Verdict } from "../../api/types";
import { formatCount } from "../../lib/format";
import { SOURCES, VERDICTS } from "../../lib/vocabulary";
import { figures } from "../../theme";
import type { ListingFilters } from "../views/SearchView";

export type View = "grid" | "list";

interface Props {
  filters: ListingFilters;
  onFilters: (next: ListingFilters) => void;
  facets: Facets | undefined;
  searchRef: RefObject<HTMLInputElement | null>;
}

// Show "All marketplaces" and "Any decision" in the field instead of an empty box under a floating label.
const selectSlots = { inputLabel: { shrink: true }, select: { displayEmpty: true } } as const;
// On phones the selects share each row evenly.
const selectFlex = { xs: "1 1 160px", sm: "0 1 auto" } as const;

function counted(name: string, value: number | undefined) {
  return value === undefined ? name : `${name} (${formatCount(value)})`;
}

export function FilterBar({ filters, onFilters, facets, searchRef }: Props) {
  const theme = useTheme();
  // Four buttons with counts do not fit a phone, so phones get a select like the marketplace filter.
  const narrow = useMediaQuery(theme.breakpoints.down("sm"));
  const set = (changes: Partial<ListingFilters>) => onFilters({ ...filters, ...changes });
  return (
    <Box sx={{ display: "flex", flexWrap: "wrap", gap: 1.5, alignItems: "center" }}>
      <TextField
        value={filters.search}
        onChange={(event) => set({ search: event.target.value })}
        placeholder="Search titles and listing IDs"
        inputRef={searchRef}
        sx={{ flex: "1 1 240px", maxWidth: 380 }}
        slotProps={{
          htmlInput: { "aria-label": "Search titles and listing IDs", "aria-keyshortcuts": "/", maxLength: 256 },
          input: { startAdornment: <InputAdornment position="start"><Search fontSize="small" /></InputAdornment> },
        }}
      />
      <TextField select label="Marketplace" value={filters.source} sx={{ minWidth: 168, flex: selectFlex }} slotProps={selectSlots}
        onChange={(event) => set({ source: event.target.value as Source | "" })}>
        <MenuItem value="">All marketplaces</MenuItem>
        {(Object.keys(SOURCES) as Source[]).map((source) => <MenuItem key={source} value={source}>{SOURCES[source]}</MenuItem>)}
      </TextField>
      {narrow ? (
        <TextField select label="Decision" value={filters.verdict} sx={{ minWidth: 168, flex: selectFlex }} slotProps={selectSlots}
          onChange={(event) => set({ verdict: event.target.value as Verdict | "" })}>
          <MenuItem value="">Any decision</MenuItem>
          {(Object.keys(VERDICTS) as Verdict[]).map((verdict) => (
            <MenuItem key={verdict} value={verdict}>{counted(VERDICTS[verdict], facets?.verdict[verdict])}</MenuItem>
          ))}
        </TextField>
      ) : (
        <ToggleButtonGroup exclusive size="small" value={filters.verdict} aria-label="Decision"
          onChange={(_, verdict: Verdict | "" | null) => set({ verdict: verdict ?? "" })}>
          <ToggleButton value="">Any decision</ToggleButton>
          {(Object.keys(VERDICTS) as Verdict[]).map((verdict) => (
            <ToggleButton key={verdict} value={verdict} sx={{ gap: 0.75 }}>
              {VERDICTS[verdict]}
              {facets && <Box component="span" sx={{ color: "text.secondary", ...figures }}>{formatCount(facets.verdict[verdict])}</Box>}
            </ToggleButton>
          ))}
        </ToggleButtonGroup>
      )}
    </Box>
  );
}

interface ViewProps {
  latest: boolean;
  onLatest: (latest: boolean) => void;
  view: View;
  onView: (view: View) => void;
}

/** How the list is shown: earlier decisions, and photos or rows. */
export function ViewOptions({ latest, onLatest, view, onView }: ViewProps) {
  return (
    <Box sx={{ display: "flex", alignItems: "center", gap: 1.5 }}>
      <Tooltip title="When a listing's decision changes, the earlier decision stays in history. Turn this on to list those too.">
        <FormControlLabel
          control={<Switch size="small" checked={!latest} onChange={(event) => onLatest(!event.target.checked)} />}
          label="Earlier decisions"
          slotProps={{ typography: { variant: "body2" } }}
          sx={{ mr: 0 }}
        />
      </Tooltip>
      <ToggleButtonGroup exclusive size="small" value={view} onChange={(_, next: View | null) => next && onView(next)}
        aria-label="Layout">
        <ToggleButton value="grid" aria-label="Photo grid"><GridViewOutlined fontSize="small" /></ToggleButton>
        <ToggleButton value="list" aria-label="Rows"><ViewListOutlined fontSize="small" /></ToggleButton>
      </ToggleButtonGroup>
    </Box>
  );
}
