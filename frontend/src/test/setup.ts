import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach } from "vitest";
import { cleanup, configure } from "@testing-library/react";

import { blockNetwork } from "./mockApi";

// Pages are lazy-loaded (React.lazy). On a busy machine (e.g. Docker builds running) the first import of a page
// can take longer than Testing Library's default 1 s wait, so findBy* queries get more time. Passing tests are
// not slowed down: findBy* returns as soon as the element appears.
configure({ asyncUtilTimeout: 5000 });

beforeEach(() => {
  localStorage.clear();
  blockNetwork();
});

afterEach(() => cleanup());
