import * as Y from "yjs"

import {
  FrameType,
  CloseCode,
  PROTOCOL_VERSION,
  controlFrame,
  dataFrame,
  encodeFrame,
  decodeFrame,
  frameJson,
  frameToString,
  type Frame,
} from "./protocol"

export type ConnectionState =
  | "connecting" // socket open, HELLO not yet exchanged
  | "syncing" // HELLO done, waiting on SYNC_STEP1/2 or replay to finish
  | "live" // caught up, steady state
  | "offline" // socket closed, a reconnect would make sense
  | "closed" // closed for a reason that should NOT reconnect (bad ticket, unauthorized, protocol error)

export interface ProviderOptions {
  url: string
  maxFrameBytes?: number
  onStateChange?: (state: ConnectionState) => void
}

interface ServerHello {
  conn_id: string
  doc_id: string
  role: string
  server_seq: number
  resumed: boolean
  ping_interval_ms: number
}

const REMOTE_ORIGIN = "remote"

export class CollabProvider {
  readonly doc = new Y.Doc()

  private ws: WebSocket | null = null
  private state: ConnectionState = "connecting"
  private role: string | null = null

  private readonly clientId = Math.floor(Math.random() * 2 ** 32)
  private nextClientSeq = 1
  private lastAppliedSeq: bigint | null = null
  private resumeTargetSeq: bigint | null = null

  private pendingLocalUpdates: Uint8Array[] = []

  private readonly options: ProviderOptions
  private readonly maxFrameBytes: number
  private readonly onStateChange: (state: ConnectionState) => void

  constructor(options: ProviderOptions) {
    this.options = options
    this.maxFrameBytes = options.maxFrameBytes ?? 1024 * 1024
    this.onStateChange = options.onStateChange ?? (() => {})
    this.doc.on("update", this.handleLocalUpdate)
  }

  get connectionState(): ConnectionState {
    return this.state
  }

  get documentRole(): string | null {
    return this.role
  }

  connect(): void {
    this.ws?.close() 

    this.setState("connecting")
    const ws = new WebSocket(this.options.url)
    ws.binaryType = "arraybuffer"
    this.ws = ws

    ws.addEventListener("open", () => this.sendHello())
    ws.addEventListener("message", (event) => this.handleMessage(event.data as ArrayBuffer))
    ws.addEventListener("close", (event) => this.handleClose(event))
  }

  disconnect(): void {
    this.ws?.close(CloseCode.NORMAL)
    this.ws = null
  }


  private send(frame: Frame): void {
    if (this.ws?.readyState !== WebSocket.OPEN) return
    this.ws.send(encodeFrame(frame))
  }

  private sendHello(): void {
    this.send(
      controlFrame(FrameType.CLIENT_HELLO, {
        protocol: PROTOCOL_VERSION,
        client_id: this.clientId,
        last_seq: this.lastAppliedSeq === null ? null : Number(this.lastAppliedSeq),
      }),
    )
  }

  private handleLocalUpdate = (update: Uint8Array, origin: unknown): void => {
    if (origin === REMOTE_ORIGIN) return

    if (this.state !== "live") {
      this.pendingLocalUpdates.push(update)
      return
    }
    this.send(dataFrame(FrameType.UPDATE, update, BigInt(this.nextClientSeq++)))
  }

  private flushPendingLocalUpdates(): void {
    const pending = this.pendingLocalUpdates
    this.pendingLocalUpdates = []
    for (const update of pending) {
      this.send(dataFrame(FrameType.UPDATE, update, BigInt(this.nextClientSeq++)))
    }
  }


  private handleMessage(raw: ArrayBuffer): void {
    let frame: Frame
    try {
      frame = decodeFrame(raw, this.maxFrameBytes)
    } catch (err) {
      console.error("collab: bad frame from server", err)
      this.ws?.close(CloseCode.PROTOCOL_ERROR)
      return
    }

    switch (frame.type) {
      case FrameType.SERVER_HELLO:
        this.handleServerHello(frame)
        return
      case FrameType.SYNC_STEP1:
        this.handleSyncStep1(frame)
        return
      case FrameType.SYNC_STEP2:
        Y.applyUpdate(this.doc, frame.payload, REMOTE_ORIGIN)
        if (this.state === "syncing" && this.resumeTargetSeq === null) {
          this.setState("live")
        }
        return
      case FrameType.UPDATE:
        Y.applyUpdate(this.doc, frame.payload, REMOTE_ORIGIN)
        this.lastAppliedSeq = frame.seq
        if (this.resumeTargetSeq !== null && frame.seq >= this.resumeTargetSeq) {
          this.resumeTargetSeq = null
          this.setState("live")
        }
        return
      case FrameType.ACK:
        return
      case FrameType.PING:
        this.send(controlFrame(FrameType.PONG, frameJson(frame)))
        return
      case FrameType.ERROR:
        console.error("collab: server error", frameJson(frame))
        return
      default:
        console.warn("collab: unhandled frame", frameToString(frame))
    }
  }

  private handleServerHello(frame: Frame): void {
    const hello = frameJson(frame) as unknown as ServerHello
    this.role = hello.role
    const serverSeq = BigInt(hello.server_seq)

    if (hello.resumed) {
      if (this.lastAppliedSeq !== null && this.lastAppliedSeq >= serverSeq) {
        this.setState("live")
      } else {
        this.resumeTargetSeq = serverSeq
        this.setState("syncing") 
      }
    } else {
      this.setState("syncing") 
    }
  }

  private handleSyncStep1(frame: Frame): void {
    const diff = Y.encodeStateAsUpdate(this.doc, frame.payload)
    this.send(dataFrame(FrameType.SYNC_STEP2, diff))

    this.send(dataFrame(FrameType.SYNC_STEP1, Y.encodeStateVector(this.doc)))
  }

  private handleClose(event: CloseEvent): void {
    this.ws = null
    const terminal = new Set<number>([
      CloseCode.TICKET_INVALID,
      CloseCode.PROTOCOL_ERROR,
      CloseCode.UNAUTHORIZED,
      CloseCode.DOC_NOT_FOUND,
    ])
    this.setState(terminal.has(event.code) ? "closed" : "offline")
  }

  private setState(next: ConnectionState): void {
    if (this.state === next) return
    const enteringLive = next === "live"
    this.state = next
    this.onStateChange(next)
    if (enteringLive) this.flushPendingLocalUpdates()
  }
}
