# Postman Collection

Files: `postman/AgentABI.postman_collection.json`, `postman/AgentABI.local.postman_environment.json.example`.

## 1. Import the collection
Postman → Import → select `postman/AgentABI.postman_collection.json`.

## 2. Import the environment
Postman → Import → select `postman/AgentABI.local.postman_environment.json.example`. Rename the imported environment (e.g. "AgentABI Local") and select it as active. The `.example` suffix is intentional — copy/rename it locally; never commit a filled-in copy with real values.

## 3. Set `base_url`
Defaults to `http://localhost:8000`. Change it if the API runs elsewhere.

## 4. Get an AgentABI JWT (GitHub OAuth2)
Postman cannot drive the interactive GitHub login (spec requires a browser). In a browser, visit `{base_url}/api/v1/auth/github/login`, complete GitHub's consent screen, and the callback returns the AgentABI JWT (`access_token`) in the JSON response.

## 5. Put the JWT in `access_token`
Paste the token into the environment's `access_token` variable (type `secret`, so it's masked in the UI). Every request except Health, GitHub OAuth login/callback, and the GitHub webhook uses collection-level Bearer auth (`{{access_token}}`) automatically.

## 6. Calling protected endpoints
Run "Projects → Create" first (stores `project_id`) or set it manually, then the rest of the Projects/Components/Graph/Compatibility/Trajectories/Replays folders will work in order — several requests store IDs (e.g. `component_id`, `scan_id`) into the environment on success so later requests can reference them.

## 7. Role requirements
Create/update actions generally require ADMIN or OWNER in the organization/project; read actions accept any membership (OWNER/ADMIN/MEMBER). The audit endpoint is ADMIN/OWNER only — a MEMBER token gets 403. See each request's description in the collection, and `docs/DECISIONS.md` for the full RBAC model.

## 8. Organization isolation
A JWT's role is reloaded from the database per request, scoped to the organization/project in the path. Calling a route with an `organization_id`/`project_id` the caller has no membership in returns 404 (not 403) for cross-tenant resources, so existence is not leaked.

## 9. Webhook testing
"GitHub Webhook → Ping (webhook delivery)" has a pre-request script that computes `X-Hub-Signature-256` via HMAC-SHA256 from the environment's `github_webhook_secret`, using `crypto-js` (bundled in Postman's sandbox). Set `github_webhook_secret` to match your local server's configured webhook secret before sending, or the request will correctly receive `401`. This request uses `noauth` — it does not send an AgentABI Bearer token, since GitHub authenticates via the signature instead.

## 10. Endpoints needing real infrastructure
Compatibility scans and replay execution depend on running workers/executors not shipped as part of this phase's tooling — a `POST .../replays/{id}/execute` call can legitimately return `503` if no executor is configured; this is documented behavior, not a bug. The GitHub OAuth login/callback pair needs a real GitHub OAuth App configured in the server's environment.
