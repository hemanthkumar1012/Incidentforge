import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

export default tseslint.config(...tseslint.configs.recommended, {
  plugins: { "react-hooks": reactHooks },
  rules: { ...reactHooks.configs.recommended.rules, "no-restricted-syntax": ["error", {
    selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']",
    message: "Never render HTML from the API: evidence is untrusted.",
  }] },
});
