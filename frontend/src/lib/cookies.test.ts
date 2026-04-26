import { describe, expect, test } from "vitest";
import { signPkceCookie, verifyPkceCookie } from "./cookies";

const SECRET = "test-secret-at-least-32-bytes-long-aaaaaaaa";

describe("PKCE cookie sign/verify", () => {
  test("verify returns the original payload", async () => {
    const payload = { verifier: "v123", state: "s123", callbackUrl: "/laws" };
    const signed = await signPkceCookie(payload, SECRET);
    const out = await verifyPkceCookie(signed, SECRET);
    expect(out).toEqual(payload);
  });

  test("verify returns null when signature is tampered", async () => {
    const payload = { verifier: "v", state: "s", callbackUrl: "/" };
    const signed = await signPkceCookie(payload, SECRET);
    const tampered = signed.slice(0, -2) + (signed.endsWith("ab") ? "cd" : "ab");
    expect(await verifyPkceCookie(tampered, SECRET)).toBeNull();
  });

  test("verify returns null when wrong secret is used", async () => {
    const payload = { verifier: "v", state: "s", callbackUrl: "/" };
    const signed = await signPkceCookie(payload, SECRET);
    expect(await verifyPkceCookie(signed, "different-secret-xxxxxxxxxxxxxxxxxxxx")).toBeNull();
  });

  test("verify returns null when cookie has no dot separator", async () => {
    expect(await verifyPkceCookie("nodothere", SECRET)).toBeNull();
  });
});
