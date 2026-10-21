// 데스크톱 껍데기 규칙: Node(CommonJS) + JS 권장. 포맷은 Prettier 가 맡는다.
const js = require("@eslint/js");
const globals = require("globals");

module.exports = [
  { ignores: ["node_modules", "release", "dist"] },
  {
    files: ["**/*.js"],
    ...js.configs.recommended,
    languageOptions: { ecmaVersion: 2022, sourceType: "commonjs", globals: { ...globals.node } },
    rules: {
      ...js.configs.recommended.rules,
      "no-unused-vars": ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^_", caughtErrors: "none" }],
      "no-empty": ["error", { allowEmptyCatch: true }],
    },
  },
  // 앱 화면(부팅 · 설치)은 브라우저에서 돈다. setup-model.js 는 테스트(Node)와 함께 쓴다.
  {
    files: ["src/pages/**/*.js"],
    languageOptions: { sourceType: "script", globals: { ...globals.browser } },
  },
  {
    files: ["src/pages/setup-model.js"],
    languageOptions: { globals: { ...globals.browser, ...globals.node } },
  },
];
