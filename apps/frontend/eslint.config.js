// Flat config (ESLint 9). Deliberately small: type-aware linting on the whole app
// would double CI time for rules `tsc --noEmit` already enforces.

import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist"] },
  {
    files: ["src/**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: { ecmaVersion: 2022, globals: globals.browser },
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // The SSE payloads are typed at the point of use (`payload as StepEvent`);
      // the transport itself carries `any` by nature.
      "@typescript-eslint/no-explicit-any": "off",
    },
  }
);
