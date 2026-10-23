// ZIP (STORE) writer: browser-native downloads, UTF-8 names, CRC-32; no CDN dependency.
const encoder = new TextEncoder();
const table = Uint32Array.from({ length: 256 }, (_, index) => {
  let crc = index;
  for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0);
  return crc >>> 0;
});

function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) crc = table[(crc ^ byte) & 255] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

export async function makeZip(files) {
  if (!files.length || files.length > 65535) throw new Error("ZIP에 담을 파일 개수를 확인하세요.");
  const total = files.reduce((size, file) => size + file.blob.size, 0);
  if (total > 256 * 1024 * 1024) throw new Error("전체 결과가 256 MB를 초과합니다. 개별 파일로 다운로드하세요.");
  const chunks = [], central = [], used = new Set();
  let offset = 0;
  for (const file of files) {
    const original = file.name.replaceAll("\\", "/").split("/").pop().replace(/[\x00-\x1f]/g, "") || "file";
    let name = original, index = 1;
    while (used.has(name.toLowerCase())) {
      const dot = original.lastIndexOf(".");
      name = dot > 0 ? `${original.slice(0, dot)} (${index++})${original.slice(dot)}` : `${original} (${index++})`;
    }
    used.add(name.toLowerCase());
    const encoded = encoder.encode(name);
    if (encoded.length > 65535) throw new Error("파일 이름이 너무 깁니다.");
    const bytes = new Uint8Array(await file.blob.arrayBuffer()), crc = crc32(bytes);
    const local = new Uint8Array(30 + encoded.length), header = new DataView(local.buffer);
    header.setUint32(0, 0x04034b50, true);
    header.setUint16(4, 20, true);
    header.setUint16(6, 0x0800, true);
    header.setUint16(12, 0x21, true); // 1980-01-01
    header.setUint32(14, crc, true);
    header.setUint32(18, bytes.length, true);
    header.setUint32(22, bytes.length, true);
    header.setUint16(26, encoded.length, true);
    local.set(encoded, 30);
    chunks.push(local, bytes);
    const entry = new Uint8Array(46 + encoded.length), view = new DataView(entry.buffer);
    view.setUint32(0, 0x02014b50, true);
    view.setUint16(4, 20, true);
    view.setUint16(6, 20, true);
    view.setUint16(8, 0x0800, true);
    view.setUint16(14, 0x21, true);
    view.setUint32(16, crc, true);
    view.setUint32(20, bytes.length, true);
    view.setUint32(24, bytes.length, true);
    view.setUint16(28, encoded.length, true);
    view.setUint32(42, offset, true);
    entry.set(encoded, 46);
    central.push(entry);
    offset += local.length + bytes.length;
  }
  const size = central.reduce((sum, entry) => sum + entry.length, 0);
  const end = new Uint8Array(22), view = new DataView(end.buffer);
  view.setUint32(0, 0x06054b50, true);
  view.setUint16(8, files.length, true);
  view.setUint16(10, files.length, true);
  view.setUint32(12, size, true);
  view.setUint32(16, offset, true);
  return new Blob([...chunks, ...central, end], { type: "application/zip" });
}
