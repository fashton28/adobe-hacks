import js from "@eslint/js";
import globals from "globals";

export default [
    { ignores: ["dist/", "node_modules/"] },
    js.configs.recommended,
    {
        files: ["src/**/*.js", "test/**/*.mjs", "eslint.config.mjs"],
        languageOptions: { ecmaVersion: 2023, sourceType: "module", globals: { ...globals.browser } }
    },
    {
        files: ["test/**/*.mjs"],
        languageOptions: { globals: { ...globals.node } }
    },
    {
        files: ["webpack.config.cjs"],
        languageOptions: { sourceType: "commonjs", globals: { ...globals.node } }
    }
];
