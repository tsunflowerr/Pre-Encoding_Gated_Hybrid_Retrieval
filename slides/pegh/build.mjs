import { readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const directory = path.dirname(fileURLToPath(import.meta.url));
const [html, css, js] = await Promise.all([
  readFile(path.join(directory, 'index.html'), 'utf8'),
  readFile(path.join(directory, 'styles.css'), 'utf8'),
  readFile(path.join(directory, 'deck.js'), 'utf8'),
]);
let result = html
  .replace('<link rel="stylesheet" href="styles.css">', () => `<style>\n${css}\n</style>`)
  .replace('<script src="deck.js" defer></script>', () => `<script>\n${js}\n</script>`);
const assets = new Set([...html.matchAll(/src="(assets\/[^\"]+)"/g)].map(match => match[1]));
for (const asset of assets) {
  const data = await readFile(path.join(directory, asset));
  const mime = path.extname(asset) === '.svg' ? 'image/svg+xml' : 'image/png';
  result = result.replaceAll(`src="${asset}"`, `src="data:${mime};base64,${data.toString('base64')}"`);
}
const output = path.join(directory, 'PE_GH_SLIDES.html');
await writeFile(output, result, 'utf8');
console.log(`Built standalone HTML: ${output}`);
