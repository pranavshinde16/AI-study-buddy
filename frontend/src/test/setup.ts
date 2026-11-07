import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach } from "vitest";
import { cleanup } from "@testing-library/react";

import { blockNetwork } from "./mockApi";

beforeEach(() => {
  localStorage.clear();
  blockNetwork();
});

afterEach(() => cleanup());
