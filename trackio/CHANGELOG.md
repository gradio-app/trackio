# trackio

## 0.33.0

### Features

- [#648](https://github.com/gradio-app/trackio/pull/648) [`6a1063f`](https://github.com/gradio-app/trackio/commit/6a1063f7c834f850390866b80608ca17c8563199) - Deprecate persisting data to HF Datasets in favor of Buckets.  Thanks @abidlabs!

### Fixes

- [#649](https://github.com/gradio-app/trackio/pull/649) [`8506189`](https://github.com/gradio-app/trackio/commit/8506189b69f6c0361e6420ef545abaad4a773cb3) - render logged histograms in the dashboard's Metrics tab.  Thanks @abidlabs!

## 0.32.2

### Features

- [#641](https://github.com/gradio-app/trackio/pull/641) [`2d1c01a`](https://github.com/gradio-app/trackio/commit/2d1c01a5ce0307ec5c81660c512bf6f25dd3120a) - Improve logbook layout and public repository views.  Thanks @abidlabs!
- [#643](https://github.com/gradio-app/trackio/pull/643) [`e8292c5`](https://github.com/gradio-app/trackio/commit/e8292c5c26baa0e7e806144fa1bbf5ecfb492f3d) - docs: document the artifact tables in the storage schema page.  Thanks @adrien-grl!

## 0.32.1

### Features

- [#639](https://github.com/gradio-app/trackio/pull/639) [`73971e6`](https://github.com/gradio-app/trackio/commit/73971e66a4f1daf5c42341727349e6f82ab4e887) - Fix logbook code overflow, CLI command truncation, Hub link contrast, resource ID validation, and live visibility detection for referenced trace datasets and Buckets.  Thanks @abidlabs!

## 0.32.0

### Features

- [#635](https://github.com/gradio-app/trackio/pull/635) [`b4587b0`](https://github.com/gradio-app/trackio/commit/b4587b0ebce18756a0f38e3721ed2880a7307137) - Add Code & Markdown, Traces, and Workspace logbook views with live local refresh, guided empty states, and privacy-aware manual publishing to Agent Traces Datasets and HF Buckets.  Thanks @NielsRogge!

## 0.31.5

### Features

- [#630](https://github.com/gradio-app/trackio/pull/630) [`bed508c`](https://github.com/gradio-app/trackio/commit/bed508c04c487686dea3dea70c67b058dd895f96) - Fix automatic dashboard cells to use the active logbook page instead of creating a page named after the Trackio project.  Thanks @abidlabs!

## 0.31.4

### Features

- [#628](https://github.com/gradio-app/trackio/pull/628) [`3eeaa99`](https://github.com/gradio-app/trackio/commit/3eeaa99bd05bef69053b9a1b5c7af3abf56c360c) - let `logbook cell figure` embed image files directly.  Thanks @abidlabs!/n  `trackio logbook cell figure` now accepts an image path via a new `--image`/n  flag, and `--html <file>` transparently embeds the file when it points at an/n  image. Previously the only way to add a PNG/JPG figure was to hand-encode it/n  into an `<img>` data-URI, and passing an image path to `--html` crashed with a/n  `UnicodeDecodeError` (the binary file was read as UTF-8 text). Images are/n  embedded as responsive base64 data URIs. The Python API `add_figure_cell` gains/n  a matching `image=` parameter.

## 0.31.3

### Features

- [#626](https://github.com/gradio-app/trackio/pull/626) [`174aecf`](https://github.com/gradio-app/trackio/commit/174aecff33e6d1cc8d71965a73538c0510abed46) - Fix logbook Markdown escaping and figure hotspot navigation.  Thanks @abidlabs!

## 0.31.2

### Features

- [#624](https://github.com/gradio-app/trackio/pull/624) [`a0918ed`](https://github.com/gradio-app/trackio/commit/a0918edc7594bb211f9e6871546b9d36939f0658) - Fix poster hotspot navigation after iframe load.  Thanks @abidlabs!

## 0.31.1

### Features

- [#621](https://github.com/gradio-app/trackio/pull/621) [`a40f1a4`](https://github.com/gradio-app/trackio/commit/a40f1a464c51652ecdeab04d999659d71b76047e) - add native fullscreen mode for logbook figures.  Thanks @abidlabs!
- [#623](https://github.com/gradio-app/trackio/pull/623) [`31fd4d7`](https://github.com/gradio-app/trackio/commit/31fd4d7b4004f0c511484f089e6a550da1b4d71e) - let interactive logbook figures navigate to logbook pages.  Thanks @abidlabs!

## 0.31.0

### Features

- [#601](https://github.com/gradio-app/trackio/pull/601) [`8c49140`](https://github.com/gradio-app/trackio/commit/8c491406c54685369d43f3a9c4d4a0e99108bc49) - browse artifacts from the UI.  Thanks @Saba9!
- [#602](https://github.com/gradio-app/trackio/pull/602) [`1ae1558`](https://github.com/gradio-app/trackio/commit/1ae155803b5450b181a47767255421499074c70b) - feat: add Artifact.add_reference to reference external objects without copy.  Thanks @adrien-grl!

## 0.30.4

### Features

- [#618](https://github.com/gradio-app/trackio/pull/618) [`64c18f6`](https://github.com/gradio-app/trackio/commit/64c18f65bf98d6f54040395a1ca0473347ba6a2b) - Logbook: share button on figures + `logbook pin` CLI.  Thanks @abidlabs!

## 0.30.3

### Features

- [#616](https://github.com/gradio-app/trackio/pull/616) [`645498b`](https://github.com/gradio-app/trackio/commit/645498be37bafab28f884a36e80c5bc0eab06cd9) - Logbook single page.  Thanks @abidlabs!

## 0.30.2

### Features

- [#614](https://github.com/gradio-app/trackio/pull/614) [`eba80c7`](https://github.com/gradio-app/trackio/commit/eba80c7464af250519a90b8ac3179ff6652b651a) - Render logbooks as single-page documents with section navigation and contextual resources.  Thanks @abidlabs!
- [#612](https://github.com/gradio-app/trackio/pull/612) [`2c1b943`](https://github.com/gradio-app/trackio/commit/2c1b9436b093e9f9335c99c10fe4b6afa622e314) - Warn that logbook open is experimental.  Thanks @abidlabs!
- [#611](https://github.com/gradio-app/trackio/pull/611) [`96b1d94`](https://github.com/gradio-app/trackio/commit/96b1d94def7596aa1302864cbfc57942dd63822b) - Logbook: auto-capture output artifacts and live-embedded dashboard cells.  Thanks @abidlabs!

## 0.30.1

### Features

- [#609](https://github.com/gradio-app/trackio/pull/609) [`2ed1295`](https://github.com/gradio-app/trackio/commit/2ed12959c73aa9c04ca1096cf7a8315ce2886ed1) - Serve live logbook preview from open.  Thanks @abidlabs!

## 0.30.0

### Features

- [#603](https://github.com/gradio-app/trackio/pull/603) [`a793fd8`](https://github.com/gradio-app/trackio/commit/a793fd88827482134bce295c6228e117de64566a) - Move default artifact downloads under `./.trackio/artifact-downloads/` so materialized files stay out of the project root.  Thanks @abidlabs!
- [#604](https://github.com/gradio-app/trackio/pull/604) [`dd3b8ee`](https://github.com/gradio-app/trackio/commit/dd3b8eeef4e0da8bf0df6238617e20ae81f3e564) - docs: clarify artifact types.  Thanks @abidlabs!
- [#586](https://github.com/gradio-app/trackio/pull/586) [`7db4c3b`](https://github.com/gradio-app/trackio/commit/7db4c3b6de6ff4903daf7dabed8842f212c8b7fd) - artifact tracking API — `log_artifact`, `use_artifact`, and an `Artifact` class for versioned, named file collections with aliases, content-addressed deduplication, and producer/consumer run lineage; works offline and syncs blobs to Hugging Face Spaces/Datasets.  Thanks @Saba9!
- [#597](https://github.com/gradio-app/trackio/pull/597) [`5ba561e`](https://github.com/gradio-app/trackio/commit/5ba561e1b4023abdf63624f4fb396367ed6e9e76) - Add experiment logbooks: shareable static-Space lab notebooks.  Thanks @abidlabs!

## 0.29.0

### Features

- [#593](https://github.com/gradio-app/trackio/pull/593) [`ca4722c`](https://github.com/gradio-app/trackio/commit/ca4722c19d2219a3a78b5977149873b9dff73f34) - Add CLI command to list Trackio Spaces.  Thanks @abidlabs!

## 0.28.1

### Features

- [#589](https://github.com/gradio-app/trackio/pull/589) [`5e9905d`](https://github.com/gradio-app/trackio/commit/5e9905d7815bb063f2d9bb38aa76177405c5e2b4) - Reduce Metrics page log payloads by requesting scalar-only metrics and add URL x-axis initialization/fallback handling.  Thanks @evalstate!
- [#590](https://github.com/gradio-app/trackio/pull/590) [`56493a6`](https://github.com/gradio-app/trackio/commit/56493a6e9a0114b8655ab44b8c3dec7bae2a5df5) - Use TRACKIO_WRITE_TOKEN for server write token.  Thanks @abidlabs!

## 0.28.0

### Features

- [#582](https://github.com/gradio-app/trackio/pull/582) [`d9dabb5`](https://github.com/gradio-app/trackio/commit/d9dabb5bda8147ad7c9203646358bd0880fa6521) - Add JSONL inbox fragments: durable logging when the Space is unreachable and on network filesystems.  Thanks @abidlabs!

## 0.27.0

### Features

- [#567](https://github.com/gradio-app/trackio/pull/567) [`8c0ce21`](https://github.com/gradio-app/trackio/commit/8c0ce21ff9746d7c6a250684b1b5f0f3f04e0520) - Add CPU, RAM, disk, network and sensor metrics monitoring for non-Apple devices.  Thanks @yannsadowski!
- [#571](https://github.com/gradio-app/trackio/pull/571) [`57bc7df`](https://github.com/gradio-app/trackio/commit/57bc7df27ecd7b3ff543dbd2bff5c94182bfb69e) - Fix IndexError when importing CSV with no numeric metric columns.  Thanks @Ckal!
- [#577](https://github.com/gradio-app/trackio/pull/577) [`db0e730`](https://github.com/gradio-app/trackio/commit/db0e730463103142688c1c0efef9ff68a52e281d) - Sort and paginate media items.  Thanks @abidlabs!
- [#576](https://github.com/gradio-app/trackio/pull/576) [`6f635e2`](https://github.com/gradio-app/trackio/commit/6f635e22553ce2deaece6a0d6289475ab8683040) - Render plot/metric titles as searchable DOM text.  Thanks @abidlabs!
- [#579](https://github.com/gradio-app/trackio/pull/579) [`cf7759e`](https://github.com/gradio-app/trackio/commit/cf7759efaab73ce1e98a8a2355dc1f65d54bc775) - Merge image viewer with current media page, credit to @catwell.  Thanks @abidlabs!

## 0.26.0

### Features

- [#553](https://github.com/gradio-app/trackio/pull/553) [`06011ac`](https://github.com/gradio-app/trackio/commit/06011acc9c73341fd234f9cd8eaf96d5a34ad8ce) - fix: serve static-Space assets at /static/trackio.  Thanks @abidlabs!
- [#563](https://github.com/gradio-app/trackio/pull/563) [`551569c`](https://github.com/gradio-app/trackio/commit/551569c16fb56ec63249ebdc28348d326ccf7126) - Fix Traces UI a bit.  Thanks @abidlabs!
- [#550](https://github.com/gradio-app/trackio/pull/550) [`5690acd`](https://github.com/gradio-app/trackio/commit/5690acda5da303c63ad332451afeab3e9750fd1a) - fix: keep sparse metrics sparse through smoothing.  Thanks @abidlabs!
- [#551](https://github.com/gradio-app/trackio/pull/551) [`0ef7266`](https://github.com/gradio-app/trackio/commit/0ef72660695cf932f3906ddbf33d41d087280a22) - add "group by" dropdown to sidebar.  Thanks @Saba9!
- [#538](https://github.com/gradio-app/trackio/pull/538) [`a15c1a8`](https://github.com/gradio-app/trackio/commit/a15c1a8877c07514e0596630bb7c7299299994a9) - Subdue empty dashboard tabs.  Thanks @abidlabs!
- [#559](https://github.com/gradio-app/trackio/pull/559) [`0b53a41`](https://github.com/gradio-app/trackio/commit/0b53a413909598f92138b6b6395a91c2d5034faf) - Store traces separately from metrics.  Thanks @abidlabs!
- [#556](https://github.com/gradio-app/trackio/pull/556) [`d110001`](https://github.com/gradio-app/trackio/commit/d110001dbd9f6b262dfe41f2b702e3a71aa0cfc9) - fix: keep selected x-axis option in dropdown and dismiss dropdown on re-click.  Thanks @Saba9!
- [#560](https://github.com/gradio-app/trackio/pull/560) [`aee2923`](https://github.com/gradio-app/trackio/commit/aee2923d3ada4f74d62d065c16f1f6a56a295e48) - Paginate Traces tab with step filter.  Thanks @abidlabs!

### Fixes

- [#540](https://github.com/gradio-app/trackio/pull/540) [`0b674ac`](https://github.com/gradio-app/trackio/commit/0b674ac6438738de89bc5b3fb700ccfd8a39368c) - raise default metrics sampling cap from 1500 to 3000 so client-side smoothing on the Metrics tab runs over higher-resolution data.  Thanks @edbeeching!

## 0.25.1

### Features

- [#535](https://github.com/gradio-app/trackio/pull/535) [`d7f1b27`](https://github.com/gradio-app/trackio/commit/d7f1b27a98f185d2d97ef54975d5865e0b5243c9) - Avoid HF token leaks in static snapshots.  Thanks @abidlabs!

## 0.25.0

### Features

- [#533](https://github.com/gradio-app/trackio/pull/533) [`08bc5eb`](https://github.com/gradio-app/trackio/commit/08bc5eb090525d3ff5f7fa4233c30c42162aa74c) - Fix Windows-only emoji mojibake when uploading Space README.  Thanks @tomaarsen!
- [#518](https://github.com/gradio-app/trackio/pull/518) [`e7ed176`](https://github.com/gradio-app/trackio/commit/e7ed176da53d8b49290fddd890b3d18c0b9b958f) - Traces in Trackio.  Thanks @abidlabs!
- [#531](https://github.com/gradio-app/trackio/pull/531) [`27a50a3`](https://github.com/gradio-app/trackio/commit/27a50a37362020304b774344b4c774ff548985b6) - Add configurable custom frontends for Trackio.  Thanks @abidlabs!

## 0.24.2

### Features

- [#527](https://github.com/gradio-app/trackio/pull/527) [`7d1c0b9`](https://github.com/gradio-app/trackio/commit/7d1c0b9c37ce9a9845e6bbe6c083da9d36084caf) - Fix dashboard UX issues: smoothing in share URL, run selection, and run filtering.  Thanks @abidlabs!
- [#526](https://github.com/gradio-app/trackio/pull/526) [`643878a`](https://github.com/gradio-app/trackio/commit/643878a82985fab9e6675f769ff0107cb46e042a) - Add emoji to README and deploy README content.  Thanks @qgallouedec!
- [#529](https://github.com/gradio-app/trackio/pull/529) [`a77972b`](https://github.com/gradio-app/trackio/commit/a77972b68541ebe9e056824e69c9bbca3979ece4) - Remove pydub dependency.  Thanks @abidlabs!

## 0.24.1

### Features

- [#524](https://github.com/gradio-app/trackio/pull/524) [`65a6897`](https://github.com/gradio-app/trackio/commit/65a6897561b465fc8f05550562f8da1ba3c99060) - Fix `trackio skills add`.  Thanks @abidlabs!
- [#522](https://github.com/gradio-app/trackio/pull/522) [`05aaca7`](https://github.com/gradio-app/trackio/commit/05aaca7f166bf7667b60b40656d677532a4bdd6e) - relax `starlette` dependency and fix import style.  Thanks @abidlabs!
- [#525](https://github.com/gradio-app/trackio/pull/525) [`32c05c5`](https://github.com/gradio-app/trackio/commit/32c05c5d5e3aa84ca7099a6fa08a9093ccd4b95f) - Restore sidebar share and embed snippets, and fix query parameter regression.  Thanks @abidlabs!

## 0.24.0

### Features

- [#502](https://github.com/gradio-app/trackio/pull/502) [`3b397df`](https://github.com/gradio-app/trackio/commit/3b397dfbaff9de137b088f3cad528117e14faab1) - Add docs on SQL & Parquet schema / format, as well as a new CLI command: `trackio query project --project PROJECT --sql SQL_QUERY`.  Thanks @abidlabs!
- [#506](https://github.com/gradio-app/trackio/pull/506) [`498bbc4`](https://github.com/gradio-app/trackio/commit/498bbc47f66cc90cc5776f363d001a5571941c00) - Scope bucket sync to trackio/ subtree to avoid walking the HF cache.  Thanks @abidlabs!
- [#505](https://github.com/gradio-app/trackio/pull/505) [`8e26ab9`](https://github.com/gradio-app/trackio/commit/8e26ab93b5d9caa2f81334f6fff42fb9cefbb232) - Add an `id` field to `Run` which is used internally, allowing users to have multiple runs with the same run name.  Thanks @abidlabs!
- [#517](https://github.com/gradio-app/trackio/pull/517) [`29e1034`](https://github.com/gradio-app/trackio/commit/29e1034b795567ec5ed6d19c5a946915a6498e2a) - Fix static exports, Space bucket handling, and other misc issues.  Thanks @abidlabs!
- [#489](https://github.com/gradio-app/trackio/pull/489) [`1b96db3`](https://github.com/gradio-app/trackio/commit/1b96db39c8fd4326e621ee2336b0fca4f263a18a) - Remove `gradio` dependency in `trackio` -- only `gradio_client` is needed locally anymore. Also lazily import `pandas` and remove it as a dependency.  Thanks @abidlabs!
- [#513](https://github.com/gradio-app/trackio/pull/513) [`d54d290`](https://github.com/gradio-app/trackio/commit/d54d290fcb1bb08358b558a43a962f78abe990ea) - Reduce HF Spaces 429s: polling tuning and batched metric logs API.  Thanks @abidlabs!
- [#516](https://github.com/gradio-app/trackio/pull/516) [`afe2959`](https://github.com/gradio-app/trackio/commit/afe295988928a3ea3ded38bdb5bb05cca85d3c74) - Fix run list order and legend overflow.  Thanks @abidlabs!
- [#515](https://github.com/gradio-app/trackio/pull/515) [`0a242b8`](https://github.com/gradio-app/trackio/commit/0a242b85127b02f532b24c7fd2bb046580cc7641) - Add Gradio-compatible /gradio_api routes on Spaces.  Thanks @abidlabs!
- [#510](https://github.com/gradio-app/trackio/pull/510) [`60bbc86`](https://github.com/gradio-app/trackio/commit/60bbc86b4e7f880de72075e5bf31b093709bb5a4) - Add server_url and TRACKIO_SERVER_URL for self-hosted servers; space_id and TRACKIO_SPACE_ID take precedence when both are set.  Thanks @abidlabs!
- [#509](https://github.com/gradio-app/trackio/pull/509) [`21c099a`](https://github.com/gradio-app/trackio/commit/21c099aa830a278973fab4c7c58a0139f417caa4) - Fix: Open browser with write_token so trackio show allows mutations.  Thanks @abidlabs!

## 0.23.0

### Features

- [#494](https://github.com/gradio-app/trackio/pull/494) [`e8a897d`](https://github.com/gradio-app/trackio/commit/e8a897d2266d9b2558f72d768b0b21f4d0a8781b) - Add a settings/CLI page to Trackio.  Thanks @abidlabs!
- [#481](https://github.com/gradio-app/trackio/pull/481) [`882647e`](https://github.com/gradio-app/trackio/commit/882647ec1599cf04500d03b5ca75ddc2733682e2) - Add multi-GPU system metrics support.  Thanks @Saba9!
- [#485](https://github.com/gradio-app/trackio/pull/485) [`46a3cc3`](https://github.com/gradio-app/trackio/commit/46a3cc3758719e171417612efee102a487e71ebd) - Fix/remove flaky E2E space tests.  Thanks @abidlabs!
- [#501](https://github.com/gradio-app/trackio/pull/501) [`06ea885`](https://github.com/gradio-app/trackio/commit/06ea8852f5e40ab3f1cf629a0a01af5c17f847a1) - Fix SQLite corruption on bucket-mounted Spaces.  Thanks @abidlabs!
- [#496](https://github.com/gradio-app/trackio/pull/496) [`af23d74`](https://github.com/gradio-app/trackio/commit/af23d74438b146c4a3512ace15ea984656e943ed) - Prevent trackio errors from crashing the user's training loop.  Thanks @abidlabs!

## 0.22.0

### Features

- [#484](https://github.com/gradio-app/trackio/pull/484) [`cc05ada`](https://github.com/gradio-app/trackio/commit/cc05ada8e89773f3a894af99b801ef680f64418f) - Fix duplicate columns in parquet export.  Thanks @abidlabs!
- [#487](https://github.com/gradio-app/trackio/pull/487) [`853f764`](https://github.com/gradio-app/trackio/commit/853f7646a70d12633afaa4f69db86425aa665413) - Relax `PIL` dependency and remove `plotly` as it's no longer used.  Thanks @abidlabs!

## 0.21.2

### Features

- [#482](https://github.com/gradio-app/trackio/pull/482) [`f62180a`](https://github.com/gradio-app/trackio/commit/f62180a0218bc99a259d5ca110a0384a6cae11c8) - Use server-side bucket copy when freezing Spaces.  Thanks @abidlabs!

## 0.21.1

### Features

- [#475](https://github.com/gradio-app/trackio/pull/475) [`fcb476c`](https://github.com/gradio-app/trackio/commit/fcb476cd37a40923e9679aaf966f41d582a878a8) - Tweaks.  Thanks @abidlabs!
- [#477](https://github.com/gradio-app/trackio/pull/477) [`7d52dfd`](https://github.com/gradio-app/trackio/commit/7d52dfdce5b6eff6a34501a6d5a620220663cf09) - Fix `.sync()` and add `.freeze()` as a separate methods.  Thanks @abidlabs!

## 0.21.0

### Features

- [#467](https://github.com/gradio-app/trackio/pull/467) [`f357deb`](https://github.com/gradio-app/trackio/commit/f357debf78957e4c1f2b901bee4f77cf397298b4) - Allow logged metrics as x-axis choices.  Thanks @abidlabs!
- [#474](https://github.com/gradio-app/trackio/pull/474) [`655673d`](https://github.com/gradio-app/trackio/commit/655673d4c6b7c8b7ee8f87f2589f2dbbc3d2ef91) - Fix file descriptor leak from `sqlite3.connect`.  Thanks @abidlabs!
- [#470](https://github.com/gradio-app/trackio/pull/470) [`bea8c9d`](https://github.com/gradio-app/trackio/commit/bea8c9dcae0b59d071b6c779c97ee525c9bbf6e7) - Restores tooltips to line plots and fixes the call to uses TTL instead of OAuth.  Thanks @abidlabs!
- [#471](https://github.com/gradio-app/trackio/pull/471) [`246fce0`](https://github.com/gradio-app/trackio/commit/246fce0a01619e1c2c538c67b3e460883334d500) - Deprecate dataset backend in favor of buckets.  Thanks @abidlabs!
- [#465](https://github.com/gradio-app/trackio/pull/465) [`3e11174`](https://github.com/gradio-app/trackio/commit/3e1117438bb8168b802245a33059affa558ae519) - Use HF buckets as backend.  Thanks @abidlabs!
- [#469](https://github.com/gradio-app/trackio/pull/469) [`915d170`](https://github.com/gradio-app/trackio/commit/915d17045133172b59195acfdcc70709229668aa) - Make static Spaces work with Buckets and also allow conversion from Gradio SDK to Static Spaces.  Thanks @abidlabs!

## 0.20.2

### Features

- [#464](https://github.com/gradio-app/trackio/pull/464) [`c89ebb3`](https://github.com/gradio-app/trackio/commit/c89ebb3b50f695bc7f16cbc6f46dce86f79a01e9) - Improve rendering of curves.  Thanks @abidlabs!
- [#462](https://github.com/gradio-app/trackio/pull/462) [`9160b78`](https://github.com/gradio-app/trackio/commit/9160b78ff6f258f0b87a4f34a24e7d0b5dfbf2fb) - Refactor plot title to display only the metric name without the path.  Thanks @qgallouedec!

## 0.20.1

### Features

- [#454](https://github.com/gradio-app/trackio/pull/454) [`22881db`](https://github.com/gradio-app/trackio/commit/22881dbbbb6b81197a00a19853771007093d61e4) - Bar chart single point.  Thanks @abidlabs!
- [#455](https://github.com/gradio-app/trackio/pull/455) [`f8db51a`](https://github.com/gradio-app/trackio/commit/f8db51a20ca61ef703f3f2c2ee1ebd9c4f239cf2) - Adds a static Trackio mode via `trackio.sync(sdk="static")` and support for the `TRACKIO_SPACE_ID` environment variable.  Thanks @abidlabs!

## 0.20.0

### Features

- [#450](https://github.com/gradio-app/trackio/pull/450) [`b0571ef`](https://github.com/gradio-app/trackio/commit/b0571ef6207a1ce346696f858ad2b7b584dd194f) - Use Svelte source for Gradio components directly in Trackio dashboard.  Thanks @abidlabs!

## 0.19.0

### Features

- [#445](https://github.com/gradio-app/trackio/pull/445) [`cef4a58`](https://github.com/gradio-app/trackio/commit/cef4a583cb76f4091fc6c0e5783124ee84f8e243) - Add remote HF Space support to CLI.  Thanks @abidlabs!
- [#444](https://github.com/gradio-app/trackio/pull/444) [`358f2a9`](https://github.com/gradio-app/trackio/commit/358f2a9ca238ee8b90b5a8c96220da287e0698fb) - Fix alerts placeholder flashing on reports page.  Thanks @abidlabs!

## 0.18.0

### Features

- [#435](https://github.com/gradio-app/trackio/pull/435) [`4a47112`](https://github.com/gradio-app/trackio/commit/4a471128e18a39e45fad48a67fd711c5ae9e4aed) - feat: allow hiding section header accordions.  Thanks @Saba9!
- [#439](https://github.com/gradio-app/trackio/pull/439) [`18e9650`](https://github.com/gradio-app/trackio/commit/18e96503d5a3a7cf926e92782d457e23c19942bd) - Add alerts with webhooks, CLI, and documentation.  Thanks @abidlabs!
- [#438](https://github.com/gradio-app/trackio/pull/438) [`0875ccd`](https://github.com/gradio-app/trackio/commit/0875ccd3d8a41b1376f64030f21cfe8cdcc73b05) - Add "share this view" functionality.  Thanks @qgallouedec!
- [#409](https://github.com/gradio-app/trackio/pull/409) [`9282403`](https://github.com/gradio-app/trackio/commit/9282403d8896d48679b0f888208a7ba5bdd4271a) - Add Apple Silicon GPU and system monitoring support.  Thanks @znation!
- [#434](https://github.com/gradio-app/trackio/pull/434) [`4193223`](https://github.com/gradio-app/trackio/commit/41932230a3a2e1c16405dba08ecba5a42f11d1a8) - fix: table slider crash.  Thanks @Saba9!

### Fixes

- [#441](https://github.com/gradio-app/trackio/pull/441) [`3a2d11d`](https://github.com/gradio-app/trackio/commit/3a2d11dab0b4b37c925abc30ef84b0e2910321ee) - preserve x-axis step when toggling run checkboxes.  Thanks @Saba9!

## 0.17.0

### Features

- [#428](https://github.com/gradio-app/trackio/pull/428) [`f7dd1ce`](https://github.com/gradio-app/trackio/commit/f7dd1ce2dc8a1936f9983467fcbcf93bfef01e09) - feat: add ability to rename runs.  Thanks @Saba9!
- [#437](https://github.com/gradio-app/trackio/pull/437) [`2727c0b`](https://github.com/gradio-app/trackio/commit/2727c0b0755f48f7f186162ea45185c98f6b5516) - Add markdown reports across Trackio.  Thanks @abidlabs!
- [#427](https://github.com/gradio-app/trackio/pull/427) [`5aeb9ed`](https://github.com/gradio-app/trackio/commit/5aeb9edcfd2068d309d9d64f172dcbcc327be1ab) - Make Trackio logging much more robust.  Thanks @abidlabs!

## 0.16.1

### Features

- [#431](https://github.com/gradio-app/trackio/pull/431) [`c7ce55b`](https://github.com/gradio-app/trackio/commit/c7ce55b14dd5eb0c2165fb15df17dd60721c9325) - Lazy load the UI when trackio is imported.  Thanks @abidlabs!

## 0.16.0

### Features

- [#426](https://github.com/gradio-app/trackio/pull/426) [`ead4dc8`](https://github.com/gradio-app/trackio/commit/ead4dc8e74ee2d8e47d61bca0a7668456acf49be) - Fix redundant double rendering of group checkboxes.  Thanks @abidlabs!
- [#413](https://github.com/gradio-app/trackio/pull/413) [`39c4750`](https://github.com/gradio-app/trackio/commit/39c4750951d554ba6eb4d58847c6bb444b2891a8) - Check `dist-packages` when checking for source installation.  Thanks @sergiopaniego!
- [#423](https://github.com/gradio-app/trackio/pull/423) [`2e52ab3`](https://github.com/gradio-app/trackio/commit/2e52ab303e3041718a6a56fbf84d0848aca9ad67) - Fix legend outline visibility issue.  Thanks @Raghunath-Balaji!
- [#407](https://github.com/gradio-app/trackio/pull/407) [`c8a384d`](https://github.com/gradio-app/trackio/commit/c8a384ddfe5a295cecf862a26178d40e48acb424) - Fix pytests that were failling locally on MacOS.  Thanks @abidlabs!
- [#405](https://github.com/gradio-app/trackio/pull/405) [`35aae4e`](https://github.com/gradio-app/trackio/commit/35aae4e3aa3e2b2888887528478b9dc6a9808bda) - Add conditional padding for HF Space dashboard when not in iframe.  Thanks @znation!

## 0.15.0

### Features

- [#397](https://github.com/gradio-app/trackio/pull/397) [`6b38ad0`](https://github.com/gradio-app/trackio/commit/6b38ad02e5d73a0df49c4eede7e91331282ece04) - Adds `--host` cli option support.  Thanks @abidlabs!
- [#396](https://github.com/gradio-app/trackio/pull/396) [`4a4d1ab`](https://github.com/gradio-app/trackio/commit/4a4d1ab85e63d923132a3fa7afa5d90e16431bec) - Fix run selection issue.  Thanks @abidlabs!
- [#394](https://github.com/gradio-app/trackio/pull/394) [`c47a3a3`](https://github.com/gradio-app/trackio/commit/c47a3a31f8c4b83bce1aa7fc22eeba3d9021ad3d) - Add wandb-compatible API for trackio.  Thanks @abidlabs!
- [#378](https://github.com/gradio-app/trackio/pull/378) [`b02046a`](https://github.com/gradio-app/trackio/commit/b02046a5b0dad7c9854e099a87f884afba4aecb2) - Add JSON export button for line plots and upgrade gradio dependency.  Thanks @JamshedAli18!

## 0.14.2

### Features

- [#386](https://github.com/gradio-app/trackio/pull/386) [`f9452cd`](https://github.com/gradio-app/trackio/commit/f9452cdb8f0819368f3610f7ac0ed08957305275) - Fixing some issues related to deployed Trackio Spaces.  Thanks @abidlabs!

## 0.14.1

### Features

- [#382](https://github.com/gradio-app/trackio/pull/382) [`44fe9bb`](https://github.com/gradio-app/trackio/commit/44fe9bb264fb2aafb0ec302ff15227c045819a2c) - Fix app file path when Trackio is not installed from source.  Thanks @abidlabs!
- [#380](https://github.com/gradio-app/trackio/pull/380) [`c3f4cff`](https://github.com/gradio-app/trackio/commit/c3f4cff74bc5676e812773d8571454894fcdc7cc) - Add CLI commands for querying projects, runs, and metrics.  Thanks @abidlabs!

## 0.14.0

### Features

- [#377](https://github.com/gradio-app/trackio/pull/377) [`5c5015b`](https://github.com/gradio-app/trackio/commit/5c5015b68c85c5de51111dad983f735c27b9a05f) - fixed wrapping issue in Runs table.  Thanks @gaganchapa!
- [#374](https://github.com/gradio-app/trackio/pull/374) [`388e26b`](https://github.com/gradio-app/trackio/commit/388e26b9e9f24cd7ad203affe9b709be885b3d24) - Save Optimized Parquet files.  Thanks @lhoestq!
- [#371](https://github.com/gradio-app/trackio/pull/371) [`fbace9c`](https://github.com/gradio-app/trackio/commit/fbace9cd7732c166f34d268f54b05bb06846cc5d) - Add GPU metrics logging.  Thanks @kashif!
- [#367](https://github.com/gradio-app/trackio/pull/367) [`862840c`](https://github.com/gradio-app/trackio/commit/862840c13e30fc960cbee5b9eac4d3c25beba9de) - Add option to only show latest run, and fix the double logo issue.  Thanks @abidlabs!

## 0.13.1

### Features

- [#369](https://github.com/gradio-app/trackio/pull/369) [`767e9fe`](https://github.com/gradio-app/trackio/commit/767e9fe095d7c6ed102016caf927c1517fb8618c) - tiny pr removing unnecessary code.  Thanks @abidlabs!

## 0.13.0

### Features

- [#358](https://github.com/gradio-app/trackio/pull/358) [`073715d`](https://github.com/gradio-app/trackio/commit/073715d1caf8282f68890117f09c3ac301205312) - Improvements to `trackio.sync()`.  Thanks @abidlabs!

## 0.12.0

### Features

- [#357](https://github.com/gradio-app/trackio/pull/357) [`02ba815`](https://github.com/gradio-app/trackio/commit/02ba815358060f1966052de051a5bdb09702920e) - Redesign media and tables to show up on separate page.  Thanks @abidlabs!
- [#359](https://github.com/gradio-app/trackio/pull/359) [`08fe9c9`](https://github.com/gradio-app/trackio/commit/08fe9c9ddd7fe99ee811555fdfb62df9ab88e939) - docs: Improve docstrings.  Thanks @qgallouedec!

## 0.11.0

### Features

- [#355](https://github.com/gradio-app/trackio/pull/355) [`ea51f49`](https://github.com/gradio-app/trackio/commit/ea51f4954922f21be76ef828700420fe9a912c4b) - Color code run checkboxes and match with plot lines.  Thanks @abidlabs!
- [#353](https://github.com/gradio-app/trackio/pull/353) [`8abe691`](https://github.com/gradio-app/trackio/commit/8abe6919aeefe21fc7a23af814883efbb037c21f) - Remove show_api from demo.launch.  Thanks @sergiopaniego!
- [#351](https://github.com/gradio-app/trackio/pull/351) [`8a8957e`](https://github.com/gradio-app/trackio/commit/8a8957e530dd7908d1fef7f2df030303f808101f) - Add `trackio.save()`.  Thanks @abidlabs!

## 0.10.0

### Features

- [#305](https://github.com/gradio-app/trackio/pull/305) [`e64883a`](https://github.com/gradio-app/trackio/commit/e64883a51f7b8b93f7d48b8afe55acdb62238b71) - bump to gradio 6.0, make `trackio` compatible, and fix related issues.  Thanks @abidlabs!

## 0.9.1

### Features

- [#344](https://github.com/gradio-app/trackio/pull/344) [`7e01024`](https://github.com/gradio-app/trackio/commit/7e010241d9a34794e0ce0dc19c1a6f0cf94ba856) - Avoid redundant calls to /whoami-v2.  Thanks @Wauplin!

## 0.9.0

### Features

- [#343](https://github.com/gradio-app/trackio/pull/343) [`51bea30`](https://github.com/gradio-app/trackio/commit/51bea30f2877adff8e6497466d3a799400a0a049) - Sync offline projects to Hugging Face spaces.  Thanks @candemircan!
- [#341](https://github.com/gradio-app/trackio/pull/341) [`4fd841f`](https://github.com/gradio-app/trackio/commit/4fd841fa190e15071b02f6fba7683ef4f393a654) - Adds a basic UI test to `trackio`.  Thanks @abidlabs!
- [#339](https://github.com/gradio-app/trackio/pull/339) [`011d91b`](https://github.com/gradio-app/trackio/commit/011d91bb6ae266516fd250a349285670a8049d05) - Allow customzing the trackio color palette.  Thanks @abidlabs!

## 0.8.1

### Features

- [#336](https://github.com/gradio-app/trackio/pull/336) [`5f9f51d`](https://github.com/gradio-app/trackio/commit/5f9f51dac8677f240d7c42c3e3b2660a22aee138) - Support a list of `Trackio.Image` in a `trackio.Table` cell.  Thanks @abidlabs!

## 0.8.0

### Features

- [#331](https://github.com/gradio-app/trackio/pull/331) [`2c02d0f`](https://github.com/gradio-app/trackio/commit/2c02d0fd0a5824160528782402bb0dd4083396d5) - Truncate table string values that are greater than 250 characters (configuirable via env variable).  Thanks @abidlabs!
- [#324](https://github.com/gradio-app/trackio/pull/324) [`50b2122`](https://github.com/gradio-app/trackio/commit/50b2122e7965ac82a72e6cb3b7d048bc10a2a6b1) - Add log y-axis functionality to UI.  Thanks @abidlabs!
- [#326](https://github.com/gradio-app/trackio/pull/326) [`61dc1f4`](https://github.com/gradio-app/trackio/commit/61dc1f40af2f545f8e70395ddf0dbb8aee6b60d5) - Fix: improve table rendering for metrics in Trackio Dashboard.  Thanks @vigneshwaran!
- [#328](https://github.com/gradio-app/trackio/pull/328) [`6857cbb`](https://github.com/gradio-app/trackio/commit/6857cbbe557a59a4642f210ec42566d108294e63) - Support trackio.Table with trackio.Image columns.  Thanks @abidlabs!
- [#323](https://github.com/gradio-app/trackio/pull/323) [`6857cbb`](https://github.com/gradio-app/trackio/commit/6857cbbe557a59a4642f210ec42566d108294e63) - add Trackio client implementations in Go, Rust, and JS.  Thanks @vaibhav-research!

## 0.7.0

### Features

- [#277](https://github.com/gradio-app/trackio/pull/277) [`db35601`](https://github.com/gradio-app/trackio/commit/db35601b9c023423c4654c9909b8ab73e58737de) - fix: make grouped runs view reflect live updates.  Thanks @Saba9!
- [#320](https://github.com/gradio-app/trackio/pull/320) [`24ae739`](https://github.com/gradio-app/trackio/commit/24ae73969b09fb3126acd2f91647cdfbf8cf72a1) - Add additional query parms for xmin, xmax, and smoothing.  Thanks @abidlabs!
- [#270](https://github.com/gradio-app/trackio/pull/270) [`cd1dfc3`](https://github.com/gradio-app/trackio/commit/cd1dfc3dc641b4499ac6d4a1b066fa8e2b52c57b) - feature: add support for logging audio.  Thanks @Saba9!

## 0.6.0

### Features

- [#309](https://github.com/gradio-app/trackio/pull/309) [`1df2353`](https://github.com/gradio-app/trackio/commit/1df23534d6c01938c8db9c0f584ffa23e8d6021d) - Add histogram support with wandb-compatible API.  Thanks @abidlabs!
- [#315](https://github.com/gradio-app/trackio/pull/315) [`76ba060`](https://github.com/gradio-app/trackio/commit/76ba06055dc43ca8f03b79f3e72d761949bd19a8) - Add guards to avoid silent fails.  Thanks @Xmaster6y!
- [#313](https://github.com/gradio-app/trackio/pull/313) [`a606b3e`](https://github.com/gradio-app/trackio/commit/a606b3e1c5edf3d4cf9f31bd50605226a5a1c5d0) - No longer prevent certain keys from being used. Instead, dunderify them to prevent collisions with internal usage.  Thanks @abidlabs!
- [#317](https://github.com/gradio-app/trackio/pull/317) [`27370a5`](https://github.com/gradio-app/trackio/commit/27370a595d0dbdf7eebbe7159d2ba778f039da44) - quick fixes for trackio.histogram.  Thanks @abidlabs!
- [#312](https://github.com/gradio-app/trackio/pull/312) [`aa0f3bf`](https://github.com/gradio-app/trackio/commit/aa0f3bf372e7a0dd592a38af699c998363830eeb) - Fix video logging by adding TRACKIO_DIR to allowed_paths.  Thanks @abidlabs!

## 0.5.3

### Features

- [#300](https://github.com/gradio-app/trackio/pull/300) [`5e4cacf`](https://github.com/gradio-app/trackio/commit/5e4cacf2e7ce527b4ce60de3a5bc05d2c02c77fb) - Adds more environment variables to allow customization of Trackio dashboard.  Thanks @abidlabs!

## 0.5.2

### Features

- [#293](https://github.com/gradio-app/trackio/pull/293) [`64afc28`](https://github.com/gradio-app/trackio/commit/64afc28d3ea1dfd821472dc6bf0b8ed35a9b74be) - Ensures that the TRACKIO_DIR environment variable is respected.  Thanks @abidlabs!
- [#287](https://github.com/gradio-app/trackio/pull/287) [`cd3e929`](https://github.com/gradio-app/trackio/commit/cd3e9294320949e6b8b829239069a43d5d7ff4c1) - fix(sqlite): unify .sqlite extension, allow export when DBs exist, clean WAL sidecars on import.  Thanks @vaibhav-research!

### Fixes

- [#291](https://github.com/gradio-app/trackio/pull/291) [`3b5adc3`](https://github.com/gradio-app/trackio/commit/3b5adc3d1f452dbab7a714d235f4974782f93730) - Fix the wheel build.  Thanks @pngwn!

## 0.5.1

### Fixes

- [#278](https://github.com/gradio-app/trackio/pull/278) [`314c054`](https://github.com/gradio-app/trackio/commit/314c05438007ddfea3383e06fd19143e27468e2d) - Fix row orientation of metrics plots.  Thanks @abidlabs!