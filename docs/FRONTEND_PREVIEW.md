# Frontend preview

The repository now includes a standalone, dependency-free browser frontend at `frontend/`.
It is intentionally separate from the Python package and can be previewed without Node.js.

## Start a local preview

Run the LangGraph API with an isolated state directory:

```powershell
$env:PYTHONPATH = "$PWD/src"
$env:UKA_USE_LLM = "1"
$env:UKA_STATE_DIR = "$PWD/build/frontend-preview/state"
uv run uka-lg --project-root . serve --host 127.0.0.1 --port 8877
```

In a second terminal, serve the frontend:

```powershell
python -m http.server 8890 --bind 127.0.0.1 --directory frontend
```

Open <http://127.0.0.1:8890/>. The frontend calls `http://127.0.0.1:8877` by default.

## What is included

- Provider and graph health summary, including the configured model revision.
- Evidence-first knowledge intake with the `accepted -> interrupt -> resume` approval flow.
- Tenant and security-scope context controls.
- Scoped retrieval with answer, unknowns, and evidence-pack rendering.
- A live evidence-trail timeline backed by `/v1/threads/{thread_id}/events`.
- An active Experience library backed by `GET /v1/knowledge`, including the model synthesis,
  context, problem, mechanism, action, outcome, rationale, source logic, applicability boundary,
  original-evidence comparison, learning lineage, and a one-click retrieval action.

### Actor and retrieval explained

`actor_id` is an audit identity label: it records who initiated an ingest, retrieval, or
approval request. The preview defaults it to `control-room`, meaning “the local control-room
UI”; it is not an administrator role and does not bypass the human gate. In a real deployment,
set it to the authenticated user or service identity supplied by the gateway.

After approval, use the **Knowledge library** section rather than guessing a query. Each card
shows what the model understood separately from what the source said. Selecting **用这条经验检索**
fills the source identifier and resolved domain, then returns the synthesis plus expandable source
evidence. Evolution cards also show their knowledge delta, parent knowledge count, candidate state,
and required gates.

The API enables CORS only for the local preview ports (`8890` and `3000`). For a production
deployment, put the frontend behind the same trusted gateway as the API and replace this
allow-list with the exact origin used by that deployment.

## Preview verification

The `0.2.0` preview was exercised against the real configured `glm-5.2` provider using an
isolated `demo-ui/private` state:

1. ingest and approve a contextual Agent-governance baseline and a refinement;
2. verify the refinement uses prior Knowledge and only creates a gated Evolution candidate;
3. route and retrieve cybersecurity, finance, mechanical-engineering, and education experiences;
4. filter the Experience library and use the education card's one-click retrieval action;
5. confirm `ANSWERED / 1 EXPERIENCE`, expandable original evidence, and zero browser console errors.

The reproducible AAWO summary is in
[`CONTEXTUAL_EXPERIENCE_AND_EVOLUTION_REPORT_2026-08-10.md`](CONTEXTUAL_EXPERIENCE_AND_EVOLUTION_REPORT_2026-08-10.md).

This is a local preview, not an externally hosted public deployment. The API and frontend
processes bind to loopback only.
