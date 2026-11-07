/**
 * Fake axios adapter for tests: requests never touch the network (CLAUDE.md rule 7).
 * Routes are keyed "METHOD /path" (path without the /api base URL and without the query string).
 */
import { AxiosError, AxiosHeaders, type AxiosAdapter, type InternalAxiosRequestConfig } from "axios";

import { api } from "@/api/client";

export interface MockResponse {
  status?: number;
  data?: unknown;
  headers?: Record<string, string>;
}

export type MockHandler = MockResponse | ((config: InternalAxiosRequestConfig) => MockResponse | Promise<MockResponse>);

export interface MockApi {
  calls: InternalAxiosRequestConfig[];
}

export function errorBody(code: string, message: string, details: Record<string, unknown> = {}) {
  return { error: { code, message, details } };
}

export function mockApi(routes: Record<string, MockHandler>): MockApi {
  const state: MockApi = { calls: [] };
  const adapter: AxiosAdapter = async (config) => {
    state.calls.push(config);
    const key = `${(config.method ?? "get").toUpperCase()} ${config.url ?? ""}`;
    const handler = routes[key];
    if (!handler) throw new Error(`mockApi: no handler for ${key}`);
    const res = typeof handler === "function" ? await handler(config) : handler;
    const response = {
      data: res.data,
      status: res.status ?? 200,
      statusText: String(res.status ?? 200),
      headers: AxiosHeaders.from(res.headers ?? {}),
      config,
      request: {},
    };
    if (response.status >= 400) {
      throw new AxiosError(`HTTP ${response.status}`, AxiosError.ERR_BAD_RESPONSE, config, {}, response);
    }
    return response;
  };
  api.defaults.adapter = adapter;
  return state;
}

/** Default for every test: any request without a mock fails loudly instead of using the network. */
export function blockNetwork(): void {
  api.defaults.adapter = async (config) => {
    throw new Error(`Unmocked request in test: ${config.method?.toUpperCase()} ${config.url}`);
  };
}
