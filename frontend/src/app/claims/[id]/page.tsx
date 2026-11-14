import fs from "node:fs";
import path from "node:path";
import Client from "./client";

// For the static hosted demo, pre-render one page per recorded claim.
export function generateStaticParams() {
  try {
    const rows = JSON.parse(fs.readFileSync(path.join(process.cwd(), "public/snapshot/claims.json"), "utf8"));
    return rows.map((r: { id: string }) => ({ id: r.id }));
  } catch {
    return [];
  }
}

export default function Page() {
  return <Client />;
}
