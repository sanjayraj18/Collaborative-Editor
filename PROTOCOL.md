# Collab Wire Protocol v1

## 1. Transport

Single WebSocket, binary frames only. A text frame is a protocol violation
and closes the connection with `4002`.

    ws://<host>/ws?doc=<doc_id>&ticket=<ticket>

The ticket travels in the query string because browsers cannot set custom
headers on a WebSocket handshake — the `WebSocket` constructor exposes no
such API. This is safe only because the ticket is single-use, HMAC-signed,
bound to one document, and expires in 30 seconds. See Phase 1.

## 2. Envelope

Every frame:

    +--------+------------------+-------------------+
    | type   | seq              | payload           |
    | u8     | u64 big-endian   | 0..N bytes        |
    +--------+------------------+-------------------+
    | byte 0 | bytes 1..8       | bytes 9..         |
    +--------+------------------+-------------------+

Header is a fixed 9 bytes. Payload is JSON (UTF-8) for control frames and
opaque binary for data frames.

## 3. Frame types

### Control frames — payload is a JSON object

| Code | Name           | Dir | Payload |
|------|----------------|-----|---------|
| 0x01 | CLIENT_HELLO   | C→S | `{"protocol":1,"client_id":<u32>,"last_seq":<u64\|null>}` |
| 0x02 | SERVER_HELLO   | S→C | `{"conn_id":<str>,"doc_id":<str>,"role":"reader"\|"writer","server_seq":<u64>,"resumed":<bool>,"ping_interval_ms":<int>}` |
| 0x03 | ACK            | S→C | `{"client_seq":<u64>,"server_seq":<u64>}` |
| 0x04 | ERROR          | S→C | `{"code":<int>,"message":<str>}` |
| 0x05 | PING           | S→C | `{"t":<epoch_ms>}` |
| 0x06 | PONG           | C→S | `{"t":<epoch_ms>}` |

### Data frames — payload is a y-protocols message

| Code | Name       | Dir | Payload |
|------|------------|-----|---------|
| 0x10 | SYNC_STEP1 | ↔   | Yjs state vector |
| 0x11 | SYNC_STEP2 | ↔   | Yjs update (diff against the received state vector) |
| 0x12 | UPDATE     | ↔   | Yjs incremental update |
| 0x13 | AWARENESS  | ↔   | y-protocols awareness update |

## 4. The `seq` field

Meaningful **only on `UPDATE` and `ACK`**. Every other frame sets it to `0`
and receivers must ignore it.

| Direction | Frame  | Meaning |
|-----------|--------|---------|
| S→C       | UPDATE | Server-assigned room sequence. Strictly increasing, gapless, per document. This is the resume cursor. |
| C→S       | UPDATE | The client's own monotonic counter (`client_seq`), used with `client_id` for dedupe. |
| S→C       | ACK    | The server sequence assigned to the client's op (payload carries the `client_seq` it answers). |

Sequence numbers are **per document**, assigned solely by the room task
(Phase 3). They are not global and not comparable across documents.

## 5. Connection lifecycle

    1. C: POST /api/docs/{doc_id}/ticket        (HTTP, authenticated)
       S: {"ticket": "...", "expires_at": ...}

    2. C: WebSocket upgrade with ?doc=&ticket=
       S: check Origin -> check ticket signature -> burn nonce
          -> check ticket doc_id matches ?doc -> authorize(user, doc)
          -> accept, or reject with 4001/4003/4004

    3. C: CLIENT_HELLO         (must arrive within 5s, else 4002)
       S: SERVER_HELLO

    4a. resumed == true:
        S: UPDATE(last_seq+1) .. UPDATE(server_seq)     replay, in order
    4b. resumed == false:
        S: SYNC_STEP1(server state vector)
        C: SYNC_STEP2(diff)  then  SYNC_STEP1(client state vector)
        S: SYNC_STEP2(diff)

    5. Steady state: UPDATE, AWARENESS, PING/PONG in any order.

A client that sends any frame other than `CLIENT_HELLO` as its first frame
is closed with `4002`.

## 6. Resume

`CLIENT_HELLO.last_seq` is the highest server sequence the client has
**applied**. The server replays `last_seq+1 .. server_seq` from its ring
buffer.

If `last_seq` is older than the oldest entry in the ring, the server sets
`resumed: false` and falls back to a full sync (step 4b). Resume is an
optimization, never a correctness requirement.

Duplicate `UPDATE`s from a client are dropped by `(client_id, client_seq)`.
Yjs updates are idempotent by construction, so a replayed op is harmless —
the dedupe exists to keep the op log and sequence space clean.

## 7. Close codes

| Code | Name            | Cause | Client should |
|------|-----------------|-------|---------------|
| 1000 | NORMAL          | Clean shutdown by either side | Not reconnect |
| 1001 | GOING_AWAY      | Tab closed / server stopping | Reconnect with backoff |
| 4001 | TICKET_INVALID  | Missing, malformed, expired, or already-used ticket | Fetch a new ticket, reconnect |
| 4002 | PROTOCOL_ERROR  | Bad frame, unknown type, text frame, oversized, no HELLO | Not reconnect (bug) |
| 4003 | UNAUTHORIZED    | Authenticated but not permitted on this document | Not reconnect |
| 4004 | DOC_NOT_FOUND   | Document does not exist | Not reconnect |
| 4008 | SLOW_CONSUMER   | Send queue exceeded its bound past the grace window | Reconnect and resume |
| 4009 | SERVER_DRAINING | Node shutting down or room migrating (V2) | Reconnect with backoff |
| 4029 | RATE_LIMITED    | Too many ops from one connection | Reconnect after a delay |

`4008` is not an error. It is the designed outcome of the backpressure
policy: evicting a lagging client is safe precisely because resume makes
reconnection cheap and lossless.

## 8. Limits

| Limit | Value | Enforced in |
|-------|-------|-------------|
| Max frame | 1 MiB | Phase 2 reader |
| Max awareness payload | 64 KiB | Phase 5 |
| Send queue | 256 frames / 8 MiB | Phase 2 writer |
| Ping interval | 20s | Phase 4 |
| Pong deadline | 45s | Phase 4 |
| HELLO deadline | 5s | Phase 2 |
| Resume ring | 1024 ops per document | Phase 3 |

## 9. Versioning

`CLIENT_HELLO.protocol` must equal `1`. Any other value is answered with
`ERROR` then close `4002`. Frame codes are append-only — never renumber an
existing type.
