import { Fragment } from "react";
import codexColor from "../assets/agents/codex-color.svg";
import claudeColor from "../assets/agents/claudecode-color.svg";
import geminiColor from "../assets/agents/geminicli-color.svg";
import cursorMark from "../assets/agents/cursor.svg";
import opencodeMark from "../assets/agents/opencode.svg";
import piMark from "../assets/agents/pi.svg";
import { FIND, VERIFY, money } from "../lib/directory";
import "../styles/setup.css";
import { Coupon } from "./Coupon";

export interface SetupProps {
  agentPrompt: string;
  askCommand: string;
  online: boolean;
  onNav: (id: string) => void;
}

const AGENTS = [
  { name: "Codex", mark: codexColor },
  { name: "Claude Code", mark: claudeColor },
  { name: "Cursor", mark: cursorMark },
  { name: "OpenCode", mark: opencodeMark },
  { name: "Gemini CLI", mark: geminiColor },
  { name: "Pi", mark: piMark },
];

export function Setup(props: SetupProps) {
  const { agentPrompt, askCommand, online } = props;

  return (
    <section className="sheet setup" data-sec="" id="setup" data-folio="p. 2" data-screen-label="Set up">
      <div className="frame">
        <div className="pagehead">
          <span>Set up</span>
          <span className="ph-mid">Bucket.io directory</span>
          <span>2</span>
        </div>

        <h2 className="labelbar" data-reveal>
          Set up with your coding agent
        </h2>

        <p className="setup-lede">
          Open any coding agent and paste the line below. It reads the setup guide and walks you through installing
          BucketIO, adding your Treg key, and placing a first call.
        </p>

        <div className="setup-agents">
          <span className="micro">Works with</span>
          {AGENTS.map((agent, index) => (
            <Fragment key={agent.name}>
              {index > 0 ? (
                <span className="setup-sep" aria-hidden="true">
                  ·
                </span>
              ) : null}
              <span className="setup-agent">
                <img src={agent.mark} alt="" width={18} height={18} aria-hidden="true" />
                {agent.name}
              </span>
            </Fragment>
          ))}
        </div>

        <Coupon
          command={agentPrompt}
          note="No expiry. Redeemable on your own machine."
          stub="FREE"
          serial="NO. 0001"
          buttonLabel="Tear off & copy"
          voidColor="paper-bright"
        />

        {online ? null : <p className="micro setup-offline">Offline demo — the setup line still works.</p>}

        <div className="setup-call" data-reveal>
          <div className="setup-call-cmd">$ {askCommand}</div>
          <div className="rowline">
            <span>› 01 In the bucket</span>
            <span className="leader" aria-hidden="true" />
            <span className="push">no</span>
          </div>
          <div className="rowline">
            <span>› 02 Company format known</span>
            <span className="leader" aria-hidden="true" />
            <span className="push">first.last@</span>
          </div>
          <div className="rowline">
            <span>· built iris.calloway@meridianfreight.com</span>
            <span className="leader" aria-hidden="true" />
          </div>
          <div className="rowline">
            <span>· Treg verify</span>
            <span className="leader" aria-hidden="true" />
            <span className="push">deliverable · {money(VERIFY)}</span>
          </div>
          <div className="setup-win">✓ listed as VF — {money(FIND - VERIFY)} less than a cold find</div>
        </div>

        <p className="setup-note">Illustrative output — the setup line and a sample call.</p>

        <div className="folio">— 2 —</div>
      </div>
    </section>
  );
}
