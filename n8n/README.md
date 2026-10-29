# n8n staff reminders (optional)

A self-hosted **n8n Community** workflow that sends one follow-up reminder to staff who have not answered an evidence request (PRD §12.1, P0+). ProofCircuit works without it.

n8n is only a scheduler:

1. When the agent (or a person) requests evidence from staff, the **backend** starts the workflow. It persists a `staff.evidence_requested` trigger with the new task, then POSTs it to the n8n webhook with `Authorization: Bearer N8N_WEBHOOK_TOKEN`. Transient failures (connection errors, time-outs, 5xx) are retried twice with the same `event_id`. An authentication or configuration error pauses the trigger. Either way the drawer shows "Reminder scheduling unavailable" with a retry button.
2. The **Webhook** node acknowledges at once. The acknowledgement means the trigger was received, not that a reminder was sent.
3. The **Wait** node waits until `remind_at` (`REMINDER_DELAY_SECONDS` after the request, default 120).
4. The **HTTP Request** node calls `POST {BACKEND_BASE_URL}/api/cases/{case_id}/reminders` with `Authorization: Bearer N8N_SERVICE_TOKEN`, sending only `staff_task_id`, `request_round` and `reminder_number`.
5. The **backend** decides everything else:
   - It rechecks that the same request round is still open, staff have not replied, uploaded or sent a voice note, the case is still waiting for evidence, and the deadline is in the future.
   - It picks the recipient, locale and template from the stored task.
   - It places at most one reminder per round in the local in-app staff inbox. Nothing is sent over WhatsApp or SMS.
   - Duplicate callbacks return `already_processed`.

| Callback result | Meaning |
| --- | --- |
| `202 queued` | Accepted. The runner rechecks cancellation under the case lock, then sends or skips. |
| `200 already_processed` | The same (merchant, case, task, round, reminder number) was handled before. Nothing new is sent. |
| `200 skipped` + `reason` | `not_due`, `task_responded`, `staff_replied`, `superseded`, `round_changed`, `case_…` or `deadline_passed`. Nothing is sent. |
| `401` / `404` / `422` / `503` | Bad or missing service token / case or task outside the service's merchant scope / invalid reminder number / reminders not configured. |

## Files

- `staff-reminder.json`: the workflow export (Webhook → Wait until `remind_at` → HTTP Request). It holds only credential **references**, no secrets.
- `docker-compose.yml`: n8n pinned to `n8nio/n8n:2.45.6`, on `127.0.0.1:5678` only, with a persistent `n8n_data` volume.
- `setup.py`: one-command setup through the n8n CLI. It needs Docker with the compose plugin and the Python standard library.
- `.env`: created by `setup.py`. It holds `N8N_ENCRYPTION_KEY`, both tokens and `BACKEND_BASE_URL`. It is gitignored; never commit it or paste its values.

## Set up

From the repository root:

```bash
python n8n/setup.py --write-backend-env
```

This does the following:

1. Generates the secrets into `n8n/.env` (once; existing values are kept).
2. Starts n8n.
3. Imports the two Header Auth credentials:
   - "ProofCircuit trigger token (backend to n8n)": `Authorization: Bearer <N8N_WEBHOOK_TOKEN>`
   - "ProofCircuit service token (n8n to backend)": `Authorization: Bearer <N8N_SERVICE_TOKEN>`
4. Imports and **publishes** the workflow, then restarts n8n so the production webhook is registered.
5. Appends to `backend/.env`: `REMINDERS_ENABLED=true`, `N8N_REMINDER_WEBHOOK_URL=http://127.0.0.1:5678/webhook/proofcircuit-staff-reminder` and both tokens.

Restart the backend afterwards. **Providers** in the drawer (or `GET /api/providers`) then shows `n8n_reminders: configured`.

No n8n account is needed for the webhook to run. To look at executions in the editor at http://127.0.0.1:5678, create the owner account yourself on first visit.

### Doing it by hand instead

1. Run `docker compose -f n8n/docker-compose.yml up -d`, after putting `N8N_ENCRYPTION_KEY=<random>` in `n8n/.env`.
2. In the editor, import `staff-reminder.json`.
3. Create the two Header Auth credentials above (header name `Authorization`, value `Bearer <token>`) and select them on the **Staff evidence requested** and **Call ProofCircuit reminder command** nodes.
4. Publish the workflow. Use the **production** webhook URL it shows (`/webhook/...`), not the temporary test URL (`/webhook-test/...`).
5. Put that URL and both tokens in the backend settings.

## Addresses

| From → to | Address | Why |
| --- | --- | --- |
| Backend → n8n | `http://127.0.0.1:5678/webhook/proofcircuit-staff-reminder` | The container publishes port 5678 on the host's loopback only. |
| n8n → backend | `http://host.docker.internal:8000` (`BACKEND_BASE_URL` in `n8n/.env`) | Inside the container, `localhost` is the container. Docker Desktop provides `host.docker.internal`; on Linux, the compose file maps it to the host gateway. Verified on Docker Desktop for Windows with the backend bound to `127.0.0.1`. |

The n8n container, not the backend, needs `BACKEND_BASE_URL`. The backend's own `BACKEND_BASE_URL` setting is informational.

## Sample trigger test

With n8n and the backend running, request delivery proof in the app (agent or **Request delivery proof from staff**). The staff drawer then shows "Reminder scheduled by n8n for …", and after the delay "Reminder sent to the staff inbox".

To check the webhook's authentication directly (Git Bash; the token values are never printed):

```bash
set -a; . n8n/.env; set +a
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:5678/webhook/proofcircuit-staff-reminder -H 'Content-Type: application/json' -d '{}'
```

This prints `403` (no token, or a wrong one). With `-H "Authorization: Bearer $N8N_WEBHOOK_TOKEN"` and a real trigger body, the webhook answers `200`. Anything a forged trigger leads n8n to call back with is still rechecked by the backend.

For rehearsal, set `REMINDER_DELAY_SECONDS=30` on the backend rather than changing the clock.

## Stop or remove

```bash
docker compose -f n8n/docker-compose.yml down        # stop (keeps the volume)
docker compose -f n8n/docker-compose.yml down -v     # also delete the n8n data volume
```

The compose service uses `restart: unless-stopped`, so a running n8n starts again with Docker until you stop it.

n8n's Sustainable Use License allows this local, internal use. Review it before any commercial embedding.
