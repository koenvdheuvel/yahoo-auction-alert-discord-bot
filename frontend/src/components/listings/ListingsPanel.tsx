import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import LinearProgress from "@mui/material/LinearProgress";
import Skeleton from "@mui/material/Skeleton";
import Typography from "@mui/material/Typography";
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";

import type { CandidateQuery } from "../../api/client";
import { useCandidates } from "../../api/hooks";
import type { Candidate, Source } from "../../api/types";
import { formatCount, safeUrl } from "../../lib/format";
import { isTyping, useDebounced } from "../../lib/hooks";
import { figures } from "../../theme";
import type { TitleSeed } from "../TitleTestDialog";
import type { ListingFilters } from "../Workspace";
import { EmptyState, LoadError } from "../common/Feedback";
import { FilterBar, ViewOptions, type View } from "./FilterBar";
import { ListingDrawer } from "./ListingDrawer";
import { ListingFrame } from "./ListingFrame";

const VIEW_KEY = "filter-lab:view";
// Frames of at least 196px; a phone still gets two columns (the gap is 12px).
const GRID_COLUMNS = "repeat(auto-fill, minmax(min(196px, calc(50% - 6px)), 1fr))";

function seedFrom(candidate: Candidate): TitleSeed {
  const source = ["yahooauction", "mercari", "surugaya"].includes(candidate.source) ? candidate.source as Source : undefined;
  return { title: candidate.title, source, price: candidate.payload.price ?? null };
}

interface Props {
  alertId: string | null;
  filters: ListingFilters;
  onFilters: (next: ListingFilters) => void;
  onTestTitle: (seed: TitleSeed) => void;
}

