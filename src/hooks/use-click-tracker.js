import { useCallback, useRef } from "react";

function useClickTracker() {
  const clickCounts = useRef({
    oneSecond: 0,
    fifteenSeconds: 0,
    sixtySeconds: 0,
  });

  const clickTimestamps = useRef([]);

  const trackClick = useCallback(() => {
    const now = Date.now();
    clickTimestamps.current.push(now);

    // Remove timestamps older than 60 seconds
    const sixtySecondsAgo = now - 60000;
    clickTimestamps.current = clickTimestamps.current.filter(
      (timestamp) => timestamp > sixtySecondsAgo
    );
    clickCounts.current.sixtySeconds = clickTimestamps.current.length;
    clickCounts.current.fifteenSeconds = clickTimestamps.current.filter(
      (timestamp) => timestamp > now - 15000
    ).length;
    clickCounts.current.oneSecond = clickTimestamps.current.filter(
      (timestamp) => timestamp > now - 1000
    ).length;
  }, []);

  return [clickCounts, trackClick];
}

export default useClickTracker;
