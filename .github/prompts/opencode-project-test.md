You are running inside the `curator-skills` repository on a CI self-hosted runner.

Goal:
- Validate that the current project still runs correctly.
- Do not modify any files.
- Do not create commits or branches.

Follow this process exactly:
1. Read `AGENTS.md` and obey the repository instructions.
2. Confirm the repository structure briefly.
3. Run these commands from the repository root:
   - `python3 -m compileall confluence-curation`
   - `python3 confluence-curation/scripts/configure_confluence.py status --json`
   - `python3 confluence-curation/scripts/smoke_pipeline.py`
4. If any command fails:
   - explain which command failed
   - summarize the most likely cause in 3 bullets or fewer
   - print exactly `OPENCODE_TEST_STATUS: FAIL` on its own line at the end
5. If all commands succeed:
   - summarize what passed in 3 bullets or fewer
   - print exactly `OPENCODE_TEST_STATUS: PASS` on its own line at the end

Important constraints:
- Use the existing repository commands only.
- Keep the output concise.
- The final line must be only one of the two required status markers.
