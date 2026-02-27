/**
 * ScannerSimulatorService — degrades a perfect vector PDF into a raster PDF
 * that mimics output from a low-quality flatbed or fax scanner.
 *
 * Why this pipeline exists:
 *   DocuSeal produces clean vector PDFs (text is scalable, perfectly sharp).
 *   Real-world documents arrive as scanned raster images with noise, blur,
 *   and contrast loss. Training or testing OCR models on perfect PDFs leads
 *   to inflated accuracy metrics that collapse on real data. This service
 *   deliberately introduces "physical" artefacts so test data reflects
 *   real-world scanner output.
 *
 * Three-stage pipeline (Simplification Cascades):
 *   1. Rasterize  — PDF pages → PNG buffers  (pdf2pic + poppler pdftoppm)
 *   2. Degrade    — PNG buffer → dirty JPG   (sharp: grayscale, blur, noise)
 *   3. Reassemble — dirty JPGs → new PDF     (pdf-lib embed as full pages)
 *
 * Why poppler (pdftoppm) instead of Ghostscript:
 *   Ghostscript requires a separate OS install and is unavailable on this
 *   machine. poppler's pdftoppm is already installed (used by the sibling
 *   hades OCR pipeline) and produces identical raster output.
 *
 * Why sequential page processing (no Promise.all):
 *   Image processing is CPU-bound. Parallel execution of sharp transforms
 *   would saturate all cores simultaneously, causing memory spikes and
 *   unpredictable throughput. Sequential processing is slower but stable
 *   and predictable for batch workloads.
 */

import { fromPath } from "pdf2pic";
import sharp from "sharp";
import { PDFDocument } from "pdf-lib";
import * as fs from "node:fs";
import * as path from "node:path";
import * as os from "node:os";

// ── Degradation constants ─────────────────────────────────────────────

/**
 * Simulates a 150 DPI consumer-grade scanner.
 * Why 150 DPI: cheap office scanners default to 150–200 DPI. Going lower
 * destroys legibility; going higher produces unnecessarily large files and
 * looks too clean to be realistic.
 */
const RASTER_DPI = 150;

/**
 * Output JPEG quality for degraded pages.
 * Why 65: balances realism (visible compression artefacts) against file size.
 * Quality 60–70 gives 10×–15× compression vs PNG while still being OCR-readable.
 */
const JPEG_QUALITY = 65;

/**
 * Gaussian blur sigma (pixels).
 * Why 0.8: subtle defocus — simulates a slightly out-of-focus scan glass
 * without making text unreadable. Values above 1.5 are too destructive.
 */
const BLUR_SIGMA = 0.8;

/**
 * Brightness multiplier.
 * Why 0.92: cheap scanner bulbs under-expose slightly, producing a greyish
 * background. Values below 0.85 lose detail in dark ink strokes.
 */
const BRIGHTNESS_FACTOR = 0.92;

/**
 * Noise overlay opacity (0–255 alpha for the noise layer).
 * Why 35: just enough grain to break the "too clean" appearance without
 * obscuring characters. Equivalent to a mild sensor noise pattern.
 */
const NOISE_ALPHA = 35;

// ── Service ─────────────────────────────────────────────────────────

export class ScannerSimulatorService {
  /**
   * Degrade a vector PDF to look like a low-quality scanned document.
   *
   * Reads the PDF at `inputPath`, applies the rasterize → degrade →
   * reassemble pipeline, and writes the result to `outputPath`.
   * If `outputPath` equals `inputPath` the original file is overwritten.
   *
   * @param inputPath  - Absolute path to the source (vector) PDF.
   * @param outputPath - Absolute path where the scanned PDF will be written.
   *                     May equal inputPath to overwrite in place.
   * @throws {RasterizationError}  if pdf2pic fails to convert any page.
   * @throws {DegradationError}    if sharp fails to process an image buffer.
   * @throws {ReassemblyError}     if pdf-lib fails to build the output PDF.
   */
  async simulate(inputPath: string, outputPath: string): Promise<void> {
    // Stage 1 — Rasterize: PDF pages → raw PNG buffers
    const pageBuffers = await this.rasterizePdf(inputPath);

    // Stage 2 — Degrade: apply scanner artefacts to each page image
    const degradedBuffers: Buffer[] = [];
    for (const pngBuffer of pageBuffers) {
      // Why sequential: CPU-bound sharp transforms; parallel would saturate cores
      degradedBuffers.push(await this.degradePage(pngBuffer));
    }

    // Stage 3 — Reassemble: embed degraded JPEGs into a new PDF
    await this.reassemblePdf(degradedBuffers, outputPath);
  }

