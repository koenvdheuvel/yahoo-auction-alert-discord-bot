import ArrowDropDown from "@mui/icons-material/ArrowDropDown";
import Check from "@mui/icons-material/Check";
import Close from "@mui/icons-material/Close";
import GridViewOutlined from "@mui/icons-material/GridViewOutlined";
import Search from "@mui/icons-material/Search";
import ViewListOutlined from "@mui/icons-material/ViewListOutlined";
import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import FormControlLabel from "@mui/material/FormControlLabel";
import IconButton from "@mui/material/IconButton";
import InputAdornment from "@mui/material/InputAdornment";
import ListItemText from "@mui/material/ListItemText";
import MenuItem from "@mui/material/MenuItem";
import MenuList from "@mui/material/MenuList";
import Switch from "@mui/material/Switch";
import TextField from "@mui/material/TextField";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import { useId, useState, type ReactNode, type RefObject } from "react";

import type { Facets, Source, Verdict } from "../../api/types";
import { formatCount } from "../../lib/format";
import { usePhone } from "../../lib/responsive";
import { SOURCES, VERDICTS } from "../../lib/vocabulary";
import { figures } from "../../theme";
import { SheetDialog } from "../common/Sheet";
import type { ListingFilters } from "../views/SearchView";

export type View = "grid" | "list";

interface Props {
  filters: ListingFilters;
  onFilters: (next: ListingFilters) => void;
  facets: Facets | undefined;
  searchRef: RefObject<HTMLInputElement | null>;
}

// Show "All marketplaces" in the field instead of an empty box under a floating label.
const selectSlots = { inputLabel: { shrink: true }, select: { displayEmpty: true } } as const;

interface Choice<T extends string> {
  value: T;
  label: string;
  count?: number;
}

function sourceChoices(): Choice<Source | "">[] {
  return [{ value: "", label: "All marketplaces" },
    ...(Object.keys(SOURCES) as Source[]).map((source) => ({ value: source, label: SOURCES[source] }))];
}

function verdictChoices(facets: Facets | undefined): Choice<Verdict | "">[] {
  const verdicts = Object.keys(VERDICTS) as Verdict[];
  const any = facets ? verdicts.reduce((sum, verdict) => sum + facets.verdict[verdict], 0) : undefined;
  return [{ value: "", label: "Any decision", count: any },
    ...verdicts.map((verdict) => ({ value: verdict, label: VERDICTS[verdict], count: facets?.verdict[verdict] }))];
}

interface SheetProps<T extends string> {
  open: boolean;
  onClose: () => void;
  title: string;
  choices: Choice<T>[];
  value: T;
  onPick: (value: T) => void;
}

/** The choices for one filter as large rows, with the current one checked. Picking one closes the sheet. */
function ChoiceSheet<T extends string>({ open, onClose, title, choices, value, onPick }: SheetProps<T>) {
  const id = useId();
  return (
    <SheetDialog open={open} onClose={onClose} maxWidth="xs" aria-labelledby={id}>
      <DialogTitle id={id} sx={{ pb: 1 }}>{title}</DialogTitle>
      <DialogContent sx={{ px: 0, pb: 1.5 }}>
        <MenuList autoFocusItem={open} variant="selectedMenu" aria-labelledby={id} sx={{ py: 0 }}>
          {choices.map((choice) => {
            const current = choice.value === value;
            return (
              <MenuItem key={choice.value} selected={current} role="menuitemradio" aria-checked={current}
                onClick={() => { onPick(choice.value); onClose(); }} sx={{ minHeight: 52, px: 3, gap: 2 }}>
                <ListItemText primary={choice.label} />
                {choice.count !== undefined && (
                  <Typography variant="body2" color="textSecondary" sx={figures}>{formatCount(choice.count)}</Typography>
                )}
                {/* The check has a fixed slot, so the counts line up. */}
                <Box sx={{ width: 24, display: "flex", flex: "none" }}>{current && <Check fontSize="small" />}</Box>
              </MenuItem>
            );
          })}
        </MenuList>
      </DialogContent>
    </SheetDialog>
  );
}

// Chips are 36 pixels tall. A tap up to 4 pixels above or below one still counts, so a finger gets 44.
const chip = {
  flex: "none", height: 36, borderRadius: 18, fontSize: "0.8125rem", position: "relative",
  "&::after": { content: '""', position: "absolute", inset: "-4px 0" },
} as const;

function ChipLabel({ children }: { children: ReactNode }) {
  return (
    <Box component="span" sx={{ display: "inline-flex", alignItems: "center" }}>
      {children}
      <ArrowDropDown sx={{ fontSize: 20, mr: -0.75 }} />
    </Box>
  );
}

