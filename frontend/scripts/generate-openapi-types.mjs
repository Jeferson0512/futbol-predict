import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptDir, "..");
const inputPath = process.argv[2] ?? path.join(projectRoot, "src", "api", "openapi.json");
const outputPath = process.argv[3] ?? path.join(projectRoot, "src", "api", "generated.ts");

const openapi = JSON.parse(readFileSync(inputPath, "utf-8"));
const schemas = openapi.components?.schemas ?? {};
const schemaNames = Object.keys(schemas).sort();

const lines = [
  "/* eslint-disable */",
  "// This file is generated from src/api/openapi.json.",
  "// Run `npm run generate:api-types` after exporting OpenAPI from the backend.",
  "",
  "export type components = {",
  "  schemas: {",
];

for (const name of schemaNames) {
  lines.push(`    ${propertyName(name)}: ${indent(tsType(schemas[name]), 4)};`);
}

lines.push("  };", "};", "");

for (const name of schemaNames) {
  lines.push(`export type ${safeTypeName(name)} = components["schemas"][${JSON.stringify(name)}];`);
}

lines.push("");

mkdirSync(path.dirname(outputPath), { recursive: true });
writeFileSync(outputPath, lines.join("\n"), "utf-8");
console.log(`Generated ${path.relative(projectRoot, outputPath)}`);

function tsType(schema) {
  if (!schema || typeof schema !== "object") {
    return "unknown";
  }
  if (schema.$ref) {
    return refName(schema.$ref);
  }
  if (Array.isArray(schema.enum)) {
    return schema.enum.map(literal).join(" | ") || "never";
  }
  if (Array.isArray(schema.anyOf)) {
    return union(schema.anyOf.map(tsType));
  }
  if (Array.isArray(schema.oneOf)) {
    return union(schema.oneOf.map(tsType));
  }
  if (Array.isArray(schema.allOf)) {
    return schema.allOf.map(tsType).join(" & ") || "unknown";
  }
  if (Array.isArray(schema.type)) {
    return union(schema.type.map((item) => tsType({ ...schema, type: item })));
  }

  switch (schema.type) {
    case "null":
      return "null";
    case "boolean":
      return "boolean";
    case "integer":
    case "number":
      return "number";
    case "string":
      return "string";
    case "array":
      return `${parenthesizeArrayItem(tsType(schema.items))}[]`;
    case "object":
      return objectType(schema);
    default:
      if (schema.properties || schema.additionalProperties) {
        return objectType(schema);
      }
      return "unknown";
  }
}

function objectType(schema) {
  const properties = schema.properties ?? {};
  const required = new Set(schema.required ?? []);
  const entries = Object.entries(properties).map(([name, propertySchema]) => {
    const optional = required.has(name) ? "" : "?";
    return `  ${propertyName(name)}${optional}: ${tsType(propertySchema)};`;
  });

  if (schema.additionalProperties && typeof schema.additionalProperties === "object") {
    entries.push(`  [key: string]: ${tsType(schema.additionalProperties)};`);
  } else if (schema.additionalProperties === true) {
    entries.push("  [key: string]: unknown;");
  }

  if (entries.length === 0) {
    return "Record<string, never>";
  }
  return `{\n${entries.join("\n")}\n}`;
}

function union(types) {
  return [...new Set(types)].join(" | ") || "never";
}

function refName(ref) {
  return `components["schemas"][${JSON.stringify(ref.split("/").at(-1))}]`;
}

function propertyName(name) {
  return /^[A-Za-z_$][\w$]*$/.test(name) ? name : JSON.stringify(name);
}

function safeTypeName(name) {
  const cleaned = name.replace(/[^A-Za-z0-9_$]/g, "_");
  return /^[A-Za-z_$]/.test(cleaned) ? cleaned : `_${cleaned}`;
}

function literal(value) {
  if (value === null) {
    return "null";
  }
  return JSON.stringify(value);
}

function parenthesizeArrayItem(type) {
  return type.includes(" | ") || type.includes(" & ") ? `(${type})` : type;
}

function indent(value, spaces) {
  return value.replaceAll("\n", `\n${" ".repeat(spaces)}`);
}
