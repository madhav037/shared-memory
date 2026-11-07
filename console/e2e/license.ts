import { createPrivateKey, sign } from "node:crypto";

/**
 * TEST-ONLY signing key, the same seed as tests/license_keys.py. The journey server (tests/console_e2e_server.py) trusts
 * its public half and nothing else does: a real server's built-in public key is a different pair.
 */
const TEST_SEED = Buffer.from(Array.from({ length: 32 }, (_, place) => place));
const PKCS8_ED25519_PREFIX = Buffer.from("302e020100300506032b657004220420", "hex");

const b64 = (raw: Buffer) => raw.toString("base64url");

/** A license key signed by the test key, in the format of src/shared_memory/license.py. */
export function signLicense(fields: { team: string; member_cap: number; issued: string; expires: string; key_id: string }) {
  const payload = JSON.stringify(
    Object.fromEntries(Object.entries(fields).sort(([one], [other]) => (one < other ? -1 : 1))),
  );
  const signed = `sm1.${b64(Buffer.from(payload))}`;
  const key = createPrivateKey({
    key: Buffer.concat([PKCS8_ED25519_PREFIX, TEST_SEED]),
    format: "der",
    type: "pkcs8",
  });
  return `${signed}.${b64(sign(null, Buffer.from(signed), key))}`;
}
