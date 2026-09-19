# Wangshangliao (native Python)

## Conversations and logs

Untitled Wangshangliao conversations use their session alias/name, or the private account/group ID, as a list display fallback. Existing titles are preserved and no additional model request is made. Trace reconnections carry the last cursor to replay retained entries. When AstrBot file logging and trace file logging are enabled, history recovers entries from the current files after restart. It reads at most 4 MiB and 1,000 entries per file, returning at most 2,000 merged entries. Older rotated files are not loaded by this endpoint. Traces are not a complete message archive. Lists, details and exports use consistent display titles; search also matches session aliases.

A 390 px viewport check verified wrapping of long trace fields. Browser reconnection and service restart recovered the synthetic acceptance records.

![Mobile trace acceptance](/images/wangshangliao/trace-acceptance-mobile.png)

## Plain-text replies

The developer-window backend supports a separate `private_ai` scope for one-way ordinary private-message testing: at most five minutes and ten incoming messages, with one correlated reply per message. It excludes slash commands, respects the private-reply switch, and expires on restart. A Dashboard scope selector has not yet been added. Managed-account tests do not replace ordinary external-account acceptance.

Wangshangliao does not render rich text. Moderation help uses section labels, blank lines and numbered examples. The plugin appends platform-specific plain-text requirements without replacing the persona, converts ordinary AI Markdown results into text, preserves link URLs, code contents and structured mentions, and disables text-to-image for these results. Other platforms are unaffected. Messages sent directly by third-party plugins do not pass through this AI result hook.

After authentication, the form scrolls to a sticky warning with a prominent Save login and connect button. Unsaved logins trigger a browser refresh/close warning and a route-leave confirmation. Successful saving clears the warning. Authentication alone does not establish the messaging connection.

## Architecture and ownership

### Commands and developer windows (in development)

In private chat, `/帮助`, `/help` and `/群管帮助` return the Wangshangliao command guide. Groups receive only a private-chat redirect. Managed bot accounts still require an active developer window; administrator status does not bypass bot exclusion.

Browser acceptance covers saved values after refresh and switching instances at a 390px viewport. Saving a draft never opens the window. The screenshot shows temporary acceptance values, restored after testing.

![Developer window mobile saved values](/images/wangshangliao/developer-window-mobile.png)

Private test sending and receiving share one developer window. Sending still requires saved proactive permission and only permits `/群管` commands, never ordinary chat. Closed, expired or exhausted windows reject new commands. Controlled bot tests cover private directories, numbered mute/unmute, permission rejection and result queries; server acceptance remains distinct from final platform confirmation.

Group mentions support only mute, unmute, kick, announce, mute-all and unmute-all under `/群管`. Full help, identity, directories, search, rules and result queries are private-chat only; group requests receive a short private-chat redirect without query data. Private member lists show the group nickname or account nickname alongside the selection number and business ID.

The plugin implements `/群管帮助` and `/群管` with administrator checks and ten-minute private directory selections. The developer panel opens or closes an instance-bound test window for private commands, group commands, or keyword rules (maximum 300 seconds and ten inbound messages). Rule keywords require the `WSL_TEST_` prefix. Scope settings persist with Save changes; saving never activates the window. Windows grant no administrator or moderation capabilities and do not survive account replacement, instance shutdown or restart. Refresh retrieves runtime window status. Full live acceptance remains pending.

![Wangshangliao AstrBot architecture](/images/wangshangliao/architecture-layers.svg)

Core supplies `/sid`, `admins_id`, command registration and permission filters, models, personas, knowledge bases, session routing, configuration, authentication and logs. The moderation plugin owns keyword matching, the 24-hour counter, warnings, cooldowns, penalty selection and administrator commands. Command implementation and live acceptance are tracked separately.

The adapter owns login, reconnects, directories, business/NIM identity mappings, message and mention conversion, fixed platform actions, capability checks and idempotency. It does not parse moderation commands. The plugin does not call protocol endpoints directly.

A user obtains UID through private `/sid` and adds that UID to AstrBot's administrator list; UMO is for session routing. This administrator role can authorize other AstrBot administrative commands, not only Wangshangliao moderation. Planned commands must check the operator role, enabled target group, saved action grant, native platform role and target identity. Automatic rules do not require the offender to be an administrator or mention the bot.

`/platforms` contains instance connection, group selection, reply switches, action grants and rule parameters; rendering rule parameters there does not transfer rule execution into the adapter. Developer exceptions never replace these grants. Server acceptance is not delivery confirmation.

