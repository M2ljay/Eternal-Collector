import { FC, type ReactNode, useState } from "react";
import { capsuleArtSources } from "../../utils/steamCapsuleArt";

/**
 * Steam's own portrait capsule for a shortcut (`capsuleArtSources`), tried in
 * order; `fallback` is shown once every source has failed. Mount it with
 * `key={appId}` so a new app starts from its first source.
 */
export const CapsuleArt: FC<{ appId: number; className: string; fallback: ReactNode }> = ({
  appId,
  className,
  fallback,
}) => {
  const sources = capsuleArtSources(appId);
  const [attempt, setAttempt] = useState(0);
  const src = sources[attempt];
  if (src === undefined) return <>{fallback}</>;
  return (
    <img key={src} className={className} src={src} alt="" loading="lazy" onError={() => setAttempt((n) => n + 1)} />
  );
};
