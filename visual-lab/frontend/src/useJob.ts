import { useEffect, useState } from "react";
import { getJSON } from "./api";

export interface Job<R = unknown> {
  id: string;
  kind: string;
  status: "queued" | "running" | "done" | "failed";
  progress: number;
  result: R | null;
  error: string | null;
}

/** Poll a background job until it finishes. */
export function useJob<R = unknown>(id: string | null): Job<R> | null {
  const [job, setJob] = useState<Job<R> | null>(null);
  useEffect(() => {
    if (!id) { setJob(null); return; }
    let stop = false;
    const poll = async () => {
      try {
        const j = await getJSON<Job<R>>(`/api/jobs/${id}`);
        if (stop) return;
        setJob(j);
        if (j.status === "queued" || j.status === "running") setTimeout(poll, 600);
      } catch {
        if (!stop) setTimeout(poll, 1500);
      }
    };
    poll();
    return () => { stop = true; };
  }, [id]);
  return job;
}
