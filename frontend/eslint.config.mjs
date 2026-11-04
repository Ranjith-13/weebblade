import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

/* DESIGN.md: "No em-dashes in visible copy." It is the single most reliable
 * tell of generated prose, and the first pass of this site shipped 13 of them,
 * including in the page title. The rule has since been broken twice more and
 * caught by hand both times - once in the changes teaser on the page every
 * visitor lands on - so it is enforced here instead.
 *
 * The one carve-out is the marker for "no value" in tabular data, which is a
 * typographic convention rather than a flourish. It is exported as NULL_MARKER
 * from lib/types.ts, written as an escape, so the four places that print it
 * need no allowlist and a reader can see that the dash there is deliberate.
 *
 * Comments are not matched: they are not AST nodes these selectors can reach,
 * and this file, DESIGN.md and ARCHITECTURE.md all discuss the character at length.
 * The en-dash is not matched either - "A-Z" in the sort chips is a range, which
 * is what an en-dash is for.
 */
const NO_EM_DASH =
  'Em-dash in visible copy. DESIGN.md bans it: it is the clearest tell of generated prose. ' +
  'Use a colon, a comma or brackets - or NULL_MARKER from @/lib/types if this is the ' +
  '"no value" marker on a plate, a search result or a social card.';

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    files: ["app/**/*.{ts,tsx}", "components/**/*.{ts,tsx}", "lib/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-syntax": [
        "error",
        { selector: "JSXText[value=/\\u2014/]", message: NO_EM_DASH },
        { selector: "Literal[value=/\\u2014/]", message: NO_EM_DASH },
        { selector: "TemplateElement[value.cooked=/\\u2014/]", message: NO_EM_DASH },
      ],
    },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
]);

export default eslintConfig;
