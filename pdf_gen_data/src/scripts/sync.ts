/**
 * sync.ts — Auto-discovery script for DocuSeal template synchronisation.
 *
 * Fetches every template from the live DocuSeal API, compares it against
 * mapping_config.json, and merges the two using a smart fallback strategy:
 *
 *   Priority 1 – match by `docuseal_template_id`  (survives renames)
 *   Priority 2 – match by `name` (case-insensitive) (fixes wrong IDs)
 *   Priority 3 – neither match → append as brand-new template
 *
 * Run: npm run sync
 *
 * Why a standalone script (not baked into index.ts):
 *   Sync is a developer-facing maintenance tool — it must NOT run on every
 *   `npm run dev` because it requires API access and writes to config files.
 *   Keeping it separate means normal data-generation is never blocked by
 *   network availability or unintentional config changes.
 */

import axios, { AxiosError } from "axios";
import { EnvService } from "../services/env.service";
import { ConfigService } from "../services/config.service";
import {
  DocuSealApiResponseSchema,
  DocuSealApiTemplate,
  MappingConfig,
  TemplateConfig,
} from "../types";

// ── Constants ─────────────────────────────────────────────────────────

/**
 * Sentinel value placed in fields that have no Faker mapping yet.
 * Must be a non-empty string to pass FieldMappingSchema validation.
 */
const TODO_VALUE = "TODO: assign faker method";

/** Abort the HTTP request if DocuSeal doesn't respond within this time. */
const API_TIMEOUT_MS = 10_000;

// ── Custom error ──────────────────────────────────────────────────────

class SyncError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SyncError";
  }
}

// ── DocuSeal API client ───────────────────────────────────────────────

/**
 * Fetch all templates from the DocuSeal API.
 *
 * Why Zod validation at the boundary: the API is an external contract that
 * can change between DocuSeal releases. Validating here catches breaking
 * changes (renamed keys, restructured fields) before they silently corrupt
 * mapping_config.json.
 *
 * Why a dedicated timeout: without one the script hangs forever if DocuSeal
 * is unreachable, giving the developer zero feedback.
 *
 * @param apiUrl  - Base API URL from DOCUSEAL_API_URL env var.
 * @param apiKey  - Auth token from DOCUSEAL_API_KEY env var.
 * @returns       Validated array of DocuSeal template objects.
 * @throws {SyncError} on network failure, auth error, or unexpected shape.
 */
async function fetchApiTemplates(
  apiUrl: string,
  apiKey: string
): Promise<DocuSealApiTemplate[]> {
  // Trim any trailing slash so we never produce double-slash URLs.
  const url = `${apiUrl.replace(/\/+$/, "")}/templates`;

  try {
    const response = await axios.get(url, {
      headers: { "X-Auth-Token": apiKey },
      timeout: API_TIMEOUT_MS,
    });

    const parsed = DocuSealApiResponseSchema.safeParse(response.data);
    if (!parsed.success) {
      const issues = parsed.error.issues
        .map((i) => `  • ${i.path.join(".")}: ${i.message}`)
        .join("\n");
      throw new SyncError(
        `DocuSeal API returned an unexpected response shape:\n${issues}\n` +
          "Check that DOCUSEAL_API_URL points to a supported DocuSeal version."
      );
    }

    return parsed.data.data;
  } catch (error) {
    // Re-throw our own errors untouched.
    if (error instanceof SyncError) throw error;

    // Translate known Axios errors into actionable messages.
    const axiosErr = error as AxiosError;
    if (axiosErr.isAxiosError) {
      const status = axiosErr.response?.status;

      if (status === 401) {
        throw new SyncError(
          "Authentication failed (HTTP 401). Verify DOCUSEAL_API_KEY in your .env file."
        );
      }
      if (status === 404) {
        throw new SyncError(
          `Templates endpoint not found (HTTP 404).\n` +
            `  URL tried: ${url}\n` +
            "  Verify DOCUSEAL_API_URL points to the correct DocuSeal instance."
        );
      }
      if (!axiosErr.response) {
        // No response means the server is completely unreachable.
        throw new SyncError(
          `DocuSeal API is unreachable at "${url}". Is the server running?\n` +
            `  Cause: ${axiosErr.message}`
        );
      }

      throw new SyncError(
        `API request failed (HTTP ${status}): ${axiosErr.message}`
      );
    }

    throw new SyncError(
      `Unexpected error while fetching templates: ${(error as Error).message}`
    );
  }
}

