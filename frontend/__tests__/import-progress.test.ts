import { describe, it, expect } from "vitest";

describe("Import progress parsing", () => {
  it("parses SSE progress events correctly", () => {
    const events: any[] = [];
    const sseData = [
      'event: progress\ndata: {"phase":"metadata","message":"Fetching law metadata"}\n\n',
      'event: progress\ndata: {"phase":"version","current":1,"total":3,"message":"Importing version 1"}\n\n',
      'event: complete\ndata: {"law_id":1,"title":"Legea 506/2004","versions_imported":3}\n\n',
    ];

    for (const chunk of sseData) {
      const lines = chunk.split("\n");
      let currentEvent = "progress";
      for (const line of lines) {
        if (line.startsWith("event:")) currentEvent = line.slice(6).trim();
        else if (line.startsWith("data:")) {
          events.push({ event: currentEvent, data: JSON.parse(line.slice(5).trim()) });
        }
      }
    }

    expect(events).toHaveLength(3);
    expect(events[0].data.phase).toBe("metadata");
    expect(events[1].data.current).toBe(1);
    expect(events[1].data.total).toBe(3);
    expect(events[2].data.law_id).toBe(1);
  });

  it("calculates progress percentage", () => {
    const progress = { current: 3, total: 9 };
    const pct = Math.round((progress.current / progress.total) * 100);
    expect(pct).toBe(33);
  });
});
