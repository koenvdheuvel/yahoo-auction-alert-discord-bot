import DeleteSweepOutlined from "@mui/icons-material/DeleteSweepOutlined";
import EditNoteOutlined from "@mui/icons-material/EditNoteOutlined";
import ExpandMore from "@mui/icons-material/ExpandMore";
import MoreVert from "@mui/icons-material/MoreVert";
import RestoreOutlined from "@mui/icons-material/RestoreOutlined";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import ButtonBase from "@mui/material/ButtonBase";
import Collapse from "@mui/material/Collapse";
import IconButton from "@mui/material/IconButton";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useMutation, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError, api } from "../../api/client";
import { keys } from "../../api/hooks";
import type { AlertSummary, RuleVersion, RulesResponse } from "../../api/types";
import { describeRuleset } from "../../lib/describe";
import { errorMessage } from "../../lib/errors";
import { formatCount, formatDateTime, plural } from "../../lib/format";
import { longPressable, useLongPress } from "../../lib/gestures";
import { usePhone } from "../../lib/responsive";
import type { Draft } from "../../lib/useDraft";
import { usePostRemoval } from "../../lib/usePostRemoval";
import { figures } from "../../theme";
import { ConfirmDialog, EmptyState, LoadError } from "../common/Feedback";
import { useNotify } from "../common/notify";
import { ActionSheet, type SheetAction } from "../common/Sheet";
import { PostRemovalPreview } from "../removal/PostRemovalPreview";
import { RemovalProgress } from "../removal/RemovalProgress";
import { RulesetSummary } from "./RulesetSummary";

/** When the version was published, and which older version it brought back. */
function publishedAt(version: RuleVersion, restoredFrom: number | undefined): string {
  const restored = version.restored_from_version_id ? `, restored from version ${restoredFrom ?? "an older version"}` : "";
  return `${formatDateTime(version.created_at)}${restored}`;
}

interface PhoneVersionProps {
  version: RuleVersion;
  current: boolean;
  restoredFrom: number | undefined;
  shown: boolean;
  rulesId: string;
  onToggle: () => void;
  onActions: () => void;
}

/** A version on a phone: a tap on it shows or hides its rules, and ⋮ or a long press opens its actions. */
function PhoneVersion({ version, current, restoredFrom, shown, rulesId, onToggle, onActions }: PhoneVersionProps) {
  const press = useLongPress(onActions);
  return (
    <Stack direction="row" sx={{ alignItems: "flex-start" }}>
      <Typography variant="subtitle1" component="h3" sx={{ flex: 1, minWidth: 0 }}>
        <ButtonBase onClick={onToggle} aria-expanded={shown} aria-controls={shown ? rulesId : undefined} {...press}
          sx={{ width: "100%", justifyContent: "flex-start", alignItems: "flex-start", gap: 1, textAlign: "left", font: "inherit",
            pl: 2, pr: 0.5, py: 1.5, "@media (hover: hover)": { "&:hover": { bgcolor: "action.hover" } }, ...longPressable }}>
          {/* A button inside a heading may only hold text, so every line is a span. */}
          <Box component="span" sx={{ flex: 1, minWidth: 0 }}>
            <Box component="span" sx={{ display: "flex", flexWrap: "wrap", alignItems: "baseline", columnGap: 1, ...figures }}>
              Version {version.version}
              {current && <Typography variant="caption" sx={{ color: "success.main", fontWeight: 650 }}>Published now</Typography>}
            </Box>
            <Typography variant="body2" component="span" sx={{ display: "block" }}>{describeRuleset(version.ruleset)}</Typography>
            <Typography variant="caption" color="textSecondary" sx={{ display: "block" }}>{publishedAt(version, restoredFrom)}</Typography>
          </Box>
          <ExpandMore sx={{ flex: "none", color: "text.secondary", transition: "transform 150ms ease-out",
            transform: shown ? "rotate(180deg)" : "none" }} />
        </ButtonBase>
      </Typography>
      <IconButton aria-label={`More actions for version ${version.version}`} aria-haspopup="dialog" onClick={onActions}
        sx={{ mt: 0.5, mr: 0.5 }}>
        <MoreVert />
      </IconButton>
    </Stack>
  );
}

interface Props {
  alert: AlertSummary | null;
  rules: UseQueryResult<RulesResponse>;
  draft: Draft;
  onEditRules: () => void;
  /** Whether you have Manage Channels in the search's channel, which restoring and removing posts need. */
  canChange?: boolean;
}

