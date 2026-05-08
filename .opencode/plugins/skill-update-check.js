import { spawnSync } from "node:child_process";
import { existsSync, realpathSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const RELATIVE_SCRIPT = "confluence-curation/scripts/_skill_update_check.py";

function findRepoRoot(startFile) {
  let dir;
  try {
    dir = path.dirname(realpathSync(startFile));
  } catch {
    dir = path.dirname(startFile);
  }
  for (let i = 0; i < 8; i += 1) {
    const candidate = path.join(dir, RELATIVE_SCRIPT);
    if (existsSync(candidate)) {
      return { root: dir, script: candidate };
    }
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return null;
}

export const SkillUpdateCheckPlugin = async () => {
  let armed = true;
  return {
    "session.created": async () => {
      if (!armed) return;
      armed = false;
      const here = fileURLToPath(import.meta.url);
      const found = findRepoRoot(here);
      if (!found) return;
      try {
        spawnSync("python3", [found.script], {
          cwd: found.root,
          stdio: ["ignore", "ignore", "inherit"],
          timeout: 8000,
          env: { ...process.env, GIT_TERMINAL_PROMPT: "0" },
        });
      } catch {
        // Never block the session on a failed update check.
      }
    },
  };
};

export default SkillUpdateCheckPlugin;
