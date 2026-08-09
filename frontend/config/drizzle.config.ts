import { defineConfig } from "drizzle-kit";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

export default defineConfig({
  out: resolve(frontendRoot, "drizzle"),
  schema: resolve(frontendRoot, "db/schema.ts"),
  dialect: "sqlite",
});
