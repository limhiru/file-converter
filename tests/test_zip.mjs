import assert from "node:assert/strict";
import test from "node:test";
import { makeZip } from "../app/static/zip.js";

test("browser ZIP writes UTF-8 names, CRC-32 and a central directory", async () => {
  const blob = await makeZip([{ name: "한글.txt", blob: new Blob(["123456789"]) }]);
  const bytes = new Uint8Array(await blob.arrayBuffer()), view = new DataView(bytes.buffer);
  assert.equal(view.getUint32(0, true), 0x04034b50);
  assert.equal(view.getUint16(6, true), 0x0800);
  assert.equal(view.getUint32(14, true), 0xcbf43926); // standard CRC-32 test vector
  const length = view.getUint16(26, true);
  assert.equal(new TextDecoder().decode(bytes.slice(30, 30 + length)), "한글.txt");
  assert.equal(new TextDecoder().decode(bytes.slice(30 + length, 39 + length)), "123456789");
  const end = bytes.length - 22;
  assert.equal(view.getUint32(end, true), 0x06054b50);
  assert.equal(view.getUint16(end + 10, true), 1);
  assert.equal(view.getUint32(view.getUint32(end + 16, true), true), 0x02014b50);
});

test("browser ZIP resolves duplicate filenames and strips parent paths", async () => {
  const blob = await makeZip(["../같음.txt", "같음.txt"].map(name => ({ name, blob: new Blob(["ok"]) })));
  const text = new TextDecoder().decode(await blob.arrayBuffer());
  assert.ok(text.includes("같음 (1).txt"));
  assert.ok(!text.includes("../"));
});

test("browser ZIP enforces nonempty input and aggregate size", async () => {
  await assert.rejects(makeZip([]), /개수/);
  await assert.rejects(makeZip([{ name: "large", blob: { size: 257 * 1024 * 1024 } }]), /256 MB/);
});
