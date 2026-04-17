## Summary

Adds first-class support for logging to a **self-hosted Trackio server** via `trackio.init(..., server_url=...)` and the `TRACKIO_SERVER_URL` environment variable, so training jobs can target a dashboard you run on your own machine or infrastructure (not only a Hugging Face Space).

**Precedence:** `space_id` / `TRACKIO_SPACE_ID` always takes priority over `server_url` / `TRACKIO_SERVER_URL` when both are configured (arguments or env). The self-hosted URL is ignored in that case—no error.

Resolution logic lives in `trackio.utils.resolve_space_id_and_server_url()` and is covered by unit tests.

## Documentation

- [Self-host the Server](docs/source/self_hosted_server.md) (how-to: `trackio show`, bind host, `server_url` / `TRACKIO_SERVER_URL`, write-token caution)
- [Environment variables](docs/source/environment_variables.md): `TRACKIO_SERVER_URL` and precedence vs `TRACKIO_SPACE_ID`
- [Track](docs/source/track.md): new subsection on remote logging (Space vs self-hosted)
- [README](README.md): feature bullets and a **Self-hosted Trackio server** section with a doc link

## Tests

- E2E: logging to a local dashboard using `server_url` with the `full_url` from `trackio.show()`
- Unit: `resolve_space_id_and_server_url` (env precedence, explicit `space_id` over `server_url`, server-only)

## Release

Changeset: minor (`feat: Add first-class server_url for self-hosted Trackio servers`).

Closes #498
