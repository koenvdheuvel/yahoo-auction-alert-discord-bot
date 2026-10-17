import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "./client";
import { keys, refreshAccess } from "./hooks";

describe("refreshAccess", () => {
  it("asks for the session, the searches and the servers again after a 404, and only then", () => {
    const client = new QueryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    refreshAccess(client, new ApiError("Alert no longer exists", 404, "not_found"));
    expect(invalidate.mock.calls.map(([filters]) => filters?.queryKey)).toEqual([keys.session, keys.alerts, keys.guilds]);
    invalidate.mockClear();
    refreshAccess(client, new ApiError("Busy", 429, "busy"));
    refreshAccess(client, new Error("network"));
    expect(invalidate).not.toHaveBeenCalled();
  });
});
