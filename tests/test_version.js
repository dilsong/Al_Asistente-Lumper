/** Una sola fuente de verdad para la versión de AL. */
const fs = require("fs");
const path = require("path");
const assert = require("assert");

const root = path.join(__dirname, "..");
const versionJs = fs.readFileSync(path.join(root, "static", "version.js"), "utf8");
const sw = fs.readFileSync(path.join(root, "static", "sw.js"), "utf8");
const app = fs.readFileSync(path.join(root, "static", "app.js"), "utf8");
const html = fs.readFileSync(path.join(root, "static", "index.html"), "utf8");

const match = versionJs.match(/AL_APP_VERSION\s*=\s*"([^"]+)"/);
assert.ok(match, "version.js define AL_APP_VERSION");
const version = match[1];
assert.strictEqual(version, "1.0.15");

assert.ok(sw.includes('importScripts("/static/version.js")'), "sw.js importa version.js");
assert.ok(sw.includes("self.AL_APP_VERSION"), "sw.js usa la versión importada");
assert.ok(!/const APP_VERSION = "1\.0\.\d+"/.test(sw), "sw.js no hardcodea la versión");
assert.ok(sw.includes('url.pathname.endsWith("/version.js")'), "SW revalida version.js");

assert.ok(html.includes('id="settings-app-version"'), "Ajustes tiene el pie de versión");
assert.ok(html.includes("/static/version.js"), "index carga version.js");
assert.ok(!html.includes("app.js?v=1.0."), "index no hardcodea ?v= de app.js");
assert.ok(!html.includes("styles.css?v=1.0."), "index no hardcodea ?v= de styles.css");

assert.ok(app.includes("function versionAl"), "app.js lee la versión");
assert.ok(app.includes("pintarVersionAl"), "app.js pinta Ajustes");
assert.ok(app.includes("Versión AL"), "texto visible de versión");
assert.ok(app.includes("sw.js?v="), "registro SW con query de versión");
assert.ok(app.includes("window.AL_VERSION"), "versión consultable en consola");

const hardcoded = [];
["static/sw.js", "static/index.html", "static/app.js"].forEach((rel) => {
  const texto = fs.readFileSync(path.join(root, rel), "utf8");
  if (texto.includes("1.0.15")) hardcoded.push(rel);
});
assert.deepStrictEqual(hardcoded, [], `1.0.15 no debe repetirse fuera de version.js: ${hardcoded.join(", ")}`);

console.log("OK test_version", version);
