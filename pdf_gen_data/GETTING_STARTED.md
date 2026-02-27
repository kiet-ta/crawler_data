# Getting Started

This guide walks you through running `pdf-gen-data` end-to-end — from spinning up DocuSeal locally to finding the generated PDFs on disk.

**What the tool does:** reads field-mapping rules from `mapping_config.json`, generates Vietnamese fake data via Faker.js, submits it to a local DocuSeal instance, waits for each PDF to render, then downloads all files to `./output_pdfs/`.

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Node.js | ≥ 18 | Uses built-in `node:fs`, `node:stream/promises` |
| npm | ≥ 9 | Bundled with Node 18 |
| Docker | any | Easiest way to run DocuSeal locally |

---

## 1. Start DocuSeal locally

DocuSeal needs to be running before you execute the tool. The quickest path is Docker:

```bash
docker run --rm -p 3000:3000 \
  -v docuseal_data:/data \
  docuseal/docuseal
```

Then open `http://localhost:3000` in a browser, finish the setup wizard, and create your first admin account.

> If you already have a running instance (e.g. via Docker Compose in the parent project), skip this step.

---

## 2. Get your API key

1. Log in to DocuSeal at `http://localhost:3000`.
2. Go to **Settings → API**.
3. Copy the token — you'll paste it into `.env` in the next step.

---

## 3. Create a template in DocuSeal

The tool submits data to an existing template. You need at least one before running.

1. In DocuSeal, click **New Template**.
2. Upload a PDF or build a form from scratch.
3. Add fields and give them meaningful names (e.g. `Full Name`, `Email`, `Phone Number`).
4. Save the template.

> **Tip — skip manual ID lookups entirely.**  
> Instead of copying the numeric ID from the URL and editing `mapping_config.json` by hand, use the `npm run sync` command (step 6). It discovers all your templates automatically, fills in the correct IDs, and flags any unmapped fields as `TODO`.

