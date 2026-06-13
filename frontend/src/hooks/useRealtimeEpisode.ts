// Connects an EpisodeWebSocketClient for the given episode id and routes frames
// + connection status into the store. Cleans up (stops the client) on unmount
// or when the episode id changes.

import { useEffect, useRef } from "react";
import { EpisodeWebSocketClient } from "@/api/ws";
import { useStore } from "@/state/store";

export function useRealtimeEpisode(episodeId: string | undefined): void {
  const clientRef = useRef<EpisodeWebSocketClient | null>(null);

  useEffect(() => {
    if (!episodeId) return;
    useStore.getState().setMode("live");
    useStore.getState().setEpisodeId(episodeId);
    useStore.getState().setConnection({ status: "connecting", error: null });

    const client = new EpisodeWebSocketClient({
      episodeId,
      onFrame: (frame) => {
        // Realtime frames flow through the same latestFrame path the offline
        // SceneView subscribes to (one SimFrame schema, one render path).
        useStore.getState().pushRealtimeFrame(frame);
      },
      onStatus: (status, error, attempts) => {
        useStore.getState().setConnection({
          status,
          error: error ?? null,
          attempts: attempts ?? useStore.getState().connection.attempts,
        });
      },
    });
    clientRef.current = client;
    client.connect();

    return () => {
      client.stop();
      clientRef.current = null;
    };
  }, [episodeId]);
}
