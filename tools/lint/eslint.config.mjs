// ESLint for askdnd's own JavaScript (foundations F4, docs/plans/2026-11-13-engineering-practices.md): rules that catch
// bugs, not style. app.js is one script in the browser; the vendored libraries in app/static/vendor/ are left alone.
import js from "@eslint/js";
import globals from "globals";

export default [
  { ignores: ["**/vendor/**", "**/node_modules/**"] },
  js.configs.recommended,
  {
    files: ["app/static/**/*.js"],
    languageOptions: {
      ecmaVersion: 2023,
      sourceType: "script",
      globals: { ...globals.browser, htmx: "readonly", Sortable: "readonly", TurndownService: "readonly", htmlToImage: "readonly", DiceBox: "readonly" },
    },
    rules: {
      // the bug of Nov 13: a second function `place` replaced the roll card's, and its windows opened off screen
      "no-redeclare": ["error", { builtinGlobals: false }],
      "no-shadow": ["error", { builtinGlobals: false, hoist: "functions" }],
      "no-implicit-globals": "error",
      "no-use-before-define": ["error", { functions: false, classes: true, variables: false }],
      "no-unused-vars": ["error", { args: "none", caughtErrors: "none" }],
      "no-empty": ["error", { allowEmptyCatch: true }],
      eqeqeq: ["error", "smart"],
      "no-eval": "error",
      "no-implied-eval": "error",
      "no-new-func": "error",
      "no-self-compare": "error",
      "no-template-curly-in-string": "error",
      "no-unmodified-loop-condition": "error",
      "no-unreachable-loop": "error",
      "array-callback-return": "error",
      "no-constructor-return": "error",
      "no-promise-executor-return": "error",
    },
  },
];
