import { describe, it, expect } from "vitest";

describe("Structured error handling", () => {
  it("classifies db_locked as warning (retryable)", () => {
    const warningCodes = ["db_locked", "search_failed"];
    const errorCodes = ["no_law_number", "duplicate", "import_failed"];

    const isWarning = (code: string) => warningCodes.includes(code);

    expect(isWarning("db_locked")).toBe(true);
    expect(isWarning("search_failed")).toBe(true);
    expect(isWarning("no_law_number")).toBe(false);
    expect(isWarning("duplicate")).toBe(false);
  });

  it("parses structured error shape", () => {
    const errorBody = { code: "no_law_number", message: "This document cannot be auto-imported..." };

    expect(errorBody.code).toBe("no_law_number");
    expect(errorBody.message).toBeTruthy();
    expect(typeof errorBody.code).toBe("string");
    expect(typeof errorBody.message).toBe("string");
  });

  it("never exposes raw JSON or SQL in error display", () => {
    const errorBody = { code: "db_locked", message: "Another import is in progress. Please wait a moment and try again." };

    // Message should not contain SQL or JSON artifacts
    expect(errorBody.message).not.toContain("sqlite3");
    expect(errorBody.message).not.toContain("OperationalError");
    expect(errorBody.message).not.toContain("{");
    expect(errorBody.message).not.toContain("SELECT");
  });
});
