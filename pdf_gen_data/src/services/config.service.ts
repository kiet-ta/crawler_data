/**
 * ConfigService — reads and validates `mapping_config.json`.
 *
 * Why a dedicated service:
 *   Single Responsibility — this class owns config I/O only.
 *   All parsing and validation happen here so the rest of the app
 *   can trust the data it receives.
 *
 * Strict error handling:
 *   • File missing  → throws with clear path info.
 *   • Invalid JSON  → throws with parse details.
 *   • Schema errors → throws with Zod validation messages.
 */

import * as fs from "node:fs";
import * as path from "node:path";
import { MappingConfig, MappingConfigSchema } from "../types";

/**
 * Why process.cwd(): `__dirname` points to `src/` (ts-node) or `dist/`
 * (compiled), but the config file always lives at the project root.
 * `process.cwd()` is stable regardless of execution mode.
 */
const PROJECT_ROOT = process.cwd();

export class ConfigService {
  private readonly configPath: string;

  /**
   * @param configPath — absolute or relative path to the JSON config.
   *   Defaults to `mapping_config.json` in the project root.
   */
  constructor(configPath?: string) {
    this.configPath =
      configPath ?? path.resolve(PROJECT_ROOT, "mapping_config.json");
  }

  /**
   * Load, parse, and validate the mapping configuration file.
   *
   * @returns A fully validated `MappingConfig` object.
   * @throws {ConfigFileNotFoundError} if the file does not exist.
   * @throws {ConfigParseError}        if the file is not valid JSON.
   * @throws {ConfigValidationError}   if the JSON does not match the schema.
   */
  load(): MappingConfig {
    const rawContent = this.readFile();
    const parsed = this.parseJson(rawContent);
    return this.validate(parsed);
  }

  // ── Private helpers ───────────────────────────────────────────────

  /**
   * Read the raw file content from disk.
   */
  private readFile(): string {
    if (!fs.existsSync(this.configPath)) {
      throw new ConfigFileNotFoundError(this.configPath);
    }

    try {
      return fs.readFileSync(this.configPath, "utf-8");
    } catch (error) {
      throw new ConfigFileNotFoundError(
        this.configPath,
        `Unable to read file: ${(error as Error).message}`
      );
    }
  }

  /**
   * Parse raw string content as JSON.
   */
  private parseJson(content: string): unknown {
    try {
      return JSON.parse(content);
    } catch (error) {
      throw new ConfigParseError(
        this.configPath,
        (error as Error).message
      );
    }
  }

  /**
   * Validate parsed JSON against the Zod schema.
   */
  private validate(data: unknown): MappingConfig {
    const result = MappingConfigSchema.safeParse(data);

    if (!result.success) {
      const issues = result.error.issues
        .map((i: { path: (string | number)[]; message: string }) => `  • ${i.path.join(".")}: ${i.message}`)
        .join("\n");
      throw new ConfigValidationError(this.configPath, issues);
    }

    return result.data;
  }

  /**
   * Validate, back up the current file, and persist `data` to disk.
   *
   * Why validate before write: we must never persist data that fails
   * MappingConfigSchema — a corrupt config file would break every
   * subsequent `npm run dev` startup.
   *
   * Why create a backup: gives the developer a one-step recovery path if
   * the merged output looks unexpected. A `.backup.json` sibling is
   * sufficient; deeper rollback is available via git history.
   *
   * @param data — The merged config to persist.
   * @throws {ConfigValidationError} if `data` fails schema validation.
   * @throws {ConfigSaveError}       if the file cannot be written.
   */
  save(data: MappingConfig): void {
    // 1. Final schema guard — reject corrupt data before touching disk.
    const validated = this.validate(data);

    // 2. Backup the existing file (non-fatal if it fails).
    this.backupCurrentFile();

    // 3. Atomic write: pretty-print with 2-space indentation.
    try {
      fs.writeFileSync(
        this.configPath,
        JSON.stringify(validated, null, 2),
        "utf-8"
      );
    } catch (error) {
      throw new ConfigSaveError(
        this.configPath,
        (error as Error).message
      );
    }
  }

  /**
   * Copy the current config to a `.backup.json` sibling file.
   *
   * Why best-effort (no throw): a backup failure is annoying but must
   * not block the save — the user would rather have an updated config
   * without a backup than a stale config because the backup path is
   * temporarily unwritable (e.g. read-only filesystem).
   */
  private backupCurrentFile(): void {
    if (!fs.existsSync(this.configPath)) return;

    const backupPath = this.configPath.replace(/\.json$/, ".backup.json");
    try {
      fs.copyFileSync(this.configPath, backupPath);
    } catch (error) {
      console.warn(
        `[ConfigService] Could not create backup at "${backupPath}": ${
          (error as Error).message
        }`
      );
    }
  }
}

// ── Custom error classes ────────────────────────────────────────────

/**
 * Why custom errors: they let callers distinguish between "file missing",
 * "bad JSON", and "schema mismatch" without parsing error messages.
 */

export class ConfigFileNotFoundError extends Error {
  constructor(filePath: string, detail?: string) {
    super(
      `Configuration file not found: "${filePath}".${
        detail ? ` ${detail}` : ""
      }\nEnsure mapping_config.json exists in the project root.`
    );
    this.name = "ConfigFileNotFoundError";
  }
}

export class ConfigParseError extends Error {
  constructor(filePath: string, detail: string) {
    super(
      `Failed to parse JSON in "${filePath}": ${detail}\n` +
        "Check for trailing commas or invalid syntax."
    );
    this.name = "ConfigParseError";
  }
}

export class ConfigValidationError extends Error {
  constructor(filePath: string, issues: string) {
    super(
      `Configuration validation failed for "${filePath}":\n${issues}\n` +
        "Refer to mapping_config.json schema in src/types.ts."
    );
    this.name = "ConfigValidationError";
  }
}

export class ConfigSaveError extends Error {
  constructor(filePath: string, detail: string) {
    super(`Failed to save configuration to "${filePath}": ${detail}`);
    this.name = "ConfigSaveError";
  }
}