export function VersionsPanel({ alert, rules, draft, onEditRules, canChange = false }: Props) {
  const client = useQueryClient();
  const notify = useNotify();
  const phone = usePhone();
  const [open, setOpen] = useState<string | null>(null);
  const [restoring, setRestoring] = useState<RuleVersion | null>(null);
  const [loading, setLoading] = useState<RuleVersion | null>(null);
  // The version whose actions sheet is open on a phone. It stays set while the sheet slides away.
  const [sheet, setSheet] = useState<{ version: RuleVersion; open: boolean } | null>(null);

  const restore = useMutation({
    mutationFn: (version: RuleVersion) => api.restore(alert!.id, version.id, rules.data?.active_version?.id ?? null),
    onSuccess: (created, version) => {
      client.setQueryData<RulesResponse>(keys.rules(alert!.id), (current) => current && {
        ...current, active_version: created, versions: [created, ...current.versions], versions_total: current.versions_total + 1,
      });
      setRestoring(null);
      notify(`Restored version ${version.version} as version ${created.version}. The next check uses it.`);
      void client.invalidateQueries({ queryKey: keys.rules(alert!.id) });
      void client.invalidateQueries({ queryKey: keys.alerts });
    },
    onError: (error) => {
      setRestoring(null);
      if (error instanceof ApiError && error.code === "version_conflict") {
        void client.invalidateQueries({ queryKey: keys.rules(alert!.id) });
        notify("Other rules were published meanwhile. Check the list again before restoring.", "warning");
      } else {
        notify(`Restoring failed: ${errorMessage(error)}`, "error");
      }
    },
  });

  const [removing, setRemoving] = useState(false);
  const removal = usePostRemoval(alert?.id ?? null, undefined, removing);
  const closeRemoval = () => {
    setRemoving(false);
    removal.reset();
  };
  const removePosts = useMutation({
    mutationFn: (ids: string[]) => api.removePosts(alert!.id, rules.data!.active_version!.id, ids),
    onSuccess: (result) => {
      closeRemoval();
      const skipped = result.skipped ? ` ${plural(result.skipped, "post was", "posts were")} skipped because ${result.skipped === 1 ? "it" : "they"} changed meanwhile.` : "";
      notify(`${plural(result.queued, "post")} will be removed from Discord${result.bot_running ? "" : " when the bot runs next"}.${skipped}`);
      void client.invalidateQueries({ queryKey: keys.removalStatus(alert!.id) });
    },
    onError: (error) => {
      closeRemoval();
      if (error instanceof ApiError && error.code === "version_conflict") {
        void client.invalidateQueries({ queryKey: keys.rules(alert!.id) });
        notify("Other rules were published meanwhile, so nothing was removed. Check the posts again.", "warning");
      } else {
        notify(`Removing the posts failed: ${errorMessage(error)}`, "error");
      }
    },
  });

  if (!alert) {
    return <EmptyState title="Choose a search to see its rule versions">Each search keeps every version of its rules that was published.</EmptyState>;
  }
  if (rules.isError) return <LoadError error={rules.error} what="Rule versions" onRetry={() => void rules.refetch()} />;
  if (rules.isPending) return <Stack spacing={1.5}>{[0, 1, 2].map((index) => <Skeleton key={index} variant="rounded" height={88} />)}</Stack>;

  const { versions, versions_total: total, active_version: active } = rules.data;
  const loadIntoDraft = (version: RuleVersion) => {
    draft.update(version.ruleset);
    setLoading(null);
    notify(`Version ${version.version} is in your draft. Nothing changes until you publish.`);
    onEditRules();
  };
  const startLoad = (version: RuleVersion) => (draft.edited ? setLoading(version) : loadIntoDraft(version));
  // The same actions as the buttons on larger screens.
  const sheetActions = (version: RuleVersion): SheetAction[] => [
    { label: "Load into draft", icon: <EditNoteOutlined />, onSelect: () => startLoad(version) },
    version.id === active?.id
      ? { label: "Remove filtered posts", icon: <DeleteSweepOutlined />, disabled: !canChange, onSelect: () => setRemoving(true) }
      : { label: "Restore", icon: <RestoreOutlined />, disabled: !canChange, onSelect: () => setRestoring(version) },
  ];

  if (!versions.length) {
    return (
      <EmptyState title="Nothing published yet" action={<Button variant="outlined" color="inherit" onClick={onEditRules}>Open the rules</Button>}>
        Each time you publish rules for “{alert.search_query}”, the version is kept here and can be restored.
      </EmptyState>
    );
  }

  return (
    <Box>
      <RemovalProgress alertId={alert.id} />
      <Box component="ol" sx={{ listStyle: "none", p: 0, m: 0, border: 1, borderColor: "divider", borderRadius: 1, bgcolor: "background.paper" }}>
        {versions.map((version) => {
          const current = version.id === active?.id;
          const restoredFrom = version.restored_from_version_id
            ? versions.find((other) => other.id === version.restored_from_version_id)?.version : undefined;
          const shown = open === version.id;
          const rulesId = `version-rules-${version.id}`;
          const toggle = () => setOpen(shown ? null : version.id);
          return (
            <Box component="li" key={version.id} sx={{ px: phone ? 0 : 2, py: phone ? 0 : 1.5, borderBottom: 1, borderColor: "divider",
              "&:last-of-type": { borderBottom: 0 } }}>
              {phone ? (
                <PhoneVersion version={version} current={current} restoredFrom={restoredFrom} shown={shown} rulesId={rulesId}
                  onToggle={toggle} onActions={() => setSheet({ version, open: true })} />
              ) : (
                <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} sx={{ alignItems: { md: "center" } }}>
                  <Box sx={{ minWidth: 92 }}>
                    <Typography variant="subtitle1" component="h3" sx={figures}>Version {version.version}</Typography>
                    {current && <Typography variant="caption" sx={{ color: "success.main", fontWeight: 650 }}>Published now</Typography>}
                  </Box>
                  <Box sx={{ flex: 1, minWidth: 0 }}>
                    <Typography variant="body2">{describeRuleset(version.ruleset)}</Typography>
                    <Typography variant="caption" color="textSecondary">{publishedAt(version, restoredFrom)}</Typography>
                  </Box>
                  <Stack direction="row" spacing={1}>
                    <Button size="small" color="inherit" onClick={toggle} aria-expanded={shown} aria-controls={shown ? rulesId : undefined}>
                      {shown ? "Hide rules" : "Show rules"}
                    </Button>
                    <Button size="small" variant="outlined" color="inherit" onClick={() => startLoad(version)}>
                      Load into draft
                    </Button>
                    {!current && (
                      <Button size="small" variant="outlined" color="inherit" onClick={() => setRestoring(version)}
                        disabled={!canChange}>Restore</Button>
                    )}
                    {current && (
                      <Button size="small" variant="outlined" color="inherit" onClick={() => setRemoving(true)}
                        disabled={!canChange}>
                        Remove filtered posts
                      </Button>
                    )}
                  </Stack>
                </Stack>
              )}
              <Collapse in={shown} unmountOnExit>
                <Box id={rulesId} sx={phone ? { px: 2, pb: 1.5 } : { pt: 1.5 }}><RulesetSummary ruleset={version.ruleset} /></Box>
              </Collapse>
            </Box>
          );
        })}
      </Box>
      {total > versions.length && (
        <Typography variant="caption" color="textSecondary" component="p" sx={{ mt: 1, ...figures }}>
          Showing the latest {formatCount(versions.length)} of {formatCount(total)} versions. Older versions are kept but not listed.
        </Typography>
      )}
      <ConfirmDialog open={restoring !== null} title={`Restore version ${restoring?.version ?? ""}?`} confirm="Restore"
        busy={restore.isPending} onConfirm={() => restoring && restore.mutate(restoring)} onClose={() => setRestoring(null)}>
        <Typography variant="body2">
          Its rules are published again as a new version, and the next check of “{alert.search_query}” uses them. Your draft
          is not changed. Nothing is posted by restoring.
        </Typography>
      </ConfirmDialog>
      <ConfirmDialog open={loading !== null} title="Replace your draft?" confirm="Replace draft"
        onConfirm={() => loading && loadIntoDraft(loading)} onClose={() => setLoading(null)}>
        <Typography variant="body2">
          Your draft has unpublished changes. Loading version {loading?.version} replaces them.
        </Typography>
      </ConfirmDialog>
      <ConfirmDialog open={removing} maxWidth="sm" title="Remove the Discord posts the published rules filter?"
        confirm={removal.selected.length ? `Remove ${plural(removal.selected.length, "post")}` : "Remove posts"}
        confirmDisabled={!removal.selected.length || removal.preview.isFetching}
        busy={removePosts.isPending} onConfirm={() => removePosts.mutate(removal.selected)} onClose={closeRemoval}>
        <Typography variant="body2" sx={{ mb: 1.5 }}>
          Version {active?.version} decides which of the posts for “{alert.search_query}” go. Nothing is removed until you
          confirm.
        </Typography>
        <PostRemovalPreview removal={removal} />
      </ConfirmDialog>
      {phone && sheet && (
        <ActionSheet open={sheet.open} onClose={() => setSheet({ ...sheet, open: false })} title={`Version ${sheet.version.version}`}
          actions={sheetActions(sheet.version)}>
          <Typography variant="body2" color="textSecondary">{describeRuleset(sheet.version.ruleset)}</Typography>
          {!canChange && (
            <Typography variant="caption" color="textSecondary" component="p" sx={{ mt: 1 }}>
              You need Manage Channels in this search's channel to restore a version or remove posts.
            </Typography>
          )}
        </ActionSheet>
      )}
    </Box>
  );
}
