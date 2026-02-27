/**
 * DocusealClient — typed HTTP client for the local DocuSeal API.
 *
 * Why Axios: ships its own TypeScript types, supports streaming responses
 * for PDF downloads, and provides a clean interceptor model for auth headers.
 *
 * Authentication: every request carries the `X-Auth-Token` header.
 * The token is injected via the constructor — never hardcoded here.
 */

import axios, { AxiosError, AxiosInstance } from "axios";
import { createWriteStream } from "node:fs";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";

import { GeneratedRecord } from "./data-generator.service";

/** Maximum number of status-poll attempts before giving up. */
const MAX_POLL_RETRIES = 10;

/** Sleep duration between each polling attempt (milliseconds). */
const POLL_INTERVAL_MS = 1_000;

// ── DTOs ────────────────────────────────────────────────────────────

export interface CreateSubmissionOptions {
  /** DocuSeal template ID from mapping_config.json. */
  templateId: number;
  /** Faker-generated field values to pre-fill the form. */
  fields: GeneratedRecord;
  /**
   * Submitter email — required by DocuSeal's API for every submission.
   * Use a value from the generated record when possible.
   */
  email: string;
}

export interface SubmissionResult {
  submissionId: number;
  submitterId: number;
  status: string;
}

export interface SubmissionDocument {
  id: number;
  name: string;
  /** Signed download URL — only populated once DocuSeal finishes rendering. */
  url: string;
}

interface DocusealSubmissionResponse {
  id: number;
  status: string;
  /** Present and populated once the background render worker completes. */
  documents?: SubmissionDocument[];
}

// ── Client ──────────────────────────────────────────────────────────

export class DocusealClient {
  private readonly http: AxiosInstance;
  /** Stored separately for use in direct axios calls (e.g. stream download). */
  private readonly apiKey: string;

  /**
   * @param apiUrl - Base URL of the DocuSeal API, e.g. http://localhost:3000/api
   * @param apiKey - Authentication token. Read from .env — never hardcoded.
   */
  constructor(apiUrl: string, apiKey: string) {
    this.apiKey = apiKey;
    this.http = axios.create({
      baseURL: apiUrl,
      headers: {
        "X-Auth-Token": apiKey,
        "Content-Type": "application/json",
      },
      timeout: 15_000,
    });
  }

  /**
   * Create a new DocuSeal submission with pre-filled Faker data.
   *
   * `send_email: false` — skips notification emails for local test data.
   * `completed: true`   — auto-signs the form so no manual signing UI is needed.
   *
   * @param options - Template ID, generated field values, and submitter email.
   * @returns IDs and initial status of the created submission.
   * @throws {DocusealApiError} on any HTTP or network failure.
   */
  async createSubmission(options: CreateSubmissionOptions): Promise<SubmissionResult> {
    const { templateId, fields, email } = options;

    try {
      const response = await this.http.post<
        Array<{ id: number; submission_id: number; status: string }>
      >("/submissions", {
        template_id: templateId,
        send_email: false,
        submitters: [
          {
            email,
            values: fields,
            // completed: true tells DocuSeal to bypass the signing UI and treat
            // this submission as already signed — useful for automated test data.
            completed: true,
          },
        ],
      });

      const submitters = response.data;
      if (!submitters || submitters.length === 0) {
        throw new DocusealApiError(
          "createSubmission",
          "API returned an empty submitters array — verify template_id is correct."
        );
      }

      const first = submitters[0];
      return {
        submissionId: first.submission_id,
        submitterId: first.id,
        status: first.status,
      };
    } catch (error) {
      return this.handleError("createSubmission", error);
    }
  }

