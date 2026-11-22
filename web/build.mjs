// Bundle web/app.src.js (with genlayer-js) into docs/app.js for GitHub Pages.
import { build } from "esbuild";
import path from "node:path";
import { fileURLToPath } from "node:url";

const web = path.dirname(fileURLToPath(import.meta.url));
await build({
  entryPoints: [path.join(web, "app.src.js")],
  outfile: path.join(web, "..", "docs", "app.js"),
  bundle: true, format: "esm", platform: "browser", target: ["es2022"], minify: true,
  legalComments: "none", logLevel: "warning",
});
console.log("built docs/app.js");
