import type { ReactNode } from "react";
import { FIND, VERIFY, money } from "../lib/directory";
import type { GrayDecision, LayaMode } from "../lib/types";
import "../styles/features.css";

export interface FeaturesProps {
  mode: LayaMode;
  onMode: (mode: LayaMode) => void;
  serverMode: string | null;
  grayLog: GrayDecision[];
  online: boolean;
  onNav: (id: string) => void;
}

interface CardProps {
  no: string;
  label: string;
  title: string;
  body: string;
  price: string;
  action: string;
  target: string;
  specimen: ReactNode;
  onNav: (id: string) => void;
}

function Card({ no, label, title, body, price, action, target, specimen, onNav }: CardProps) {
  return (
    <div className="features-card" data-reveal>
      <div className="micro">
        <span className="micro-verm features-num">{no}</span> / {label}
      </div>
      <div className="display-sm">{title}</div>
      <p className="features-body">{body}</p>
      <div className="features-spec">{specimen}</div>
      <div className="features-foot">
        <span className="features-price">{price}</span>
        <button type="button" className="tlink" onClick={() => onNav(target)}>
          {action}
        </button>
      </div>
    </div>
  );
}

export function Features({ mode, onMode, serverMode, grayLog, online, onNav }: FeaturesProps) {
  const agreed = grayLog.filter((decision) => decision.agree).length;

  return (
    <section
      id="features"
      className="features"
      data-sec
      data-folio="pp. 3–5"
      data-screen-label="What it does"
    >
      <div className="frame">
        <div className="pagehead">
          <span>What it does</span>
          <span className="ph-mid">Bucket.io directory</span>
          <span>3–5</span>
        </div>

        <div className="labelbar" data-reveal>
          What it does
        </div>

        <div className="features-grid">
          <Card
            no="01"
            label="In the bucket · free"
            title="Answer from your own pages"
            body="If the person is already listed, the answer comes straight from the SQLite file on your machine. Nothing is sent, nothing is charged."
            price="$0.00 per call"
            action="See the white pages ↓"
            target="white"
            onNav={onNav}
            specimen={
              <div className="rowline">
                <span>
                  <b>OKAFOR</b> Adaeze
                </span>
                <span className="leader" />
                <span className="push">adaeze.okafor@meridianfreight.com</span>
              </div>
            }
          />

          <Card
            no="02"
            label="Format known · verify"
            title="Write the address, then only check it"
            body="When the company’s format is on file, BucketIO builds the address itself and asks Treg only whether it can be delivered."
            price={`From ${money(VERIFY)}`}
            action="See the yellow pages ↓"
            target="yellow"
            onNav={onNav}
            specimen={
              <>
                <div className="rowline">
                  <span>meridianfreight.com</span>
                  <span className="leader" />
                  <span className="push">first.last@</span>
                </div>
                <div className="rowline">
                  <span>Treg verify</span>
                  <span className="leader" />
                  <span className="push">deliverable</span>
                </div>
              </>
            }
          />

          <Card
            no="03"
            label="A stranger · find & learn"
            title="Find once, learn the company"
            body="For a company it has never seen, Treg finds the person. The answer is kept and the format learned, so the next person there is a check."
            price={`From ${money(FIND)}`}
            action="Place a call ↓"
            target="assist"
            onNav={onNav}
            specimen={
              <div className="rowline">
                <span>orchardbank.com</span>
                <span className="leader" />
                <span className="push">first.last@ learned</span>
              </div>
            }
          />

          <Card
            no="04"
            label="Nobody found · pencil"
            title="Pencil in the likeliest address"
            body="When Treg finds no one, BucketIO writes down the most probable address from the formats it has learned, marked unverified."
            price="$0.00 · unverified"
            action="Try the pencil ↓"
            target="assist"
            onNav={onNav}
            specimen={
              <div className="rowline">
                <span>Albescu Odette</span>
                <span className="leader" />
                <span className="push">
                  <span className="pencil">odette.albescu@foxglovecartography.com</span>
                </span>
              </div>
            }
          />
        </div>

        <div className="features-op" data-reveal>
          <div className="features-op-left">
            <div className="micro">
              <span className="micro-verm features-num">05</span> / The operator · scores only
            </div>
            <div className="display-sm">Laya breaks ties. It never dials.</div>
            <p className="features-body">
              Laya (convaiinnovations/laya) scores the candidates when a company’s format is unsure, and breaks the
              tie. The pattern cache does most of the saving. Laya starts in shadow, where its picks are only logged,
              and turns active once the log shows it is right.
            </p>
          </div>

          <div className="features-op-right">
            <div className="micro features-ink2">Laya is set to</div>
            <div className="features-switch" role="group" aria-label="Laya mode">
              <button
                type="button"
                className={mode === "Shadow" ? "is-on" : "is-off"}
                aria-pressed={mode === "Shadow"}
                onClick={() => onMode("Shadow")}
              >
                Shadow
              </button>
              <button
                type="button"
                className={mode === "Active" ? "is-on" : "is-off"}
                aria-pressed={mode === "Active"}
                onClick={() => onMode("Active")}
              >
                Active
              </button>
            </div>
            <div className="micro features-ink2">
              {grayLog.length} gray-zone · Laya agreed {agreed} · disagreed {grayLog.length - agreed}
            </div>
            {online && serverMode !== null ? (
              <div className="micro features-ink2">Server is running Laya {serverMode}.</div>
            ) : null}
            {grayLog.length > 0 ? (
              <div className="features-log">
                {grayLog.slice(0, 4).map((decision, index) => (
                  <div className="features-log-row" data-line key={`${decision.co}-${index}`}>
                    {decision.co} · rules {decision.rules} · Laya {decision.laya} · {decision.outcome}
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        </div>

        <p className="features-note">
          Find from {money(FIND)}, verify from {money(VERIFY)}. Treg rates are the lowest listed per job on treg.to as
          of September 2026. Misses on most finders are not charged. With your own provider keys, your own rates
          apply.
        </p>

        <div className="folio">— 3 · 5 —</div>
      </div>
    </section>
  );
}