Configure allowed actions per bot and group in AstrBot. Member ranks have been removed; commands use the `/群管` prefix. Keyword automation requires the corresponding action grant and native platform privileges.

Re-login stops the old connection. Click Save login and connect (or save the bot) after authentication. A `reauth_required` error means the persisted session is invalid: log in again and save within ten minutes. Empty enabled groups disable group handling; ordinary member bots can chat but cannot perform administration.

This fork runs business authentication, device verification, encrypted session recovery and NIM messaging inside AstrBot. It uses AstrBot models, personas and group context. No Rust process, DH workbench or HTTP/SSE bridge runs alongside it. Instances support multiple enabled groups with explicit-mention text replies, plus private text conversations.

## Current capabilities and deployment checks (2026-09-18)

- Password and SMS login are supported. Users supply SMS codes; failed automatic verification falls back to manual verification. Authentication, saving and an online connection are distinct states.
- Multiple enabled groups are supported, with per-group replies and moderation grants. Group replies still require a mention. Configured bot accounts exclude one another, including disabled instances.
- Member pagination rejects inconsistent identities and cursor loops. Cloud private-session discovery remains unverified; local sessions do not represent the entire cloud directory.
- Proactive text is disabled by default. The entry point reuses the outbox, but per-target grants, stable scheduled operation IDs, result queries and private-session format handling remain incomplete. The current session-and-content key can return an earlier result for repeated identical text; do not treat this as complete scheduled delivery.
- Accepted is not peer-confirmed. Unknown sends are not retried. Media, some moderation readbacks, 24-hour stability and renewal acceptance remain pending.

### Linux migration checks

Use the source or Docker commands below and install dependencies for the target architecture. Do not copy Windows binaries or a macOS virtual environment. Linux filenames are case-sensitive; include all models and Node resources.

The bundled runtime serializes verification with one model and one Node worker, rather than the standalone service's 30-request concurrency. Validate Node startup, OpenCV ONNX inference, timeout cleanup, real authentication, saved connections and restart recovery on Linux. Deployment support is not evidence of successful Linux, x86_64 or ARM64 acceptance. A different network egress can also affect verification.


## Setup

Use Python 3.12+, run `uv sync`, then run `pnpm install`, `pnpm generate:api` and `pnpm build` in `dashboard`. Serve the resulting `dashboard/dist` through your deployment.

Set the server environment variable `ASTRBOT_WANGSHANGLIAO_CONFIG` to a private JSON file. Use mode `0600` on Unix and a service-account-only ACL on Windows. Required fields: `origin` (HTTPS origin), `headers`, `metadata` (14 integers), `signing_seed`, `body_key`, `message_key`, `server_key` (standard Base64, 32 bytes each), `captcha_id`, `app_key`, and `device_id`. An administrator must supply valid deployment values; none are bundled. Missing and invalid configurations return `deployment_missing` and `deployment_invalid` respectively.

Do not copy old databases, sealed sessions or captured protocol data. Passwords are used only for the current login request. Browser responses never contain provider session credentials.

## Create a bot

The connection form groups account login, group selection, and bot controls in order, using AstrBot rounded buttons and theme styles.


The former “log in to the workbench, then copy bridge URL/token” flow becomes **Create robot → Wangshangliao → Account login**. Other platform entry points are unchanged.

1. Select Wangshangliao and start login.
2. Enter the account and password, then complete the human verification widget.
3. If device verification is required, enter the SMS code and complete verification. Resends respect the cooldown.
4. After authentication, select the AstrBot configuration and enter one business group ID. An empty group list disables all groups.
5. Save to establish the messaging connection. Authentication and NIM connectivity are separate states.

![Native account login](/images/wangshangliao/login-en.png)

Transactions expire after ten minutes and are bound to the Dashboard user and preallocated instance ID. Saving consumes an opaque session reference and writes instance-bound encrypted credentials. Retrying a successful save does not create another bot.

## Messaging and recovery

Only structured mentions of the current business account trigger group replies. Select the member in the client; typed nicknames, `@DH` and account numbers are not identity evidence. Other-account mentions do not match. Explicitly mentioning multiple bots lets each apply its own reply settings. Ordinary messages enter only built-in group context. Context use follows the selected AstrBot configuration.

Group events await pipeline completion before the next event. Incoming messages are persisted before ACK; lost ACKs retain deduplication records. Outgoing intent is persisted before sending. `accepted` means server acceptance, not peer delivery. `unknown` sends are not automatically retried; interrupted generation is marked `needs_review` rather than replaying the model.

