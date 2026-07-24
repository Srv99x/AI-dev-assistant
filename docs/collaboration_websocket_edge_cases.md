# Collaboration WebSocket — Edge Case Reference

## Protocol
The real-time collaboration module uses WebSockets to connect multiple clients to a single session identified by the `session_id` URL parameter. A global manager controls instances of `CollaborationRoom` representing individual sessions.

## Message Types
- `ping`: Keepalive check; returns `pong`.
- `code_update`: Applies code changes and increments versions. Broadcasts update to all users.
- `cursor_update`: Updates a user's cursor position. Broadcasts to everyone except the sender.
- `comment_added`: Appends a comment to the session. Broadcasts to all users.

## Edge Cases by Category

### Connection & Presence Edge Cases
- **Two users join simultaneously**
  - *Behavior*: Protected by `async with room.lock`. The lock ensures a sequential and safe connection process, meaning there is no race condition in color assignment or presence list updating.
  - *Documentation Gap*: The async concurrency lock applies per-room, not globally.
- **User joins with an empty name**
  - *Behavior*: Defaults to `"Anonymous"`, then `.strip()` is applied and it is sliced to a maximum of 40 characters.
  - *Documentation Gap*: Missing explicit notes on fallback defaults.
- **User joins a session that doesn't exist yet**
  - *Behavior*: Auto-creates via `_get_room()`. If a session doesn't exist, it allocates a new `CollaborationRoom` instantly.
  - *Documentation Gap*: Rooms are lazily initialized.
- **What happens to the room when the last user disconnects?**
  - *Behavior*: When the last socket is removed, `should_delete = not room.sockets` evaluates to `True`. The entire room is deleted from memory.
  - *Documentation Gap*: All room data (code, version, comments) is ephemeral. If all users disconnect, state is permanently lost.

### Message & Protocol Edge Cases
- **Unknown `type` field sent**
  - *Behavior*: Ignored by standard routes and caught at the end. Returns an `error` message `"Unsupported collaboration message type: {message_type}"`.
  - *Documentation Gap*: Supported event types need to be outlined for client implementations.
- **Non-dict payload (e.g. JSON Array)**
  - *Behavior*: Returns an error payload: `"message payload must be a JSON object"`.
  - *Documentation Gap*: Clients must explicitly serialize to dictionaries/objects.
- **Code that is exactly at the character limit vs 1 character over**
  - *Behavior*: `MAX_CODE_CHARS = 50,000`. An update of 50,000 characters passes, but 50,001 returns `"code exceeds 50000 characters"`.
  - *Documentation Gap*: Maximum code size is weakly exposed to the frontend.
- **Empty comment text**
  - *Behavior*: After `.strip()`, if the comment evaluates to `False`, it returns `"comment text is required"`.
  - *Documentation Gap*: Needs client-side validation to avoid wasted WebSocket roundtrips on empty messages.
- **Comment text exactly at the limit**
  - *Behavior*: `MAX_COMMENT_CHARS = 1,000`. A comment of 1,000 chars is valid, but 1,001 chars rejects with an error.
  - *Documentation Gap*: Similar to code, character bounds are not clearly documented.
- **Cursor update with non-dict cursor value**
  - *Behavior*: Fails silently by checking `if not isinstance(raw_cursor, dict): return`.
  - *Documentation Gap*: Invalid cursor payloads do not raise explicitly tracked errors, which might disguise client-side bugs.

### Concurrency & State Edge Cases
- **Stale code update (Version Conflict)**
  - *Behavior*: If `incoming_version < room.version`, the backend drops the update. It instead responds with a `"sync_required"` payload containing the correct truth to force the stale client back to parity.
  - *Documentation Gap*: Needs highlighting so client-side sync protocols anticipate this exact `"sync_required"` event.
- **Broadcast to a client that has already disconnected**
  - *Behavior*: Catches `RuntimeError` internally and batches stale socket ids in `stale_clients`, cleanly disconnecting them afterwards.
  - *Documentation Gap*: Explains the resilient retry mechanics when sockets drop unexpectedly.
- **Cursor update for a `client_id` not in `room.users`**
  - *Behavior*: The update is quietly ignored and not broadcasted.
  - *Documentation Gap*: Out-of-sync cursor payloads are discarded gracefully.

### Security & Validation Edge Cases
- **Code field is not a string**
  - *Behavior*: If the code is parsed as a number or list, the update fails and responds with `"code must be a string"`.
  - *Documentation Gap*: Explicit strict-typing guidelines on standard schema.
- **`session_id` with special characters**
  - *Behavior*: Has no string validation restrictions in the URL route definition.
  - *Documentation Gap*: Should highlight any potential URL encoding caveats or path traversal vulnerability vectors.
- **Cursor values that are negative**
  - *Behavior*: Effectively sanitizes all bounds. `line` and `column` are clamped to a minimum of 1 via `max(1, int(value))`. `selectionStart` and `selectionEnd` are clamped to a minimum of 0 via `max(0, int(value))`.
  - *Documentation Gap*: Cursor coordinates are actively sanitized, protecting state from malformed out-of-bounds rendering.

## Error Responses Reference
If an error happens during the session, the WebSocket will emit a message structured as `{"type": "error", "detail": "..."}`. Possible details include:
- `"message payload must be a JSON object"`
- `"Unsupported collaboration message type: {type}"`
- `"code must be a string"`
- `"code exceeds {MAX} characters"`
- `"comment text is required"`
- `"comment exceeds {MAX} characters"`