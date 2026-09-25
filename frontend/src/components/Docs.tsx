import { useCallback, useEffect, useRef, useState } from "react";
import { copyText } from "./Coupon";
import "../styles/docs.css";

export interface DocsProps {
  installCommand: string;
  connectCommand: string;
  askCommand: string;
  agentPrompt: string;
  repoUrl: string;
  online: boolean;
  onNav: (id: string) => void;
}

const COPIED_MS = 1800;

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    },
    [],
  );

  const onCopy = useCallback(() => {
    copyText(text);
    setCopied(true);
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setCopied(false), COPIED_MS);
  }, [text]);

  return (
    <button type="button" onClick={onCopy}>
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

interface StepProps {
  no: string;
  title: string;
  blurb: string;
  command: string;
  note?: string;
}

function Step({ no, title, blurb, command, note }: StepProps) {
  return (
    <div className="docs-step" data-reveal>
      <div className="docs-step-head">
        <span className="docs-step-no">{no}</span> {title}
      </div>
      <p className="docs-step-blurb">{blurb}</p>
      <div className="cmdbox">
        <code>$ {command}</code>
        <CopyButton text={command} />
      </div>
      {note ? <p className="micro docs-step-note">{note}</p> : null}
    </div>
  );
}

export function Docs({ installCommand, connectCommand, askCommand, agentPrompt, repoUrl, online }: DocsProps) {
  const agentUrl = (agentPrompt.match(/https?:\/\/\S+/) ?? ["/llms.txt"])[0].replace(/^https?:\/\//, "");

  return (
    <section className="sheet docs" id="docs" data-sec data-folio="p. 12" data-screen-label="Docs">
      <div className="frame">
        <div className="pagehead">
          <span>Docs</span>
          <span className="ph-mid">Bucket.io directory</span>
          <span>12</span>
        </div>

        <div className="labelbar" data-reveal>
          Set up in three steps
        </div>

        <div className="docs-grid">
          <Step
            no="01"
            title="Install"
            blurb="Install BucketIO. It creates one SQLite file, the bucket, in your home folder."
            command={installCommand}
            note={"Or the one-shot bundle: .\\scripts\\setup_lreg.ps1 (Windows) · ./scripts/setup_lreg.sh"}
          />
          <Step
            no="02"
            title="Connect Treg"
            blurb="Add your Treg key. Your own provider keys and rates apply."
            command={connectCommand}
          />
          <Step
            no="03"
            title="Place a call"
            blurb="Ask for anyone by name and company, or let your agent do it."
            command={askCommand}
          />
        </div>

        <div className="docs-lower" data-reveal>
          <div className="docs-privacy">
            <div className="docs-subhead">Privacy</div>
            <p className="docs-privacy-text">
              The bucket stays on your machine. Only the name and company you ask about go to Treg, and only when the
              bucket can’t answer. <b>Laya scores; it never writes an address.</b>
            </p>
          </div>
          <div className="docs-links">
            <a className="docs-link" href={repoUrl} target="_blank" rel="noopener">
              <span className="rowline">
                <span>Agent runbook</span>
                <span className="leader" aria-hidden="true" />
                <span className="push">{agentUrl}</span>
              </span>
            </a>
            <a className="docs-link" href={repoUrl} target="_blank" rel="noopener">
              <span className="rowline">
                <span>Source code</span>
                <span className="leader" aria-hidden="true" />
                <span className="push">GitHub ↗</span>
              </span>
            </a>
            <a className="docs-link" href="https://treg.to" target="_blank" rel="noopener">
              <span className="rowline">
                <span>Treg</span>
                <span className="leader" aria-hidden="true" />
                <span className="push">treg.to ↗</span>
              </span>
            </a>
            <a className="docs-link" href="https://huggingface.co/convaiinnovations/laya" target="_blank" rel="noopener">
              <span className="rowline">
                <span>Operator model</span>
                <span className="leader" aria-hidden="true" />
                <span className="push">convaiinnovations/laya</span>
              </span>
            </a>
          </div>
        </div>

        <div className="folio">— 12 —</div>
        {online ? null : <p className="micro docs-offline">Offline demo — the setup commands still apply.</p>}
      </div>
    </section>
  );
}
