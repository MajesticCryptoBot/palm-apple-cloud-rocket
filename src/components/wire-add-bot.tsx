import { useState } from "react";
import { Bot, Check, Megaphone, Plus, X } from "lucide-react";
import { BOT_PROFILES, type BotProfile, useDesk } from "@/lib/wire/store";

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
          <div><h2 id="add-bot-title" className="text-lg font-semibold">Add a trading bot</h2><p className="text-sm text-muted">Connect a script that is already on this PC</p></div>
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

export function PlusMenu({ onChannel, onBot, onClose }: { onChannel: () => void; onBot: () => void; onClose: () => void }) {
  return (
    <div className="absolute top-16 right-4 z-40 w-56 overflow-hidden rounded-xl border border-line bg-sidebar py-1 shadow-xl" onMouseLeave={onClose}>
      <button type="button" onClick={onChannel} className="flex w-full items-center gap-3 px-3 py-2.5 text-left hover:bg-elevated"><Megaphone className="size-4 text-accent" /> New Channel</button>
      <button type="button" onClick={onBot} className="flex w-full items-center gap-3 px-3 py-2.5 text-left hover:bg-elevated"><Bot className="size-4 text-accent" /> Add a trading bot</button>
    </div>
  );
}

export function NewChannelDialog({ onClose }: { onClose: () => void }) {
  const createChannel = useDesk((s) => s.createChannel);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [photo, setPhoto] = useState("");
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/65 p-4" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <section role="dialog" aria-modal="true" className="w-full max-w-md overflow-hidden rounded-2xl border border-line bg-sidebar text-fg shadow-2xl">
        <header className="flex items-center justify-between border-b border-line px-5 py-4">
          <h2 className="text-lg font-semibold">New Channel</h2>
          <button onClick={onClose} className="grid size-9 place-items-center rounded-full hover:bg-elevated" aria-label="Close"><X className="size-5" /></button>
        </header>
        <div className="space-y-3 p-5">
          <label className="grid size-20 cursor-pointer place-items-center overflow-hidden rounded-full bg-elevated text-xs text-muted">
            {photo ? <img src={photo} alt="" className="size-full object-cover" /> : "Photo"}
            <input type="file" accept="image/*" className="hidden" onChange={(e) => {
              const file = e.target.files?.[0];
              if (!file) return;
              const reader = new FileReader();
              reader.onload = () => { if (typeof reader.result === "string") setPhoto(reader.result); };
              reader.readAsDataURL(file);
            }} />
          </label>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Channel name" className="w-full rounded-lg border border-line bg-bg px-3 py-2 outline-none" />
          <textarea value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Description" rows={3} className="w-full rounded-lg border border-line bg-bg px-3 py-2 outline-none" />
          <p className="text-xs text-muted">Private. Only you can see this channel. No subscribers, no bot menu.</p>
        </div>
        <footer className="flex justify-end gap-2 border-t border-line px-5 py-3">
          <button onClick={onClose} className="rounded-lg px-4 py-2 text-sm">Cancel</button>
          <button disabled={!name.trim()} onClick={() => { createChannel({ name: name.trim(), description: description.trim(), photo: photo || undefined }); onClose(); }} className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-bg disabled:opacity-40">Create</button>
        </footer>
      </section>
    </div>
  );
}
