# PDF Gen Data

Local Node.js (TypeScript) tool to generate fake data via [Faker.js](https://fakerjs.dev/) and send it to a local [DocuSeal](https://www.docuseal.co/) instance.

## Quick Start

```bash
# 1. Install dependencies
npm install

# 2. Copy environment template and fill in your values
cp .env.example .env

# 3. Run in development mode
npm run dev

# 4. Build for production
npm run build && npm start
```

## Project Structure

```
pdf_gen_data/
├── mapping_config.json          # Template ↔ Faker field mappings
├── src/
│   ├── index.ts                 # Entry point
│   ├── types.ts                 # Zod schemas & TS types
│   └── services/
│       └── config.service.ts    # Reads & validates mapping_config.json
├── package.json
├── tsconfig.json
├── .env.example
└── .gitignore
```

## Configuration

Edit `mapping_config.json` to map DocuSeal template fields to Faker.js methods.

**Field format:** `"<DocuSeal Field Name>": "<faker.module.method>"`

Optional parameters can be appended with a pipe: `"string.numeric|{\"length\":12}"`

## Scripts

| Command         | Description                    |
| --------------- | ------------------------------ |
| `npm run dev`   | Run with ts-node (development) |
| `npm run build` | Compile TypeScript → `dist/`   |
| `npm start`     | Run compiled output            |
| `npm run lint`  | Lint source files              |
