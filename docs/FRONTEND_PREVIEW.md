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

The API enables CORS only for the local preview ports (`8890` and `3000`). For a production
deployment, put the frontend behind the same trusted gateway as the API and replace this
allow-list with the exact origin used by that deployment.

## Preview verification

The local preview was exercised against the real configured `glm-5.2` provider using an
isolated `demo-ui/private` state:

1. ingest a mechanical calibration record;
2. approve the human gate in the UI;
3. retrieve the active knowledge and render its evidence pack;
4. confirm the live activity timeline contains provider, graph, approval, and retrieval events.

This is a local preview, not an externally hosted public deployment. The API and frontend
processes bind to loopback only.