/** Phones: the search on its own row, then the filters as chips in a row that scrolls sideways. */
function PhoneFilters({ filters, onFilters, facets, searchField }: Omit<Props, "searchRef"> & { searchField: ReactNode }) {
  const [sheet, setSheet] = useState<"source" | "verdict" | null>(null);
  const set = (changes: Partial<ListingFilters>) => onFilters({ ...filters, ...changes });
  const verdicts = verdictChoices(facets);
  const verdict = verdicts.find((choice) => choice.value === filters.verdict)!;
  const source = filters.source ? SOURCES[filters.source] : "All marketplaces";
  return (
    <Box sx={{ display: "grid", gap: 0.5 }}>
      {searchField}
      <Box role="group" aria-label="Filters" sx={{ display: "flex", gap: 1, overflowX: "auto", mx: -2, px: 2, py: 0.5,
        scrollbarWidth: "none", "&::-webkit-scrollbar": { display: "none" } }}>
        <Chip variant={filters.source ? "filled" : "outlined"} color={filters.source ? "primary" : "default"} sx={chip}
          label={<ChipLabel>{source}</ChipLabel>} aria-label={`Marketplace: ${source}`} aria-haspopup="dialog"
          onClick={() => setSheet("source")} />
        <Chip variant={filters.verdict ? "filled" : "outlined"} color={filters.verdict ? "primary" : "default"} sx={chip}
          label={(
            <ChipLabel>
              {verdict.label}
              {filters.verdict && verdict.count !== undefined && (
                <Box component="span" sx={{ ml: 0.75, opacity: 0.8, ...figures }}>{formatCount(verdict.count)}</Box>
              )}
            </ChipLabel>
          )}
          aria-label={`Decision: ${verdict.label}${filters.verdict && verdict.count !== undefined ? ` (${formatCount(verdict.count)})` : ""}`}
          aria-haspopup="dialog" onClick={() => setSheet("verdict")} />
        <Chip variant={filters.latest ? "outlined" : "filled"} color={filters.latest ? "default" : "primary"} sx={chip}
          icon={filters.latest ? undefined : <Check />} label="Earlier decisions" aria-pressed={!filters.latest}
          onClick={() => set({ latest: !filters.latest })} />
      </Box>
      <ChoiceSheet open={sheet === "source"} onClose={() => setSheet(null)} title="Marketplace" choices={sourceChoices()}
        value={filters.source} onPick={(value) => set({ source: value })} />
      <ChoiceSheet open={sheet === "verdict"} onClose={() => setSheet(null)} title="Decision" choices={verdicts}
        value={filters.verdict} onPick={(value) => set({ verdict: value })} />
    </Box>
  );
}

export function FilterBar({ filters, onFilters, facets, searchRef }: Props) {
  const phone = usePhone();
  const set = (changes: Partial<ListingFilters>) => onFilters({ ...filters, ...changes });
  const searchField = (
    <TextField
      value={filters.search}
      onChange={(event) => set({ search: event.target.value })}
      placeholder="Search titles and listing IDs"
      inputRef={searchRef}
      sx={phone ? undefined : { flex: "1 1 240px", maxWidth: 380 }}
      // The search runs as you type, so the keyboard's Search key only puts the keyboard away.
      onKeyDown={phone ? (event) => { if (event.key === "Enter") (event.target as HTMLElement).blur(); } : undefined}
      slotProps={{
        htmlInput: { "aria-label": "Search titles and listing IDs", "aria-keyshortcuts": "/", maxLength: 256,
          enterKeyHint: "search" },
        input: {
          startAdornment: <InputAdornment position="start"><Search fontSize="small" /></InputAdornment>,
          endAdornment: phone && filters.search ? (
            <InputAdornment position="end">
              <IconButton edge="end" aria-label="Clear the search"
                onClick={() => { set({ search: "" }); searchRef.current?.focus(); }}><Close fontSize="small" /></IconButton>
            </InputAdornment>
          ) : undefined,
        },
      }}
    />
  );
  if (phone) return <PhoneFilters filters={filters} onFilters={onFilters} facets={facets} searchField={searchField} />;
  return (
    <Box sx={{ display: "flex", flexWrap: "wrap", gap: 1.5, alignItems: "center" }}>
      {searchField}
      <TextField select label="Marketplace" value={filters.source} sx={{ minWidth: 168 }} slotProps={selectSlots}
        onChange={(event) => set({ source: event.target.value as Source | "" })}>
        {sourceChoices().map((choice) => <MenuItem key={choice.value} value={choice.value}>{choice.label}</MenuItem>)}
      </TextField>
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
    </Box>
  );
}

/** Photos or rows. */
export function LayoutToggle({ view, onView }: { view: View; onView: (view: View) => void }) {
  const square = { "@media (pointer: coarse)": { minWidth: 44 } };
  return (
    <ToggleButtonGroup exclusive size="small" value={view} onChange={(_, next: View | null) => next && onView(next)}
      aria-label="Layout">
      <ToggleButton value="grid" aria-label="Photo grid" sx={square}><GridViewOutlined fontSize="small" /></ToggleButton>
      <ToggleButton value="list" aria-label="Rows" sx={square}><ViewListOutlined fontSize="small" /></ToggleButton>
    </ToggleButtonGroup>
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
      <LayoutToggle view={view} onView={onView} />
    </Box>
  );
}
