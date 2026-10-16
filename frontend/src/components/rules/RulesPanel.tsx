import Add from "@mui/icons-material/Add";
import CheckCircleOutlined from "@mui/icons-material/CheckCircleOutlined";
import ErrorOutlined from "@mui/icons-material/ErrorOutlined";
import WarningAmberOutlined from "@mui/icons-material/WarningAmberOutlined";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import CircularProgress from "@mui/material/CircularProgress";
import FormControlLabel from "@mui/material/FormControlLabel";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useMutation, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError, api } from "../../api/client";
import { keys, refreshAccess, useValidation } from "../../api/hooks";
import type { AlertSummary, Policy, RemovalResult, RuleGroup, RulesResponse, Ruleset } from "../../api/types";
import { errorMessage } from "../../lib/errors";
import { formatRelative, plural } from "../../lib/format";
import { useDebounced } from "../../lib/hooks";
import { LIMITS, cannotAddTerm, fieldLocation, groupsFromSearch, newGroup } from "../../lib/ruleset";
import type { Draft } from "../../lib/useDraft";
import { usePostRemoval } from "../../lib/usePostRemoval";
import type { StoredReplay } from "../views/SearchView";
import { ConfirmDialog, EmptyState, LoadError } from "../common/Feedback";
import { useNotify } from "../common/notify";
import { PostRemovalPreview } from "../removal/PostRemovalPreview";
import { GroupEditor } from "./GroupEditor";
import { JsonEditor } from "./JsonEditor";
import { RuleSettings } from "./RuleSettings";

const ADD: [Policy, string][] = [["require", "Must-match group"], ["exclude", "Exclude group"], ["review", "Hold-for-review group"]];

interface Props {
  alert: AlertSummary | null;
  rules: UseQueryResult<RulesResponse>;
  draft: Draft;
  /** Whether you may change the search, which deleting its Discord filters needs. */
  canChange?: boolean;
  replay: StoredReplay | null;
  onTestTitle: () => void;
  onReplay: () => void;
}

