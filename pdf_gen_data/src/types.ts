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