See [Customise field mappings](#customise-field-mappings) for all supported Faker methods.

---

## 4. Install dependencies

```bash
cd crawler_data/pdf_gen_data
npm install
```

---

## 5. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in both values:

```dotenv
DOCUSEAL_API_URL=http://localhost:3000/api
DOCUSEAL_API_KEY=your_api_key_here
```

The tool validates these at startup and throws a clear error if either is missing — so if you see `EnvValidationError`, check this file first.

---

## 6. Sync templates from DocuSeal (recommended)

The sync command auto-discovers every template in your running DocuSeal instance, updates `mapping_config.json` with accurate IDs and field names, and tells you exactly which fields still need a Faker method.

```bash
npm run sync
```

**Example output:**
```
🔄  DocuSeal Template Sync starting...

   Fetching templates from http://localhost:3000/api ...
   Found 2 template(s) on the server.
   Loaded local config with 2 template(s).
   Merging ...
   Saved  → mapping_config.json  (backup → mapping_config.backup.json)

─────────────────────────────────────────────────────────
  📋  DocuSeal Sync — Summary
─────────────────────────────────────────────────────────

  ✅  Updated  (2)
       • Real Estate Sales Contract
       • Lease Agreement

  🆕  Added    (0)
       (none)

  📝  TODOs    (3 field(s) need a Faker method)
       Open mapping_config.json and replace every "TODO: assign faker method"
       with a real Faker.js expression.  Ref: https://fakerjs.dev/api/
─────────────────────────────────────────────────────────
```

**What the sync does for each API template:**

| Situation | Action |
|---|---|
| Template ID matches local config | Updates name, preserves all existing Faker methods, adds new fields as `TODO` |
| Name matches but ID was wrong | Self-corrects `docuseal_template_id`, same merge |
| Completely new template | Appends full block with all fields as `TODO` |
| Local template not found in API | Kept with a ⚠️ stale warning (never auto-deleted) |

After syncing, open `mapping_config.json` and replace every `"TODO: assign faker method"` value with a real Faker expression. See [Customise field mappings](#customise-field-mappings).

> **Backup:** every `npm run sync` automatically writes a `mapping_config.backup.json` before overwriting the main file — a one-step recovery if anything looks unexpected.

> **Re-run anytime:** sync is idempotent. Run it again whenever you add or rename templates in DocuSeal.

---

## 7. Run the tool

```bash
npm run dev
```

For each template in `mapping_config.json`, the tool generates **5 records** and saves the resulting PDFs:

```
📄 Template [ID 1]: "Real Estate Sales Contract"
  [1/5] Submission 42 created — waiting for PDF render…
  ✅ Saved → output_pdfs/real_estate_sales_contract_1.pdf
  [2/5] Submission 43 created — waiting for PDF render…
  ✅ Saved → output_pdfs/real_estate_sales_contract_2.pdf
  ...
```

PDFs land in `./output_pdfs/` (gitignored by default).

---

## Customise field mappings

Each field value in `mapping_config.json` maps to a [`fakerVI`](https://fakerjs.dev/api/) method (Vietnamese locale).

**Basic method:**
```json
"Full Name": "person.fullName"
```

**Method with parameters** — append `|` then a JSON object:
```json
"ID Number": "string.numeric|{\"length\":12}",
"Property Price": "finance.amount|{\"min\":100000,\"max\":999999,\"dec\":0}"
```

**Commonly useful methods:**

| Field type | Faker method |
|---|---|
| Full name | `person.fullName` |
| Email | `internet.email` |
| Phone number | `phone.number` |
| Street address | `location.streetAddress` |
| City | `location.city` |
| Date of birth | `date.past` |
| Future date | `date.future` |
| Recent date | `date.recent` |
| Fixed-length number | `string.numeric\|{"length":12}` |
| Currency amount | `finance.amount\|{"min":500,"max":5000,"dec":0}` |

Browse the full list at [fakerjs.dev/api](https://fakerjs.dev/api/).

---

## Troubleshoot common errors

**`EnvValidationError: DOCUSEAL_API_URL Required`**
`.env` is missing or the variable is empty. Re-check [step 5](#5-configure-environment-variables).

**`SyncError: Authentication failed (HTTP 401)`**
API key rejected during `npm run sync`. Re-copy it from DocuSeal **Settings → API** and update `DOCUSEAL_API_KEY` in `.env`.

**`SyncError: DocuSeal API is unreachable`**
DocuSeal isn't running or `DOCUSEAL_API_URL` is wrong. Start the Docker container and confirm the URL matches the port it's listening on.

**`SyncError: DocuSeal API returned an unexpected response shape`**
The running DocuSeal version uses a different API response structure. Check for a DocuSeal update or open an issue with the raw API response.

**`DocusealApiError: HTTP 401`**
The API key is wrong. Re-copy it from DocuSeal **Settings → API**.

**`DocusealApiError: HTTP 404` on createSubmission**
The `docuseal_template_id` in `mapping_config.json` doesn't match any template. Run `npm run sync` to auto-correct all IDs.

**`SubmissionTimeoutError: not ready after 10 polling attempts`**
DocuSeal's render worker didn't finish in 10 s. This usually means the template is very heavy or the DocuSeal container is under-resourced. Increase `MAX_POLL_RETRIES` in [src/services/docuseal.client.ts](src/services/docuseal.client.ts#L12) or give the Docker container more memory.

**`FakerMethodError: method "X" does not exist on fakerVI`**
The Faker method path in `mapping_config.json` is wrong. Check the exact method name at [fakerjs.dev/api](https://fakerjs.dev/api/) — the Vietnamese locale (`fakerVI`) supports the same methods as the default locale.

**Generated PDFs look blank / fields not filled**
The field names in `mapping_config.json` must match the field names in the DocuSeal template exactly (case-sensitive). Open the template in DocuSeal, check each field's name, and align them.

---

## Project structure reference

```
pdf_gen_data/
├── mapping_config.json              ← Edit this to configure templates & fields
├── mapping_config.backup.json       ← Auto-created by npm run sync (safe rollback)
├── output_pdfs/                     ← Generated PDFs land here (gitignored)
├── src/
│   ├── index.ts                     ← Orchestrator: runs the generation loop
│   ├── types.ts                     ← Zod schemas + TypeScript types (incl. DocuSeal API)
│   ├── scripts/
│   │   └── sync.ts                  ← Auto-discovery: fetch templates, merge config
│   ├── services/
│   │   ├── config.service.ts        ← Reads, validates & saves mapping_config.json
│   │   ├── data-generator.service.ts← Calls fakerVI dynamically per field
│   │   ├── docuseal.client.ts       ← DocuSeal API: submit, poll, download
│   │   └── env.service.ts           ← Loads & validates .env variables
│   └── utils/
│       └── fs.utils.ts              ← ensureOutputDir + OUTPUT_PDFS_DIR
├── .env.example                     ← Copy to .env and fill in your values
├── package.json
└── tsconfig.json
```
