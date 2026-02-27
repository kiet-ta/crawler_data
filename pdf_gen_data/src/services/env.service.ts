/**
 * EnvService — loads and validates required environment variables.
 *
 * Why load at startup: failing fast with a clear error message (before any
 * network calls) saves the developer from cryptic 401/network errors later.
 *
 * Why Zod: reuses the same validation library already present in the project
 * and produces field-level error messages (e.g. "DOCUSEAL_API_KEY: Required").
 */

import { config as loadDotenv } from "dotenv";
import { z } from "zod";

// Load .env into process.env before the schema reads it.
// Why here (module-level): ensures the file is loaded exactly once,
// the moment this module is first imported.
loadDotenv();

const EnvSchema = z.object({
  DOCUSEAL_API_URL: z.string().url({
    message: "Must be a valid URL, e.g. http://localhost:3000/api",
  }),
  DOCUSEAL_API_KEY: z.string().min(1, {
    message: "API key cannot be empty",
  }),
});

type EnvConfig = z.infer<typeof EnvSchema>;

export class EnvService {
  /** Validated DocuSeal base API URL. */
  readonly apiUrl: string;

  /**
   * Validated DocuSeal API key.
   *
   * Why readonly and not a getter: once validated the value is immutable.
   * A getter would silently re-read process.env on every call, which could
   * return a mutated value if something changes the environment at runtime.
   */
  readonly apiKey: string;

  constructor() {
    const result = EnvSchema.safeParse(process.env);

    if (!result.success) {
      const issues = result.error.issues
        .map(
          (i: { path: (string | number)[]; message: string }) =>
            `  • ${i.path.join(".")}: ${i.message}`
        )
        .join("\n");
      throw new EnvValidationError(issues);
    }

    const env: EnvConfig = result.data;
    this.apiUrl = env.DOCUSEAL_API_URL;
    this.apiKey = env.DOCUSEAL_API_KEY;
    // Note: apiKey is never logged — the EnvValidationError message
    // only references field names, not values.
  }
}

// ── Custom error ────────────────────────────────────────────────────

export class EnvValidationError extends Error {
  constructor(issues: string) {
    super(
      `Environment variable validation failed:\n${issues}\n` +
        "Copy .env.example to .env and fill in the required values."
    );
    this.name = "EnvValidationError";
  }
}