Private text messages enter AstrBot without a mention and follow the selected model, permissions and session settings. Private conversations are isolated from groups and other peers/accounts, and work with an empty enabled-group list. Only authenticated Wangshangliao text envelopes are supported. Moderation uses Dashboard-configured capability grants. Media is not implemented. A basic proactive text entry point exists; scheduled delivery remains incomplete.

Disabling and saving stops processing but retains the session. Logging out immediately stops the instance and deletes the local recovery session. Logging in again stops the old connection and replaces credentials after successful authentication and save.

Files live under the AstrBot data directory: `platform_data/wangshangliao/<SHA256(instance ID)>/`. They include `session.key`, `session.sealed`, and `messages.sqlite3`. Co-located encryption protects against accidental configuration disclosure, not access by a host administrator. Treat backups as credential material.

To roll back, stop the AstrBot instance first, confirm its processing has ended, and only then restore the old system's group AI configuration. Deleting bot configuration alone is not credential erasure; log out first when erasure is intended.

## Validation

Run `uv run pytest tests/test_wangshangliao_wire.py tests/test_wangshangliao_native.py`, `uv run ruff format .`, and `uv run ruff check .`. In `dashboard`, run API generation, build, and `node --test tests/*.test.mjs`. The reproducible mocked browser scenario is `dashboard/tests/wangshangliao.browser.js`.

Offline coverage includes synthetic protocol vectors, signed/encrypted HTTP exchanges, simulated NIM WebSockets, registration ownership and cancellation, save rollback, deduplication and EventBus completion. It uses no real account or external Wangshangliao connection.

Live acceptance is pending valid deployment configuration, an explicitly designated test account/group, and confirmation that the old AI is stopped. Verify silence for ordinary chat, one reply per mention, independent peer receipt, reconnect/restart, disable and logout. Offline success is not production acceptance. Actual local verification is macOS ARM64 with Python 3.12; Windows, Linux and x86_64 remain unverified.

Before live login, run `uv run python scripts/check_wangshangliao.py`. It checks deployment configuration and saved session binding without network access or credential output. Exit code 1 means setup is incomplete. A successful preflight does not certify live messaging.

Legacy Rust login deployments may omit `message_key`. Account authentication is allowed, but adapter startup reports `message_key_missing` without connecting the messaging service. A malformed supplied message key still produces `deployment_invalid`. Login and messaging readiness are verified separately.

With explicit administrator approval, an existing Rust protocol deployment can be converted once into independently encrypted AstrBot configuration under `platform_data/wangshangliao/deployment/` in the data directory. Account sessions and passwords are not imported. This configuration is loaded when `ASTRBOT_WANGSHANGLIAO_CONFIG` is unset; an invalid explicit path never silently falls back. To revert, stop the service and move this directory out of the data directory.

Retry a failed challenge in the same verification popup. After verification succeeds, the form shows that login is being submitted. Network failures and provider rejection are reported separately from challenge failure. Closing the popup allows another login attempt.

After authentication, select enabled groups from the fetched group list. This replaces the manual enabled-group-ID field. Ordinary members may enable text replies; moderation requires platform admin permissions. The built-in local solver handles slider challenges by default and the UI retains a manual fallback when it is unavailable. Green indicates verification in progress; red indicates failure.

## Local guide and remaining acceptance

The setup button now opens `/local-docs/wangshangliao.html` on the Dashboard host instead of the external documentation site. Guides are generated during the Dashboard build.

Saved authentication is not proof of an online messaging connection. Empty enabled groups disable group handling. Saved bots can refresh groups without a temporary login transaction. Expired sessions require authentication. Fixed moderation capabilities and announcement readback are implemented; independent group-mute state readback, media and recalls remain pending; proactive text has a basic implementation only. Text sends do not require admin status but remain subject to platform restrictions. Long-running stability requires separate acceptance.

Authentication diagnostics: business 401 immediately requires login; HTTP 429 honors Retry-After. Transient disconnects use jittered backoff and one scheduled heartbeat. Unknown server kicks stop with nim_kicked because the reference does not establish reason-field semantics. Historical unsupported records lack message type; new records retain only format and reason.

Group roles are based on owner identity or the current account member record. Unrecognized or unavailable roles remain unknown. The first roster page does not prove completeness. Private directory selection currently covers locally known conversations and displays an incomplete-directory notice.


