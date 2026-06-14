# VERA — Third-Party Software (TPS reference)

Epic's TPS form caps at **10 sources** — these are the **10 most important** (every
non-permissive license + VERA's direct deps). Fill the form **in this order**.

**Same answers for every entry:**
- **Seller:** EazyLabs · **Plugin:** VERA
- **Distributed as:** Binary (Python wheel) bundled under `Content/Python/Lib/site-packages/`, unmodified
- **Linking:** **Dynamically linked** (imported by the editor's embedded Python at runtime)
- **Sends data back to the creator?** **No** for all (see note below)
- **COPY OF LICENSE** is *optional*; files are pre-extracted in `docs/tps_licenses/<pkg>/`

> Data note: none of these libraries send telemetry to their authors. The
> `anthropic`/`openai` SDKs transmit the user's own prompts to the LLM endpoint
> the user configures (with the user's own API key) — that is the user's chosen
> service call, not background data collection.

---

## The 10 to declare

### 1 — PySide6 6.11.1 · LGPL-3.0-only
- **URL:** https://pypi.org/project/PySide6/
- **License file:** `E:\PCW\VERA\docs\tps_licenses\PySide6\LGPL-3.0.txt`
- **What it does / why VERA needs it:** Qt-for-Python GUI bindings. VERA's in-editor chat panel is a Qt window hosting an embedded web view (QtWebEngine); without it there is no UI. Covers the whole Qt family (Essentials/Addons/shiboken6).
- **Linking:** Dynamically linked. · **Data to creator:** No.

### 2 — anthropic 0.109.1 · MIT
- **URL:** https://pypi.org/project/anthropic/
- **License file:** `E:\PCW\VERA\docs\tps_licenses\anthropic\LICENSE`
- **What / why:** Official Anthropic (Claude) API client. Lets VERA's agent talk to Claude models when the user selects Anthropic as the provider.
- **Linking:** Dynamically linked. · **Data to creator:** No (sends the user's prompts to Anthropic only when the user supplies an API key).

### 3 — openai 2.41.1 · Apache-2.0
- **URL:** https://pypi.org/project/openai/
- **License file:** `E:\PCW\VERA\docs\tps_licenses\openai\LICENSE`
- **What / why:** Official OpenAI API client, also used for any OpenAI-compatible endpoint (LM Studio / Ollama / local servers). VERA's agent uses it for GPT and local models.
- **Linking:** Dynamically linked. · **Data to creator:** No (sends prompts only to the user-configured endpoint).

### 4 — mcp 1.27.2 · MIT
- **URL:** https://pypi.org/project/mcp/
- **License file:** `E:\PCW\VERA\docs\tps_licenses\mcp\LICENSE`
- **What / why:** Model Context Protocol SDK. VERA exposes/consumes MCP tools so external IDEs and agents can drive the Unreal editor.
- **Linking:** Dynamically linked. · **Data to creator:** No.

### 5 — cryptography 49.0.0 · Apache-2.0 OR BSD-3-Clause
- **URL:** https://pypi.org/project/cryptography/
- **License file:** `E:\PCW\VERA\docs\tps_licenses\cryptography\LICENSE`
- **What / why:** Cryptographic primitives + TLS (bundles OpenSSL). Transitive dep of the HTTP stack; enables secure HTTPS to the LLM APIs.
- **Linking:** Dynamically linked. · **Data to creator:** No.

### 6 — certifi 2026.5.20 · MPL-2.0
- **URL:** https://pypi.org/project/certifi/
- **License file:** `E:\PCW\VERA\docs\tps_licenses\certifi\LICENSE`
- **What / why:** Mozilla root CA certificate bundle. Enables TLS certificate validation for HTTPS requests to LLM providers.
- **Linking:** Dynamically linked. · **Data to creator:** No.

### 7 — tqdm 4.68.2 · MPL-2.0 AND MIT
- **URL:** https://pypi.org/project/tqdm/
- **License file:** `E:\PCW\VERA\docs\tps_licenses\tqdm\LICENCE`
- **What / why:** Progress-bar utility. Transitive dep used by the SDKs for streaming/download progress.
- **Linking:** Dynamically linked. · **Data to creator:** No.

### 8 — pydantic 2.13.4 · MIT
- **URL:** https://pypi.org/project/pydantic/
- **License file:** `E:\PCW\VERA\docs\tps_licenses\pydantic\LICENSE`
- **What / why:** Type-driven data validation/serialization. Core dependency of the anthropic/openai/mcp SDKs for their request/response models.
- **Linking:** Dynamically linked. · **Data to creator:** No.

### 9 — httpx 0.28.1 · BSD-3-Clause
- **URL:** https://pypi.org/project/httpx/
- **License file:** `E:\PCW\VERA\docs\tps_licenses\httpx\LICENSE.md`
- **What / why:** HTTP client. The transport the LLM SDKs use to make API requests.
- **Linking:** Dynamically linked. · **Data to creator:** No.

### 10 — pywin32 312 · PSF
- **URL:** https://pypi.org/project/pywin32/
- **License file:** `E:\PCW\VERA\docs\tps_licenses\pywin32\LICENSE`
- **What / why:** Python bindings for the Windows API. Transitive dep providing Windows platform support for the libraries above.
- **Linking:** Dynamically linked. · **Data to creator:** No.

---

## Appendix — full bundled list (42 packages)

Shipped under `Content/Python/Lib/site-packages/`. Source URL for any:
`https://pypi.org/project/<name>/`.

| Software | Version | License |
|----------|---------|---------|
| annotated-types | 0.7.0 | MIT |
| anthropic | 0.109.1 | MIT |
| anyio | 4.13.0 | MIT |
| attrs | 26.1.0 | MIT |
| certifi | 2026.5.20 | MPL-2.0 |
| cffi | 2.0.0 | MIT |
| click | 8.4.1 | BSD-3-Clause |
| colorama | 0.4.6 | BSD |
| cryptography | 49.0.0 | Apache-2.0 OR BSD-3-Clause |
| distro | 1.9.0 | Apache-2.0 |
| docstring_parser | 0.18.0 | MIT |
| h11 | 0.16.0 | MIT |
| httpcore | 1.0.9 | BSD-3-Clause |
| httpx | 0.28.1 | BSD-3-Clause |
| httpx-sse | 0.4.3 | MIT |
| idna | 3.18 | BSD-3-Clause |
| jiter | 0.15.0 | MIT |
| jsonschema | 4.26.0 | MIT |
| jsonschema-specifications | 2025.9.1 | MIT |
| mcp | 1.27.2 | MIT |
| openai | 2.41.1 | Apache-2.0 |
| pycparser | 3.0 | BSD-3-Clause |
| pydantic | 2.13.4 | MIT |
| pydantic_core | 2.46.4 | MIT |
| pydantic-settings | 2.14.1 | MIT |
| PyJWT | 2.13.0 | MIT |
| PySide6 | 6.11.1 | LGPL-3.0-only |
| PySide6_Addons | 6.11.1 | LGPL-3.0-only |
| PySide6_Essentials | 6.11.1 | LGPL-3.0-only |
| python-dotenv | 1.2.2 | BSD-3-Clause |
| python-multipart | 0.0.32 | Apache-2.0 |
| pywin32 | 312 | PSF |
| referencing | 0.37.0 | MIT |
| rpds-py | 2026.5.1 | MIT |
| shiboken6 | 6.11.1 | LGPL-3.0-only |
| sniffio | 1.3.1 | MIT OR Apache-2.0 |
| sse-starlette | 3.4.4 | BSD-3-Clause |
| starlette | 1.3.1 | BSD-3-Clause |
| tqdm | 4.68.2 | MPL-2.0 AND MIT |
| typing_extensions | 4.15.0 | PSF-2.0 |
| typing-inspection | 0.4.2 | MIT |
| uvicorn | 0.49.0 | BSD-3-Clause |
