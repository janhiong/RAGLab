import { fileURLToPath } from "node:url";
const demoOnly = process.env.NEXT_PUBLIC_DEMO_ONLY === "true";
const basePath = process.env.NEXT_PUBLIC_BASE_PATH || "";
export default {
  ...(demoOnly ? { output: "export", trailingSlash: true } : {}),
  basePath,
  turbopack: { root: fileURLToPath(new URL("../..", import.meta.url)) },
};