Login, session restoration, connection changes, message processing and send results use AstrBot logging. Entries include the instance, stage and hashed correlation identifier without credentials or message bodies. Repeated failures are limited to once per minute per lifecycle, with aggregate counts on subsequent entries. Live Dashboard acceptance is pending.

### Manual Moderation

Configure allowed actions per bot and group in AstrBot. Member ranks and chat moderation commands have been removed. Keyword automation requires an explicit mute grant and platform administrator privileges.

```sh
uv run python scripts/wangshangliao_moderate.py --bot BOT_ID --group GROUP_ID --action mute --member MEMBER_ID --operation UNIQUE_ID
```

This previews the operation. Add `--confirm` after checking it. Actions are `mute` (one minute), `unmute`, `mute_all`, `unmute_all`, and `announce --text CONTENT`. Use a new ID for each new operation and reuse the original ID to retrieve an attempted operation. Unknown outcomes are never resent; changed content under the same ID is rejected. Execution rechecks account and role; administrator targets are rejected.

Chat moderation commands and member-level grants have been removed. Configure bot capabilities per group in AstrBot. Keyword moderation requires an explicit mute grant and native platform permissions.

Member mute/unmute and announcement readback passed live validation. Group-wide requests were accepted, but independent state readback remains unimplemented. Member lookup now shares pagination and identity validation; live large-group completeness remains unverified. Group mute does not automatically expire. Accepted is not verified; check platform state before another operation after an unknown outcome.

Group directories load automatically when switching bots. Selected group IDs remain visible if fetching fails. Save changes after selecting groups; switching with unsaved edits prompts before discarding them. The page shows save status; being online does not imply moderation privileges.

Automatic replies: disable private replies or disable replies per enabled group in bot settings. Enabled group replies still require a mention. Defaults preserve existing behavior; disabling retains history.

SMS login: select SMS login, enter a +86 phone number, complete human verification to request a code, then submit the code and verify to log in. No password is required. The user completes CAPTCHA and receives the SMS.

Configured Wangshangliao bot accounts in the same AstrBot instance automatically exclude one another, including disabled instances. Their private and group messages do not trigger automatic replies or keyword moderation. Private sends to these accounts are also blocked to prevent reply loops.
# Bundled authentication runtime

Group replies now mention only the original sender. Violation automation has independent mute/removal keywords; mute wins on simultaneous matches. A persistent per-bot/group/member window starts on the first violation and expires after 24 hours. The first violation attempts recall when authorized, then sends a structured mention warning. Subsequent violations apply the selected penalty subject to the per-group penalty cooldown. Duplicate message IDs do not increment counts. Recall failures do not block warnings or penalties; uncertain operations are not retried. Managed bots and privileged members are excluded. Legacy keywords map to mute rules but now warn on the first violation. Removal and recall have implementation coverage but still require live acceptance.

Mention identity clarification: incoming structured mention IDs are NIM IDs, not business account IDs. The adapter matches the authenticated session's NIM ID and emits an AstrBot At component using its business account ID. Mentions of other users are ignored normally.

Group developer tests can now pass `group="BUSINESS_GROUP_ID"` to `configure_pair`. Grants are isolated by account pair and group; omit `group` for private-only tests. Group replies still require a structured mention of the current account and an enabled group reply setting. Managed bot messages cannot trigger keyword moderation. The shared send budget is consumed before each reply attempt, including failures. No grant is enabled by deployment or restart.

Developer-only private bot testing can temporarily allow a configured business-account pair via the process-local `developer_gate.configure_pair` function. There is no Dashboard, chat or public API switch. The default is closed; grants last at most 300 seconds with a shared budget of at most 10 send attempts, including failed or uncertain sends. Restarting the process discards grants. Group messages, moderation, reply settings and proactive authorization are not bypassed. A separate Python process cannot enable a running service's gate; use a controlled in-process test entry point and call `close_all()` in cleanup.

WSL verification uses the bundled solver by default; no HTTP service on port 7795 is required.
The approximately 19 MB ONNX model ships with the source. The first verification starts a local worker that reuses one model and one Node.js worker. No browser, GPU or PyTorch is required.
The worker is released at shutdown or terminated on timeout/cancellation.

For Linux source deployments, install Python 3.12+ and Node.js on PATH, then run:

```sh
uv sync --extra wsl
uv run --extra wsl main.py
```

Build the repository's Docker image with the optional runtime:

```sh
docker build --build-arg INSTALL_WSL=true -t astrbot:wsl .
```

