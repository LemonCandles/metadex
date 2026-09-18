import { defineConfig, globalIgnores } from "eslint/config";
import nextConfig from "eslint-config-next/core-web-vitals";
import nextTypeScriptConfig from "eslint-config-next/typescript";

export default defineConfig([
  ...nextConfig,
  ...nextTypeScriptConfig,
  globalIgnores([".next/**", "out/**", "build/**", "next-env.d.ts"]),
]);
