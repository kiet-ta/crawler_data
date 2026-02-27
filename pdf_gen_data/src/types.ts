/**
 * Type definitions for the PDF Gen Data tool.
 *
 * Why separated: Keeping types in their own file follows SRP — these
 * definitions describe the shape of data, not behaviour.  Other modules
 * import only what they need without pulling in runtime dependencies.
 */

import { z } from "zod";

// ── Zod schemas (runtime validation) ────────────────────────────────

/**
 * Schema for a single template field mapping.
 * The key is the DocuSeal field name; the value is a Faker.js method
 * string, optionally followed by `|{json_params}`.
 *
 * Examples:
 *   "person.fullName"
 *   "string.numeric|{\"length\":12}"
 */
export const FieldMappingSchema = z.record(z.string().min(1), z.string().min(1));

/**
 * Schema for one template entry inside `mapping_config.json`.
 */
export const TemplateConfigSchema = z.object({
  docuseal_template_id: z.number().int().positive(),
  name: z.string().min(1),
  description: z.string().optional(),
  fields: FieldMappingSchema,
});

/**
 * Root schema — the whole config file.
 */
export const MappingConfigSchema = z.object({
  templates: z.array(TemplateConfigSchema).min(1),
});

// ── Derived TypeScript types ────────────────────────────────────────

export type FieldMapping = z.infer<typeof FieldMappingSchema>;
export type TemplateConfig = z.infer<typeof TemplateConfigSchema>;
export type MappingConfig = z.infer<typeof MappingConfigSchema>;

// ── DocuSeal API response schemas ───────────────────────────────────

/**
 * A single field object returned by the DocuSeal REST API.
 *
 * Why passthrough: DocuSeal may include extra metadata (uuid, type, required,
 * submitter_uuid, …) that we don't need. Using passthrough avoids false
 * validation failures when the API adds new properties in future versions.
 */
export const DocuSealApiFieldSchema = z
  .object({ name: z.string().min(1) })
  .passthrough();

/**
 * A submitter role within a template.
 * Some DocuSeal versions nest fields under each submitter rather than at the
 * top-level template object — we handle both with the same extractor.
 */
export const DocuSealApiSubmitterSchema = z
  .object({
    name: z.string().optional(),
    fields: z.array(DocuSealApiFieldSchema).optional(),
  })
  .passthrough();

/**
 * A document object within a template.
 * Older DocuSeal builds place form fields here instead of at the template root.
 */
export const DocuSealApiDocumentSchema = z
  .object({
    fields: z.array(DocuSealApiFieldSchema).optional(),
  })
  .passthrough();

/**
 * A single template as returned by `GET /api/templates`.
 *
 * Why three optional field locations: DocuSeal has changed where it surfaces
 * fields across self-hosted versions and its SaaS offering.  Declaring all
 * three as optional lets `extractFieldNames` in sync.ts harvest fields from
 * whichever location the running instance actually uses.
 */
export const DocuSealApiTemplateSchema = z
  .object({
    id: z.number().int().positive(),
    name: z.string().min(1),
    fields: z.array(DocuSealApiFieldSchema).optional(),
    submitters: z.array(DocuSealApiSubmitterSchema).optional(),
    documents: z.array(DocuSealApiDocumentSchema).optional(),
  })
  .passthrough();

/**
 * Paginated response envelope returned by `GET /api/templates`.
 *
 * Why validate the envelope: ensures we detect breaking API changes
 * (e.g., the `data` key being renamed) immediately at the boundary,
 * before any merge logic runs.
 */
export const DocuSealApiResponseSchema = z.object({
  data: z.array(DocuSealApiTemplateSchema),
  pagination: z
    .object({ count: z.number() })
    .passthrough()
    .optional(),
});

export type DocuSealApiField = z.infer<typeof DocuSealApiFieldSchema>;
export type DocuSealApiSubmitter = z.infer<typeof DocuSealApiSubmitterSchema>;
export type DocuSealApiDocument = z.infer<typeof DocuSealApiDocumentSchema>;
export type DocuSealApiTemplate = z.infer<typeof DocuSealApiTemplateSchema>;
export type DocuSealApiResponse = z.infer<typeof DocuSealApiResponseSchema>;
