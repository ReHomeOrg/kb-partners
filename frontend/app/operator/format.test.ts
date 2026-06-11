import { describe, expect, it } from "vitest";

import { operatorActions } from "./format";

describe("operatorActions", () => {
  it("NEW → классификация", () => {
    expect(operatorActions("NEW").map((a) => a.value)).toEqual(["classify"]);
  });

  it("CLASSIFIED → реклассификация + подбор", () => {
    expect(operatorActions("CLASSIFIED").map((a) => a.value)).toEqual(["classify", "assign"]);
  });

  it("ASSIGNED → диспетчеризация", () => {
    expect(operatorActions("ASSIGNED").map((a) => a.value)).toEqual(["dispatch"]);
  });

  it("FAILED_DISPATCH → переназначение (assign)", () => {
    expect(operatorActions("FAILED_DISPATCH").map((a) => a.value)).toEqual(["assign"]);
  });

  it("терминальные → нет действий", () => {
    expect(operatorActions("PAID")).toEqual([]);
    expect(operatorActions("CANCELLED")).toEqual([]);
  });
});
