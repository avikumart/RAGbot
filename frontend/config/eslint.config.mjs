import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    settings: {
      next: {
        rootDir: "frontend/",
      },
    },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    "frontend/.next/**",
    "frontend/out/**",
    "frontend/build/**",
    "frontend/dist/**",
    "frontend/next-env.d.ts",
  ]),
]);

export default eslintConfig;