Use the usual AstrBot data volume and port configuration. Deployment credentials and sessions remain in data; migrate that volume or import the WSL deployment and log in on the new server.
`ASTRBOT_YIDUN_SOLVER_URL` remains compatible: unset or `builtin` selects the bundled worker, an empty string selects manual verification, and an HTTP URL selects an external service.
Missing optional dependencies or failed verification fall back to manual verification.

## Moderation verification status (2026-09-19)

Controlled live tests confirmed a first-violation mention warning at recipient ingress and member removal through a complete roster readback. A later sequence exercised standalone recall, recall with mute, unmute, and recall with removal. The administrator confirmed all three recall notices on the mobile client. Mute and unmute received server acceptance but lack independent state readback.

The test used a temporary native adapter process with an exact group, sender, and message-marker filter. It invoked the existing rule handler for selected real messages, not the production plugin's managed-account filter. Ordinary-user end-to-end plugin acceptance remains pending. Original configurations were restored; the temporary process-local exception was closed. Existing 24-hour violation counts were preserved.

Moderation is configured through per-bot action grants and automation rules. The old manual moderation component is not mounted; its preview API does not expose removal or recall. Real 24-hour expiry and long-running stability remain unverified.

A subsequent controlled test used the normal launchd service and saved Dashboard grants: an unmatched bot message was ignored, while one exact test message reached the production plugin, received recall/removal acceptance, and removal was confirmed by roster readback. The sender configuration was restored. The one-use exception was exhausted and its startup environment cleared. This does not validate browser saving or ordinary-user behavior.

The developer-only `ASTRBOT_WSL_MODERATION_TEST` startup JSON accepts business-ID strings `receiver`, `sender`, `group`, absolute Unix `expires` (at most 300 seconds ahead on loading), and `messages` (at most two exact full texts). It is disabled by default, one-way, and consumed before plugin execution. It grants neither normal chat replies nor moderation capabilities; saved grants and platform identity checks remain mandatory. Clear the startup parameter and restart normally after a test.

Browser continuation checks on 2026-09-19 confirmed the Chinese moderation controls, keyword-rule expansion, unsaved-change feedback, and restoration of saved values after reload without submitting configuration. Switching to `wangshangliao_809ac622` displayed its ordinary-member role in the test group; all three Wangshangliao instances appeared online in the selector. Save round trips, English rendering, and the complete mobile matrix remain separate checks.

A platform member can also be an AstrBot-managed account. Both non-admin test accounts remain subject to the managed-account moderation filter, including when disabled. Their ordinary-member role does not bypass that filter; controlled rule-handler tests do not establish production plugin-entry acceptance.

Further checks on 2026-09-19 passed 151 Python tests on both macOS ARM64 and an isolated Linux ARM64 container, 55 frontend tests, type checking, production build, and Ruff. Sixteen A/B configuration combinations matched API and disk values. Invalid cooldowns, boolean types, and group IDs were rejected without changing saved settings. One normal service restart preserved a disabled A and enabled B with their reply settings; original configurations were subsequently restored.

A real B-to-A group mention reached ingress state `ignored_bot` (message `2178890399857246942`). The initial check ran while the message was pending; following the same message to completion verified exclusion without resending. With proactive sending disabled, the IM API rejected a send with `proactive_not_authorized` and no new outbox row. This API calls `send_by_session` directly and does not establish full Context-path acceptance. All three instances were online after cleanup. Browser save matrices, ordinary-user production paths, unsupported capabilities, clean Linux deployment, and the real 24-hour/renewal checks remain outstanding; previous login validation is retained.

## Authorization and reply updates

Proactive sending requires both the master switch and an explicit target grant. Existing configurations without targets authorize none. Normal replies use their own switches. Member pages contain at most 30 entries within a byte budget; use `/群管 下一页` in private chat. Numbers refer only to the current page and expire after ten minutes.

Formatted and redacted replies are split into segments of at most 4096 UTF-8 bytes. Stable logical and segment IDs prevent blind retries; unknown outcomes stop further segments. Optional `operation_id` identifies retries, while independent calls receive new IDs. `GET /api/v1/im/operations/{operation_id}?platform_id=BOT_ID` queries stored outcomes without sending. Server acceptance is not peer confirmation.

Unknown members trigger bounded complete-roster refreshes. A failed group does not block other groups or private chat. Failed warnings are attempted before punishment on a later violation; unknown warnings neither trigger blind retries nor count as successful warnings. Legacy environment overrides were removed; development uses instance-bound test windows only.

![Proactive target authorization](/images/wangshangliao/permissions-mobile.png)
