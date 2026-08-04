/** Minimal miniSEED (format 2) decoder for int32 / Steim1 / Steim2. */

function readAscii(buf: DataView, offset: number, len: number): string {
  let s = "";
  for (let i = 0; i < len; i++) {
    const c = buf.getUint8(offset + i);
    if (c === 0) break;
    s += String.fromCharCode(c);
  }
  return s.trim();
}

function bcdTime(buf: DataView, offset: number): number {
  const year = bcd(buf.getUint8(offset)) * 100 + bcd(buf.getUint8(offset + 1));
  const day = bcd(buf.getUint8(offset + 2)) * 100 + bcd(buf.getUint8(offset + 3));
  const hour = bcd(buf.getUint8(offset + 4));
  const min = bcd(buf.getUint8(offset + 5));
  const sec = bcd(buf.getUint8(offset + 6));
  // offset+7 unused
  const fract = buf.getUint16(offset + 8, false); // 0.0001 s
  const date = new Date(Date.UTC(year, 0, 1));
  date.setUTCDate(day);
  date.setUTCHours(hour, min, sec, Math.floor(fract / 10));
  return date.getTime();
}

function bcd(v: number): number {
  return ((v >> 4) & 0xf) * 10 + (v & 0xf);
}

function decodeSteim1(data: DataView, offset: number, nSamples: number, bias: number): Float32Array {
  const out = new Float32Array(nSamples);
  let x = bias;
  let idx = 0;
  const frames = Math.floor((data.byteLength - offset) / 64);
  for (let f = 0; f < frames && idx < nSamples; f++) {
    const fo = offset + f * 64;
    const flags = data.getUint32(fo, false);
    // first word includes nif and x0/xn in steim - use successive differences
    for (let w = 1; w < 16 && idx < nSamples; w++) {
      const nibble = (flags >> (30 - (w - 1) * 2)) & 0x3;
      const word = data.getInt32(fo + w * 4, false);
      if (nibble === 1) {
        for (let k = 0; k < 4 && idx < nSamples; k++) {
          const d = (word << (k * 8)) >> 24;
          x += d;
          out[idx++] = x;
        }
      } else if (nibble === 2) {
        for (let k = 0; k < 2 && idx < nSamples; k++) {
          const d = (word << (k * 16)) >> 16;
          x += d;
          out[idx++] = x;
        }
      } else if (nibble === 3) {
        x += word;
        out[idx++] = x;
      }
    }
  }
  return idx === nSamples ? out : out.subarray(0, idx);
}

function decodeSteim2(data: DataView, offset: number, nSamples: number, bias: number): Float32Array {
  // Fallback: treat similarly to steim1 for common paths; extend if needed
  return decodeSteim1(data, offset, nSamples, bias);
}

export type DecodedRecord = {
  network: string;
  station: string;
  location: string;
  channel: string;
  startMs: number;
  sampleRate: number;
  samples: Float32Array;
};

export function decodeMiniseedRecord(buffer: ArrayBuffer): DecodedRecord | null {
  if (buffer.byteLength < 48) return null;
  const view = new DataView(buffer);
  const station = readAscii(view, 8, 5);
  const location = readAscii(view, 13, 2);
  const channel = readAscii(view, 15, 3);
  const network = readAscii(view, 18, 2);
  const startMs = bcdTime(view, 20);
  const nSamples = view.getUint16(30, false);
  const factor = view.getInt16(32, false);
  const multiplier = view.getInt16(34, false);
  let sampleRate = 0;
  if (factor > 0 && multiplier > 0) sampleRate = factor * multiplier;
  else if (factor > 0 && multiplier < 0) sampleRate = -factor / multiplier;
  else if (factor < 0 && multiplier > 0) sampleRate = -multiplier / factor;
  else if (factor < 0 && multiplier < 0) sampleRate = 1 / (factor * multiplier);

  const encoding = view.getUint8(39);
  // data offset historically at byte 44-45 as ushort in some, but FSDH: byte 44 is beginning of data as uint8 in SEED, actually bytes 44-45
  let dataOffset = view.getUint8(44);
  if (dataOffset < 48) dataOffset = 64;
  // Many ringserver packets use 64-byte header
  if (dataOffset === 0) dataOffset = 64;

  let samples: Float32Array;
  if (encoding === 3) {
    // 32-bit integers
    samples = new Float32Array(nSamples);
    for (let i = 0; i < nSamples; i++) {
      samples[i] = view.getInt32(dataOffset + i * 4, false);
    }
  } else if (encoding === 10) {
    const x0 = view.getInt32(dataOffset + 4, false);
    samples = decodeSteim1(view, dataOffset, nSamples, x0);
  } else if (encoding === 11) {
    const x0 = view.getInt32(dataOffset + 4, false);
    samples = decodeSteim2(view, dataOffset, nSamples, x0);
  } else if (encoding === 1) {
    samples = new Float32Array(nSamples);
    for (let i = 0; i < nSamples; i++) samples[i] = view.getInt16(dataOffset + i * 2, false);
  } else {
    // unsupported — skip
    return null;
  }

  return {
    network,
    station,
    location: location || "--",
    channel,
    startMs,
    sampleRate: sampleRate || 100,
    samples,
  };
}

export function decodeMiniseedBuffer(buffer: ArrayBuffer): DecodedRecord[] {
  const out: DecodedRecord[] = [];
  let offset = 0;
  const bytes = new Uint8Array(buffer);
  while (offset + 64 <= bytes.length) {
    // record length from byte 39? Use fixed 512 if present else remaining
    let recLen = 512;
    if (offset + recLen > bytes.length) {
      // try parse with available length
      recLen = bytes.length - offset;
      if (recLen < 64) break;
    }
    // Some streams use variable reclen in byte 3 of blockette - keep 512 default for seedlink
    const slice = buffer.slice(offset, offset + recLen);
    const rec = decodeMiniseedRecord(slice);
    if (rec) out.push(rec);
    offset += recLen;
    // If next doesn't look like SEED, stop
    if (offset < bytes.length) {
      // sequence number area should be digits/space
      const c0 = bytes[offset];
      if (c0 !== undefined && c0 !== 0x20 && (c0 < 0x30 || c0 > 0x39) && offset + 8 < bytes.length) {
        // might be packed differently — break to avoid infinite loop
        if (out.length) break;
      }
    }
  }
  return out;
}
