/**
 * Orchestrator — wires all services together and drives the generation loop.
 *
 * Flow per template:
 *   Read Config → Generate fake record (fakerVI) → POST /submissions
 *   → Poll until PDF is ready → Download PDF to ./output_pdfs/
 *
 * Why sequential loop (not Promise.all):
 *   The DocuSeal instance is local. Firing all submissions in parallel would
 *   flood the render worker queue, making polling results non-deterministic
 *   and console output unreadable. Sequential execution is simpler, predictable,
 *   and fast enough for the target volume (5 records × N templates).
 */

import * as path from "node:path";

import { ConfigService } from "./services/config.service";
import { DataGeneratorService, GeneratedRecord } from "./services/data-generator.service";
import { DocusealClient } from "./services/docuseal.client";
import { EnvService } from "./services/env.service";
import { ensureOutputDir, OUTPUT_PDFS_DIR } from "./utils/fs.utils";

/** Records generated per template. */
const RECORDS_PER_TEMPLATE = 5;

async function main(): Promise<void> {
  console.log("🚀 PDF Gen Data — starting up…\n");

  // ── Bootstrap: fail fast before any network call ──────────────────
  const env = new EnvService();
  const config = new ConfigService().load();

  // ── Wire up services ──────────────────────────────────────────────
  const generator = new DataGeneratorService();
  const client = new DocusealClient(env.apiUrl, env.apiKey);

  ensureOutputDir(OUTPUT_PDFS_DIR);

  let totalSuccess = 0;
  let totalFailed = 0;

  // ── Outer loop: each template in the config ───────────────────────
  for (const template of config.templates) {
    console.log(
      `\n📄 Template [ID ${template.docuseal_template_id}]: "${template.name}"`
    );

    // ── Inner loop: RECORDS_PER_TEMPLATE records per template ─────
    for (let i = 1; i <= RECORDS_PER_TEMPLATE; i++) {
      try {
        // Step 1 — Generate Vietnamese fake data
        const record = generator.generateRecord(template);

        // Step 2 — Resolve a submitter email (DocuSeal requires one per submission)
        const email = extractEmail(record, i);

        // Step 3 — Create submission (auto-signed via completed: true)
        const result = await client.createSubmission({
          templateId: template.docuseal_template_id,
          fields: record,
          email,
        });

        console.log(
          `  [${i}/${RECORDS_PER_TEMPLATE}] Submission ${result.submissionId} created — waiting for PDF render…`
        );

        // Step 4 — Poll until the background render worker is done
        const documents = await client.waitForSubmissionReady(result.submissionId);

        // Step 5 — Stream the first (main) document to disk
        const safeName = template.name.replace(/\s+/g, "_").toLowerCase();
        const outputFilename = `${safeName}_${i}.pdf`;
        const outputPath = path.join(OUTPUT_PDFS_DIR, outputFilename);

        await client.downloadPdf(documents[0].url, outputPath);

        console.log(`  ✅ Saved → output_pdfs/${outputFilename}`);
        totalSuccess++;
      } catch (error) {
        // Graceful degradation — log and continue with the next record
        console.error(
          JSON.stringify({
            event: "record_failed",
            template: template.name,
            record: i,
            errorType: (error as Error).name,
            error: (error as Error).message,
          })
        );
        totalFailed++;
      }
    }
  }

  // ── Summary ───────────────────────────────────────────────────────
  console.log("\n" + "─".repeat(50));
  console.log(
    JSON.stringify(
      {
        event: "pipeline_complete",
        totalSuccess,
        totalFailed,
        outputDir: OUTPUT_PDFS_DIR,
      },
      null,
      2
    )
  );
}

/**
 * Find an email address in a generated record to satisfy DocuSeal's
 * required `submitters[].email` field.
 *
 * Why: different templates use different field names ("Email", "Tenant Email").
 * Searching case-insensitively for "email" in the key avoids hardcoding any
 * particular field name here (Open/Closed Principle).
 *
 * @param record - The generated field values for one submission.
 * @param index  - Record index, used only to build a deterministic fallback.
 * @returns A non-empty email string.
 */
function extractEmail(record: GeneratedRecord, index: number): string {
  const emailEntry = Object.entries(record).find(([key]) =>
    key.toLowerCase().includes("email")
  );
  return emailEntry?.[1] ?? `auto_${index}@placeholder.local`;
}

// Top-level async entry — catch fatal errors and exit with code 1
main().catch((error: Error) => {
  console.error(
    JSON.stringify({
      event: "fatal_error",
      errorType: error.name,
      error: error.message,
    })
  );
  process.exit(1);
});