  /**
   * Poll `GET /submissions/{id}` until all documents have a download URL,
   * then return the document list.
   *
   * Why polling is mandatory:
   *   DocuSeal renders PDFs in a background worker. Even when `completed: true`
   *   is set, the render takes 0.5–2 s depending on template complexity.
   *   Calling the download endpoint immediately results in a 404 or a corrupt
   *   (empty/partial) PDF. Polling ensures we only download fully rendered files.
   *
   * @param submissionId - ID returned by `createSubmission`.
   * @returns Array of documents with populated download URLs.
   * @throws {SubmissionTimeoutError} if the PDF is not ready within
   *         MAX_POLL_RETRIES × POLL_INTERVAL_MS milliseconds.
   * @throws {DocusealApiError}       on persistent API failures.
   */
  async waitForSubmissionReady(submissionId: number): Promise<SubmissionDocument[]> {
    for (let attempt = 1; attempt <= MAX_POLL_RETRIES; attempt++) {
      // Sleep first — the render worker always needs at least ~500 ms.
      await sleep(POLL_INTERVAL_MS);

      try {
        const response = await this.http.get<DocusealSubmissionResponse>(
          `/submissions/${submissionId}`
        );

        const docs: SubmissionDocument[] = response.data.documents ?? [];
        const isReady = docs.length > 0 && docs.every((doc) => Boolean(doc.url));

        if (isReady) {
          return docs;
        }

        // Log waiting state so the operator can see progress without alarm
        console.log(
          JSON.stringify({
            event: "poll_waiting",
            submissionId,
            attempt,
            maxAttempts: MAX_POLL_RETRIES,
            docsFound: docs.length,
          })
        );
      } catch (error) {
        // Transient poll errors (e.g. 502 from local Docker restart) are logged
        // but do NOT abort the retry loop — we keep trying until max attempts.
        console.error(
          JSON.stringify({
            event: "poll_error",
            submissionId,
            attempt,
            error: (error as Error).message,
          })
        );
      }
    }

    // Exhausted all retries — surface as a typed, actionable error
    throw new SubmissionTimeoutError(submissionId, MAX_POLL_RETRIES);
  }

  /**
   * Download a rendered PDF from DocuSeal and stream it directly to disk.
   *
   * Why streaming (not buffering): PDFs can be several MB. Streaming writes
   * data chunk-by-chunk to avoid loading the entire file into heap memory.
   *
   * @param documentUrl - Signed download URL from `waitForSubmissionReady`.
   * @param outputPath  - Absolute local path where the PDF file will be saved.
   * @throws {DocusealApiError} on download failure.
   */
  async downloadPdf(documentUrl: string, outputPath: string): Promise<void> {
    try {
      const response = await axios.get<Readable>(documentUrl, {
        responseType: "stream",
        headers: { "X-Auth-Token": this.apiKey },
        timeout: 30_000,
      });

      // pipeline handles back-pressure and cleans up streams on error
      await pipeline(response.data as Readable, createWriteStream(outputPath));
    } catch (error) {
      return this.handleError("downloadPdf", error);
    }
  }

  // ── Error handling ────────────────────────────────────────────────

  /**
   * Normalise Axios and generic errors into typed `DocusealApiError` exceptions.
   *
   * Why return type `never`: signals to TypeScript that every call site
   * in a catch block always throws — no missing-return false positives.
   */
  private handleError(operation: string, error: unknown): never {
    // Re-throw our own typed errors unchanged so callers can instanceof-check
    if (
      error instanceof DocusealApiError ||
      error instanceof SubmissionTimeoutError
    ) {
      throw error;
    }

    if (axios.isAxiosError(error)) {
      const axiosErr = error as AxiosError;
      // Structured log — never includes auth tokens or sensitive field values
      console.error(
        JSON.stringify({
          event: "docuseal_api_error",
          operation,
          status: axiosErr.response?.status,
          statusText: axiosErr.response?.statusText,
          data: axiosErr.response?.data,
          message: axiosErr.message,
        })
      );
      throw new DocusealApiError(
        operation,
        `HTTP ${axiosErr.response?.status ?? "network"}: ${axiosErr.message}`
      );
    }

    throw new DocusealApiError(operation, (error as Error).message);
  }
}

// ── Helpers ──────────────────────────────────────────────────────────

/**
 * Pause async execution for the given number of milliseconds.
 *
 * @param ms - Sleep duration.
 */
function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// ── Custom errors ────────────────────────────────────────────────────

export class DocusealApiError extends Error {
  constructor(operation: string, detail: string) {
    super(`DocuSeal API error in "${operation}": ${detail}`);
    this.name = "DocusealApiError";
  }
}

export class SubmissionTimeoutError extends Error {
  constructor(submissionId: number, maxRetries: number) {
    super(
      `Submission ${submissionId} was not ready after ${maxRetries} polling attempt(s) ` +
        `(${maxRetries}s total). The PDF render may have failed — check DocuSeal server logs.`
    );
    this.name = "SubmissionTimeoutError";
  }
}
