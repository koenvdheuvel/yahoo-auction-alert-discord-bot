import { afterEach, describe, expect, it, vi } from "vitest";

import { api, ApiError, onSessionEnded, request, type CandidateQuery } from "./client";

function respond(status: number, body: unknown) {
  const fetch = vi.fn(() => Promise.resolve(new Response(JSON.stringify(body), {
    status, headers: { "Content-Type": "application/json" },
  })));
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("request", () => {
  it("returns the JSON body of a successful response", async () => {
    respond(200, { authenticated: true });
    await expect(request("/api/session")).resolves.toEqual({ authenticated: true });
  });

  it("turns an error body into an ApiError with the field at fault", async () => {
    respond(400, { error: "invalid_request", message: "Group 2, Term 3: Invalid regular expression", field: "groups.1.terms.2" });
    const error = await request("/api/rules/validate", { method: "POST", body: {} }).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 400, code: "invalid_request", field: "groups.1.terms.2",
      message: "Group 2, Term 3: Invalid regular expression" });
  });

  it("still explains a failure without a JSON body", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response("Bad gateway", { status: 502 }))));
    await expect(request("/api/alerts")).rejects.toMatchObject({
      status: 502, code: "http_error", message: "The request failed with status 502.",
    });
  });

  it("reports a network failure as status 0", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))));
    await expect(request("/api/alerts")).rejects.toMatchObject({ status: 0, code: "network_error" });
  });

  it("tells the app when the session is gone, but not for a wrong key at sign-in", async () => {
    const ended = vi.fn();
    const stop = onSessionEnded(ended);
    respond(401, { error: "unauthorized", message: "Sign in again" });
    await expect(request("/api/login", { method: "POST", body: { token: "wrong" } })).rejects.toBeInstanceOf(ApiError);
    expect(ended).not.toHaveBeenCalled();
    await expect(request("/api/alerts")).rejects.toBeInstanceOf(ApiError);
    expect(ended).toHaveBeenCalledTimes(1);
    stop();
  });

  it("tells the app why the session ended", async () => {
    const ended = vi.fn();
    const stop = onSessionEnded(ended);
    respond(401, { error: "access_revoked", message: "You no longer have Manage Channels" });
    await expect(request("/api/alerts")).rejects.toBeInstanceOf(ApiError);
    expect(ended).toHaveBeenCalledWith(expect.objectContaining({ status: 401, code: "access_revoked" }));
    stop();
  });

  it("sends JSON bodies with a content type and no body for reads", async () => {
    const fetch = respond(200, {});
    await request("/api/alerts");
    await request("/api/replay", { method: "POST", body: { alert_id: "1" } });
    const [read, write] = fetch.mock.calls as unknown as [[string, RequestInit], [string, RequestInit]];
    expect(read[1]).toMatchObject({ method: "GET", body: undefined, credentials: "same-origin" });
    expect(write[1]).toMatchObject({ method: "POST", body: '{"alert_id":"1"}',
      headers: { Accept: "application/json", "Content-Type": "application/json" } });
  });
});

describe("api.candidates", () => {
  const query: CandidateQuery = { alertId: "5", guildId: null, search: "B1 ポスター", source: "mercari", verdict: "review", latest: true };

  it("asks for facet counts on the first page only", async () => {
    const fetch = respond(200, { items: [] });
    await api.candidates(query, null, 48);
    await api.candidates({ ...query, latest: false }, "MjAyNi0xMC0xNlQwMDowMDowMFp8MTA", 48);
    const calls = fetch.mock.calls as unknown as [[string], [string]];
    const first = new URL(calls[0][0], "http://filter.lab");
    const next = new URL(calls[1][0], "http://filter.lab");
    expect(Object.fromEntries(first.searchParams)).toEqual({
      limit: "48", latest: "1", alert_id: "5", search: "B1 ポスター", source: "mercari", verdict: "review", facets: "1",
    });
    expect(next.searchParams.get("cursor")).toBe("MjAyNi0xMC0xNlQwMDowMDowMFp8MTA");
    expect(next.searchParams.get("latest")).toBe("0");
    expect(next.searchParams.has("facets")).toBe(false);
  });

  it("asks for one server's listings only when no search is selected", async () => {
    const fetch = respond(200, { items: [] });
    await api.candidates({ ...query, alertId: null, guildId: "22" }, null, 48);
    await api.candidates({ ...query, guildId: "22" }, null, 48);
    const calls = fetch.mock.calls as unknown as [[string], [string]];
    expect(new URL(calls[0][0], "http://filter.lab").searchParams.get("guild_id")).toBe("22");
    expect(new URL(calls[1][0], "http://filter.lab").searchParams.has("guild_id")).toBe(false);
  });
});
