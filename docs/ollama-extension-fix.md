### Workaround for `vscode-ollama` 0.17.x

The official `vscode-ollama` extension probes the Ollama HTTP server for a
`/version` endpoint when it activates. That endpoint was introduced in a later
release; the current Windows build (0.17.5/0.17.6 as of March 4 2026) returns
404, causing the extension to display the spurious warning:

```
unable to verify Ollama server version...
```

The warning itself is harmless, but it also prevents the language‑models panel
from showing the configured model.  Until the extension is updated to handle
404s gracefully you can patch it locally.

1. locate the installed extension in the WSL filesystem (you may be using a
   remote SSH session so the path begins with `~/.vscode-server`):
   ```sh
   ~/.vscode-server/extensions/warm3snow.vscode-ollama-<version>/{dist,out}/extension.js
   ```
   There are two copies of the runtime code – one under `dist` that ships on the
   VS Code marketplace and another under `out` that is actually executed by the
   editor.  **Be sure to edit both files** (or just `out/extension.js`) when you
   apply the workaround.

2. modify `extension.js` and either replace or prepend the following snippet
   near the top of the `activate` function (e.g. just after the
   "Initializing Ollama client with config" log).  The patched code uses
   `/version` and swallows any failure so 0.17‑series servers will no longer
   trigger the warning.

```js
// version probe (workaround for 0.17.x servers)
(function(){
    const e = n();
    const base = e.baseUrl.replace(/\/+$/,'');
    const url = `${base}/version`;
    fetch(url, { method: 'GET' })
        .then(r => {
            if (!r.ok) {
                console.log('Ollama version probe returned', r.status);
                return;
            }
            return r.json();
        })
        .then(j => {
            if (j && j.version) {
                console.log('Ollama server version', j.version);
            }
        })
        .catch(_ => {
            console.log('skipping Ollama version check');
        });
})();
```

3. **Reload the VS Code window** (`Ctrl+Shift+P` → **Reload Window**) or restart
the editor.  The new JavaScript will be picked up only after a reload.

After patching and reloading you should no longer see the version warning and
models will list correctly.  When the extension is updated upstream (or the
server begins serving `/version`) you can remove the workaround or simply
reinstall the extension to restore its original behaviour.

Alternatively you can file an issue against the extension repository so that
the upstream author can incorporate a proper fix.
