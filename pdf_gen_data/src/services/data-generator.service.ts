/**
 * DataGeneratorService — dynamically invokes Faker.js (Vietnamese locale)
 * to produce fake field values based on the mapping_config.json declarations.
 *
 * Why fakerVI: The tool targets Vietnamese real estate documents. Vietnamese
 * names and addresses make the test data realistic and help catch font/encoding
 * issues in DocuSeal templates early.
 *
 * Why dynamic dispatch: The mapping config is declarative ("person.fullName").
 * Resolving methods at runtime avoids a giant switch-case and lets you add
 * new faker methods without touching this service (Open/Closed Principle).
 */

import { fakerVI } from "@faker-js/faker";
import { TemplateConfig } from "../types";

/** A single generated record: DocuSeal field name → generated string value. */
export type GeneratedRecord = Record<string, string>;

export class DataGeneratorService {
  /**
   * Generate one fake-data record for the given template.
   *
   * @param template - Template config containing the field-to-faker mappings.
   * @returns An object where every key is a DocuSeal field name and every value
   *          is a string produced by the corresponding Faker.js method.
   * @throws {FakerMethodError} if a Faker method path cannot be resolved.
   */
  generateRecord(template: TemplateConfig): GeneratedRecord {
    const record: GeneratedRecord = {};

    for (const [fieldName, fakerExpression] of Object.entries(template.fields)) {
      record[fieldName] = this.invokeFakerMethod(fakerExpression);
    }

    return record;
  }

  /**
   * Generate multiple fake-data records for the given template.
   *
   * @param template - Template configuration.
   * @param count    - Number of records to produce (default: 1).
   * @returns Array of generated records, each independently randomised.
   */
  generateMany(template: TemplateConfig, count: number = 1): GeneratedRecord[] {
    return Array.from({ length: count }, () => this.generateRecord(template));
  }

  // ── Private helpers ───────────────────────────────────────────────

  /**
   * Parse a Faker expression and invoke the resolved function.
   *
   * Expression format:
   *   "module.method"                        — no params
   *   "module.method|{\"key\":value}"        — JSON params passed as first arg
   */
  private invokeFakerMethod(expression: string): string {
    const { methodPath, params } = this.parseExpression(expression);
    const fakerFn = this.resolveFakerFunction(methodPath);

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const rawValue: unknown = params ? fakerFn(params) : (fakerFn as () => unknown)();
    return this.formatValue(rawValue);
  }

  /**
   * Split a Faker expression into its method path and optional JSON params.
   *
   * Why extracted: keeps invokeFakerMethod focused on orchestration,
   * and the parsing logic is independently unit-testable (DRY/SRP).
   *
   * @param expression - e.g. "person.fullName" or "string.numeric|{\"length\":12}"
   */
  private parseExpression(expression: string): {
    methodPath: string;
    params: Record<string, unknown> | undefined;
  } {
    const pipeIndex = expression.indexOf("|");

    if (pipeIndex === -1) {
      return { methodPath: expression, params: undefined };
    }

    const methodPath = expression.slice(0, pipeIndex);
    const rawParams = expression.slice(pipeIndex + 1);

    try {
      const params = JSON.parse(rawParams) as Record<string, unknown>;
      return { methodPath, params };
    } catch {
      throw new FakerMethodError(
        expression,
        `Invalid JSON parameters after pipe: ${rawParams}`
      );
    }
  }

  /**
   * Walk the fakerVI object tree and return the callable method bound to
   * its parent module so that internal `this` references remain valid.
   *
   * @param methodPath - Dot-separated path, e.g. "person.fullName"
   */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  private resolveFakerFunction(methodPath: string): (...args: any[]) => unknown {
    const segments = methodPath.split(".");

    // Traverse all segments except the last — current ends up as the parent module
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let current: any = fakerVI;

    for (let i = 0; i < segments.length - 1; i++) {
      const segment = segments[i];
      if (current == null || !(segment in current)) {
        throw new FakerMethodError(
          methodPath,
          `Segment "${segment}" does not exist on fakerVI.`
        );
      }
      current = current[segment];
    }

    // Access the final method name on the parent module
    const lastSegment = segments[segments.length - 1];
    if (current == null || !(lastSegment in current)) {
      throw new FakerMethodError(
        methodPath,
        `Method "${lastSegment}" does not exist on fakerVI.${segments.slice(0, -1).join(".")}.`
      );
    }

    const fn = current[lastSegment];

    if (typeof fn !== "function") {
      throw new FakerMethodError(
        methodPath,
        `"${lastSegment}" is not a function (got ${typeof fn}).`
      );
    }

    // Bind to parent module so `this.faker` references inside Faker methods work
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return (fn as (...args: any[]) => unknown).bind(current);
  }

  /**
   * Normalise any Faker return value to a plain string.
   *
   * Why extracted: Faker methods may return Date, number, boolean, or string.
   * DocuSeal field values must be strings — centralising the coercion here
   * avoids duplicating it for every field type (DRY).
   */
  private formatValue(raw: unknown): string {
    if (raw instanceof Date) {
      return formatDateISO(raw);
    }
    return String(raw);
  }
}

// ── Standalone helpers ────────────────────────────────────────────────

/**
 * Format a Date as YYYY-MM-DD (ISO 8601 date, no time component).
 *
 * Why a standalone export: date formatting is a cross-cutting concern that
 * may be reused in log entries or output file names without importing the
 * full service.
 *
 * @param date - The Date object to format.
 * @returns ISO date string, e.g. "2025-07-14".
 */
export function formatDateISO(date: Date): string {
  return date.toISOString().split("T")[0];
}

// ── Custom error ────────────────────────────────────────────────────

export class FakerMethodError extends Error {
  constructor(methodPath: string, detail: string) {
    super(
      `Failed to invoke Faker method "${methodPath}": ${detail}\n` +
        "Verify the method path exists in @faker-js/faker v9 (fakerVI locale)."
    );
    this.name = "FakerMethodError";
  }
}