// ── Field extraction ──────────────────────────────────────────────────

/**
 * Extract all unique, non-empty field names from a DocuSeal template object.
 *
 * Why check three locations: DocuSeal has changed where it surfaces fields
 * across self-hosted versions and its SaaS offering. Fields may appear at:
 *
 *   (a) template.fields[]                 — modern self-hosted builds
 *   (b) template.submitters[n].fields[]   — older / SaaS versions
 *   (c) template.documents[n].fields[]    — document-centric templates
 *
 * Checking all three and de-duplicating with a Set ensures no field is ever
 * missed, regardless of which DocuSeal version the user is running.
 *
 * @param template - A validated DocuSeal API template object.
 * @returns        Deduplicated list of trimmed field name strings.
 */
function extractFieldNames(template: DocuSealApiTemplate): string[] {
  const names = new Set<string>();

  // Helper: add non-empty trimmed names from any field array.
  const collect = (fields?: Array<{ name: string }>) =>
    fields?.forEach((f) => {
      const trimmed = f.name?.trim();
      if (trimmed) names.add(trimmed);
    });

  collect(template.fields);
  template.submitters?.forEach((sub) => collect(sub.fields));
  template.documents?.forEach((doc) => collect(doc.fields));

  return Array.from(names);
}

// ── Merge engine ──────────────────────────────────────────────────────

interface SyncStats {
  /** Templates updated (matched by ID or by name). */
  updated: string[];
  /** Brand-new templates appended from the API. */
  added: string[];
  /** Local templates no longer found in the API. */
  stale: string[];
  /** Total fields across all templates still marked as TODO. */
  todoCount: number;
}

/**
 * Merge a single API template into the local templates list.
 *
 * Fallback matching strategy (most-reliable → least-reliable):
 *
 *   1. Match by `docuseal_template_id` — the API's numeric ID is the
 *      authoritative stable key. A user renaming their form in DocuSeal
 *      must NOT destroy carefully crafted Faker mappings.
 *
 *   2. Match by `name` (case-insensitive trim) — rescues the common case
 *      where a user typed the wrong template ID by hand. The name match
 *      self-corrects the persisted ID without losing any field mappings.
 *
 *   3. Neither match → append a fully new template block with all fields
 *      set to TODO_VALUE for the user to fill in.
 *
 * Field merge policy:
 *   • Existing field → Faker method is always preserved (never overwritten).
 *   • New API field   → set to TODO_VALUE so the user knows it needs mapping.
 *   • Removed API field → kept in local config (safe default; user decides).
 *
 * @param localTemplates - Current (immutable) local template list.
 * @param apiTemplate    - Single template fetched from the API.
 * @param apiFieldNames  - Extracted field names from the API template.
 * @param stats          - Mutable stats object updated in place.
 * @returns              New template list with the API template merged in.
 */
