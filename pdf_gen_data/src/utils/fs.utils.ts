/**
 * Filesystem utilities for the PDF Gen Data tool.
 *
 * Why a dedicated module: I/O helpers are infrastructure concerns —
 * keeping them out of business-logic services makes each service
 * independently testable (SRP).
 */

import * as fs from "node:fs";
import * as path from "node:path";

/**
 * Absolute path to the output directory where downloaded PDFs are saved.
 *
 * Why process.cwd(): consistent with ConfigService — the output folder
 * always lives at the project root regardless of the execution mode
 * (ts-node from src/ or compiled from dist/).
 */
export const OUTPUT_PDFS_DIR = path.resolve(process.cwd(), "output_pdfs");

/**
 * Create the given directory (and all parent directories) if it does not
 * already exist. Idempotent — safe to call on every startup.
 *
 * @param dirPath - Absolute path to the directory to create.
 */
export function ensureOutputDir(dirPath: string): void {
  fs.mkdirSync(dirPath, { recursive: true });
}
