# Agent marks

The six coding-agent marks used by the setup section. They were fetched once
from the LobeHub static icon set and committed here, so the page makes no
runtime third-party image requests:

    https://unpkg.com/@lobehub/icons-static-svg@latest/icons/<slug>.svg

| File | Agent | Variant |
|---|---|---|
| `codex-color.svg` | Codex | colour |
| `claudecode-color.svg` | Claude Code | colour |
| `geminicli-color.svg` | Gemini CLI | colour |
| `cursor.svg` | Cursor | monochrome |
| `opencode.svg` | OpenCode | monochrome |
| `pi.svg` | Pi | monochrome |

Source: [LobeHub icons](https://github.com/lobehub/lobe-icons) (MIT). The SVGs
keep their original `lobe-icons-*` gradient ids; they are rendered through
`<img>` so those ids never collide with the page.