function mergeTemplate(
  localTemplates: TemplateConfig[],
  apiTemplate: DocuSealApiTemplate,
  apiFieldNames: string[],
  stats: SyncStats
): TemplateConfig[] {
  // Shallow-copy so we never mutate the caller's array.
  const result = [...localTemplates];

  // ── Step 1: match by ID (most reliable) ──────────────────────────
  let matchIndex = result.findIndex(
    (t) => t.docuseal_template_id === apiTemplate.id
  );
  let matchReason: "id" | "name" | "new" = "id";

  // ── Step 2: fallback — match by name (catches manually wrong IDs) ─
  if (matchIndex === -1) {
    matchIndex = result.findIndex(
      (t) =>
        t.name.toLowerCase().trim() === apiTemplate.name.toLowerCase().trim()
    );
    matchReason = "name";
  }

  // ── Step 3: no match → new template ──────────────────────────────
  if (matchIndex === -1) {
    matchReason = "new";
  }

  if (matchReason === "new") {
    // Build a new template entry; every field starts as a TODO.
    const newFields: Record<string, string> = {};
    for (const fieldName of apiFieldNames) {
      newFields[fieldName] = TODO_VALUE;
    }

    result.push({
      docuseal_template_id: apiTemplate.id,
      name: apiTemplate.name,
      description: "TODO: add description",
      fields: newFields,
    });

    stats.added.push(apiTemplate.name);
    stats.todoCount += apiFieldNames.length;
  } else {
    // Merge into the matched entry.
    // Spread to avoid mutating the original object from the copied array.
    const existing: TemplateConfig = { ...result[matchIndex] };

    // Always sync the authoritative values from the API.
    existing.docuseal_template_id = apiTemplate.id;
    existing.name = apiTemplate.name;

    // Merge fields: preserve every existing Faker expression, add new ones.
    const mergedFields: Record<string, string> = { ...existing.fields };
    for (const fieldName of apiFieldNames) {
      if (!(fieldName in mergedFields)) {
        mergedFields[fieldName] = TODO_VALUE;
      }
    }
    existing.fields = mergedFields;
    result[matchIndex] = existing;

    const label =
      matchReason === "name"
        ? `${apiTemplate.name}  (ID corrected via name-match)`
        : apiTemplate.name;
    stats.updated.push(label);

    // Count ALL remaining TODOs in this template, not just new ones.
    stats.todoCount += Object.values(mergedFields).filter(
      (v) => v === TODO_VALUE
    ).length;
  }

  return result;
}

/**
 * Identify local templates that are no longer present in the API.
 *
 * Why warn instead of delete: silently removing a template with carefully
 * crafted Faker mappings would be irreversible without git.  We surface
 * the information and let the developer decide.
 *
 * Why use the ORIGINAL local list: running stale detection on the post-merge
 * list would produce false positives because mergeTemplate updates IDs and
 * names in place.
 *
 * @param originalLocal - The local template list BEFORE any merging.
 * @param apiTemplates  - All templates fetched from the API.
 * @param stats         - Mutable stats object updated in place.
 */
function detectStaleTemplates(
  originalLocal: TemplateConfig[],
  apiTemplates: DocuSealApiTemplate[],
  stats: SyncStats
): void {
  const apiIds = new Set(apiTemplates.map((t) => t.id));
  const apiNames = new Set(
    apiTemplates.map((t) => t.name.toLowerCase().trim())
  );

  for (const t of originalLocal) {
    const existsById = apiIds.has(t.docuseal_template_id);
    const existsByName = apiNames.has(t.name.toLowerCase().trim());
    if (!existsById && !existsByName) {
      stats.stale.push(t.name);
    }
  }
}

// ── Console reporter ──────────────────────────────────────────────────

/**
 * Print a human-friendly sync summary to stdout.
 *
 * Why not structured JSON output: this is a developer CLI tool. A readable
 * summary surfaces actionable information (which fields still need attention)
 * faster than machine-readable JSON would.
 */
function printSummary(stats: SyncStats): void {
  const divider = "─".repeat(57);

  console.log(`\n${divider}`);
  console.log("  📋  DocuSeal Sync — Summary");
  console.log(divider);

  console.log(`\n  ✅  Updated  (${stats.updated.length})`);
  if (stats.updated.length > 0) {
    stats.updated.forEach((name) => console.log(`       • ${name}`));
  } else {
    console.log("       (none)");
  }

  console.log(`\n  🆕  Added    (${stats.added.length})`);
  if (stats.added.length > 0) {
    stats.added.forEach((name) => console.log(`       • ${name}`));
  } else {
    console.log("       (none)");
  }

  if (stats.stale.length > 0) {
    console.log(
      `\n  ⚠️   Stale    (${stats.stale.length})  — in local config, NOT in API`
    );
    stats.stale.forEach((name) => console.log(`       • ${name}`));
    console.log(
      "       These entries were kept. Remove them manually if no longer needed."
    );
  }

  if (stats.todoCount > 0) {
    console.log(
      `\n  📝  TODOs    (${stats.todoCount} field(s) need a Faker method)`
    );
    console.log(
      `       Open mapping_config.json and replace every "${TODO_VALUE}"`
    );
    console.log(
      "       with a real Faker.js expression.  Ref: https://fakerjs.dev/api/"
    );
  } else {
    console.log("\n  🎉  All fields are fully mapped — no TODOs remaining!");
  }

  console.log(`\n${divider}\n`);
}

