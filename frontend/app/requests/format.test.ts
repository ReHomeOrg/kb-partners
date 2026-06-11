import { describe, expect, it } from "vitest";

import { partnerActions, statusLabel } from "./format";

describe("statusLabel", () => {
  it("маппит известные статусы и падает на исходный для неизвестных", () => {
    expect(statusLabel("DISPATCHED")).toBe("Передана вам");
    expect(statusLabel("DONE")).toBe("Выполнена");
    expect(statusLabel("WEIRD")).toBe("WEIRD");
  });
});

describe("partnerActions", () => {
  it("DISPATCHED → принять/отклонить", () => {
    expect(partnerActions("DISPATCHED").map((a) => a.value)).toEqual(["accepted", "rejected"]);
  });

  it("ACCEPTED → начать выполнение, IN_PROGRESS → завершить", () => {
    expect(partnerActions("ACCEPTED").map((a) => a.value)).toEqual(["in_progress"]);
    expect(partnerActions("IN_PROGRESS").map((a) => a.value)).toEqual(["done"]);
  });

  it("в прочих статусах действий нет", () => {
    expect(partnerActions("PAID")).toEqual([]);
    expect(partnerActions("NEW")).toEqual([]);
  });
});
