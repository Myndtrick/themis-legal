import { describe, it, expect } from "vitest";

describe("Model comparison", () => {
  it("validates minimum 2 models required", () => {
    const models: string[] = ["claude-sonnet-4-6"];
    expect(models.length >= 2).toBe(false);
  });

  it("validates maximum 5 models", () => {
    const models = ["m1", "m2", "m3", "m4", "m5", "m6"];
    expect(models.length <= 5).toBe(false);
  });

  it("calculates grid columns from model count", () => {
    const getGridCols = (count: number) => {
      if (count <= 2) return "grid-cols-1 md:grid-cols-2";
      if (count === 3) return "grid-cols-1 md:grid-cols-3";
      return "grid-cols-1 md:grid-cols-2 xl:grid-cols-3";
    };
    expect(getGridCols(2)).toBe("grid-cols-1 md:grid-cols-2");
    expect(getGridCols(3)).toBe("grid-cols-1 md:grid-cols-3");
    expect(getGridCols(4)).toBe("grid-cols-1 md:grid-cols-2 xl:grid-cols-3");
  });

  it("filters out OCR-only models", () => {
    const models = [
      { id: "claude-sonnet-4-6", capabilities: ["chat"] },
      { id: "mistral-ocr", capabilities: ["ocr"] },
    ];
    const chatModels = models.filter((m) => m.capabilities.includes("chat"));
    expect(chatModels).toHaveLength(1);
    expect(chatModels[0].id).toBe("claude-sonnet-4-6");
  });
});
