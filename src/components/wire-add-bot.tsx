import { Bot, Check, Plus, X } from "lucide-react";
import { BOT_PROFILES, type BotProfile } from "@/lib/wire/store";

type Props = {
  existing: string[];
  onPick: (profile: BotProfile) => void;
  onClose: () => void;
};

export function AddBotDialog({ existing, onPick, onClose }: Props) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/65 p-4" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <section role="dialog" aria-modal="true" aria-labelledby="add-bot-title" className="wire-settings-dialog w-full max-w-lg overflow-hidden rounded-2xl border border-line bg-sidebar text-fg shadow-2xl">
        <header className="flex items-center justify-between border-b border-line px-5 py-4">
          <div><h2 id="add-bot-title" className="text-lg font-semibold">Add a bot</h2><p className="text-sm text-muted">Choose a local bot connection</p></div>
          <button onClick={onClose} className="grid size-9 place-items-center rounded-full hover:bg-elevated" aria-label="Close"><X className="size-5" /></button>
        </header>
        <div className="space-y-2 p-4">
          {BOT_PROFILES.map((profile) => {
            const added = existing.includes(profile.directory);
            return (
              <button key={profile.directory} type="button" disabled={added} onClick={() => onPick(profile)} className="flex w-full items-center gap-3 rounded-xl border border-line bg-elevated/60 p-3 text-left hover:border-accent hover:bg-bubble-out disabled:cursor-default disabled:opacity-50">
                <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-accent-strong/25 text-accent"><Bot className="size-5" /></span>
                <span className="min-w-0 flex-1"><span className="block font-medium">{profile.name}</span><span className="block text-xs text-muted">{profile.exchange}</span></span>
                <span className="text-xs text-muted">{added ? <span className="inline-flex items-center gap-1"><Check className="size-3.5" /> Added</span> : <span className="inline-flex items-center gap-1"><Plus className="size-3.5" /> Add chat</span>}</span>
              </button>
            );
          })}
        </div>
        <footer className="flex justify-end border-t border-line px-5 py-3"><button onClick={onClose} className="rounded-lg bg-accent-strong px-4 py-2 text-sm font-medium">Cancel</button></footer>
      </section>
    </div>
  );
}