export function RulesPanel({ alert, rules, draft, replay, onTestTitle, onReplay, canChange = false }: Props) {
  const client = useQueryClient();
  const notify = useNotify();
  const [confirming, setConfirming] = useState(false);
  const debounced = useDebounced(draft.serialized, 350);
  const validation = useValidation(draft.ready ? debounced : null);
  const checking = validation.isFetching || debounced !== draft.serialized;
  const invalid = validation.data?.state === "invalid" ? validation.data : null;
  const fault = fieldLocation(invalid?.field);
  const ruleset = draft.ruleset;
  const replayed = replay !== null && replay.serialized === draft.serialized;

  const [removeAlso, setRemoveAlso] = useState(false);
  const removal = usePostRemoval(alert?.id ?? null, ruleset, confirming && removeAlso);
  const closePublish = () => {
    setConfirming(false);
    setRemoveAlso(false);
    removal.reset();
  };

  const publish = useMutation({
    // Removal is queued only once the rules are published. A failure there does not undo the publication.
    mutationFn: async (removeIds: string[]) => {
      const version = await api.publish(alert!.id, ruleset, draft.baseVersionId);
      let removed: RemovalResult | null = null;
      let removalError: unknown = null;
      if (removeIds.length) {
        try {
          removed = await api.removePosts(alert!.id, version.id, removeIds);
        } catch (error) {
          removalError = error;
        }
      }
      return { version, removed, removalError };
    },
    onSuccess: ({ version, removed, removalError }) => {
      // Show the new version at once, so the old rules do not flash back while reloading.
      client.setQueryData<RulesResponse>(keys.rules(alert!.id), (current) => current && {
        ...current, active_version: version, versions: [version, ...current.versions], versions_total: current.versions_total + 1,
      });
      draft.discard();
      closePublish();
      if (removalError) {
        // The removal's error is caught above, so the global 404 handling does not see it.
        refreshAccess(client, removalError);
        notify(`Published version ${version.version}, but its posts were not queued for removal: ${errorMessage(removalError)} `
          + "You can remove them from Versions.", "warning");
      } else if (removed) {
        const skipped = removed.skipped ? ` ${plural(removed.skipped, "post was", "posts were")} skipped because ${removed.skipped === 1 ? "it" : "they"} changed meanwhile.` : "";
        notify(`Published version ${version.version}. ${plural(removed.queued, "post")} will be removed from Discord`
          + `${removed.bot_running ? "" : " when the bot runs next"}; Versions shows the progress.${skipped}`);
        void client.invalidateQueries({ queryKey: keys.removalStatus(alert!.id) });
      } else {
        notify(`Published version ${version.version}. The next check of “${alert!.search_query}” uses it.`);
      }
      void client.invalidateQueries({ queryKey: keys.rules(alert!.id) });
      void client.invalidateQueries({ queryKey: keys.alerts });
    },
    onError: (error) => {
      closePublish();
      if (error instanceof ApiError && error.code === "version_conflict") {
        void client.invalidateQueries({ queryKey: keys.rules(alert!.id) });
        notify("Other rules were published first. Your draft is kept; see the note above it.", "warning");
      } else {
        notify(`Publishing failed: ${errorMessage(error)}`, "error");
      }
    },
  });

  if (alert && rules.isError) return <LoadError error={rules.error} what="The rules" onRetry={() => void rules.refetch()} />;
  if (!draft.ready) return <Stack spacing={2}>{[0, 1, 2].map((index) => <Skeleton key={index} variant="rounded" height={140} />)}</Stack>;

  const update = (next: Ruleset) => draft.update(next);
  const setGroups = (groups: RuleGroup[]) => update({ ...ruleset, groups });
  const groups = ruleset.groups;
  const cannotAdd = (group: RuleGroup) => (method: Parameters<typeof cannotAddTerm>[2], added: { terms: number; regex: number }) =>
    cannotAddTerm(ruleset, group, method, added);
  const canPublish = alert !== null && draft.edited && validation.data?.state === "valid" && !checking && !draft.outdated;
  const nextVersion = (rules.data?.versions[0]?.version ?? 0) + 1;

  return (
    <Box sx={{ display: "grid", gap: 2.5 }}>
      {draft.outdated && (
        <Alert severity="warning" action={
          <Stack direction="row" spacing={1}>
            <Button color="inherit" size="small" onClick={draft.rebase}>Keep my draft</Button>
            <Button color="inherit" size="small" onClick={draft.discard}>Discard it</Button>
          </Stack>}>
          {draft.published
            ? `Version ${draft.published.version} was published after you started this draft. Check it under Versions, then keep your draft to publish over it, or discard your draft.`
            : "The rules you started from were replaced after you started this draft."}
        </Alert>
      )}
      {!alert && (
        <Alert severity="info">
          This is a scratch draft for trying rules on titles. Choose a search on the left to replay and publish rules for it.
        </Alert>
      )}
      <Typography variant="body2" color="text.secondary" sx={{ maxWidth: 760 }}>
        A listing is allowed when every must-match group matches and no exclude group does. Hold-for-review groups keep a
        match from being posted until you look at it. Inside a group, any term can match, or all terms must.
      </Typography>

      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", lg: "minmax(0, 1fr) 340px" }, gap: 3, alignItems: "start" }}>
        <Box sx={{ display: "grid", gap: 1.5 }}>
          {groups.length === 0 && (
            <Box sx={{ border: 1, borderColor: "divider", borderStyle: "dashed", borderRadius: 1 }}>
              <EmptyState title="No rule groups yet" action={
                alert && (
                  <Button variant="outlined" color="inherit" onClick={() => setGroups(groupsFromSearch(alert.search_query))}>
                    Start from the search words
                  </Button>
                )}>
                Without groups, every listing that passes the Discord filters is allowed. A good start is one group for
                what the listing is about and one for the kind of product, each with its spellings in Japanese and English.
              </EmptyState>
            </Box>
          )}
          {groups.map((group, index) => (
            <GroupEditor key={group.id} group={group} index={index} count={groups.length}
              error={fault.group === index && invalid ? { message: invalid.message, term: fault.term } : null}
              cannotAdd={cannotAdd(group)}
              onChange={(next) => setGroups(groups.map((item, at) => (at === index ? next : item)))}
              onMove={(offset) => {
                const next = [...groups];
                const [moved] = next.splice(index, 1);
                next.splice(index + offset, 0, moved!);
                setGroups(next);
              }}
              onDuplicate={() => setGroups([...groups.slice(0, index + 1),
                { ...newGroup(group.policy, `${group.label} copy`, group.terms.map((term) => ({ ...term }))), match: group.match,
                  normalize: group.normalize }, ...groups.slice(index + 1)])}
              onRemove={() => setGroups(groups.filter((_, at) => at !== index))} />
          ))}
          <Stack direction="row" sx={{ flexWrap: "wrap", gap: 1 }}>
            {ADD.map(([policy, name]) => (
              <Button key={policy} variant="outlined" color="inherit" startIcon={<Add />} disabled={groups.length >= LIMITS.groups}
                onClick={() => setGroups([...groups, newGroup(policy)])}>
                {name}
              </Button>
            ))}
          </Stack>
          {invalid && fault.section && fault.section !== "groups" && fault.section !== "price" && (
            <Alert severity="error">{invalid.message}</Alert>
          )}
          <JsonEditor ruleset={ruleset} onApply={update} disabled={!draft.ready} />
        </Box>
        <Box component="aside" aria-label="Settings for all groups" sx={{ bgcolor: "background.paper", border: 1, borderColor: "divider",
          borderRadius: 1, p: 2 }}>
          <RuleSettings ruleset={ruleset} onChange={update} filters={alert ? rules.data?.legacy_filters ?? [] : null}
            alertId={alert?.id ?? null} canChange={canChange}
            priceError={invalid && fault.section === "price" ? invalid.message : null} />
        </Box>
      </Box>

      <Box role="region" aria-label="Draft" sx={{ position: "sticky", bottom: 0, zIndex: 3, mx: { xs: -2, md: -3 }, px: { xs: 2, md: 3 },
        py: 1.5, bgcolor: "background.paper", borderTop: 1, borderColor: "divider",
        display: "flex", flexWrap: "wrap", alignItems: "center", gap: 2 }}>
        <Box sx={{ flex: "1 1 280px", minWidth: 0 }}>
          <Typography variant="body2" sx={{ fontWeight: 650 }}>
            {draft.edited
              ? draft.published ? `Unpublished changes to version ${draft.published.version}` : "Unpublished rules"
              : draft.published ? `Same as published version ${draft.published.version}` : "No rules published for this search"}
          </Typography>
          <Box aria-live="polite" sx={{ display: "flex", alignItems: "center", gap: 0.75, mt: 0.25, minHeight: 20 }}>
            {draft.outdated ? (
              <>
                <WarningAmberOutlined color="warning" sx={{ fontSize: 15 }} />
                <Typography variant="caption" color="warning.main">
                  {draft.published ? `Version ${draft.published.version} was published after you started this draft.`
                    : "The rules changed after you started this draft."}
                </Typography>
                <Button size="small" color="inherit" onClick={draft.rebase} sx={{ py: 0 }}>Keep my draft</Button>
                <Button size="small" color="inherit" onClick={draft.discard} sx={{ py: 0 }}>Discard it</Button>
              </>
            ) : checking ? (
              <><CircularProgress size={12} aria-hidden="true" /><Typography variant="caption" color="text.secondary">Checking the draft</Typography></>
            ) : validation.isError ? (
              <Typography variant="caption" color="error">The draft could not be checked: {errorMessage(validation.error)}</Typography>
            ) : invalid ? (
              <><ErrorOutlined color="error" sx={{ fontSize: 15 }} /><Typography variant="caption" color="error">{invalid.message}</Typography></>
            ) : (
              <><CheckCircleOutlined color="success" sx={{ fontSize: 15 }} />
                <Typography variant="caption" color="text.secondary">
                  {draft.edited && alert
                    ? replayed ? `Valid. Replayed ${formatRelative(replay.ranAt)}.` : "Valid. Not replayed yet."
                    : "Valid."}
                </Typography></>
            )}
          </Box>
        </Box>
        <Stack direction="row" sx={{ flexWrap: "wrap", gap: 1 }}>
          {draft.edited && !draft.outdated && <Button color="inherit" onClick={draft.discard}>Discard changes</Button>}
          <Button variant="outlined" color="inherit" onClick={onTestTitle}>Test a title</Button>
          {alert && <Button variant="outlined" color="inherit" onClick={onReplay} disabled={Boolean(invalid)}>Replay draft</Button>}
          {alert && (
            <Button variant="contained" onClick={() => setConfirming(true)} disabled={!canPublish || publish.isPending}>
              Publish
            </Button>
          )}
        </Stack>
      </Box>

      {alert && (
        <ConfirmDialog open={confirming} title={`Publish rules for “${alert.search_query}”?`} maxWidth={removeAlso ? "sm" : "xs"}
          confirm={removeAlso && removal.selected.length ? `Publish and remove ${plural(removal.selected.length, "post")}` : "Publish"}
          confirmDisabled={removeAlso && (removal.preview.isFetching || removal.preview.isError)}
          busy={publish.isPending} onConfirm={() => publish.mutate(removeAlso ? removal.selected : [])} onClose={closePublish}>
          <Typography variant="body2" sx={{ mb: 1.5 }}>
            They become version {nextVersion}, and the next check of this search uses them. Listings that were already
            posted are not posted again, and publishing posts nothing by itself.
          </Typography>
          {!replayed && (
            <Typography variant="body2" color="warning.main" sx={{ mb: 1.5 }}>
              You have not replayed this draft. A replay shows which recent listings it would allow or filter.
            </Typography>
          )}
          <FormControlLabel label="Also remove Discord posts these rules filter"
            control={<Checkbox checked={removeAlso} onChange={(event) => setRemoveAlso(event.target.checked)} />} />
          {removeAlso && <Box sx={{ mt: 1 }}><PostRemovalPreview removal={removal} /></Box>}
        </ConfirmDialog>
      )}
    </Box>
  );
}
