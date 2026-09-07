/**
 * Wire protocol codec — the TypeScript mirror of app/protocol.py.
 *
 * This is the ONLY place in the frontend that knows the byte layout of a
 * frame. See PROTOCOL.md for the normative spec.
 *
 * `seq` is a bigint, not a number. The wire format is a genuine unsigned
 * 64-bit integer ("!BQ" in Python's struct module); JS numbers only carry
 * full precision up to 2^53-1. bigint costs a little ergonomic friction
 * (0n instead of 0) in exchange for never silently corrupting a seq value.
 *
 * FrameType/CloseCode are `as const` objects, not `enum` — this project's
 * tsconfig sets erasableSyntaxOnly, which forbids `enum` because it compiles
 * to a real runtime object rather than erasing away like a type does. The
 * cost: plain const objects don't get TS's automatic numeric-enum reverse
 * mapping, so frameTypeName() below does that lookup by hand.
 */

export const PROTOCOL_VERSION = 1

export const HEADER_SIZE = 9 // 1 byte type + 8 bytes seq, big-endian
const MAX_SEQ = (1n << 64n) - 1n

export const FrameType = {
  // Control frames — JSON payload.
  CLIENT_HELLO: 0x01,
  SERVER_HELLO: 0x02,
  ACK: 0x03,
  ERROR: 0x04,
  PING: 0x05,
  PONG: 0x06,

  // Data frames — y-protocols binary payload.
  SYNC_STEP1: 0x10,
  SYNC_STEP2: 0x11,
  UPDATE: 0x12,
  AWARENESS: 0x13,
} as const

export type FrameType = (typeof FrameType)[keyof typeof FrameType]

const VALID_FRAME_TYPES = new Set<number>(Object.values(FrameType))

const FRAME_TYPE_NAMES = new Map<FrameType, string>(
  Object.entries(FrameType).map(([name, value]) => [value, name]),
)

function frameTypeName(type: FrameType): string {
  return FRAME_TYPE_NAMES.get(type) ?? `UNKNOWN(0x${type.toString(16)})`
}

const CONTROL_FRAMES = new Set<FrameType>([
  FrameType.CLIENT_HELLO,
  FrameType.SERVER_HELLO,
  FrameType.ACK,
  FrameType.ERROR,
  FrameType.PING,
  FrameType.PONG,
])

export const CloseCode = {
  NORMAL: 1000,
  GOING_AWAY: 1001,
  TICKET_INVALID: 4001,
  PROTOCOL_ERROR: 4002,
  UNAUTHORIZED: 4003,
  DOC_NOT_FOUND: 4004,
  SLOW_CONSUMER: 4008,
  SERVER_DRAINING: 4009,
  RATE_LIMITED: 4029,
} as const

export type CloseCode = (typeof CloseCode)[keyof typeof CloseCode]

export class ProtocolError extends Error {
  readonly closeCode: CloseCode

  constructor(message: string, closeCode: CloseCode = CloseCode.PROTOCOL_ERROR) {
    super(message)
    this.name = "ProtocolError"
    this.closeCode = closeCode
  }
}

export interface Frame {
  type: FrameType
  seq: bigint
  /** A view into the frame's underlying buffer, not a copy — see decodeFrame. */
  payload: Uint8Array
}

function isControlFrame(type: FrameType): boolean {
  return CONTROL_FRAMES.has(type)
}

export function controlFrame(type: FrameType, data: unknown, seq = 0n): Frame {
  if (!isControlFrame(type)) {
    throw new Error(`${frameTypeName(type)} is not a control frame`)
  }
  const payload = new TextEncoder().encode(JSON.stringify(data))
  return { type, seq, payload }
}

export function dataFrame(type: FrameType, payload: Uint8Array, seq = 0n): Frame {
  if (isControlFrame(type)) {
    throw new Error(`${frameTypeName(type)} is not a data frame`)
  }
  return { type, seq, payload }
}

export function encodeFrame(frame: Frame): ArrayBuffer {
  if (frame.seq < 0n || frame.seq > MAX_SEQ) {
    throw new Error(`seq out of range: ${frame.seq}`)
  }

  const buffer = new ArrayBuffer(HEADER_SIZE + frame.payload.byteLength)
  const view = new DataView(buffer)
  view.setUint8(0, frame.type)
  view.setBigUint64(1, frame.seq, false) // false = big-endian, matches "!BQ"
  new Uint8Array(buffer, HEADER_SIZE).set(frame.payload)
  return buffer
}

export function decodeFrame(raw: ArrayBuffer, maxFrameBytes: number): Frame {
  if (raw.byteLength > maxFrameBytes) {
    throw new ProtocolError(`frame too large: ${raw.byteLength} > ${maxFrameBytes}`)
  }
  if (raw.byteLength < HEADER_SIZE) {
    throw new ProtocolError(`frame too short: ${raw.byteLength} < ${HEADER_SIZE}`)
  }

  const view = new DataView(raw)
  const typeCode = view.getUint8(0)
  const seq = view.getBigUint64(1, false)

  if (!VALID_FRAME_TYPES.has(typeCode)) {
    throw new ProtocolError(`unknown frame type: 0x${typeCode.toString(16).padStart(2, "0")}`)
  }

  // A view, not a slice-copy — the payload shares memory with `raw`. Fine as
  // long as callers treat `raw` (typically a fresh WebSocket message) as
  // consumed once decoded, same assumption app/protocol.py's callers make.
  const payload = new Uint8Array(raw, HEADER_SIZE)
  return { type: typeCode as FrameType, seq, payload }
}

export function frameJson(frame: Frame): Record<string, unknown> {
  if (!isControlFrame(frame.type)) {
    throw new ProtocolError(`${frameTypeName(frame.type)} has no JSON payload`)
  }

  let parsed: unknown
  try {
    parsed = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(frame.payload))
  } catch {
    throw new ProtocolError(`${frameTypeName(frame.type)} payload is not valid JSON`)
  }

  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new ProtocolError(`${frameTypeName(frame.type)} payload must be a JSON object`)
  }
  return parsed as Record<string, unknown>
}

export function frameToString(frame: Frame): string {
  return `Frame(${frameTypeName(frame.type)}, seq=${frame.seq}, ${frame.payload.byteLength}B)`
}
