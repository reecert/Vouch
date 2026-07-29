"use client";

import { useState } from "react";

const CLI_COMMAND = `pipx install git+https://github.com/reecert/Vouch

vouch profile <your-repo> --author you@example.com \\
    --log-dir ~/.claude/projects`;

export default function CopyCliBox() {
  const [copied, setCopied] = useState(false);

  const copyCommand = () => {
    navigator.clipboard.writeText(CLI_COMMAND);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="relative rounded-lg border border-slate-200 bg-slate-100/80 p-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[11px] font-mono text-slate-500">Terminal Command</span>
        <button
          onClick={copyCommand}
          className="rounded bg-white px-2 py-0.5 text-[11px] font-semibold text-slate-700 border border-slate-200 hover:bg-slate-50 cursor-pointer shadow-2xs transition-colors"
        >
          {copied ? "✓ Copied" : "Copy"}
        </button>
      </div>
      <pre className="overflow-x-auto text-xs font-mono text-slate-800 leading-relaxed">
        <code>{CLI_COMMAND}</code>
      </pre>
    </div>
  );
}