  // ── Stage 1: Rasterization ─────────────────────────────────────────

  /**
   * Convert every page of a PDF into a PNG buffer using pdf2pic + poppler.
   *
   * @param pdfPath - Absolute path to the source PDF.
   * @returns Array of PNG `Buffer` objects, one per page.
   */
  private async rasterizePdf(pdfPath: string): Promise<Buffer[]> {
    // Write raster images to a temp directory so we don't pollute output_pdfs/
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "pdf-scan-"));

    try {
      // pdf2pic with `useSystemUtils: true` delegates to poppler's pdftoppm
      // instead of Ghostscript — no extra OS install required.
      const converter = fromPath(pdfPath, {
        density: RASTER_DPI,
        saveFilename: "page",
        savePath: tmpDir,
        format: "png",
        width: 2480, // A4 at 300 DPI equiv width; pdf2pic scales to density
        height: 3508,
      });

      // Convert all pages — `true` means "all pages"
      const results = await converter.bulk(-1, { responseType: "buffer" });

      if (!results || results.length === 0) {
        throw new RasterizationError(pdfPath, "pdf2pic returned 0 pages.");
      }

      // Extract the raw Buffer from each result object
      const buffers = results.map((result, idx) => {
        if (!result.buffer) {
          throw new RasterizationError(
            pdfPath,
            `Page ${idx + 1} produced no buffer.`
          );
        }
        return result.buffer as Buffer;
      });

      return buffers;
    } catch (error) {
      if (error instanceof RasterizationError) throw error;
      throw new RasterizationError(pdfPath, (error as Error).message);
    } finally {
      // Always clean up temp files — even on failure
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  }

  // ── Stage 2: Degradation ──────────────────────────────────────────

  /**
   * Apply scanner-quality degradation to a single PNG page buffer.
   *
   * Degradation chain (order matters in sharp — each step feeds the next):
   *   1. Grayscale    — remove colour, matches monochrome scanner output
   *   2. Blur         — simulate slight defocus on scanner glass
   *   3. Brightness   — reduce exposure like an ageing scanner bulb
   *   4. Noise        — overlay a random noise pattern via composite
   *   5. JPEG encode  — introduce compression artefacts + shrink file size
   *
   * @param pngBuffer - Raw PNG buffer of one rasterized page.
   * @returns JPEG buffer with degradation applied.
   */
  private async degradePage(pngBuffer: Buffer): Promise<Buffer> {
    try {
      // Read image metadata to know the canvas size for noise generation
      const metadata = await sharp(pngBuffer).metadata();
      const width = metadata.width ?? 1240;
      const height = metadata.height ?? 1754;

      // Generate a random greyscale noise layer of identical dimensions.
      // Why raw pixel generation: sharp has no built-in "add noise" operator.
      // Compositing a semi-transparent noise layer is the standard workaround.
      const noiseBuffer = generateNoiseBuffer(width, height, NOISE_ALPHA);

      const degraded = await sharp(pngBuffer)
        // Step 1 — convert to greyscale (monochrome scanner)
        .grayscale()
        // Step 2 — slight gaussian blur (defocus / dirty glass)
        .blur(BLUR_SIGMA)
        // Step 3 — dim slightly (ageing lamp + paper absorption)
        .modulate({ brightness: BRIGHTNESS_FACTOR })
        // Step 4 — overlay noise layer
        .composite([
          {
            input: noiseBuffer,
            raw: { width, height, channels: 4 },
            blend: "over",
          },
        ])
        // Step 5 — encode as JPEG (compression artefacts + smaller size)
        .jpeg({ quality: JPEG_QUALITY, mozjpeg: true })
        .toBuffer();

      return degraded;
    } catch (error) {
      throw new DegradationError((error as Error).message);
    }
  }

  // ── Stage 3: Reassembly ────────────────────────────────────────────

  /**
   * Embed degraded JPEG page buffers into a new PDF document and save it.
   *
   * Each JPEG fills its page exactly (no margins) to match how a scanner
   * driver saves a full-page scan.
   *
   * @param jpegBuffers - Array of degraded JPEG buffers, one per page.
   * @param outputPath  - Destination path for the assembled PDF.
   */
  private async reassemblePdf(
    jpegBuffers: Buffer[],
    outputPath: string
  ): Promise<void> {
    try {
      const doc = await PDFDocument.create();

      for (const jpegBuffer of jpegBuffers) {
        const jpegImage = await doc.embedJpg(jpegBuffer);
        const { width, height } = jpegImage.scale(1);

        const page = doc.addPage([width, height]);
        page.drawImage(jpegImage, { x: 0, y: 0, width, height });
      }

      const pdfBytes = await doc.save();

      // Ensure the output directory exists before writing
      fs.mkdirSync(path.dirname(outputPath), { recursive: true });
      fs.writeFileSync(outputPath, pdfBytes);
    } catch (error) {
      throw new ReassemblyError(outputPath, (error as Error).message);
    }
  }
}

