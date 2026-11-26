/**
 * Every write to a Steam collection stays in `src/utils/collections.ts`.
 *
 * That module acts on a collection only when the backend's ownership record
 * names its Steam id, which is what keeps the user's own collections ("VR",
 * "Completed", or one that shares a platform's name) from ever being renamed,
 * refilled or deleted. A collection write anywhere else would bypass the
 * record, so this test scans `src/` for the collectionStore write surface
 * (src/types/steam.d.ts) outside that module.
 *
 * Structural only: it matches call text, so an alias or a computed property
 * slips past it, and `.Delete(` on some other object with that method would
 * be reported too (none exists today).
 */

import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";

const SRC = path.join(process.cwd(), "src");
const OWNER = path.join(SRC, "utils", "collections.ts");
const WRITES: [label: string, pattern: RegExp][] = [
  ["NewUnsavedCollection", /\bNewUnsavedCollection\s*\(/],
  ["AsDragDropCollection", /\bAsDragDropCollection\s*\(/],
  ["Delete", /\.Delete\s*\(/],
  ["m_strName", /\bm_strName\b/],
];

async function sourceFiles(dir: string): Promise<string[]> {
  const files: string[] = [];
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name !== "__eslint_fixtures__") files.push(...(await sourceFiles(full)));
    } else if (/\.(ts|tsx)$/.test(entry.name) && !/\.(test|d)\.tsx?$/.test(entry.name)) {
      files.push(full);
    }
  }
  return files;
}

export function findCollectionWrites(file: string, text: string): string[] {
  return WRITES.filter(([, pattern]) => pattern.test(text)).map(([label]) => `${path.relative(SRC, file)}: ${label}`);
}

describe("Steam collection writes are confined to src/utils/collections.ts", () => {
  it("finds no collection write outside the owner module", async () => {
    const findings: string[] = [];
    for (const file of await sourceFiles(SRC)) {
      if (file === OWNER) continue;
      findings.push(...findCollectionWrites(file, await readFile(file, "utf8")));
    }
    expect(findings).toEqual([]);
  });

  it("is not vacuous: the owner module itself matches every pattern", async () => {
    const text = await readFile(OWNER, "utf8");
    expect(findCollectionWrites(OWNER, text)).toHaveLength(WRITES.length);
  });

  it("reports each write shape", () => {
    const probe = [
      "collectionStore.NewUnsavedCollection(name)",
      "c.AsDragDropCollection().AddApps(x)",
      "await c.Delete()",
      "c.m_strName = name",
    ].join("\n");
    expect(findCollectionWrites(path.join(SRC, "elsewhere.ts"), probe)).toEqual([
      "elsewhere.ts: NewUnsavedCollection",
      "elsewhere.ts: AsDragDropCollection",
      "elsewhere.ts: Delete",
      "elsewhere.ts: m_strName",
    ]);
  });
});
