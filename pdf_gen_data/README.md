# PDF Gen Data

Local Node.js (TypeScript) tool to generate Vietnamese fake data via [Faker.js](https://fakerjs.dev/) and send it to a local [DocuSeal](https://www.docuseal.co/) instance.

For full setup instructions, see [GETTING_STARTED.md](GETTING_STARTED.md).

## Quick Start

```bash
npm install
cp .env.example .env   # fill in DOCUSEAL_API_URL and DOCUSEAL_API_KEY
npm run dev
```

Generated PDFs are saved to `./output_pdfs/`.

## Scripts

| Command         | Description                    |
| --------------- | ------------------------------ |
| `npm run dev`   | Run with ts-node (development) |
| `npm run build` | Compile TypeScript → `dist/`   |
| `npm start`     | Run compiled output            |
| `npm run lint`  | Lint source files              |

## Project Structure

```
pdf_gen_data/
├── mapping_config.json              ← Template ↔ Faker field mappings
├── output_pdfs/                     ← Generated PDFs (gitignored)
├── src/
│   ├── index.ts                     ← Orchestrator
│   ├── types.ts                     ← Zod schemas & TS types
│   ├── services/
│   │   ├── config.service.ts        ← Reads & validates mapping_config.json
│   │   ├── data-generator.service.ts← Dynamic Faker dispatch (fakerVI locale)
│   │   ├── docuseal.client.ts       ← DocuSeal API client + PDF polling
│   │   └── env.service.ts           ← Env variable loader
│   └── utils/
│       └── fs.utils.ts              ← Output directory helpers
├── .env.example
├── package.json
└── tsconfig.json
```