export function ListingsPanel({ alertId, filters, onFilters, onTestTitle }: Props) {
  const [view, setView] = useState<View>(() => (localStorage.getItem(VIEW_KEY) === "list" ? "list" : "grid"));
  const search = useDebounced(filters.search.trim(), 300);
  const query = useMemo<CandidateQuery>(() => ({
    alertId, search, source: filters.source, verdict: filters.verdict, latest: filters.latest,
  }), [alertId, search, filters.source, filters.verdict, filters.latest]);
  const candidates = useCandidates(query);
  const { fetchNextPage, hasNextPage, isFetchingNextPage } = candidates;
  const items = useMemo(() => candidates.data?.pages.flatMap((page) => page.items) ?? [], [candidates.data]);
  const first = candidates.data?.pages[0];

  const [active, setActive] = useState(0);
  const [drawer, setDrawer] = useState<number | null>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const focusPending = useRef(false);

  // Other filters or another alert: start again at the top.
  const queryKey = JSON.stringify(query);
  const [shownKey, setShownKey] = useState(queryKey);
  if (shownKey !== queryKey) {
    setShownKey(queryKey);
    setActive(0);
    setDrawer(null);
  }

  useEffect(() => {
    localStorage.setItem(VIEW_KEY, view);
  }, [view]);

  // Keyboard moves focus to the new frame once it is rendered.
  useEffect(() => {
    if (!focusPending.current) return;
    focusPending.current = false;
    const node = listRef.current?.querySelector<HTMLElement>(`[data-index="${active}"]`);
    node?.focus({ preventScroll: true });
    node?.scrollIntoView({ block: "nearest" });
  }, [active, items.length]);

  // Load the next page before the end of the list comes into view.
  useEffect(() => {
    const node = sentinelRef.current;
    if (!node || !hasNextPage) return;
    const observer = new IntersectionObserver((entries) => {
      if (entries[0]?.isIntersecting && !isFetchingNextPage) void fetchNextPage();
    }, { rootMargin: "800px 0px" });
    observer.observe(node);
    return () => observer.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "/" || event.defaultPrevented || isTyping(event) || document.querySelector(".MuiModal-root")) return;
      event.preventDefault();
      searchRef.current?.focus();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const onActivate = useCallback((index: number) => setActive(index), []);
  const onOpen = useCallback((index: number) => setDrawer(index), []);

  const columns = () => {
    const nodes = listRef.current?.querySelectorAll<HTMLElement>("[data-index]");
    if (!nodes || nodes.length < 2 || view === "list") return 1;
    const top = nodes[0]!.offsetTop;
    let count = 0;
    for (const node of nodes) {
      if (node.offsetTop !== top) break;
      count += 1;
    }
    return Math.max(count, 1);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLUListElement>) => {
    // Keys pressed with Ctrl, Cmd or Alt are left to the browser.
    if (isTyping(event) || event.ctrlKey || event.metaKey || event.altKey || !items.length) return;
    const current = items[Math.min(active, items.length - 1)]!;
    const onFrame = (event.target as HTMLElement).dataset.index !== undefined;
    const go = (index: number) => {
      event.preventDefault();
      const next = Math.max(0, Math.min(items.length - 1, index));
      focusPending.current = true;
      setActive(next);
      if (next >= items.length - columns() * 3 && hasNextPage && !isFetchingNextPage) void fetchNextPage();
    };
    switch (event.key) {
      case "j": case "ArrowRight": go(active + 1); break;
      case "k": case "ArrowLeft": go(active - 1); break;
      case "ArrowDown": go(active + columns()); break;
      case "ArrowUp": go(active - columns()); break;
      case "Home": go(0); break;
      case "End": go(items.length - 1); break;
      case "Enter":
        if (!onFrame) return;
        event.preventDefault();
        setDrawer(active);
        break;
      case "o": {
        const url = safeUrl(current.payload.url);
        if (url) window.open(url, "_blank", "noopener,noreferrer");
        event.preventDefault();
        break;
      }
      case "t":
        event.preventDefault();
        onTestTitle(seedFrom(current));
        break;
      default:
    }
  };

  const total = first?.total ?? 0;
  const filtered = Boolean(filters.search.trim() || filters.source || filters.verdict);
  const drawerItem = drawer === null ? null : items[drawer] ?? null;

  return (
    <Box>
      <FilterBar filters={filters} onFilters={onFilters} facets={first?.facets} searchRef={searchRef} />
      <Box sx={{ display: "flex", flexWrap: "wrap", alignItems: "center", columnGap: 2, rowGap: 1, mt: 1.5, mb: 1.5, minHeight: 40 }}>
        <Typography variant="body2" color="text.secondary" aria-live="polite" sx={figures}>
          {candidates.isSuccess && (total
            ? `${formatCount(items.length)} of ${formatCount(total)} ${total === 1 ? "listing" : "listings"}`
            : "")}
        </Typography>
        {items.length > 0 && (
          <Typography variant="caption" color="text.secondary" sx={{ display: { xs: "none", md: "block" } }}>
            j and k move, Enter shows details. Press ? for all keys.
          </Typography>
        )}
        {candidates.isFetching && !candidates.isPending && <LinearProgress sx={{ flex: 1, maxWidth: 120 }} aria-label="Updating listings" />}
        <Box sx={{ ml: "auto" }}>
          <ViewOptions latest={filters.latest} onLatest={(latest) => onFilters({ ...filters, latest })} view={view} onView={setView} />
        </Box>
      </Box>

      {candidates.isError && !items.length && (
        <LoadError error={candidates.error} what="Listings" onRetry={() => void candidates.refetch()} />
      )}
      {candidates.isPending && (
        <Box sx={{ display: "grid", gridTemplateColumns: GRID_COLUMNS, gap: 1.5 }}>
          {Array.from({ length: 12 }, (_, index) => <Skeleton key={index} variant="rounded" height={304} />)}
        </Box>
      )}
      {candidates.isSuccess && !items.length && (filtered ? (
        <EmptyState title="Nothing matches these filters" action={
          <Button variant="outlined" color="inherit" onClick={() => onFilters({ ...filters, search: "", source: "", verdict: "" })}>
            Clear filters
          </Button>}>
          Try another search, or clear the filters to see every listing.
        </EmptyState>
      ) : (
        <EmptyState title="No listings yet">
          The bot saves each listing a check finds, with the decision it made. They appear here after the next check.
          To add older posts, use Import saved history in the menu.
        </EmptyState>
      ))}

      {items.length > 0 && (
        <Box component="ul" ref={listRef} onKeyDown={onKeyDown} aria-label="Listings" aria-busy={candidates.isPlaceholderData}
          sx={view === "grid"
            ? { display: "grid", gridTemplateColumns: GRID_COLUMNS, gap: 1.5, m: 0, p: 0,
              opacity: candidates.isPlaceholderData ? 0.55 : 1, "& > li": { scrollMarginTop: 120, scrollMarginBottom: 96 } }
            : { m: 0, p: 0, border: 1, borderColor: "divider", borderRadius: 1, overflow: "hidden",
              opacity: candidates.isPlaceholderData ? 0.55 : 1,
              "& > li": { scrollMarginTop: 120, scrollMarginBottom: 96 }, "& > li:last-of-type": { borderBottom: 0 } }}>
          {items.map((candidate, index) => (
            <ListingFrame key={candidate.id} candidate={candidate} index={index} layout={view}
              active={index === Math.min(active, items.length - 1)} onActivate={onActivate} onOpen={onOpen} />
          ))}
        </Box>
      )}
      <Box ref={sentinelRef} sx={{ height: "1px" }} />
      {hasNextPage && (
        <Box sx={{ display: "flex", justifyContent: "center", mt: 2 }}>
          <Button variant="outlined" color="inherit" onClick={() => void fetchNextPage()} disabled={isFetchingNextPage}>
            {isFetchingNextPage ? "Loading more" : "Load more"}
          </Button>
        </Box>
      )}
      {candidates.isError && items.length > 0 && (
        <Box sx={{ mt: 2 }}><LoadError error={candidates.error} what="More listings" onRetry={() => void fetchNextPage()} /></Box>
      )}
      <ListingDrawer
        candidate={drawerItem}
        position={drawer === null ? "" : `${formatCount(drawer + 1)} of ${formatCount(total)}`}
        hasPrevious={drawer !== null && drawer > 0}
        hasNext={drawer !== null && (drawer < items.length - 1 || Boolean(hasNextPage))}
        onPrevious={() => setDrawer((index) => (index === null ? null : Math.max(0, index - 1)))}
        onNext={() => {
          if (drawer !== null && drawer >= items.length - 3 && hasNextPage) void fetchNextPage();
          setDrawer((index) => (index === null ? null : Math.min(items.length - 1, index + 1)));
        }}
        onClose={() => {
          if (drawer !== null) {
            focusPending.current = true;
            setActive(drawer);
          }
          setDrawer(null);
        }}
        onTestTitle={(candidate) => onTestTitle(seedFrom(candidate))}
      />
    </Box>
  );
}
