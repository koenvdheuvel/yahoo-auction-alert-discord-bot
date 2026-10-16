import { QueryClient, QueryClientProvider, type InfiniteData } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CandidateQuery } from "./client";
import { keys, LABEL_BATCH, useLabelMutation } from "./hooks";
import type { Candidate, CandidatePage } from "./types";

const query: CandidateQuery = { alertId: "1", guildId: null, search: "", source: "", verdict: "", feedback: "", latest: true };

function candidate(id: string): Candidate {
  return { id, feedback: null } as Candidate;
}

function setup(ids: string[]) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  const page = { items: ids.map(candidate), facets: { feedback: { unlabeled: ids.length, relevant: 0 } } } as unknown as CandidatePage;
  client.setQueryData<InfiniteData<CandidatePage, string | null>>(keys.candidates(query), { pages: [page], pageParams: [null] });
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  return { client, ...renderHook(() => useLabelMutation(), { wrapper }) };
}

function loaded(client: QueryClient) {
  return client.getQueryData<InfiniteData<CandidatePage, string | null>>(keys.candidates(query))!.pages[0]!;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useLabelMutation", () => {
  it("labels a large selection in batches the server accepts", async () => {
    const ids = Array.from({ length: 450 }, (_, index) => String(index + 1));
    // The client always sends a JSON string body.
    const fetch = vi.fn((_url: string, init: RequestInit & { body: string }) => {
      const body = JSON.parse(init.body) as { ids: string[]; label: string };
      const items = body.ids.map((id) => ({ ...candidate(id), feedback: body.label }));
      return Promise.resolve(Response.json({ items, missing: [] }));
    });
    vi.stubGlobal("fetch", fetch);
    const { client, result } = setup(ids);

    let saved: { items: Candidate[]; missing: string[] } | undefined;
    await act(async () => {
      saved = await result.current.mutateAsync({ ids, label: "relevant" });
    });

    const sizes = fetch.mock.calls.map(([, init]) => (JSON.parse(init.body) as { ids: string[] }).ids.length);
    expect(sizes).toEqual([LABEL_BATCH, LABEL_BATCH, 50]);
    expect(saved?.items).toHaveLength(450);
    expect(loaded(client).items.every((item) => item.feedback === "relevant")).toBe(true);
    expect(loaded(client).facets?.feedback).toMatchObject({ unlabeled: 0, relevant: 450 });
  });

  it("puts the labels back when the server refuses", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(Response.json(
      { error: "invalid_request", message: "Unknown feedback label" }, { status: 400 }))));
    const { client, result } = setup(["7", "8"]);

    await act(async () => {
      await result.current.mutateAsync({ ids: ["7", "8"], label: "bundle" }).catch(() => undefined);
    });

    expect(loaded(client).items.map((item) => item.feedback)).toEqual([null, null]);
  });
});
