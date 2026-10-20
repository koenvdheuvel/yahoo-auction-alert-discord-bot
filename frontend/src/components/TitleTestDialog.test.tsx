import { setTimeout as sleep } from "node:timers/promises";

import { ThemeProvider } from "@mui/material/styles";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AlertSummary, Decision, RulesResponse, RuleVersion, Ruleset } from "../api/types";
import { saveDraft } from "../lib/drafts";
import { defaultRuleset, newGroup } from "../lib/ruleset";
import { alertSummary } from "../test/fixtures";
import { theme } from "../theme";
import { TitleTestDialog, type TitleSeed } from "./TitleTestDialog";

const POSTERS: AlertSummary = { ...alertSummary("5", "20", "BABYMETAL"), channel_name: "posters" };
const VINYL: AlertSummary = { ...alertSummary("6", "21", "vinyl"), channel_name: "records" };
const ALERTS = [POSTERS, VINYL];

interface PreviewBody {
  title: string;
  source: string;
  price: number;
  alert_id?: string;
  ruleset: Ruleset;
}

function rules(alert: AlertSummary): RulesResponse {
  const version: RuleVersion = { id: `v${alert.id}`, version: 3, search_query: alert.search_query, ruleset: defaultRuleset(),
    restored_from_version_id: null, created_at: "2026-10-16T00:00:00Z" };
  return { alert: { id: alert.id, channel_id: alert.channel_id, search_query: alert.search_query }, active_version: version,
    versions: [version], versions_total: 1, legacy_filters: [], default_ruleset: defaultRuleset() };
}


/** The server's decision as far as these tests need it: an exclude group with a term in the title filters. */
function decide(body: PreviewBody): Decision {
  const hit = body.ruleset.groups.some((group) => group.policy === "exclude" && group.terms.some((term) => body.title.includes(term.value)));
  return { verdict: hit ? "filtered" : "accepted", normalized_title: body.title.toLowerCase(), reasons: [] };
}

interface Options {
  seed?: TitleSeed;
  alert?: AlertSummary | null;
  answer?: (body: PreviewBody) => Promise<Response>;
}

function show({ seed = {}, alert = null, answer = (body) => Promise.resolve(Response.json({ decision: decide(body) })) }: Options = {}) {
  const previews: PreviewBody[] = [];
  const fetch = vi.fn((url: string, init?: RequestInit) => {
    if (url === "/api/preview") {
      const body = JSON.parse(init!.body as string) as PreviewBody;
      previews.push(body);
      return answer(body);
    }
    const found = /^\/api\/alerts\/(\d+)\/rules$/.exec(url);
    const owner = ALERTS.find((item) => item.id === found?.[1]);
    return Promise.resolve(owner ? Response.json(rules(owner))
      : Response.json({ error: "not_found", message: "Alert not found" }, { status: 404 }));
  });
  vi.stubGlobal("fetch", fetch);
  render(
    <ThemeProvider theme={theme}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <TitleTestDialog test={{ id: 1, seed, open: true }} alert={alert} alerts={ALERTS} onClose={vi.fn()} />
      </QueryClientProvider>
    </ThemeProvider>,
  );
  return { previews };
}

const search = () => screen.getByRole("combobox", { name: /Search/ });
const testButton = () => screen.getByRole("button", { name: /^Test(ing)?$/ });

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Title test", () => {
  it("tests a listing with the unpublished draft of its own search, not the search on screen", async () => {
    saveDraft("5", { ruleset: { ...defaultRuleset(),
      groups: [newGroup("exclude", "Damaged", [{ method: "contains", value: "damaged" }])] }, baseVersionId: "v5" });
    const user = userEvent.setup();
    const { previews } = show({ alert: VINYL, seed: { title: "BABYMETAL towel damaged", source: "mercari", price: 1500, alertId: "5" } });
    expect(search()).toHaveTextContent("BABYMETAL · #posters");
    await waitFor(() => expect(testButton()).toBeEnabled());
    await user.click(testButton());

    expect(await screen.findByText("Filtered")).toBeInTheDocument();
    expect(screen.getByText(/with your unpublished draft for “BABYMETAL” in #posters/)).toBeInTheDocument();
    expect(previews).toHaveLength(1);
    expect(previews[0]).toMatchObject({ alert_id: "5", title: "BABYMETAL towel damaged", source: "mercari", price: 1500 });
    expect(previews[0]!.ruleset.groups.map((group) => group.label)).toEqual(["Damaged"]);
  });

  it("cannot run a global test until a search is chosen, then tests with that search", async () => {
    const user = userEvent.setup();
    const { previews } = show();
    await user.type(screen.getByRole("textbox", { name: /Listing title/ }), "vinyl record");
    expect(testButton()).toBeDisabled();
    expect(screen.getByText("Choose the search whose rules to test against.")).toBeInTheDocument();

    await user.click(search());
    await user.click(screen.getByRole("option", { name: /vinyl/ }));
    await waitFor(() => expect(testButton()).toBeEnabled());
    await user.click(testButton());
    await waitFor(() => expect(previews).toHaveLength(1));
    expect(previews[0]).toMatchObject({ alert_id: "6" });
  });

  it("starts a test without a listing on the search on screen", async () => {
    show({ alert: VINYL, seed: { title: "vinyl" } });
    expect(search()).toHaveTextContent("vinyl · #records");
    await waitFor(() => expect(testButton()).toBeEnabled());
  });

  it("does not fall back to the search on screen when the listing's search is not available", async () => {
    show({ alert: VINYL, seed: { title: "poster", alertId: "9" } });
    expect(await screen.findByText(/This search is not available/)).toBeInTheDocument();
    expect(search()).not.toHaveTextContent("vinyl");
    expect(testButton()).toBeDisabled();
  });

  it("does not fall back to the search on screen when the listing has no registered search", () => {
    show({ alert: VINYL, seed: { title: "poster", alertId: null } });
    expect(screen.getByText(/no longer registered/)).toBeInTheDocument();
    expect(search()).not.toHaveTextContent("vinyl");
    expect(testButton()).toBeDisabled();
  });

  it("never shows an answer for another search or for an earlier title", async () => {
    const user = userEvent.setup();
    let first = true;
    let release!: (response: Response) => void;
    const { previews } = show({ alert: POSTERS, seed: { title: "BABYMETAL towel" }, answer: (body) => {
      if (!first) return Promise.resolve(Response.json({ decision: decide(body) }));
      first = false;
      return new Promise<Response>((resolve) => { release = resolve; });
    } });
    await waitFor(() => expect(testButton()).toBeEnabled());
    await user.click(testButton());
    expect(testButton()).toHaveTextContent("Testing");

    // The person moves on to another search while the first answer is on its way.
    await user.click(search());
    await user.click(screen.getByRole("option", { name: /vinyl/ }));
    await waitFor(() => expect(testButton()).toBeEnabled());
    expect(testButton()).not.toHaveTextContent("Testing");
    await act(async () => {
      release(Response.json({ decision: { verdict: "filtered", normalized_title: "babymetal towel", reasons: [] } }));
      await sleep(0);
    });
    expect(screen.queryByText("Filtered")).not.toBeInTheDocument();

    await user.click(testButton());
    expect(await screen.findByText("Allowed")).toBeInTheDocument();
    expect(screen.getByText(/with published version 3 for “vinyl” in #records/)).toBeInTheDocument();
    expect(previews.map((body) => body.alert_id)).toEqual(["5", "6"]);

    await user.type(screen.getByRole("textbox", { name: /Listing title/ }), "!");
    expect(screen.queryByText("Allowed")).not.toBeInTheDocument();
  });
});
