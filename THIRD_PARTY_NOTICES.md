# Third-party notices

AI-v-Z adapts code from the two projects below. Both are MIT licensed; their notices are reproduced in full.

## ClaudeSurvivor / claude-survives-zomboid

- Source: https://github.com/botsofcog/claude-survives-zomboid (commit 418c19f, 2026-07-16)
- Used in: `mod/AIvZ/42/media/lua/client/AIvZ.lua` (percept/intent file IPC, reflex fight-or-flee, HUD layout, auto fast-forward, manual override) and the dashboard idea in `bridge/`.

```
MIT License

Copyright (c) 2026 Joel

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

Not affiliated with or endorsed by The Indie Stone (Project Zomboid) or
Anthropic (Claude). Project Zomboid is a trademark of The Indie Stone Ltd.
```

## ClaudeBot / Claude-Plays-ProjectZomboid

- Source: https://github.com/whatcheers/Claude-Plays-ProjectZomboid (commit 1f13c89, 2026-10-03, mod v0.14.0)
- Used in: `mod/AIvZ/42/media/lua/client/AIvZ.lua` (JSON encoder, pathfinding with `ISPathFindAction`, container walking and transfer, attack/shove/flee logic, wound and stat reading) and `AIvZLoader.lua` (hot reload with `reloadLuaFile`; its arbitrary-code `eval` was deliberately not carried over).

```
MIT License

Copyright (c) 2026 whatcheers

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
