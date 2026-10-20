import { useEffect, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { Desk } from "@/components/wire-desk";
import { useDesk } from "@/lib/wire/store";

export const Route = createFileRoute("/")({ component: Home });

function Home() {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const api = useDesk.persist;
    if (api.hasHydrated()) setReady(true);
    return api.onFinishHydration(() => setReady(true));
  }, []);
  if (!ready) return <div className="h-dvh bg-bg" />;
  return <Desk />;
}
