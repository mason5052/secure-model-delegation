import { build } from "esbuild";
import { cp, mkdir, readFile, writeFile, readdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
const here = path.dirname(fileURLToPath(import.meta.url));
const target = path.resolve(here, "../src/smd_app/static/canvas");
await mkdir(target, { recursive: true });
const buildResult = await build({
  entryPoints: [path.join(here, "canvas.jsx")],
  outdir: target,
  entryNames: "canvas",
  chunkNames: "chunks/[name]-[hash]",
  bundle: true,
  splitting: true,
  format: "esm",
  conditions: ["production"],
  minify: true,
  sourcemap: false,
  target: ["chrome120"],
  legalComments: "eof",
  metafile: true,
  define: { "process.env.NODE_ENV": '"production"', "process.env.IS_PREACT": "false" },
  loader: { ".woff2": "file", ".woff": "file", ".ttf": "file" },
});
await cp(path.join(here, "node_modules/@excalidraw/excalidraw/dist/prod/fonts"), path.join(target, "fonts"), { recursive: true });
const pdfTarget = path.resolve(here, "../src/smd_app/static/pdf");
await mkdir(pdfTarget, { recursive: true });
const pdfResult = await build({ entryPoints: [path.join(here, "pdf-preview.js")], outfile: path.join(pdfTarget, "preview.js"),
  bundle: true, format: "esm", minify: true, target: ["chrome120"], legalComments: "eof", metafile: true });
await cp(path.join(here, "node_modules/pdfjs-dist/build/pdf.worker.min.mjs"), path.join(pdfTarget, "pdf.worker.mjs"));
for (const folder of ["cmaps", "standard_fonts", "wasm"]) await cp(path.join(here, "node_modules/pdfjs-dist", folder), path.join(pdfTarget, folder), { recursive: true });
await cp(path.join(here, "node_modules/pdfjs-dist/LICENSE"), path.join(pdfTarget, "LICENSE"));

const notices = [];
const bundled = new Set();
for (const input of Object.keys({ ...buildResult.metafile.inputs, ...pdfResult.metafile.inputs })) {
  const marker = input.lastIndexOf("node_modules/");
  if (marker < 0) continue;
  const rest = input.slice(marker + 13).split("/");
  const name = rest[0].startsWith("@") ? rest.slice(0, 2).join("/") : rest[0];
  bundled.add(path.resolve(here, input.slice(0, marker + 13), name));
}
for (const base of [...bundled].sort()) {
  try {
    const pkg = JSON.parse(await readFile(path.join(base, "package.json"), "utf8"));
    let license = "";
    for (const candidate of await readdir(base)) {
      if (!/^(license|licence|copying|notice)(\.|$)/i.test(candidate)) continue;
      try { license += await readFile(path.join(base, candidate), "utf8") + "\n"; } catch (_) {}
    }
    if (pkg.name === "@excalidraw/excalidraw") license += await readFile(path.join(here, "licenses/EXCALIDRAW-LICENSE"), "utf8");
    notices.push(`${pkg.name} ${pkg.version}\nLicense: ${JSON.stringify(pkg.license)}\n${license}`);
  } catch (_) {}
}
for (const file of await readdir(path.join(here, "licenses"))) {
  if (file === "EXCALIDRAW-LICENSE") continue;
  notices.push(await readFile(path.join(here, "licenses", file), "utf8"));
}
await writeFile(path.join(target, "THIRD_PARTY_NOTICES.txt"), notices.join("\n\n"));
console.log(`Built the local drawing/PDF viewers, fonts, and notices for ${bundled.size} packages.`);