// ── Entry point ───────────────────────────────────────────────────────

async function main(): Promise<void> {
  console.log("🔄  DocuSeal Template Sync starting...\n");

  // Step 1: Validate environment — fail fast before any network I/O.
  let env: EnvService;
  try {
    env = new EnvService();
  } catch (error) {
    console.error(`❌  Environment error:\n${(error as Error).message}`);
    process.exit(1);
  }

  // Step 2: Fetch live templates from the DocuSeal API.
  let apiTemplates: DocuSealApiTemplate[];
  try {
    console.log(`   Fetching templates from ${env.apiUrl} ...`);
    apiTemplates = await fetchApiTemplates(env.apiUrl, env.apiKey);
    console.log(`   Found ${apiTemplates.length} template(s) on the server.`);
  } catch (error) {
    console.error(`❌  ${(error as Error).message}`);
    process.exit(1);
  }

  if (apiTemplates.length === 0) {
    console.log(
      "\n⚠️   No templates found in the DocuSeal API. Nothing to sync.\n"
    );
    process.exit(0);
  }

  // Step 3: Load the local mapping config.
  // Why allow missing file: on first run mapping_config.json may not exist.
  // We build it entirely from the API, which is the intended onboarding flow.
  const configService = new ConfigService();
  let localConfig: MappingConfig;

  try {
    localConfig = configService.load();
    console.log(
      `   Loaded local config with ${localConfig.templates.length} template(s).`
    );
  } catch (error) {
    if ((error as Error).name === "ConfigFileNotFoundError") {
      console.log(
        "   No mapping_config.json found — will build one from scratch."
      );
      // Cast is safe: we merge at least one API template before calling save(),
      // which re-validates and enforces the min(1) constraint at runtime.
      localConfig = { templates: [] } as unknown as MappingConfig;
    } else {
      console.error(
        `❌  Failed to load local config: ${(error as Error).message}`
      );
      process.exit(1);
    }
  }

  // Step 4: Merge each API template into the local list using the
  // ID → name → new fallback strategy.
  console.log("   Merging ...");
  const stats: SyncStats = { updated: [], added: [], stale: [], todoCount: 0 };
  const originalLocal = [...localConfig.templates];

  let mergedTemplates = [...localConfig.templates];
  for (const apiTemplate of apiTemplates) {
    const fieldNames = extractFieldNames(apiTemplate);
    mergedTemplates = mergeTemplate(mergedTemplates, apiTemplate, fieldNames, stats);
  }

  // Run stale detection against the ORIGINAL list (before ID/name updates).
  detectStaleTemplates(originalLocal, apiTemplates, stats);

  // Step 5: Persist via ConfigService.save() — owns validation + backup + I/O.
  // Why not write directly here: delegating to ConfigService keeps this script
  // free of config I/O concerns (SRP) and guarantees the final validation
  // gate and backup creation that save() provides.
  const mergedConfig = { templates: mergedTemplates } as MappingConfig;

  try {
    configService.save(mergedConfig);
    console.log(
      "   Saved  → mapping_config.json  (backup → mapping_config.backup.json)"
    );
  } catch (error) {
    console.error(`❌  Failed to save config: ${(error as Error).message}`);
    process.exit(1);
  }

  // Step 6: Display the human-friendly summary.
  printSummary(stats);
}

main().catch((error: unknown) => {
  console.error(`❌  Unexpected error: ${(error as Error).message}`);
  process.exit(1);
});
