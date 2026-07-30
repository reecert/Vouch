"use client";

import { useCopied } from "@/lib/useCopied";

const CLI_COMMAND = `pipx install git+https://github.com/reecert/Vouch

vouch profile <your-repo> --author you@example.com \\
    --log-dir ~/.claude/projects`;

export default function CopyCliBox() {
  const [copied, copy] = useCopied();

  return (
    <div className="relative rounded-lg border border-slate-200 bg-slate-100/80 p-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[11px] font-mono text-slate-500">Terminal Command</span>
        <button
          onClick={() => copy(CLI_COMMAND)}
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
