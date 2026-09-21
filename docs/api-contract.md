# ZeroQueue UI / API contract

One FastAPI service serves the customer chat (`/`), the agent console
(`/agent`), and every endpoint below. Base URL in production:
`https://zeroqueue-hubble.onrender.com`.

## Customer chat

### POST /api/chat
One customer message. `multipart/form-data`:

| field | required | notes |
| --- | --- | --- |
| `session_id` | yes | browser-generated, kept in localStorage |
| `message` | no* | *message or a readable file is required |
| `file` | no | image/pdf/text; OCR text joins the question |

Response 200:
```json
{
  "answer": "Based on our Amazon shopping information ...",
  "status": "answered | clarifying | handoff",
  "citations": [{"label": "[1] Amazon shopping - How to redeem (app)", "url": "https://..."}],
  "trace": {"state": "answered", "retrieval_ms": 9.2, "total_ms": 1017.4,
            "source_count": 3, "sources": [], "confidence_band": "high",
            "handoff_reason": null},
  "attachment_note": "Read 41 words from invali-voucher.jpeg via OCR.",
  "handoff_confirmed": true
}
```
`handoff_confirmed` is present on handoff responses only. 400 when both
message and file are missing/empty; 400 for unsupported file types.

### POST /api/agent/chat
Alias of `/api/chat` under the path named in the original UI work plan.
Identical request and response.

### POST /api/handoff
The "Talk to a human" button. JSON body: `{"session_id": "...", "reason":
"customer_requested_human"}`. Response: same shape as `/api/chat` with
`status: "handoff"`.

### GET /api/human-replies/{session_id}?after_id=0
Polled by the customer chat every 5 s while handed off. Response:
`{"replies": [{"id": 3, "body": "...", "created_at": 1789...}]}`. New replies
only when `after_id` is the last id the page has shown.

## Intercom webhook

### POST /api/webhooks/intercom
Signed with HMAC-SHA1 (`X-Hub-Signature`). Topics used:
`conversation.admin.replied` (human/agent-console replies land in the
customer chat) and `conversation.operator.replied` (automation replies).
Duplicate events are ignored (dedupe by event id; duplicate parts by part
id). 503 when `INTERCOM_WEBHOOK_SECRET` is unset; 401 on a bad signature.

## Agent console (`/agent`)

All console endpoints accept the optional `x-agent-key` header; required
only when `AGENT_CONSOLE_KEY` is set (403 otherwise).

### GET /api/agent/conversations
The human queue. Response: `{"conversations": [{"session_id",
"last_customer_message", "message_count", "handoff_reason",
"confidence_band"}], "intercom_configured": true}`.

### GET /api/agent/conversations/{session_id}
Transcript plus the AI draft. Response: `{"session_id", "messages":
[{"role", "text"}], "handoff_reason", "confidence_band", "intercom_linked",
"intercom_configured", "intercom_conversation": {"conversation_id",
"state", "open"} | null, "suggestion": {"answer", "citations",
"confidence_band"}}`. `intercom_conversation` is a live
`GET /conversations/{id}` snapshot when Intercom is configured and linked,
else null. 404 for an unknown session.

### POST /api/agent/conversations/{session_id}/reply
JSON body: `{"body": "..."}`. Sends the approved reply to the customer as
an Intercom admin comment and shows it in the customer chat immediately.
Response: `{"sent": true, "conversation_id", "part_id"}` or
`{"sent": false, "reason": "intercom_not_configured | conversation_create_failed | <ErrorType>"}`.

### POST /api/agent/conversations/{session_id}/note
JSON body: `{"body": "..."}`. Adds an internal Intercom note; never shown
to the customer. Response: `{"sent": true, "conversation_id"}` or
`{"sent": false, "reason": ...}`.

## Environment variables

New in this round: `AGENT_CONSOLE_KEY` (optional; empty = open console for
the local demo). Existing: `PORT`, `MOCK_MODE`, `CORS_ORIGINS`,
`DEMO_RESET_SECRET`, `MAX_UPLOAD_MB`, `TESSERACT_CMD`, `LLM_API_KEY`,
`LLM_MODEL`, `LLM_BASE_URL`, `MOSS_PROJECT_ID`, `MOSS_PROJECT_KEY`, `MOSS_INDEX_NAME`,
`INTERCOM_ACCESS_TOKEN`, `INTERCOM_WEBHOOK_SECRET`, `INTERCOM_ADMIN_ID`,
`INTERCOM_TEAM_ID`, `INTERCOM_API_BASE`, `STATE_DB_FILE`.