// ── Helpers ───────────────────────────────────────────────────────────

/**
 * Generate a Buffer containing raw RGBA pixels of random greyscale noise.
 *
 * Why raw RGBA: sharp's `composite` with `raw` input is the most direct way
 * to overlay a pixel-level effect without writing a temp file to disk.
 * The alpha channel is fixed at `noiseAlpha` so the noise is semi-transparent.
 *
 * @param width      - Image width in pixels.
 * @param height     - Image height in pixels.
 * @param noiseAlpha - Opacity of each noise pixel (0 = invisible, 255 = opaque).
 * @returns Raw RGBA Buffer of size width × height × 4 bytes.
 */
function generateNoiseBuffer(
  width: number,
  height: number,
  noiseAlpha: number
): Buffer {
  const pixelCount = width * height;
  // 4 channels: R G B A
  const data = Buffer.alloc(pixelCount * 4);

  for (let i = 0; i < pixelCount; i++) {
    // Random greyscale value — same value for R, G, B keeps it neutral
    const grey = Math.floor(Math.random() * 256);
    const offset = i * 4;
    data[offset] = grey;       // R
    data[offset + 1] = grey;   // G
    data[offset + 2] = grey;   // B
    data[offset + 3] = noiseAlpha; // A
  }

  return data;
}

// ── Custom errors ─────────────────────────────────────────────────────

export class RasterizationError extends Error {
  constructor(pdfPath: string, detail: string) {
    super(
      `Failed to rasterize "${path.basename(pdfPath)}": ${detail}\n` +
        "Ensure poppler (pdftoppm) is installed: pacman -S poppler"
    );
    this.name = "RasterizationError";
  }
}

export class DegradationError extends Error {
  constructor(detail: string) {
    super(
      `Image degradation failed: ${detail}\n` +
        "Check that the sharp package is correctly installed (npm install sharp)."
    );
    this.name = "DegradationError";
  }
}

export class ReassemblyError extends Error {
  constructor(outputPath: string, detail: string) {
    super(
      `Failed to assemble PDF at "${outputPath}": ${detail}\n` +
        "Verify the output directory is writable."
    );
    this.name = "ReassemblyError";
  }
}
